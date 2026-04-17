"""Node 2: Journey Planner.

페이지 타입과 사용자 요청을 기반으로 탐색 목표 이벤트 목록과 큐를 생성합니다.
자동 캡처 가능 여부를 분류하고 Manual Capture 필요 이벤트를 분리합니다.
"""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from agent.state import GTMAgentState

_llm = ChatOpenAI(model="gpt-5.1")

# 자동화 불가 이벤트 (Manual Capture Gateway로 전환)
MANUAL_REQUIRED_EVENTS = {"purchase", "refund"}

# 부분 자동화 (더미 데이터 폼 입력)
PARTIAL_AUTO_EVENTS = {"add_shipping_info", "add_payment_info"}

_PLANNER_SYSTEM = """당신은 GTM 이벤트 탐색 전략가입니다.
페이지 타입, 사용자 요청, 현재 페이지 URL을 보고 캡처해야 할 GA4 이벤트 목록을 생성하세요.

다음 JSON 형식으로만 응답하세요:
{
  "exploration_queue": ["이벤트1", "이벤트2", ...],
  "reasoning": "탐색 순서 선택 이유"
}

== GA4 표준 이벤트 ==
- page_view: 모든 페이지 로드 시
- view_item_list: 카테고리/목록 페이지(PLP)
- view_item: 상품 상세 페이지(PDP) — 홈/목록에서 상품 클릭 후 발화
- add_to_cart: PDP에서 장바구니 버튼 클릭
- remove_from_cart: 장바구니 페이지
- view_cart: 장바구니 페이지
- begin_checkout: 결제 시작
- add_shipping_info, add_payment_info: 결제 단계
- 자동화 불가 (항상 제외): purchase, refund

== 커스텀/비표준 이벤트 처리 ==
사용자 요청에 아래 이벤트가 포함되면 exploration_queue에 추가하세요:
- add_to_wishlist: 상품 찜하기/위시리스트 버튼 클릭 이벤트
  (한국 쇼핑몰: ♡ 하트, '찜', '찜하기', '관심상품' 버튼)
  → PLP 상품 카드의 찜 버튼 또는 PDP의 찜 버튼에서 캡처 가능
  → purchase/refund가 아니므로 auto_capturable로 분류
- select_item: PLP에서 상품 클릭
- 기타 사용자 요청에 명시된 이벤트명: auto_capturable로 처리

== 탐색 순서 원칙 ==
1. page_view는 항상 첫 번째
2. 현재 페이지가 홈/PLP이고 view_item이 필요하면: view_item_list → view_item 순서로
3. add_to_cart는 view_item 다음에 (PDP에서 연속 캡처 가능)
4. add_to_wishlist는 add_to_cart와 같은 PDP/PLP에서 캡처 가능하므로 인접 배치
5. 자동화 불가 이벤트(purchase, refund)는 큐에서 제외
"""


async def journey_planner(state: GTMAgentState) -> GTMAgentState:
    """Node 2: 탐색 목표 이벤트 목록 + 큐 생성."""
    page_type = state["page_type"]
    user_request = state["user_request"]
    tag_type = state.get("tag_type", "GA4")
    current_url = state.get("target_url", "")

    messages = [
        SystemMessage(content=_PLANNER_SYSTEM),
        HumanMessage(
            content=(
                f"페이지 타입: {page_type}\n"
                f"현재 URL: {current_url}\n"
                f"사용자 요청: {user_request}\n"
                f"태그 유형: {tag_type}"
            )
        ),
    ]
    response = await _llm.ainvoke(messages)
    raw = response.content.strip()

    # JSON 파싱
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    try:
        result = json.loads(raw)
        queue: list[str] = result.get("exploration_queue", [])
    except json.JSONDecodeError:
        print(f"[JourneyPlanner] JSON 파싱 실패, 기본 큐 사용")
        queue = _default_queue(page_type, user_request)

    # purchase/refund만 manual_required — 나머지는 모두 auto_capturable
    # (add_to_wishlist 등 커스텀 이벤트 포함)
    auto_capturable = [e for e in queue if e not in MANUAL_REQUIRED_EVENTS]
    manual_required = [e for e in queue if e in MANUAL_REQUIRED_EVENTS]

    # 사용자 요청에 purchase/refund가 명시된 경우 manual_required에 추가
    for event in MANUAL_REQUIRED_EVENTS:
        if event in user_request.lower() and event not in manual_required:
            manual_required.append(event)

    print(f"[JourneyPlanner] 탐색 큐: {queue}")
    print(f"[JourneyPlanner] 자동 캡처: {auto_capturable}")
    print(f"[JourneyPlanner] 수동 캡처 필요: {manual_required}")

    return {
        **state,
        "exploration_queue": queue,
        "auto_capturable": auto_capturable,
        "manual_required": manual_required,
        "exploration_log": state.get("exploration_log", [])
        + [f"탐색 큐 생성: {queue}"],
    }


def _default_queue(page_type: str, user_request: str = "") -> list[str]:
    """LLM 실패 시 페이지 타입별 기본 탐색 큐.

    사용자 요청에 명시된 이벤트가 있으면 기본 큐에 추가합니다.
    """
    defaults: dict[str, list[str]] = {
        "plp":      ["page_view", "view_item_list", "view_item", "add_to_cart"],
        "pdp":      ["page_view", "view_item", "add_to_cart"],
        "cart":     ["page_view", "view_cart", "begin_checkout"],
        "checkout": ["page_view", "begin_checkout", "add_shipping_info", "add_payment_info"],
        "home":     ["page_view", "view_item_list", "view_item", "add_to_cart"],
        "unknown":  ["page_view", "view_item", "add_to_cart"],
    }
    queue = list(defaults.get(page_type, ["page_view"]))

    # 사용자 요청에 명시된 커스텀 이벤트 추가
    custom_events = ["add_to_wishlist", "select_item", "view_promotion"]
    for event in custom_events:
        if event in user_request.lower() and event not in queue:
            queue.append(event)

    return queue
