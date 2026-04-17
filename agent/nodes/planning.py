"""Node 5: Planning Agent.

수집된 이벤트를 분석하고 Variable/Trigger/Tag 설계안을 생성합니다.
HITL(Human-in-the-loop): 터미널에서 y/n으로 승인을 받고,
n이면 피드백을 받아 재설계합니다.
"""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from agent.state import GTMAgentState
from docs.fetcher import fetch_docs_for_media

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
- Trigger: "CE - {event_name}" (Custom Event)
- Tag: "GA4 - {event_name}" 또는 "Naver - {event_name}" 또는 "Kakao - {event_name}"

GA4 Measurement ID 변수명: {{GA4 Measurement ID}} (기존 컨테이너 확인 후 있으면 재사용)
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


async def planning(state: GTMAgentState) -> GTMAgentState:
    """Node 5: GTM 설계안 생성 + HITL."""
    tag_type = state.get("tag_type", "GA4")
    captured_events = state.get("captured_events", [])
    manual_capture_results = state.get("manual_capture_results", {})
    existing_config = state.get("existing_gtm_config", {})
    hitl_feedback = state.get("hitl_feedback", "")

    extraction_method = state.get("extraction_method", "datalayer")
    dom_selectors = state.get("dom_selectors", {})
    click_triggers = state.get("click_triggers", {})
    selector_validation = state.get("selector_validation", {})

    # 전체 이벤트 풀 구성
    all_events = list(captured_events)
    for event_name, schema in manual_capture_results.items():
        all_events.append({"data": schema, "source": "manual"})

    # Naver/Kakao 문서 fetch
    doc_context = ""
    doc_fetch_failed = False
    if tag_type.lower() in ("naver", "kakao"):
        media_key = "naver_analytics" if tag_type.lower() == "naver" else "kakao_pixel"
        doc_context, doc_fetch_failed = fetch_docs_for_media(media_key)
        if doc_fetch_failed:
            print(f"[Planning] {tag_type} 문서 fetch 실패 — 내장 지식으로 진행")

    # DOM 구조 정보 컨텍스트 구성
    dom_context = ""
    if extraction_method != "datalayer" and (dom_selectors or click_triggers):
        dom_context = _build_dom_context(dom_selectors, click_triggers, selector_validation)
        print(f"[Planning] DOM 기반 설계 모드 (method={extraction_method})")

    user_request = state.get("user_request", "")

    # 설계안 생성 루프 (HITL 피드백 반영)
    while True:
        plan = await _generate_plan(
            tag_type, all_events, existing_config, doc_context,
            hitl_feedback, extraction_method, dom_context,
            user_request=user_request,
        )

        # 설계안 출력
        print("\n" + "="*60)
        print("[GTM 설계안]")
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        print("="*60)

        try:
            approval = input("\n이 설계안으로 GTM을 생성하시겠습니까? (y/n): ").strip().lower()
        except EOFError:
            approval = "y"
            print("[Planning] 비대화형 모드 — 설계안 자동 승인")

        if approval == "y":
            return {
                **state,
                "doc_context": doc_context,
                "doc_fetch_failed": doc_fetch_failed,
                "plan": plan,
                "plan_approved": True,
                "hitl_feedback": "",
            }
        else:
            try:
                hitl_feedback = input("수정 요청 사항을 입력하세요: ").strip()
            except EOFError:
                hitl_feedback = ""
            print("[Planning] 피드백 반영하여 재설계합니다...")


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
    if user_request:
        content_parts.append(f"사용자 요청 (반드시 이 이벤트들을 모두 설계에 포함할 것):\n{user_request}")
    content_parts += [
        f"\n수집된 이벤트:\n{events_summary}",
    ]
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
