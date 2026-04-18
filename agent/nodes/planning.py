"""Node 5: Planning Agent.

수집된 이벤트를 분석하고 Variable/Trigger/Tag 설계안을 생성합니다.
HITL(Human-in-the-loop): 터미널에서 y/n으로 승인을 받고,
n이면 피드백을 받아 재설계합니다.
"""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

import time

from agent.state import GTMAgentState
from docs.fetcher import fetch_docs_for_media
from utils import token_tracker
from utils.ui_emitter import emit, update_state, write_plan

_llm = ChatOpenAI(model="gpt-5.1")

_PLANNING_SYSTEM_DL = """당신은 GTM(Google Tag Manager) 전문가입니다.
수집된 dataLayer 이벤트를 분석하고 GTM Variable/Trigger/Tag 설계안을 생성하세요.

다음 JSON 형식으로만 응답하세요:
{
  "variables": [
    {
      "name": "DLV - event",
      "type": "v",
      "parameters": [
        {"type": "integer", "key": "dataLayerVersion", "value": "2"},
        {"type": "template", "key": "name", "value": "event"}
      ]
    }
  ],
  "triggers": [
    {
      "name": "CE - view_item",
      "type": "customEvent",
      "customEventFilter": [
        {
          "type": "equals",
          "parameter": [
            {"type": "template", "key": "arg0", "value": "{{_event}}"},
            {"type": "template", "key": "arg1", "value": "view_item"}
          ]
        }
      ]
    }
  ],
  "tags": [
    {
      "name": "GA4 - view_item",
      "type": "gaawe",
      "parameters": [
        {"type": "template", "key": "eventName", "value": "view_item"},
        {"type": "template", "key": "measurementIdOverride", "value": "{{GA4 Measurement ID}}"}
      ],
      "event_parameters": [
        {"key": "currency", "value": "KRW"},
        {"key": "value", "value": "{{DLV - ecommerce.value}}"},
        {"key": "items", "value": "{{DLV - ecommerce.items}}"}
      ],
      "firing_trigger_names": ["CE - view_item"]
    }
  ]
}

네이밍 컨벤션:
- Variable: "DLV - {필드명}" (dataLayer variable)
- Constant Variable: "GA4 Measurement ID" (type: c, value: 측정 ID)
- Trigger: "CE - {event_name}" (Custom Event for dataLayer events)
- Trigger: "Click - {설명}" (Click Trigger for non-dataLayer events)
- Tag: "GA4 - {event_name}" 또는 "Naver - {event_name}" 또는 "Kakao - {event_name}"

== CRITICAL: customEventFilter 규칙 ==
Custom Event Trigger의 customEventFilter에서:
- 첫 번째 파라미터(arg0)는 반드시 "{{_event}}" (리터럴 문자열, DLV 변수 아님!)
- 두 번째 파라미터(arg1)는 이벤트명 (예: "view_item")
예시:
"customEventFilter": [
  {
    "type": "equals",
    "parameter": [
      {"type": "template", "key": "arg0", "value": "{{_event}}"},
      {"type": "template", "key": "arg1", "value": "view_item"}
    ]
  }
]

== CRITICAL: 각 이벤트마다 별도 Trigger 생성 ==
dataLayer source 이벤트(view_item_list, view_item, add_to_cart 등) 각각에 대해
반드시 별도의 Custom Event Trigger를 생성하세요.
GA4 Tag의 firing_trigger_names는 반드시 해당 이벤트 전용 트리거명을 사용하세요.
예: GA4 - view_item → CE - view_item, GA4 - add_to_cart → CE - add_to_cart

== CRITICAL: Custom JS Variable 주의사항 ==
GTM Custom JS Variable 내부에서는 {{변수명}} 참조 불가.
dataLayer에서 직접 접근하거나 DOM에서 읽어야 합니다.
올바른 예: function(){ return window.dataLayer && window.dataLayer.filter(x=>x.ecommerce).pop()?.ecommerce?.items || []; }

== GA4 Measurement ID ==
사용자가 GA4 측정 ID(G-XXXXXXXX)를 제공한 경우:
1. type="c" (Constant) Variable "GA4 Measurement ID"를 생성하세요.
2. 모든 GA4 Tag의 measurementIdOverride에 {{GA4 Measurement ID}} 참조를 사용하세요.

== Mixed Scenario (DL + Click Trigger 혼용) ==
수집된 이벤트 중 source=datalayer인 이벤트는 Custom Event Trigger를 사용하고,
source=dom_extraction인 이벤트는 dataLayer에 push되지 않으므로 Click Trigger를 사용하세요.

Click Trigger 예시 (add_to_wishlist):
{
  "name": "Click - 찜하기 버튼",
  "type": "click",
  "filter": [
    {
      "type": "cssSelector",
      "parameter": [
        {"type": "template", "key": "arg0", "value": "{{Click Element}}"},
        {"type": "template", "key": "arg1", "value": "button[class*='Wish'], a[class*='Wish'], [onclick*='add_wishlist']"}
      ]
    }
  ]
}

Click Trigger 기반 GA4 Tag의 이벤트 파라미터:
- value: CJS Variable로 페이지 DOM에서 가격을 숫자로 추출 (parseFloat 사용),
  또는 이전 DL 이벤트(view_item 등)에서 캡처된 {{DLV - ecommerce.value}} 참조
- currency: DLV로 이전 이벤트에서 캡처된 값 또는 Constant "KRW" 사용
- items: Custom JS Variable로 페이지 DOM에서 추출하거나, view_item 이벤트 기준으로 설계
"""

_PLANNING_SYSTEM_DOM = """당신은 GTM(Google Tag Manager) 전문가입니다.
이 사이트는 dataLayer가 없거나 불완전하므로, DOM에서 직접 데이터를 추출하는 GTM 설계가 필요합니다.

Variable 타입 가이드:
- DOM Element Variable (type "d"): CSS selector로 페이지 내 요소의 텍스트/속성 추출
- Custom JavaScript Variable (type "jsm"): JS 함수로 값을 가공해서 반환
- Auto-Event Variable (type "aev"): 클릭된 요소의 속성 자동 수집

Trigger 타입 가이드:
- Click Trigger (type "click"): 특정 CSS selector 클릭 시 발동
  → filter 조건에 cssSelector 타입 사용, {{Click Element}} 변수로 클릭된 요소 참조
- Element Visibility (type "elementVisibility"): 특정 요소가 화면에 보일 때 발동
  → parameter 배열에 visibilitySelector(CSS selector)와 visibilityIdToCSSAuto 설정
- Page View (type "pageview"): 페이지 로드 시
  → URL 경로 기반 filter 조건으로 특정 페이지만 발동 가능

다음 JSON 형식으로만 응답하세요:
{
  "variables": [
    {
      "name": "DOM - item_name",
      "type": "d",
      "parameters": [
        {"type": "template", "key": "elementId", "value": "CSS_SELECTOR"},
        {"type": "integer", "key": "selectorType", "value": "1"},
        {"type": "template", "key": "attributeName", "value": "text"}
      ]
    },
    {
      "name": "CJS - item_price",
      "type": "jsm",
      "parameters": [
        {
          "type": "template",
          "key": "javascript",
          "value": "function(){var el=document.querySelector('SELECTOR');if(!el)return 0;var t=el.textContent||el.getAttribute('content')||'';return parseFloat(t.replace(/[^0-9.]/g,''))||0;}"
        }
      ]
    }
  ],
  "triggers": [
    {
      "name": "Click - 장바구니 담기",
      "type": "click",
      "filter": [
        {
          "type": "cssSelector",
          "parameter": [
            {"type": "template", "key": "arg0", "value": "{{Click Element}}"},
            {"type": "template", "key": "arg1", "value": "CSS_SELECTOR_FOR_BUTTON"}
          ]
        }
      ]
    },
    {
      "name": "Element Visibility - 상품 노출",
      "type": "elementVisibility",
      "parameter": [
        {"type": "template", "key": "visibilitySelector", "value": "CSS_SELECTOR_FOR_ITEM"},
        {"type": "boolean", "key": "visibilityIdToCSSAuto", "value": "true"}
      ]
    },
    {
      "name": "Pageview - 상품 목록 페이지",
      "type": "pageview",
      "filter": [
        {
          "type": "contains",
          "parameter": [
            {"type": "template", "key": "arg0", "value": "{{Page Path}}"},
            {"type": "template", "key": "arg1", "value": "/product/list"}
          ]
        }
      ]
    }
  ],
  "tags": [
    {
      "name": "GA4 - add_to_cart",
      "type": "gaawe",
      "parameters": [
        {"type": "template", "key": "eventName", "value": "add_to_cart"},
        {"type": "template", "key": "measurementIdOverride", "value": "{{GA4 Measurement ID}}"}
      ],
      "event_parameters": [
        {"key": "currency", "value": "KRW"},
        {"key": "value", "value": "{{CJS - item_price}}"},
        {"key": "items", "value": "{{CJS - ecommerce_items}}"}
      ],
      "firing_trigger_names": ["Click - 장바구니 담기"]
    }
  ]
}

네이밍 컨벤션:
- DOM Variable: "DOM - {필드명}"
- Custom JS Variable: "CJS - {필드명}"
- Click Trigger: "Click - {설명}" (한국어 가능)
- Tag: "GA4 - {event_name}"

중요:
- 가격은 반드시 CJS로 숫자만 추출하는 함수 작성
- items 배열을 구성하는 CJS 변수를 별도로 만들 것
- Click Trigger의 CSS selector는 반드시 검증된 selector 사용
"""


def _extract_ga4_id(user_request: str) -> str:
    """user_request 또는 문자열에서 GA4 측정 ID(G-XXXXXXXX)를 추출합니다."""
    import re
    match = re.search(r"G-[A-Z0-9]+", user_request, re.IGNORECASE)
    return match.group(0).upper() if match else ""


def _classify_events(captured_events: list[dict]) -> tuple[list[dict], list[dict]]:
    """캡처된 이벤트를 dataLayer 이벤트와 DOM 추출 이벤트로 분류합니다.

    Returns:
        (dl_events, dom_events)
    """
    _INTERNAL = {"gtm.js", "gtm.dom", "gtm.load"}
    dl_events = [
        e for e in captured_events
        if e.get("source") not in ("dom_extraction",)
        and e.get("data", {}).get("event") not in _INTERNAL
        and e.get("data", {}).get("event")
    ]
    dom_events = [
        e for e in captured_events
        if e.get("source") == "dom_extraction"
    ]
    return dl_events, dom_events


async def planning(state: GTMAgentState) -> GTMAgentState:
    """Node 5: GTM 설계안 생성 + HITL."""
    emit("node_enter", node_id=5, node_key="planning", title="Planning · HITL")
    update_state(current_node=5, nodes_status={"planning": "run"})
    _started = time.time()

    tag_type = state.get("tag_type", "GA4")
    captured_events = state.get("captured_events", [])
    manual_capture_results = state.get("manual_capture_results", {})
    existing_config = state.get("existing_gtm_config", {})
    hitl_feedback = state.get("hitl_feedback", "")

    extraction_method = state.get("extraction_method", "datalayer")
    dom_selectors = state.get("dom_selectors", {})
    click_triggers = state.get("click_triggers", {})
    selector_validation = state.get("selector_validation", {})

    user_request = state.get("user_request", "")
    # UI 폼에서 전달된 measurement_id 우선 사용, 없으면 user_request 파싱 폴백
    ga4_measurement_id = state.get("measurement_id", "") or _extract_ga4_id(user_request)

    # 전체 이벤트 풀 구성
    all_events = list(captured_events)
    for event_name, schema in manual_capture_results.items():
        all_events.append({"data": schema, "source": "manual"})

    # DL 이벤트 vs DOM 이벤트 분류
    dl_events, dom_events = _classify_events(all_events)
    has_real_dl_events = bool(dl_events)

    # extraction_method가 dom이어도 실제 DL 이벤트가 있으면 DL 모드로 전환
    effective_method = "datalayer" if has_real_dl_events else extraction_method
    if has_real_dl_events and extraction_method != "datalayer":
        print(
            f"[Planning] extraction_method={extraction_method}이지만 "
            f"DL 이벤트 {len(dl_events)}개 감지 → DL 기반 설계 모드로 전환"
        )

    # Naver/Kakao 문서 fetch
    doc_context = ""
    doc_fetch_failed = False
    if tag_type.lower() in ("naver", "kakao"):
        media_key = "naver_analytics" if tag_type.lower() == "naver" else "kakao_pixel"
        doc_context, doc_fetch_failed = fetch_docs_for_media(media_key)
        if doc_fetch_failed:
            print(f"[Planning] {tag_type} 문서 fetch 실패 — 내장 지식으로 진행")

    # DOM 구조 정보 컨텍스트 구성 (DOM 전용 이벤트가 있을 때만)
    dom_context = ""
    if dom_events and (dom_selectors or click_triggers):
        dom_context = _build_dom_context(dom_selectors, click_triggers, selector_validation)

    # DOM 추출 이벤트에 대한 Click Trigger 컨텍스트 구성
    click_trigger_context = ""
    if dom_events:
        dom_event_names = [e.get("data", {}).get("event", "?") for e in dom_events]
        click_trigger_context = _build_click_trigger_context(dom_event_names, click_triggers)
        print(f"[Planning] DOM 전용 이벤트 (Click Trigger 필요): {dom_event_names}")

    print(f"[Planning] DL 이벤트: {[e.get('data',{}).get('event') for e in dl_events]}")
    if ga4_measurement_id:
        print(f"[Planning] GA4 Measurement ID: {ga4_measurement_id}")

    # 설계안 생성 루프 (HITL 피드백 반영)
    while True:
        plan = await _generate_plan(
            tag_type, all_events, existing_config, doc_context,
            hitl_feedback, effective_method, dom_context,
            user_request=user_request,
            ga4_measurement_id=ga4_measurement_id,
            click_trigger_context=click_trigger_context,
        )

        # 설계안 출력
        print("\n" + "="*60)
        print("[GTM 설계안]")
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        print("="*60)

        # UI에 HITL 요청 emit
        write_plan(plan)
        emit("hitl_request", plan=plan)
        update_state(nodes_status={"planning": "hitl_wait"})

        approval, hitl_feedback_new = _wait_for_hitl(state.get("hitl_mode", "cli"))

        if approval == "y":
            emit("hitl_decision", approved=True, feedback="")
            _dur = int((time.time() - _started) * 1000)
            emit("node_exit", node_id=5, status="done", duration_ms=_dur)
            update_state(nodes_status={"planning": "done"})
            return {
                **state,
                "doc_context": doc_context,
                "doc_fetch_failed": doc_fetch_failed,
                "plan": plan,
                "plan_approved": True,
                "hitl_feedback": "",
                "extraction_method": effective_method,
            }
        else:
            hitl_feedback = hitl_feedback_new
            emit("hitl_decision", approved=False, feedback=hitl_feedback)
            print("[Planning] 피드백 반영하여 재설계합니다...")


def _wait_for_hitl(hitl_mode: str) -> tuple[str, str]:
    """HITL 승인을 대기합니다. (approval, feedback) 반환."""
    from utils import logger as _logger

    run_dir = _logger.run_dir()

    if hitl_mode == "file" and run_dir:
        # UI 파일 기반 HITL: logs/{run_id}/hitl_response.json 폴링
        response_file = run_dir / "hitl_response.json"
        response_file.unlink(missing_ok=True)
        print("[Planning] UI HITL 대기 중 (최대 5분)...")
        deadline = time.time() + 300
        while time.time() < deadline:
            if response_file.exists():
                try:
                    resp = json.loads(response_file.read_text(encoding="utf-8"))
                    response_file.unlink(missing_ok=True)
                    approved = resp.get("approved", True)
                    feedback = resp.get("feedback", "")
                    print(f"[Planning] UI 응답 수신: {'승인' if approved else '거부'}")
                    return ("y" if approved else "n"), feedback
                except Exception:
                    pass
            time.sleep(1)
        print("[Planning] HITL 타임아웃 — 자동 승인")
        return "y", ""

    # CLI 모드: 터미널 input()
    try:
        approval = input("\n이 설계안으로 GTM을 생성하시겠습니까? (y/n): ").strip().lower()
    except EOFError:
        print("[Planning] 비대화형 모드 — 설계안 자동 승인")
        return "y", ""

    if approval != "y":
        try:
            feedback = input("수정 요청 사항을 입력하세요: ").strip()
        except EOFError:
            feedback = ""
        return "n", feedback

    return "y", ""


def _build_click_trigger_context(
    event_names: list[str],
    click_triggers: dict,
) -> str:
    """DOM 추출 이벤트에 대한 Click Trigger 컨텍스트를 구성합니다."""
    from browser.navigator import EVENT_CAPTURE_GUIDE

    parts = [
        "=== Click Trigger 필요 이벤트 (dataLayer 미발화) ===",
        "아래 이벤트는 dataLayer에 push되지 않아 Click Trigger를 사용해야 합니다.",
        "GTM Click 변수({{Click Classes}}, {{Click Element}}, {{Click ID}})를 활용하세요.",
        "",
    ]
    for name in event_names:
        guide = EVENT_CAPTURE_GUIDE.get(name, "")
        verified_sel = click_triggers.get(name, "")
        parts.append(f"이벤트: {name}")
        if verified_sel:
            parts.append(f"  검증된 CSS selector: {verified_sel}")
        elif guide:
            parts.append(f"  탐색 가이드: {guide[:200]}")
        parts.append(
            f"  권장 Click Trigger CSS selector 패턴 (Cafe24 기준): "
            f"button[class*='Wish'], a[class*='Wish'], "
            f".xans-product-detail [class*='wish'], [onclick*='add_wishlist']"
        )
        parts.append("")
    return "\n".join(parts)


def _build_dom_context(
    dom_selectors: dict,
    click_triggers: dict,
    selector_validation: dict,
) -> str:
    """DOM 분석 결과를 LLM 컨텍스트 문자열로 구성합니다."""
    parts: list[str] = [
        "=== DOM 구조 분석 결과 (dataLayer 미사용) ===",
        "\n검증된 CSS Selector:",
    ]
    for field, spec in dom_selectors.items():
        selector = spec.get("selector", spec) if isinstance(spec, dict) else spec
        value = selector_validation.get(field, "(미검증)")
        parts.append(f"  - {field}: {selector} → 실제 값: {str(value)[:100]}")

    if click_triggers:
        parts.append("\n클릭 트리거 대상:")
        for event_name, sel in click_triggers.items():
            parts.append(f"  - {event_name}: {sel}")

    parts.append(
        "\n이 정보를 기반으로 DOM Element / Custom JS Variable과 "
        "Click Trigger를 사용하는 GTM 설계안을 생성하세요."
    )
    return "\n".join(parts)


async def _generate_plan(
    tag_type: str,
    all_events: list[dict],
    existing_config: dict,
    doc_context: str,
    feedback: str,
    extraction_method: str = "datalayer",
    dom_context: str = "",
    user_request: str = "",
    ga4_measurement_id: str = "",
    click_trigger_context: str = "",
) -> dict:
    """LLM으로 GTM 설계안을 생성합니다."""
    events_summary = json.dumps(
        [e.get("data", e) for e in all_events[:20]],
        ensure_ascii=False,
        indent=2,
    )

    system_prompt = _PLANNING_SYSTEM_DOM if extraction_method != "datalayer" else _PLANNING_SYSTEM_DL

    content_parts = [
        f"태그 유형: {tag_type}",
        f"데이터 추출 방식: {extraction_method}",
    ]
    if ga4_measurement_id:
        content_parts.append(
            f"GA4 측정 ID: {ga4_measurement_id}\n"
            f"→ 이 ID로 'GA4 Measurement ID' Constant Variable을 생성하고 "
            f"모든 GA4 Tag의 measurementIdOverride에 사용하세요."
        )
    if user_request:
        content_parts.append(f"사용자 요청 (반드시 이 이벤트들을 모두 설계에 포함할 것):\n{user_request}")
    content_parts += [
        f"\n수집된 이벤트 (source=datalayer: CE Trigger 사용, source=dom_extraction: Click Trigger 필요):\n{events_summary}",
    ]
    if click_trigger_context:
        content_parts.append(f"\n{click_trigger_context}")
    if dom_context:
        content_parts.append(f"\n{dom_context}")
    if existing_config:
        content_parts.append(
            f"\n기존 GTM 설정 (재사용 가능):\n{json.dumps(existing_config, ensure_ascii=False)[:3000]}"
        )
    if doc_context:
        content_parts.append(f"\n{tag_type} 공식 문서:\n{doc_context[:5000]}")
    if feedback:
        content_parts.append(f"\n이전 설계안에 대한 피드백:\n{feedback}")

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content="\n".join(content_parts)),
    ]
    response = await _llm.ainvoke(messages)
    token_tracker.track("planning", response)
    raw = response.content.strip()

    # 1순위: 마크다운 코드 블록에서 JSON 추출
    if "```" in raw:
        parts = raw.split("```")
        for part in parts[1::2]:  # 홀수 인덱스 = 코드 블록 내부
            if part.startswith("json"):
                part = part[4:]
            try:
                return json.loads(part.strip())
            except json.JSONDecodeError:
                continue

    # 2순위: 직접 파싱 (코드 블록 없는 JSON)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # 3순위: 최외곽 { ... } 추출 시도 (LLM이 앞뒤에 설명 텍스트를 붙인 경우)
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            pass

    print(f"[Planning] JSON 파싱 실패: {raw[:300]}")
    return {"variables": [], "triggers": [], "tags": []}
