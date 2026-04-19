"""LLM Navigator 루프.

LLM이 HTML 스냅샷 + 지금까지의 액션 히스토리를 보고 다음 스텝을 결정하면,
Playwright가 해당 액션을 실행합니다. 최대 MAX_STEPS 스텝 후 실패 시 포기합니다.
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
)
from browser.listener import (
    event_fingerprint,
    get_captured_events,
    get_datalayer_event_context_for_llm,
    peek_datalayer_raw,
    snapshot_datalayer_names,
)
from browser.url_context import url_looks_like_pdp
from config.exploration_limits_loader import navigator_max_llm_steps
from config.llm_models_loader import llm_model
from utils import logger, token_tracker
from utils.llm_json import make_chat_llm, parse_llm_json
from utils.ui_emitter import emit

# exploration_limits.yaml → navigator.max_llm_steps (기본 6)
MAX_STEPS = navigator_max_llm_steps()

# Navigator 전략: 이벤트 성격이 다르면 LLM 지시도 달라야 함 (페이지 진입형 vs 클릭 필수형)
_IMPLICIT_CONTEXT_EVENTS = frozenset({"view_item_list", "view_cart"})
_INTERACTION_CLICK_EVENTS = frozenset({
    "add_to_cart",
    "add_to_wishlist",
    "select_item",
    "begin_checkout",
})

# PLP URL 휴리스틱 — view_item_list 조기 포기 힌트에 사용
_PLP_URL_MARKERS = (
    "goods_list",
    "catecd=",
    "/goods/",
    "category",
    "list.html",
    "cate_no",
    "product/list",
)


def _url_looks_like_plp(url: str) -> bool:
    u = (url or "").lower()
    return any(m in u for m in _PLP_URL_MARKERS)


def _surface_goal_reached_for_prompt(url: str, goal: str) -> bool:
    u = (url or "").lower()
    g = (goal or "").lower()
    if g in ("", "unknown", "current"):
        return True
    if g == "pdp":
        return ("/product/" in u) or ("goods_view" in u) or ("product_no=" in u)
    if g == "plp":
        return ("/category/" in u) or ("goods_list" in u) or ("catecd=" in u)
    if g == "cart":
        return "/cart" in u or "/basket" in u
    if g == "checkout":
        return "/checkout" in u or "/order" in u
    if g == "home":
        return u.endswith("/") or "://" in u and u.split("://", 1)[-1].count("/") <= 1
    return True


def _primary_click_selector(raw: str | None) -> str:
    """Playwright `click`은 단일 셀렉터만 유효. LLM이 쉼표로 나열하면 첫 항목만 사용."""
    s = (raw or "").strip()
    if not s or "," not in s:
        return s
    parts = [p.strip() for p in s.split(",") if p.strip()]
    if len(parts) <= 1:
        return s
    logger.warning(
        f"[Navigator] click selector 쉼표 나열 {len(parts)}개 → 첫 번째만 사용: {parts[0]!r}"
    )
    return parts[0]


def _add_to_cart_repeat_hint(action_history: list[dict]) -> str | None:
    """동일 계열 장바구니 클릭만 반복될 때 LLM에 짧은 제약."""
    rows = [h for h in action_history if h.get("target_event") == "add_to_cart"]
    if len(rows) < 2:
        return None
    tail = rows[-3:]
    succ_clicks = [
        h for h in tail
        if h.get("action") == "click" and not h.get("error") and not h.get("event_fired")
    ]
    if len(succ_clicks) >= 2:
        return (
            "[시스템 힌트] 최근 add_to_cart 히스토리에서 **click 성공·이벤트 미발화**가 연속입니다. "
            "같은 장바구니 셀렉터만 재시도하지 말고, 스냅샷에서 **옵션·필수 선택 영역을 하나의 구체 셀렉터**로 클릭하거나 "
            "다른 액션 유형(scroll은 방향 명시)을 쓰세요. 반복 한계에 가깝습니다."
        )
    return None


def _repeated_click_failure_hint(target_event: str, action_history: list[dict]) -> str | None:
    """동일 셀렉터 click이 연속 타임아웃일 때 숨김 select / 칩 UI로 전환 유도."""
    if target_event not in ("select_item", "add_to_cart"):
        return None
    rows = [
        h
        for h in action_history
        if h.get("target_event") == target_event and h.get("action") == "click"
    ]
    if len(rows) < 2:
        return None
    a, b = rows[-2], rows[-1]
    sel_a = (a.get("selector") or "").strip()
    sel_b = (b.get("selector") or "").strip()
    if not sel_a or sel_a != sel_b:
        return None
    if not (a.get("error") and b.get("error")):
        return None
    joined = ((a.get("error") or "") + " " + (b.get("error") or "")).lower()
    if "타임아웃" not in joined and "timeout" not in joined:
        return None
    clip = sel_b[:100]
    return (
        "[시스템 힌트] 같은 CSS `click`이 연속 실패했습니다. 숨겨진 `<select>`는 "
        "`select_option` 액션으로 **value**(option value)를 지정하세요. "
        "보이는 사이즈칩·라디오 링크가 있으면 그쪽 **click**을 우선하세요. "
        f"동일 셀렉터 반복을 피하세요. (실패: `{clip}`)"
    )


def _strategy_kind(target_event: str) -> Literal["implicit", "interaction", "hybrid"]:
    if target_event in _IMPLICIT_CONTEXT_EVENTS:
        return "implicit"
    if target_event in _INTERACTION_CLICK_EVENTS:
        return "interaction"
    return "hybrid"


def _strategy_user_banner(target_event: str) -> str:
    """HumanMessage 상단 — 다른 범주 규칙을 섞어 쓰지 않도록 고정."""
    kind = _strategy_kind(target_event)
    if kind == "implicit":
        return (
            "[전략 범주: implicit — 페이지/URL 진입형]\n"
            "이 타입은 **올바른 목록·장바구니 URL에 들어갔을 때 사이트가 자동으로** dataLayer에 넣는 경우가 많습니다. "
            "진입 후에도 이벤트가 없으면 **미구현·비측정** 가능성이 큽니다. "
            "add_to_cart처럼 버튼을 여러 번 두드리는 식의 조작형 탐색을 하지 마세요.\n"
        )
    if kind == "interaction":
        return (
            "[전략 범주: interaction — 클릭·조작 필수]\n"
            "이 타입은 **실제 버튼·하트·옵션·상품 링크를 클릭**해야만 발화합니다. "
            "view_item_list용 ‘목록 URL만 맞추면 된다’ ‘조금만 보고 impossible’ 같은 **implicit 전략을 적용하지 마세요**. "
            "PDP/PLP 등 실행에 맞는 화면인지 본 뒤, 스냅샷에서 셀렉터를 잡아 **click**을 중심으로 진행하세요. "
            "클릭 성공 후에도 미발화일 때만 옵션·레이어·재클릭을 검토하세요.\n"
        )
    return (
        "[전략 범주: hybrid]\n"
        "진입만으로 발화될 수도 있고, 상품 클릭 등 조작이 필요할 수도 있습니다. URL·스냅샷·히스토리로 판단하세요.\n"
    )


def _view_item_list_plp_attempt_hint(
    page_url: str,
    action_history: list[dict],
) -> str:
    """PLP에서 dataLayer 미발화 시 LLM이 미세 탐색만 반복하지 않도록 짧은 힌트."""
    if not _url_looks_like_plp(page_url):
        return ""
    nav_scroll_ok = 0
    for h in action_history:
        if h.get("target_event") != "view_item_list":
            continue
        if h.get("event_fired"):
            break
        if h.get("action") in ("navigate", "scroll") and not h.get("error"):
            nav_scroll_ok += 1
    if nav_scroll_ok < 2:
        return ""
    return (
        "[시스템 힌트] 이미 상품 목록형 URL에서 성공한 navigate/scroll가 2회 이상인데도 "
        "view_item_list가 리스너에 없습니다. 많은 쇼핑몰은 이 이벤트를 dataLayer에 넣지 않습니다. "
        "서브카테고리만 바꿔가며 반복 탐색하지 말고 **impossible**을 선택해 Manual/DOM 폴백으로 넘기세요."
    )


# 이벤트별 캡처 목표 가이드
# "무엇을 클릭하라"가 아니라 "어떤 조건이 충족되어야 이벤트가 발화되는가"를 서술합니다.
# LLM이 현재 페이지 상태와 히스토리를 보고 스스로 다음 스텝을 판단합니다.
EVENT_CAPTURE_GUIDE: dict[str, str] = {
    "view_item": (
        "[hybrid] 보통 **상품 클릭으로 PDP 진입** 시 발화. PLP에서 상품 이미지·이름 링크 click 우선. "
        "카페24: a[href*='product_no='], goods_view.php, .prdList a[href*='goods_view'] 등. "
        "목록이 스냅샷에 없으면 scroll 1회 후 재시도. implicit처럼 ‘URL만’으로 끝내지 말 것."
    ),
    "add_to_cart": (
        "[조작형] URL만 맞춘다고 발화되지 않습니다. **장바구니 담기 버튼 클릭**이 핵심입니다. "
        "순서: (1) PDP가 아니면 상품 링크/이미지 click → PDP. "
        "(2) PDP면 장바구니/담기 버튼 click. 카페24: button[onclick*='Basket'], a[onclick*='Basket'], "
        "button[id*='buy'], #buy_now_btn, .EC-purchase-btn 등. "
        "(3) 클릭 성공인데 미발화면 옵션(사이즈·색) **각각 한 셀렉터씩** click 후 장바구니 다시 click. "
        "**selector 필드에는 유효한 CSS 하나만** 넣을 것(쉼표로 여러 개 나열 금지). "
        "implicit 이벤트처럼 조기 impossible 하지 마세요."
    ),
    "add_to_wishlist": (
        "[조작형] **찜/하트/위시 버튼을 실제로 클릭**해야 발화하는 경우가 대부분입니다. "
        "♡, '찜', '찜하기', '관심상품', button[class*='wish'], button[class*='like'], "
        "[class*='heart'] 등. PDP 또는 PLP 카드 위. 보이게 scroll 후 click. "
        "목록 페이지 URL만 바꾸는 navigate만으로는 부족합니다."
    ),
    "select_item": (
        "[조작형] 목록에서 **특정 상품을 선택(클릭)**할 때 발화하는 경우가 많습니다. "
        "PLP에서 상품 썸네일·제목 링크를 click. PDP에서 옵션(사이즈 등)이 필요하면 "
        "숨김 `<select>`는 **`select_option`**(selector + **value**=option value)로 처리하고, "
        "칩 UI는 보이는 링크를 click. implicit의 ‘URL만 맞추기’와 다릅니다."
    ),
    "view_item_list": (
        "목표: 카테고리/상품 목록(PLP)에서 GA4 view_item_list가 dataLayer에 쌓이는 경우. "
        "홈이면 대표 카테고리 1개로 navigate 한 번이면 충분한 경우가 많다. "
        "카페24 등: goods_list.php?cateCd=…, 상품 그리드가 보이는 URL이면 이미 PLP로 본다. "
        "중요: PLP에 들어온 뒤 리스너에 view_item_list가 없다면, 사이트가 아예 안 쏘는 경우가 흔하다. "
        "그때는 서브카테고리만 바꿔가며 navigate·scroll을 연속 반복하지 말고 **impossible**로 끝낸다 "
        "(실무에서도 목록 진입 후 푸시 없으면 포기하는 경우가 많음). "
        "scroll은 목록이 스냅샷에 안 보일 때 최대 1회 정도만 고려한다."
    ),
    "begin_checkout": (
        "[조작형] '구매하기'·'바로구매'·'결제하기' 등 **결제 진행 버튼 click** 후 발화. "
        "장바구니가 비어 있으면 먼저 장바구니/PDP 맥락을 갖춘 뒤 click. URL 진입만으로 끝나는 이벤트가 아닙니다."
    ),
    "view_cart": (
        "목표: 장바구니 페이지 진입 시 자동 발화. "
        "상단 장바구니 아이콘 클릭 또는 URL에 /cart, /basket 포함된 링크로 이동."
    ),
}

_SYSTEM_PROMPT = """당신은 한국 이커머스 웹사이트 브라우저 자동화 에이전트입니다.
목표 GA4 이벤트를 캡처하기 위해 페이지를 탐색합니다.

매 스텝마다 스냅샷·히스토리·**사용자 메시지 맨 위의 [전략 범주: …] 한 줄**을 읽습니다.
그 범주(implicit / interaction / hybrid)에 맞는 규칙만 적용하고, 다른 범주의 규칙은 **적용하지 마세요**.

다음 JSON 형식으로만 응답하세요:
{
  "action": "click" | "select_option" | "navigate" | "scroll" | "form_fill" | "captured" | "impossible",
  "selector": "CSS selector (click/form_fill/select_option 시 필수)",
  "url": "URL (navigate 시 필수)",
  "direction": "down" | "up" (scroll 시, 기본 down)",
  "value": "select_option: <option value=\"…\">의 value | form_fill: 더미 입력값",
  "reason": "히스토리 기반으로 현재 단계를 판단한 이유와 이 액션을 선택한 근거"
}

action 설명:
- click: 버튼/링크/상품/아이콘/옵션/드롭다운 클릭
- select_option: native `<select>`에 **value**로 옵션 지정(숨김 select·고도몰/카페24 등)
- navigate: URL 직접 이동(주로 맞는 **페이지로 이동**할 때)
- scroll: 요소가 뷰포트 밖일 때
- form_fill: 더미 데이터만
- captured: 목표 이벤트가 이미 리스너에 있음
- impossible: Manual/DOM 폴백으로 넘길 합리적 사유가 있을 때

### 범주 implicit (사용자 메시지에 그렇게 적힌 경우)
- **페이지·URL 진입**이 중심이며, 사이트가 자동으로 dataLayer에 넣는지 여부를 확인합니다.
- 올바른 목록/장바구니 URL에 들어간 뒤에도 이벤트가 없으면 **미구현 가능성**이 큽니다. navigate·scroll의 **미세 반복**을 멈추고 impossible을 허용합니다.
- add_to_cart처럼 ‘클릭을 계속 시도’하는 전략은 **금지**입니다.

### 범주 interaction (사용자 메시지에 그렇게 적힌 경우)
- **반드시 클릭·조작** 후에만 발화하는 이벤트입니다. navigate는 주로 PDP/장바구니 등 **실행할 화면으로 이동**할 때만 쓰고, 끝을 click/select_option으로 맞춥니다.
- `click`의 `selector`는 **단일** 유효 CSS만(쉼표로 나열 금지). 옵션이 여러 개면 **스텝마다 하나씩** 클릭합니다. 숨김 `<select>`는 **`select_option`**을 사용합니다.
- 클릭 성공 후에도 미발화면 옵션·레이어·재클릭 등 **UI 선행 조건**을 의심합니다.
- implicit용 ‘조금만 보고 impossible’ ‘서브카테고리만 navigate’ 같은 **조기 포기·과소 클릭**은 금지입니다. 실제 버튼을 찾을 때까지 스텝을 할애하는 것이 맞습니다.

### 범주 hybrid
- 진입형과 조작형 중 무엇에 가까운지 매 스텝 판단합니다.

공통:
- 히스토리에서 이미 끝난 단계는 건너뜁니다.
- 사용자 메시지에 **[dataLayer — …]** JSON 블록이 있으면, 그건 현재 `window.dataLayer` 배열에서 **`event`가 문자열인 객체만** 요약한 것입니다. 목표 이벤트가 그 안에 이미 있으면(에이전트가 아직 파이프라인에 넣기 전이어도) **captured**를 고려하세요.
- 팝업: 실행기가 이 이벤트 루프 **시작 시 한 번** 닫기를 시도했습니다. 가림이 명확할 때만 click으로 닫으세요.

보안:
- 실제 개인정보 입력 금지. form_fill은 더미만.
"""


class LLMNavigator:
    def __init__(self, model: str | None = None):
        # lazy 팩토리: 임포트 시점이 아닌 인스턴스 생성 시점에 생성
        # (timeout은 LLM 무응답 시 UI가 무한 대기처럼 보이지 않게 하는 상한)
        # model이 None이면 config/llm_models.yaml 의 navigator 구역 사용
        resolved = llm_model("navigator") if model is None else model
        self._llm = make_chat_llm(model=resolved, timeout=120.0)
        self._action_history: list[dict] = []  # 이벤트 간 공유, 세션 내 누적

    async def decide_next_action(
        self,
        page: Page,
        target_event: str,
        captured_so_far: list[dict],
        step: int,
        action_history: list[dict],
        playbook: dict | None = None,
    ) -> dict:
        """현재 페이지 상태와 액션 히스토리를 분석하고 다음 액션을 결정합니다."""
        logger.info(
            f"[Navigator] decide_next_action 시작 "
            f"event={target_event} step={step}/{MAX_STEPS} url={page.url!r} "
            f"history_entries={len(action_history)}"
        )
        sk = _strategy_kind(target_event)
        if sk == "interaction" and url_looks_like_pdp(page.url):
            try:
                await page.mouse.wheel(0, 1200)
                await page.wait_for_timeout(400)
                await page.mouse.wheel(0, 1200)
                await page.wait_for_timeout(400)
                logger.info("[Navigator] PDP interaction: 스냅샷 전 짧은 스크롤 nudge")
            except Exception as e:
                logger.debug(f"[Navigator] PDP 스크롤 nudge 실패: {e}")
        prefer_bottom = sk == "interaction"
        snap_max = 24000 if prefer_bottom else 18000
        t_snap = time.perf_counter()
        snapshot = ""
        try:
            snapshot = await get_page_snapshot(
                page, max_chars=snap_max, prefer_bottom=prefer_bottom
            )
        except Exception as e:
            logger.error(f"[Navigator] get_page_snapshot 예외: {e}")
            return {
                "action": "impossible",
                "reason": f"페이지 스냅샷 실패: {e}",
            }
        snap_dt = time.perf_counter() - t_snap
        snapshot_failed = snapshot.startswith(
            ("스냅샷 타임아웃", "스냅샷 실패", "스냅샷 가공 실패")
        )
        if snapshot_failed:
            logger.warning(
                f"[Navigator] 스냅샷 비정상 결과 ({snap_dt:.2f}s, len={len(snapshot)}): "
                f"{snapshot[:200]!r}"
            )
        else:
            logger.info(
                f"[Navigator] 스냅샷 수집·가공 완료 ({snap_dt:.2f}s, len={len(snapshot)})"
            )
        # §Phase 1b: 스냅샷 실패/빈약 시 ¼씩 스크롤 후 재시도 2회 한도.
        if snapshot_failed or len(snapshot) < 1500:
            for attempt in range(2):
                try:
                    await page.evaluate(
                        "window.scrollBy(0, Math.floor(document.body.scrollHeight/4))"
                    )
                    await page.wait_for_timeout(500)
                    retried = await get_page_snapshot(
                        page, max_chars=snap_max, prefer_bottom=prefer_bottom
                    )
                except Exception as e:
                    logger.debug(f"[Navigator] chunked retry {attempt+1} 실패: {e}")
                    break
                if not retried.startswith(
                    ("스냅샷 타임아웃", "스냅샷 실패", "스냅샷 가공 실패")
                ) and len(retried) >= 1500:
                    logger.info(
                        f"[Navigator] 스냅샷 chunked retry {attempt+1} 성공 len={len(retried)}"
                    )
                    snapshot = retried
                    break
        captured_names = [e.get("data", {}).get("event", "") for e in captured_so_far]

        event_guide = EVENT_CAPTURE_GUIDE.get(target_event, "")

        history_text = ""
        if action_history:
            lines = []
            for h in action_history:
                fired = bool(h.get("event_fired"))
                outcome = "이벤트 발화됨" if fired else ("실패: " + h["error"] if h.get("error") else "성공 but 이벤트 미발화")
                event_label = f"[{h['target_event']}] " if h.get("target_event") != target_event else ""
                act = h.get("action", "")
                detail = ""
                if act == "scroll":
                    detail = f"direction={h.get('direction') or 'down'}"
                elif act == "navigate":
                    detail = h.get("url") or ""
                elif act == "select_option":
                    detail = f"{h.get('selector') or ''} value={h.get('value') or ''}"
                elif act == "form_fill":
                    detail = f"{h.get('selector') or ''} value={h.get('value') or ''}"
                else:
                    detail = h.get("selector") or ""
                if len(detail) > 180:
                    detail = detail[:177] + "..."
                lines.append(
                    f"  스텝{h['step']} {event_label}{act} ({detail}) → {outcome}"
                )
            history_text = "지금까지 실행한 액션 (이번 이벤트 포함 세션 전체):\n" + "\n".join(lines)

        strategy_banner = _strategy_user_banner(target_event)
        playbook = playbook or {}
        surface_goal = str(playbook.get("surface_goal", "unknown"))
        trigger_fallbacks = list(playbook.get("trigger_fallbacks") or [])
        playbook_block = (
            f"[Playbook]\n"
            f"- surface_goal: {surface_goal}\n"
            f"- trigger_fallbacks: {trigger_fallbacks}\n"
            f"- surface_goal_reached: {_surface_goal_reached_for_prompt(page.url, surface_goal)}\n"
        )

        budget_hints: list[str] = []
        if target_event == "view_item_list":
            h_plp = _view_item_list_plp_attempt_hint(page.url, action_history)
            if h_plp:
                budget_hints.append(h_plp)
            if MAX_STEPS - step <= 3:
                budget_hints.append(
                    f"[시스템 힌트] view_item_list 남은 시도 {MAX_STEPS - step + 1}회. "
                    "미세 PLP/스크롤 반복보다 impossible이 전체 파이프라인에 유리할 수 있습니다."
                )
        if target_event == "add_to_cart":
            h_cart = _add_to_cart_repeat_hint(action_history)
            if h_cart:
                budget_hints.append(h_cart)
        if target_event in ("select_item", "add_to_cart"):
            h_rep = _repeated_click_failure_hint(target_event, action_history)
            if h_rep:
                budget_hints.append(h_rep)
        budget_block = ("\n" + "\n".join(budget_hints) + "\n") if budget_hints else ""

        dl_ctx = await get_datalayer_event_context_for_llm(page)
        try:
            _snap_pre_llm = await snapshot_datalayer_names(page)
            logger.log_dl_state(
                f"navigator/{target_event}/step{step}/pre-llm",
                page.url,
                _snap_pre_llm,
                target_event=target_event,
                extra={
                    "step": step,
                    "dl_ctx_chars": len(dl_ctx or ""),
                    "dl_ctx_empty": not bool((dl_ctx or "").strip()),
                },
            )
        except Exception as e:
            logger.debug(f"[Navigator] pre-llm dataLayer 스냅샷 실패: {e}")
        dl_block = ""
        if dl_ctx:
            dl_block = (
                "[dataLayer — `event`가 문자열인 객체만, 배열 순서상 최근 일부 JSON] "
                "(배열에만 있고 push 로그에 없던 항목 포함. 이미 목표 이벤트가 있으면 **captured** 검토.)\n"
                f"{dl_ctx}\n\n"
            )

        user_content = f"""
{strategy_banner}
현재 URL: {page.url}
목표 이벤트: {target_event}
{f'[캡처 목표 가이드] {event_guide}' if event_guide else ''}
이미 캡처된 이벤트: {captured_names}
현재 스텝: {step}/{MAX_STEPS}
(click: CSS 하나만, 쉼표 금지. 숨김 `<select>` 옵션은 **select_option** + value 사용.)
{history_text}
{budget_block}
{playbook_block}
{dl_block}페이지 HTML (축약):
{snapshot}
"""
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=user_content),
        ]
        emit(
            "thought",
            who="agent",
            label="Navigator",
            text=f"[{target_event}] 스텝 {step}: LLM이 다음 동작을 결정하는 중…",
            kind="plain",
        )
        user_chars = len(user_content)
        _lm = getattr(self._llm, "model_name", None) or getattr(self._llm, "model", None)
        logger.info(
            f"[Navigator] LLM ainvoke 시작 model={_lm!r} user_message_chars≈{user_chars}"
        )
        t_llm = time.perf_counter()
        try:
            response = await self._llm.ainvoke(messages)
        except Exception as e:
            emit(
                "thought",
                who="agent",
                label="Navigator",
                text=f"[{target_event}] LLM 호출 실패: {e}",
                kind="plain",
            )
            return {
                "action": "impossible",
                "reason": f"LLM 호출 실패(타임아웃·네트워크·API 오류 등): {e}",
            }
        llm_dt = time.perf_counter() - t_llm
        logger.info(f"[Navigator] LLM ainvoke 완료 ({llm_dt:.2f}s)")
        token_tracker.track("navigator", response)
        raw = response.content or ""

        decision = parse_llm_json(raw, fallback=None)
        if not isinstance(decision, dict) or "action" not in decision:
            decision = {
                "action": "impossible",
                "reason": f"LLM 응답 파싱 실패: {raw.strip()[:200]}",
            }

        logger.info(
            f"[Navigator] 결정 action={decision.get('action')!r} "
            f"selector/url={decision.get('selector') or decision.get('url') or ''!r}"
        )
        logger.log_llm_decision(target_event, step, decision, snapshot, page.url)
        reason = decision.get("reason", "")
        if reason:
            emit("thought", who="agent", label="Navigator",
                 text=f"[{target_event}] {reason}", kind="plain")
        return decision

    async def run_for_event(
        self,
        page: Page,
        target_event: str,
        captured_so_far: list[dict],
        playbook: dict | None = None,
    ) -> Literal["captured", "manual_required", "skipped"]:
        """목표 이벤트 캡처를 시도합니다. 최대 MAX_STEPS 스텝."""
        t_run = time.perf_counter()

        def _evt_summary(outcome: str) -> None:
            logger.info(
                f"[Navigator] run_for_event 요약 event={target_event!r} outcome={outcome} "
                f"wall_s={time.perf_counter() - t_run:.2f}"
            )

        # 매 스텝 close_popup 시 동일 셀렉터 연타가 UI/시간 낭비 → 이벤트당 1회만
        await close_popup(page)
        logger.info(f"[Navigator] run_for_event 시작: 초기 close_popup 1회 event={target_event}")

        for step in range(1, MAX_STEPS + 1):
            logger.info(
                f"[Navigator] run_for_event 루프 event={target_event} "
                f"step={step}/{MAX_STEPS} url={page.url!r}"
            )
            decision = await self.decide_next_action(
                page, target_event, captured_so_far, step, self._action_history, playbook=playbook
            )
            action = decision.get("action", "impossible")

            if action == "captured":
                logger.info(f"[Navigator] {target_event} 이미 캡처됨")
                _dl_snap = await snapshot_datalayer_names(page)
                logger.log_dl_state(
                    f"navigator/{target_event}/llm-captured",
                    page.url,
                    _dl_snap,
                    target_event=target_event,
                    extra={"step": step, "reason": (decision.get("reason", "") or "")[:200]},
                )
                await logger.save_screenshot(page, target_event, step, "captured")
                _evt_summary("already_captured")
                return "captured"

            if action == "impossible":
                logger.info(f"[Navigator] {target_event} 캡처 불가: {decision.get('reason', '')[:120]}")
                # [DL] impossible 직전 상태 + 포스트갭 재폴링(log-only)
                _dl_pre = await snapshot_datalayer_names(page)
                logger.log_dl_state(
                    f"navigator/{target_event}/impossible/pre",
                    page.url,
                    _dl_pre,
                    target_event=target_event,
                    extra={"step": step, "reason": (decision.get("reason", "") or "")[:200]},
                )
                try:
                    await page.wait_for_timeout(3000)
                    _dl_post = await snapshot_datalayer_names(page)
                    _pre_sig = set(_dl_pre.get("signal_names", []))
                    _post_sig = set(_dl_post.get("signal_names", []))
                    _emerged = sorted(_post_sig - _pre_sig)
                    logger.log_dl_state(
                        f"navigator/{target_event}/impossible/post-3s",
                        page.url,
                        _dl_post,
                        target_event=target_event,
                        extra={
                            "step": step,
                            "emerged_after_gap": _emerged,
                            "target_emerged_after_gap": target_event in _emerged,
                            "note": "log-only: capture semantics unchanged",
                        },
                    )
                    try:
                        _raw = await peek_datalayer_raw(page, 14)
                        logger.log_dl_raw_peek(
                            f"navigator/{target_event}/impossible/post-3s-raw",
                            page.url,
                            _raw,
                            target_event=target_event,
                            extra={"step": step},
                        )
                    except Exception as _re:
                        logger.debug(f"[DL] raw peek 실패: {_re}")
                except Exception as _e:
                    logger.debug(f"[DL] navigator impossible post-gap 재폴링 실패: {_e}")
                await logger.save_screenshot(page, target_event, step, "impossible")
                _evt_summary("impossible")
                return "manual_required"

            await logger.save_screenshot(page, target_event, step, "before")
            logger.info(
                f"[Navigator] {target_event} 스텝{step} "
                f"action={action} "
                f"selector={decision.get('selector', decision.get('url', ''))}"
            )

            exec_decision = dict(decision)
            if action == "click":
                exec_decision["selector"] = _primary_click_selector(exec_decision.get("selector"))

            t_act = time.perf_counter()
            result = await self._execute_action(page, exec_decision)
            act_dt = time.perf_counter() - t_act
            _err = (result.error or "")[:120]
            logger.info(
                f"[Navigator] 액션 실행 끝 success={result.success} "
                f"({act_dt:.2f}s) err={_err!r}"
            )

            history_entry: dict = {
                "step": step,
                "target_event": target_event,
                "action": action,
                "selector": (
                    exec_decision.get("selector", "")
                    if action in ("click", "select_option", "form_fill")
                    else decision.get("selector", "")
                ),
                "value": (
                    exec_decision.get("value", "")
                    if action in ("select_option", "form_fill")
                    else ""
                ),
                "url": decision.get("url", ""),
                "direction": decision.get("direction", "") if action == "scroll" else "",
                "error": "",
                "event_fired": False,
            }

            if not result.success:
                history_entry["error"] = result.error
                self._action_history.append(history_entry)
                await logger.save_screenshot(page, target_event, step, "fail")
                logger.error(f"[Navigator] 스텝{step} 실패: {result.error}")
                continue

            await page.wait_for_timeout(2000)
            events = await get_captured_events(
                page, log_tag=f"navigator/{target_event}/step{step}/after-wait"
            )

            # [DL] 스텝별 폴링 결과 스냅샷
            _dl_snap = await snapshot_datalayer_names(page)
            _other_signals = [
                n for n in _dl_snap.get("signal_names", []) if n != target_event
            ]
            logger.log_dl_state(
                f"navigator/{target_event}/step{step}/after-action",
                page.url,
                _dl_snap,
                target_event=target_event,
                extra={
                    "step": step,
                    "action": action,
                    "selector": history_entry.get("selector") or history_entry.get("url") or "",
                    "other_signals": _other_signals,
                },
            )

            seen_fps = {event_fingerprint(e) for e in captured_so_far}
            new_events = [
                e for e in events
                if event_fingerprint(e) not in seen_fps
                and e.get("data", {}).get("event") == target_event
            ]
            if new_events:
                history_entry["event_fired"] = True
                self._action_history.append(history_entry)
                await logger.save_screenshot(page, target_event, step, "success")
                logger.info(f"[Navigator] {target_event} 캡처 성공 (스텝{step})")
                _evt_summary(f"captured_step{step}")
                return "captured"

            self._action_history.append(history_entry)
            logger.info(f"[Navigator] {target_event} 스텝{step}: 액션 성공 but 이벤트 미발화")
            try:
                _raw_miss = await peek_datalayer_raw(page, 10)
                logger.log_dl_raw_peek(
                    f"navigator/{target_event}/step{step}/miss-raw",
                    page.url,
                    _raw_miss,
                    target_event=target_event,
                    extra={"step": step, "action": action},
                )
            except Exception:
                pass

        # [DL] max_steps 소진 직전 상태 + 포스트갭 재폴링(log-only)
        _dl_pre = await snapshot_datalayer_names(page)
        logger.log_dl_state(
            f"navigator/{target_event}/max_steps/pre",
            page.url,
            _dl_pre,
            target_event=target_event,
            extra={"step": MAX_STEPS},
        )
        try:
            await page.wait_for_timeout(3000)
            _dl_post = await snapshot_datalayer_names(page)
            _pre_sig = set(_dl_pre.get("signal_names", []))
            _post_sig = set(_dl_post.get("signal_names", []))
            _emerged = sorted(_post_sig - _pre_sig)
            logger.log_dl_state(
                f"navigator/{target_event}/max_steps/post-3s",
                page.url,
                _dl_post,
                target_event=target_event,
                extra={
                    "emerged_after_gap": _emerged,
                    "target_emerged_after_gap": target_event in _emerged,
                    "note": "log-only: capture semantics unchanged",
                },
            )
            try:
                _raw_ms = await peek_datalayer_raw(page, 14)
                logger.log_dl_raw_peek(
                    f"navigator/{target_event}/max_steps/post-3s-raw",
                    page.url,
                    _raw_ms,
                    target_event=target_event,
                    extra={"step": MAX_STEPS},
                )
            except Exception as _re:
                logger.debug(f"[DL] max_steps raw peek 실패: {_re}")
        except Exception as _e:
            logger.debug(f"[DL] navigator max_steps post-gap 재폴링 실패: {_e}")

        logger.info(f"[Navigator] {target_event} {MAX_STEPS}스텝 소진 → Manual 이관")
        _evt_summary("max_steps_exhausted")
        return "manual_required"

    async def _execute_action(self, page: Page, decision: dict) -> ActionResult:
        action = decision.get("action")

        if action == "click":
            return await click(page, decision.get("selector", ""))
        elif action == "navigate":
            return await navigate(page, decision.get("url", ""))
        elif action == "scroll":
            return await scroll(page, decision.get("direction", "down"))
        elif action == "form_fill":
            return await form_fill(
                page,
                decision.get("selector", ""),
                decision.get("value", ""),
            )
        elif action == "select_option":
            sel = (decision.get("selector") or "").strip()
            val = str(decision.get("value", "")).strip()
            if not sel or not val:
                return ActionResult(
                    success=False,
                    error="select_option에는 selector와 value가 모두 필요합니다",
                )
            return await select_option(page, sel, val, timeout=8000)
        else:
            return ActionResult(success=False, error=f"알 수 없는 액션: {action}")
