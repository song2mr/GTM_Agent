"""Node 2: Journey Planner.

페이지 타입과 사용자 요청을 기반으로 탐색 목표 이벤트 목록과 큐를 생성합니다.
자동 캡처 가능 여부를 분류하고 Manual Capture 필요 이벤트를 분리합니다.
"""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

import time

from agent.commerce_events import (
    fallback_begin_checkout_events,
    fallback_cart_addition_events,
)
from agent.state import GTMAgentState
from utils import token_tracker
from utils.ui_emitter import emit, update_state

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
  "cart_addition_events": ["큐에 있는 이름 중", "장바구니 담기 전용 절차를 탈 이벤트"],
  "begin_checkout_events": ["큐에 있는 이름 중", "결제 시작 전용 절차를 탈 이벤트"],
  "reasoning": "탐색 순서 선택 이유"
}

**cart_addition_events (필수)**  
- PDP에서 **옵션 선택 → 담기 버튼** 같은 무거운 UI 절차가 필요한 이벤트만 넣는다.
- **반드시 `exploration_queue`에 등장한 문자열과 동일한 이름**만 사용한다(추측·변형 금지).
- 사용자 요청·태그 유형(GA4 / 네이버 / 메타 / 크리테오 등)을 읽고, "장바구니에 담기·Add to cart·카트" 등 **의미상 그 행동**에 해당하는 이벤트명을 골라 넣는다.
  예: 큐에 `add_to_cart`만 있으면 `["add_to_cart"]`, 사용자가 `custom_cart_push`를 달라고 했으면 그 이름이 큐에 있을 때만 `["custom_cart_push"]`.
- 해당 계열이 없으면 **빈 배열 `[]`**.
- **이름 패턴(add2cart 등)으로 추측하지 말고**, 요청·태그 문맥으로 판단한다.

**begin_checkout_events (필수)**  
- 장바구니 → 주문서 → **구매하기/결제하기** 등 **여러 단계·레이어**가 필요한 “결제 시작” 계열만 넣는다.
- **반드시 `exploration_queue`에 등장한 문자열과 동일한 이름**만 사용한다.
- 사용자 요청·태그 유형을 읽고 의미상 결제 진입에 해당하는 이벤트명을 고른다. 없으면 **[]**.

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

== 탐색 전용 노드 ==
- `cart_addition_events` → Node 3.25 (옵션·담기 UI)
- `begin_checkout_events` → Node 3.5 (장바구니·주문서·결제 진입)
- 위 배열에 없는 이벤트는 일반 Active Explorer(Node 3)가 처리한다.
"""


async def journey_planner(state: GTMAgentState) -> GTMAgentState:
    """Node 2: 탐색 목표 이벤트 목록 + 큐 생성."""
    emit("node_enter", node_id=2, node_key="journey_planner", title="Journey Planner")
    update_state(current_node=2, nodes_status={"journey_planner": "run"})
    _started = time.time()

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
                f"태그 유형: {tag_type}\n\n"
                "JSON에 cart_addition_events, begin_checkout_events를 반드시 포함하세요(해당 없으면 []). "
                "각 배열의 이름은 exploration_queue에 나온 문자열과 **완전히 동일**해야 합니다."
            )
        ),
    ]
    response = await _llm.ainvoke(messages)
    token_tracker.track("journey_planner", response)
    raw = response.content.strip()

    # JSON 파싱
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    try:
        result = json.loads(raw)
        queue: list[str] = result.get("exploration_queue", [])
        planner_cart: object = result.get("cart_addition_events", None)
        planner_begin: object = result.get("begin_checkout_events", None)
    except json.JSONDecodeError:
        print(f"[JourneyPlanner] JSON 파싱 실패, 기본 큐 사용")
        result = {}
        planner_cart = None
        planner_begin = None
        queue = _default_queue(page_type, user_request)

    # purchase/refund만 manual_required — 나머지는 모두 auto_capturable
    # (add_to_wishlist 등 커스텀 이벤트 포함)
    auto_capturable = [e for e in queue if e not in MANUAL_REQUIRED_EVENTS]
    ac_set = set(auto_capturable)
    if isinstance(planner_cart, list):
        cart_addition_events = [
            e.strip()
            for e in planner_cart
            if isinstance(e, str) and e.strip() in ac_set
        ]
    else:
        cart_addition_events = fallback_cart_addition_events(auto_capturable)

    if isinstance(planner_begin, list):
        begin_checkout_events = [
            e.strip()
            for e in planner_begin
            if isinstance(e, str) and e.strip() in ac_set
        ]
    else:
        begin_checkout_events = fallback_begin_checkout_events(auto_capturable)

    manual_required = [e for e in queue if e in MANUAL_REQUIRED_EVENTS]

    # 사용자 요청에 purchase/refund가 명시된 경우 manual_required에 추가
    for event in MANUAL_REQUIRED_EVENTS:
        if event in user_request.lower() and event not in manual_required:
            manual_required.append(event)

    print(f"[JourneyPlanner] 탐색 큐: {queue}")
    print(f"[JourneyPlanner] 자동 캡처: {auto_capturable}")
    print(f"[JourneyPlanner] 장바구니 담기 전용: {cart_addition_events}")
    print(f"[JourneyPlanner] 결제 시작 전용: {begin_checkout_events}")
    print(f"[JourneyPlanner] 수동 캡처 필요: {manual_required}")

    emit(
        "thought",
        who="agent",
        label="JourneyPlanner",
        text=(
            f"탐색 큐: {queue}\n"
            f"자동 캡처: {auto_capturable}\n"
            f"장바구니 담기 전용: {cart_addition_events}\n"
            f"결제 시작 전용: {begin_checkout_events}\n"
            f"Manual 필요: {manual_required}"
        ),
    )
    _dur = int((time.time() - _started) * 1000)
    emit("node_exit", node_id=2, status="done", duration_ms=_dur)
    update_state(nodes_status={"journey_planner": "done"})

    return {
        **state,
        "exploration_queue": queue,
        "auto_capturable": auto_capturable,
        "cart_addition_events": cart_addition_events,
        "begin_checkout_events": begin_checkout_events,
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
