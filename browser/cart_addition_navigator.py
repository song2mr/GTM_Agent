"""장바구니·바스켓 담기 계열 이벤트 전용 LLM Navigator.

GA4 `add_to_cart`뿐 아니라 메타/네이버/크리테오 등 **이벤트 문자열이 달라도** 동일 PDP 절차(탭/해시,
native select 옵션, 담기 버튼)를 따르도록 프롬프트·액션 공간을 분리한다.
"""

from __future__ import annotations

import time
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from playwright.async_api import Page

from browser.actions import (
    ActionResult,
    click,
    close_popup,
    form_fill,
    get_page_snapshot,
    navigate,
    scroll,
    select_option,
    set_location_hash,
)
from browser.listener import event_fingerprint, get_captured_events
from config.exploration_limits_loader import cart_addition_max_llm_steps
from utils import logger, token_tracker
from utils.llm_json import make_chat_llm, parse_llm_json
from utils.ui_emitter import emit

_PDP_URL_MARKERS = (
    "goods_view",
    "goods_no=",
    "product/detail",
    "product_no=",
    "/goods/goods_view",
)


def _url_looks_like_pdp(url: str) -> bool:
    u = (url or "").lower()
    return any(m in u for m in _PDP_URL_MARKERS)


def _primary_click_selector(raw: str | None) -> str:
    s = (raw or "").strip()
    if not s or "," not in s:
        return s
    parts = [p.strip() for p in s.split(",") if p.strip()]
    if len(parts) <= 1:
        return s
    logger.warning(
        f"[CartNavigator] click selector 쉼표 나열 {len(parts)}개 → 첫 번째만 사용: {parts[0]!r}"
    )
    return parts[0]


def _cart_repeat_hint(target_event: str, action_history: list[dict]) -> str | None:
    rows = [h for h in action_history if h.get("target_event") == target_event]
    if len(rows) < 2:
        return None
    tail = rows[-3:]
    succ_clicks = [
        h
        for h in tail
        if h.get("action") == "click" and not h.get("error") and not h.get("event_fired")
    ]
    if len(succ_clicks) >= 2:
        return (
            f"[시스템 힌트] 최근 [{target_event}] 히스토리에서 **click 성공·이벤트 미발화**가 연속입니다. "
            "같은 담기 버튼만 재시도하지 말고 **select_option으로 필수 옵션 값 지정**, "
            "**set_hash로 #cart_tab_option 등 앵커 전환**, scroll을 병행하세요."
        )
    return None


_CART_SYSTEM_PROMPT = """당신은 한국 이커머스 PDP에서 **장바구니/바스켓 담기 계열 이벤트**만 캡처하는 자동화 에이전트입니다.

목표 이벤트 이름은 GA4의 add_to_cart가 아닐 수 있습니다(메타·네이버·크리테오·커스텀명).
**리스너에 그 정확한 이름으로 dataLayer 푸시가 잡히면 성공**입니다. 이름을 바꾸거나 추측하지 마세요.

다음 JSON 형식으로만 응답하세요:
{
  "action": "click" | "select_option" | "set_hash" | "navigate" | "scroll" | "form_fill" | "captured" | "impossible",
  "selector": "CSS selector (click/form_fill/select_option 시)",
  "value": "select_option: option value 문자열 | set_hash: # 없이 fragment (예 cart_tab_option) | form_fill: 더미값",
  "url": "URL (navigate 시 필수)",
  "direction": "down" | "up" (scroll 시, 기본 down)",
  "reason": "판단 근거"
}

### 이 범주에서 중요한 실행 규칙
- **옵션(사이즈/색 등)이 필수**인 몰: `select_option`으로 `<select>`의 **value**를 지정하세요.
  `option` 노드만 click로 때우지 말고 **select_option**을 우선합니다.
- 하단 고정 **쇼핑 카트 탭**·`href="#cart_tab_option"` 류: `set_hash` 또는 `.btn_shop_cart_open` 등
  탭 오픈 링크를 **한 번** 확실히 처리한 뒤 옵션→담기 순으로 진행합니다.
- `click`의 `selector`는 **단일 CSS**만 (쉼표 나열 금지).
- PDP가 아니면 먼저 상품 상세로 `navigate`/`click`으로 이동합니다.
- 팝업이 가리면 닫기용 click은 최소화합니다(실행기가 루프 시작 시 1회 닫기 시도함).

보안: form_fill은 더미만.
"""


class CartAdditionNavigator:
    def __init__(self, model: str = "gpt-5.1"):
        # lazy 팩토리로 ChatOpenAI 생성 — 임포트 시점 API 키 의존 제거
        self._llm = make_chat_llm(model=model, timeout=120.0)
        self._action_history: list[dict] = []
        # config/exploration_limits.yaml — cart_addition.max_llm_steps
        self._max_steps = cart_addition_max_llm_steps()

    async def decide_next_action(
        self,
        page: Page,
        target_event: str,
        captured_so_far: list[dict],
        step: int,
        action_history: list[dict],
    ) -> dict:
        logger.info(
            f"[CartNavigator] decide_next_action event={target_event} "
            f"step={step}/{self._max_steps} url={page.url!r}"
        )
        if _url_looks_like_pdp(page.url):
            try:
                await page.mouse.wheel(0, 1200)
                await page.wait_for_timeout(400)
                await page.mouse.wheel(0, 1200)
                await page.wait_for_timeout(400)
                logger.info("[CartNavigator] PDP: 스냅샷 전 스크롤 nudge")
            except Exception as e:
                logger.debug(f"[CartNavigator] PDP nudge 실패: {e}")

        t_snap = time.perf_counter()
        try:
            snapshot = await get_page_snapshot(
                page, max_chars=26000, prefer_bottom=True
            )
        except Exception as e:
            logger.error(f"[CartNavigator] 스냅샷 예외: {e}")
            return {"action": "impossible", "reason": f"스냅샷 실패: {e}"}
        snap_dt = time.perf_counter() - t_snap
        logger.info(f"[CartNavigator] 스냅샷 ({snap_dt:.2f}s, len={len(snapshot)})")

        captured_names = [e.get("data", {}).get("event", "") for e in captured_so_far]
        event_guide = (
            f"목표는 리스너에서 **정확히 '{target_event}'** 이름의 이벤트를 새로 캡처하는 것입니다. "
            "한국 PDP: 하단 카트 탭 → 필수 옵션(select) → 장바구니/담기 버튼 순이 흔합니다."
        )

        history_text = ""
        if action_history:
            lines = []
            for h in action_history:
                fired = bool(h.get("event_fired"))
                outcome = (
                    "이벤트 발화됨"
                    if fired
                    else ("실패: " + h["error"] if h.get("error") else "성공 but 이벤트 미발화")
                )
                event_label = f"[{h['target_event']}] " if h.get("target_event") != target_event else ""
                act = h.get("action", "")
                detail = ""
                if act == "scroll":
                    detail = f"direction={h.get('direction') or 'down'}"
                elif act == "navigate":
                    detail = h.get("url") or ""
                elif act == "select_option":
                    detail = f"{h.get('selector','')[:80]} = {h.get('value','')}"
                elif act == "set_hash":
                    detail = h.get("value", "") or ""
                else:
                    detail = h.get("selector") or ""
                if len(detail) > 180:
                    detail = detail[:177] + "..."
                lines.append(f"  스텝{h['step']} {event_label}{act} ({detail}) → {outcome}")
            history_text = "지금까지 실행한 액션:\n" + "\n".join(lines)

        h_cart = _cart_repeat_hint(target_event, action_history)
        budget_block = f"\n{h_cart}\n" if h_cart else ""

        user_content = f"""
[전략: 장바구니·바스켓 담기 전용 노드]
현재 URL: {page.url}
목표 이벤트(문자열 그대로 매칭): {target_event}
[가이드] {event_guide}
이미 캡처된 이벤트 이름 목록: {captured_names}
현재 스텝: {step}/{self._max_steps}
{history_text}
{budget_block}
페이지 HTML (축약):
{snapshot}
"""
        messages = [
            SystemMessage(content=_CART_SYSTEM_PROMPT),
            HumanMessage(content=user_content),
        ]
        emit(
            "thought",
            who="agent",
            label="CartNavigator",
            text=f"[{target_event}] 스텝 {step}: LLM이 다음 동작을 결정하는 중…",
            kind="plain",
        )
        t_llm = time.perf_counter()
        try:
            response = await self._llm.ainvoke(messages)
        except Exception as e:
            emit(
                "thought",
                who="agent",
                label="CartNavigator",
                text=f"[{target_event}] LLM 호출 실패: {e}",
                kind="plain",
            )
            return {"action": "impossible", "reason": f"LLM 실패: {e}"}
        logger.info(f"[CartNavigator] LLM 완료 ({time.perf_counter() - t_llm:.2f}s)")
        token_tracker.track("cart_addition_navigator", response)
        raw = response.content or ""
        decision = parse_llm_json(raw, fallback=None)
        if not isinstance(decision, dict) or "action" not in decision:
            decision = {
                "action": "impossible",
                "reason": f"JSON 파싱 실패: {raw.strip()[:200]}",
            }

        logger.info(
            f"[CartNavigator] 결정 action={decision.get('action')!r} "
            f"sel/value={decision.get('selector')!r} / {decision.get('value')!r}"
        )
        logger.log_llm_decision(f"cart::{target_event}", step, decision, snapshot, page.url)
        reason = decision.get("reason", "")
        if reason:
            emit(
                "thought",
                who="agent",
                label="CartNavigator",
                text=f"[{target_event}] {reason}",
                kind="plain",
            )
        return decision

    async def run_for_event(
        self,
        page: Page,
        target_event: str,
        captured_so_far: list[dict],
    ) -> Literal["captured", "manual_required", "skipped"]:
        await close_popup(page)
        for step in range(1, self._max_steps + 1):
            decision = await self.decide_next_action(
                page, target_event, captured_so_far, step, self._action_history
            )
            action = decision.get("action", "impossible")

            if action == "captured":
                await logger.save_screenshot(page, target_event, step, "captured")
                return "captured"

            if action == "impossible":
                await logger.save_screenshot(page, target_event, step, "impossible")
                return "manual_required"

            await logger.save_screenshot(page, target_event, step, "before")
            exec_decision = dict(decision)
            if action == "click":
                exec_decision["selector"] = _primary_click_selector(exec_decision.get("selector"))

            result = await self._execute_action(page, exec_decision)

            history_entry: dict = {
                "step": step,
                "target_event": target_event,
                "action": action,
                "selector": exec_decision.get("selector", "") if action in ("click", "form_fill", "select_option") else "",
                "value": exec_decision.get("value", "") if action in ("select_option", "set_hash", "form_fill") else "",
                "url": decision.get("url", ""),
                "direction": decision.get("direction", "") if action == "scroll" else "",
                "error": "",
                "event_fired": False,
            }

            if not result.success:
                history_entry["error"] = result.error
                self._action_history.append(history_entry)
                await logger.save_screenshot(page, target_event, step, "fail")
                continue

            await page.wait_for_timeout(2000)
            events = await get_captured_events(page)
            seen_fps = {event_fingerprint(e) for e in captured_so_far}
            new_events = [
                e
                for e in events
                if event_fingerprint(e) not in seen_fps
                and e.get("data", {}).get("event") == target_event
            ]
            if new_events:
                history_entry["event_fired"] = True
                self._action_history.append(history_entry)
                await logger.save_screenshot(page, target_event, step, "success")
                return "captured"

            self._action_history.append(history_entry)
            logger.info(f"[CartNavigator] {target_event} 스텝{step}: 액션 성공 but 이벤트 미발화")

        return "manual_required"

    async def _execute_action(self, page: Page, decision: dict) -> ActionResult:
        action = decision.get("action")
        if action == "click":
            return await click(page, decision.get("selector", ""), timeout=8000)
        if action == "navigate":
            return await navigate(page, decision.get("url", ""))
        if action == "scroll":
            return await scroll(page, decision.get("direction", "down"))
        if action == "form_fill":
            return await form_fill(
                page,
                decision.get("selector", ""),
                decision.get("value", ""),
            )
        if action == "select_option":
            return await select_option(
                page,
                decision.get("selector", ""),
                decision.get("value", ""),
                timeout=8000,
            )
        if action == "set_hash":
            return await set_location_hash(page, decision.get("value", ""))
        return ActionResult(success=False, error=f"알 수 없는 액션: {action}")
