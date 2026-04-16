"""Node 2: Journey Planner.

페이지 타입과 사용자 요청을 기반으로 탐색 목표 이벤트 목록과 큐를 생성합니다.
자동 캡처 가능 여부를 분류하고 Manual Capture 필요 이벤트를 분리합니다.
"""

from __future__ import annotations

import json

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from agent.state import GTMAgentState

_llm = ChatAnthropic(model="claude-sonnet-4-6")

# 자동화 불가 이벤트 (Manual Capture Gateway로 전환)
MANUAL_REQUIRED_EVENTS = {"purchase", "refund"}

# 부분 자동화 (더미 데이터 폼 입력)
PARTIAL_AUTO_EVENTS = {"add_shipping_info", "add_payment_info"}

_PLANNER_SYSTEM = """당신은 GTM 이벤트 탐색 전략가입니다.
페이지 타입과 사용자 요청을 보고 캡처해야 할 GA4 이커머스 이벤트 목록을 생성하세요.

다음 JSON 형식으로만 응답하세요:
{
  "exploration_queue": ["이벤트1", "이벤트2", ...],
  "reasoning": "탐색 순서 선택 이유"
}

GA4 표준 이벤트 참고:
- PLP: view_item_list
- PDP: view_item
- Cart: add_to_cart, remove_from_cart, view_cart
- Checkout: begin_checkout, add_shipping_info, add_payment_info, purchase
- 공통: page_view
- 자동화 불가 (항상 제외): purchase, refund

탐색 순서는 실제 사용자 여정 순서를 따르세요.
page_view는 항상 첫 번째에 포함하세요.
"""


async def journey_planner(state: GTMAgentState) -> GTMAgentState:
    """Node 2: 탐색 목표 이벤트 목록 + 큐 생성."""
    page_type = state["page_type"]
    user_request = state["user_request"]
    tag_type = state.get("tag_type", "GA4")

    messages = [
        SystemMessage(content=_PLANNER_SYSTEM),
        HumanMessage(
            content=f"페이지 타입: {page_type}\n사용자 요청: {user_request}\n태그 유형: {tag_type}"
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
        queue = _default_queue(page_type)

    # 자동화 가능/불가 분류
    auto_capturable = [e for e in queue if e not in MANUAL_REQUIRED_EVENTS]
    manual_required = [e for e in queue if e in MANUAL_REQUIRED_EVENTS]

    # purchase/refund는 항상 manual_required에 추가 (사용자 요청에 있을 경우)
    if "purchase" in user_request.lower() and "purchase" not in manual_required:
        manual_required.append("purchase")

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


def _default_queue(page_type: str) -> list[str]:
    """LLM 실패 시 페이지 타입별 기본 탐색 큐."""
    defaults = {
        "plp": ["page_view", "view_item_list", "view_item"],
        "pdp": ["page_view", "view_item", "add_to_cart"],
        "cart": ["page_view", "view_cart", "begin_checkout"],
        "checkout": ["page_view", "begin_checkout", "add_shipping_info", "add_payment_info"],
        "home": ["page_view"],
        "unknown": ["page_view"],
    }
    return defaults.get(page_type, ["page_view"])
