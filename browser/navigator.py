"""LLM Navigator 루프.

LLM이 HTML 스냅샷과 목표 이벤트를 보고 다음 액션을 결정하면,
Playwright가 해당 액션을 실행합니다. 최대 3회 재시도 후 실패 시 포기합니다.
"""

from __future__ import annotations

import json
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from playwright.async_api import Page

from browser.actions import (
    ActionResult,
    click,
    close_popup,
    form_fill,
    get_page_snapshot,
    navigate,
    scroll,
)
from browser.listener import get_captured_events
from utils import logger

MAX_RETRIES = 3

# 이벤트별 캡처 전략 가이드
# - 어떤 페이지 타입에 있어야 하는지
# - 어떤 UI 요소를 찾아야 하는지
# Navigator가 현재 페이지에서 무엇을 해야 하는지 판단하는 데 사용됩니다.
EVENT_CAPTURE_GUIDE: dict[str, str] = {
    "view_item": (
        "상품 상세 페이지(PDP)에서 자동 발화됩니다. "
        "현재 홈/목록 페이지라면 상품 이미지나 상품명을 클릭해서 PDP로 이동하세요. "
        "한국 카페24 기반 쇼핑몰의 상품 링크 패턴: "
        "a[href*='/product/detail.html'], a[href*='product_no='], "
        ".prdList a[href*='product'], .xans-product a[href*='product']. "
        "스냅샷에서 href에 '/product/detail.html?product_no=' 가 포함된 a 태그를 찾아 클릭하세요. "
        "목록이 보이지 않으면 먼저 scroll down 후 재시도하세요."
    ),
    "add_to_cart": (
        "상품 상세 페이지(PDP)에서 '장바구니 담기/추가' 버튼을 클릭하세요. "
        "텍스트: '장바구니', '담기', 'Add to Cart', 'Buy'. "
        "카페24 패턴: button[onclick*='Basket'], a[onclick*='Basket'], "
        "button[id*='buy'], #buy_now_btn, .EC-purchase-btn. "
        "현재 목록/홈 페이지라면 먼저 상품 클릭 → PDP로 이동하세요."
    ),
    "add_to_wishlist": (
        "찜하기/위시리스트 버튼을 클릭하세요. "
        "한국 쇼핑몰에서 자주 쓰이는 패턴: ♡ 하트 아이콘, '찜', '찜하기', '관심상품', '좋아요' 텍스트, "
        "또는 button[class*='wish'], button[class*='like'], button[class*='heart'], "
        "[class*='favorite'], [class*='bookmark'] 등의 selector. "
        "PDP뿐 아니라 상품 목록(PLP)의 각 상품 카드에도 존재할 수 있습니다. "
        "현재 목록/홈 페이지에서도 상품 카드 위에 마우스를 올리면 나타나는 경우도 있으니 "
        "스크롤해서 상품 카드를 찾은 뒤 하트/찜 버튼을 클릭하세요."
    ),
    "view_item_list": (
        "카테고리/목록 페이지(PLP)에서 자동 발화됩니다. "
        "현재 홈이라면 카테고리 목록 URL을 찾아 navigate 액션으로 직접 이동하세요. "
        "카테고리 URL 패턴: /product/list.html?cate_no=XXX, /category/XXX. "
        "HTML에서 href에 '/product/list.html' 또는 '/category/'가 포함된 링크를 찾아 "
        "click 대신 navigate 액션(url 필드에 전체 URL 입력)으로 이동하세요. "
        "클릭이 안 되는 메뉴 링크가 있으면 반드시 navigate를 사용하세요."
    ),
    "begin_checkout": (
        "장바구니 또는 상품 상세 페이지에서 '구매하기', '바로구매', '결제하기' 버튼 클릭. "
        "먼저 장바구니에 상품이 있어야 합니다."
    ),
    "view_cart": (
        "장바구니 페이지로 이동하세요. "
        "상단 장바구니 아이콘 클릭 또는 URL에 /cart, /basket 포함된 링크."
    ),
}

_SYSTEM_PROMPT = """당신은 한국 이커머스 웹사이트 브라우저 자동화 에이전트입니다.
목표 GA4 이벤트를 캡처하기 위해 페이지를 탐색합니다.

다음 JSON 형식으로만 응답하세요:
{
  "action": "click" | "navigate" | "scroll" | "form_fill" | "captured" | "impossible",
  "selector": "CSS selector (click/form_fill 시 필수)",
  "url": "URL (navigate 시 필수)",
  "direction": "down" | "up" (scroll 시, 기본 down)",
  "value": "입력값 (form_fill 시 필수, 더미 데이터만)",
  "reason": "이 액션을 선택한 이유"
}

action 설명:
- click: 버튼/링크/상품/아이콘 클릭
- navigate: URL 직접 이동 (상품 상세 페이지 URL을 HTML에서 찾았을 때)
- scroll: 페이지 스크롤 (찜 버튼이 화면 밖에 있거나 상품 목록을 더 보려 할 때)
- form_fill: 폼 입력 (더미 데이터만 사용)
- captured: 이미 목표 이벤트가 캡처됨
- impossible: 이 페이지에서 목표 이벤트 캡처가 현재 불가능 (다른 페이지로 이동 필요 시 사용하지 말 것)

판단 규칙:
1. 목표 이벤트 캡처에 필요한 페이지 타입이 아니면 먼저 이동하세요 (click 또는 navigate).
2. 버튼/링크가 화면 밖에 있을 수 있으니 scroll 후 재시도하세요.
3. 팝업, 레이어, 모달이 있으면 먼저 닫으세요.
4. impossible은 정말 사이트 구조상 캡처가 불가능할 때만 사용하세요.

보안 규칙:
- 실제 개인정보(이름, 전화번호, 신용카드 등) 절대 입력 금지
- form_fill 시 항상 더미 데이터 사용
"""


class LLMNavigator:
    def __init__(self, model: str = "gpt-5.1"):
        self._llm = ChatOpenAI(model=model)

    async def decide_next_action(
        self,
        page: Page,
        target_event: str,
        captured_so_far: list[dict],
        attempt: int = 1,
        last_error: str = "",
    ) -> dict:
        """현재 페이지 상태를 분석하고 다음 액션을 결정합니다."""
        snapshot = await get_page_snapshot(page)
        captured_names = [e.get("data", {}).get("event", "") for e in captured_so_far]

        event_guide = EVENT_CAPTURE_GUIDE.get(target_event, "")
        user_content = f"""
현재 URL: {page.url}
목표 이벤트: {target_event}
{f'[이벤트 캡처 가이드] {event_guide}' if event_guide else ''}
이미 캡처된 이벤트: {captured_names}
시도 횟수: {attempt}/{MAX_RETRIES}
{f'이전 시도 오류: {last_error}' if last_error else ''}

페이지 HTML (축약):
{snapshot}
"""
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=user_content),
        ]
        response = await self._llm.ainvoke(messages)
        raw = response.content.strip()

        # JSON 파싱
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        try:
            decision = json.loads(raw)
        except json.JSONDecodeError:
            decision = {"action": "impossible", "reason": f"LLM 응답 파싱 실패: {raw[:200]}"}

        logger.log_llm_decision(target_event, attempt, decision, snapshot, page.url)
        return decision

    async def run_for_event(
        self,
        page: Page,
        target_event: str,
        captured_so_far: list[dict],
    ) -> Literal["captured", "manual_required", "skipped"]:
        """목표 이벤트 캡처를 시도합니다. 최대 MAX_RETRIES회 재시도."""
        last_error = ""

        for attempt in range(1, MAX_RETRIES + 1):
            decision = await self.decide_next_action(
                page, target_event, captured_so_far, attempt, last_error
            )
            action = decision.get("action", "impossible")

            if action == "captured":
                logger.info(f"[Navigator] {target_event} 이미 캡처됨")
                await logger.save_screenshot(page, target_event, attempt, "captured")
                return "captured"

            if action == "impossible":
                logger.info(f"[Navigator] {target_event} 캡처 불가: {decision.get('reason', '')[:120]}")
                await logger.save_screenshot(page, target_event, attempt, "impossible")
                return "manual_required"

            # 팝업 먼저 처리
            await close_popup(page)

            # 액션 실행 전 스크린샷
            await logger.save_screenshot(page, target_event, attempt, "before")
            logger.info(
                f"[Navigator] {target_event} 시도{attempt} "
                f"action={action} "
                f"selector={decision.get('selector', decision.get('url', ''))}"
            )

            result = await self._execute_action(page, decision)

            if not result.success:
                last_error = result.error
                await logger.save_screenshot(page, target_event, attempt, "fail")
                logger.error(f"[Navigator] 시도{attempt} 실패: {result.error}")
                continue

            # 이벤트 발화 확인
            await page.wait_for_timeout(2000)
            events = await get_captured_events(page)
            new_events = [
                e for e in events
                if e not in captured_so_far
                and e.get("data", {}).get("event") == target_event
            ]
            if new_events:
                await logger.save_screenshot(page, target_event, attempt, "success")
                logger.info(f"[Navigator] {target_event} 캡처 성공 (시도{attempt})")
                return "captured"

            last_error = "액션 실행 성공했으나 이벤트 미발화"
            logger.info(f"[Navigator] {target_event} 시도{attempt}: 액션 성공 but 이벤트 미발화")

        logger.info(f"[Navigator] {target_event} {MAX_RETRIES}회 실패 → Manual 이관")
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
        else:
            return ActionResult(success=False, error=f"알 수 없는 액션: {action}")
