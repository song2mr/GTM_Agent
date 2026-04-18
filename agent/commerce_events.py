"""장바구니 담기 전용 플로우 — **이벤트명은 Journey Planner(LLM)가 결정**한다.

`cart_addition_events` / `begin_checkout_events`는 Journey Planner(LLM)가 JSON으로 넘기는 것이 정식 경로다.
이 모듈의 폴백은 **해당 필드가 없을 때** 구버전·파싱 실패에 대비한 최소 안전망(GA4 기본명만)이다.
"""

from __future__ import annotations


def fallback_cart_addition_events(auto_capturable: list[str]) -> list[str]:
    """`cart_addition_events`가 응답에 없을 때만: 큐에 `add_to_cart`가 있으면 그것만."""
    if "add_to_cart" in auto_capturable:
        return ["add_to_cart"]
    return []


def fallback_begin_checkout_events(auto_capturable: list[str]) -> list[str]:
    """`begin_checkout_events`가 응답에 없을 때만: 큐에 `begin_checkout`이 있으면 그것만."""
    if "begin_checkout" in auto_capturable:
        return ["begin_checkout"]
    return []
