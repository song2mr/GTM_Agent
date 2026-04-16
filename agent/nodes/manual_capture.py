"""Node 4: Manual Capture Gateway.

purchase, refund 등 자동 캡처 불가 이벤트에 대해 사용자에게
A) 직접 캡처 / B) 표준 스키마 승인 / C) 스킵 중 선택하게 합니다.
"""

from __future__ import annotations

import json

from agent.state import GTMAgentState

# GA4 표준 이벤트 스키마 (Option B용)
GA4_STANDARD_SCHEMAS: dict[str, dict] = {
    "purchase": {
        "event": "purchase",
        "ecommerce": {
            "transaction_id": "T_12345",
            "value": 59900,
            "tax": 0,
            "shipping": 3000,
            "currency": "KRW",
            "items": [
                {
                    "item_id": "SKU_001",
                    "item_name": "상품명",
                    "affiliation": "",
                    "coupon": "",
                    "discount": 0,
                    "index": 0,
                    "item_brand": "브랜드",
                    "item_category": "카테고리",
                    "price": 59900,
                    "quantity": 1,
                }
            ],
        },
    },
    "refund": {
        "event": "refund",
        "ecommerce": {
            "transaction_id": "T_12345",
            "value": 59900,
            "currency": "KRW",
            "items": [
                {
                    "item_id": "SKU_001",
                    "item_name": "상품명",
                    "price": 59900,
                    "quantity": 1,
                }
            ],
        },
    },
}


async def manual_capture(state: GTMAgentState) -> GTMAgentState:
    """Node 4: 수동 캡처 게이트웨이 — 사용자 선택(A/B/C)."""
    manual_required: list[str] = state.get("manual_required", [])
    manual_capture_results: dict = dict(state.get("manual_capture_results", {}))
    skipped_events: list[str] = list(state.get("skipped_events", []))

    if not manual_required:
        print("[ManualCapture] 수동 캡처 필요 이벤트 없음, 스킵")
        return {
            **state,
            "manual_capture_results": manual_capture_results,
            "skipped_events": skipped_events,
        }

    for event_name in manual_required:
        if event_name in manual_capture_results or event_name in skipped_events:
            continue

        standard_schema = GA4_STANDARD_SCHEMAS.get(event_name, {})
        schema_str = json.dumps(standard_schema, ensure_ascii=False, indent=2)

        print(f"\n{'='*60}")
        print(f"[{event_name}] 이벤트는 자동 캡처가 불가능합니다.")
        print("방법을 선택하세요:\n")
        print("A) 직접 캡처")
        print("   브라우저 콘솔에서 실제 주문완료 후 아래 명령어 실행:")
        print("   > copy(JSON.stringify(window.dataLayer))")
        print("   결과를 여기에 붙여넣어 주세요.\n")
        if standard_schema:
            print("B) GA4 표준 스키마로 진행 (권장)")
            print(f"   {schema_str}\n")
        print("C) 이 이벤트 스킵")
        print(f"{'='*60}")

        while True:
            choice = input("선택 (A/B/C): ").strip().upper()

            if choice == "A":
                pasted = input("dataLayer JSON을 붙여넣으세요: ").strip()
                try:
                    data = json.loads(pasted)
                    if isinstance(data, list):
                        # window.dataLayer 전체를 붙여넣은 경우
                        matching = [
                            item for item in data
                            if isinstance(item, dict) and item.get("event") == event_name
                        ]
                        schema = matching[-1] if matching else data[-1] if data else {}
                    else:
                        schema = data
                    manual_capture_results[event_name] = schema
                    print(f"[ManualCapture] {event_name} 스키마 저장 완료")
                    break
                except json.JSONDecodeError:
                    print("JSON 파싱 실패. 다시 시도하거나 B/C를 선택하세요.")
                    continue

            elif choice == "B" and standard_schema:
                manual_capture_results[event_name] = standard_schema
                print(f"[ManualCapture] {event_name} 표준 스키마 적용")
                break

            elif choice == "C":
                skipped_events.append(event_name)
                print(f"[ManualCapture] {event_name} 스킵")
                break

            else:
                valid = "A, B, C" if standard_schema else "A, C"
                print(f"잘못된 입력입니다. {valid} 중 하나를 선택하세요.")

    return {
        **state,
        "manual_capture_results": manual_capture_results,
        "skipped_events": skipped_events,
    }
