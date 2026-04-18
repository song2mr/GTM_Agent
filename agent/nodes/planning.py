"""Node 5: Planning Agent.

수집된 이벤트를 분석하고 Variable/Trigger/Tag 설계안을 생성합니다.
HITL(Human-in-the-loop): 터미널에서 y/n으로 승인을 받고,
n이면 피드백을 받아 재설계합니다.
"""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage

import time

from agent.state import GTMAgentState
from config.llm_models_loader import llm_model
from docs.fetcher import fetch_docs_for_media
from utils import logger, token_tracker
from utils.llm_json import make_chat_llm, parse_llm_json
from utils.ui_emitter import emit, update_state, write_plan

_PLANNING_SYSTEM = """당신은 GTM(Google Tag Manager) 전문가입니다.
수집된 이벤트를 분석하고 GTM Variable/Trigger/Tag 설계안을 생성하세요.

== 핵심 판단 규칙: 이벤트별 source 필드를 보고 트리거 타입을 결정하세요 ==

각 이벤트의 source 필드:
- source가 없거나 "datalayer" 또는 "datalayer+dom" → dataLayer에서 발화한 이벤트
  → Custom Event Trigger (type: customEvent) + DLV Variable 사용
- source = "dom_extraction" → dataLayer 미발화, DOM에서 추출한 이벤트
  → Click Trigger (type: click) + DOM/CJS Variable 사용

이벤트 이름이 GA4 공식 명칭(add_to_cart)이 아니더라도(addToCart, AddCart 등)
dataLayer에서 실제 발화된 이벤트라면 해당 이름 그대로 CE Trigger를 만드세요.
(customEventFilter의 arg1에 실제 이벤트명을 그대로 사용)

== Variable 타입 가이드 ==

dataLayer 이벤트용:
- DLV (type "v"): dataLayer.push된 값 참조
  parameters: [{"type":"integer","key":"dataLayerVersion","value":"2"}, {"type":"template","key":"name","value":"ecommerce.items"}]

DOM 추출 이벤트용:
- DOM Element Variable (type "d"): CSS selector로 텍스트/속성 추출
- Custom JavaScript Variable (type "jsm"): JS 함수로 값 가공

== Trigger 타입 가이드 ==

dataLayer 이벤트 → Custom Event Trigger:
- type: "customEvent"
- customEventFilter: arg0는 반드시 "{{_event}}" (리터럴), arg1은 실제 이벤트명

DOM 추출 이벤트 → Click Trigger:
- type: "click"
- filter: cssSelector 타입, arg0는 "{{Click Element}}", arg1은 CSS selector

== 다음 JSON 형식으로만 응답하세요 ==
{
  "variables": [
    {
      "name": "DLV - ecommerce.items",
      "type": "v",
      "parameters": [
        {"type": "integer", "key": "dataLayerVersion", "value": "2"},
        {"type": "template", "key": "name", "value": "ecommerce.items"}
      ]
    },
    {
      "name": "CJS - item_price",
      "type": "jsm",
      "parameters": [
        {
          "type": "template",
          "key": "javascript",
          "value": "function(){var el=document.querySelector('SELECTOR');if(!el)return 0;return parseFloat(el.textContent.replace(/[^0-9.]/g,''))||0;}"
        }
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
    },
    {
      "name": "Click - 장바구니 담기",
      "type": "click",
      "filter": [
        {
          "type": "cssSelector",
          "parameter": [
            {"type": "template", "key": "arg0", "value": "{{Click Element}}"},
            {"type": "template", "key": "arg1", "value": "button[class*='cart']"}
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
    },
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

== 네이밍 컨벤션 ==
- DLV Variable: "DLV - {필드명}" (예: "DLV - ecommerce.items")
- DOM Variable: "DOM - {필드명}"
- CJS Variable: "CJS - {필드명}"
- Constant Variable: "GA4 Measurement ID" (type: c)
- CE Trigger: "CE - {실제이벤트명}" (예: "CE - addToCart")
- Click Trigger: "Click - {설명}"
- Tag: "GA4 - {event_name}" 또는 "Naver - {event_name}" 또는 "Kakao - {event_name}"

== CRITICAL 규칙 ==
1. 이벤트마다 반드시 별도 Trigger를 만들고, Tag의 firing_trigger_names는 해당 전용 트리거명 사용
2. GTM Custom JS Variable 내부에서는 {{변수명}} 참조 불가 — dataLayer나 DOM에서 직접 접근
3. GA4 측정 ID(G-XXXXXXXX)가 있으면 Constant Variable "GA4 Measurement ID"를 만들고 모든 GA4 Tag에 사용
4. DOM 추출 이벤트의 가격은 CJS로 숫자만 추출 (parseFloat), items도 CJS로 별도 구성
"""


def _extract_ga4_id(user_request: str) -> str:
    """user_request 또는 문자열에서 GA4 측정 ID(G-XXXXXXXX)를 추출합니다."""
    import re
    match = re.search(r"G-[A-Z0-9]+", user_request, re.IGNORECASE)
    return match.group(0).upper() if match else ""




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

    # Naver/Kakao 문서 fetch
    doc_context = ""
    doc_fetch_failed = False
    if tag_type.lower() in ("naver", "kakao"):
        media_key = "naver_analytics" if tag_type.lower() == "naver" else "kakao_pixel"
        doc_context, doc_fetch_failed = fetch_docs_for_media(media_key)
        if doc_fetch_failed:
            logger.warning(f"[Planning] {tag_type} 문서 fetch 실패 — 내장 지식으로 진행")

    # DOM 구조 정보 컨텍스트 구성
    dom_context = ""
    if dom_selectors or click_triggers:
        dom_context = _build_dom_context(dom_selectors, click_triggers, selector_validation)

    if ga4_measurement_id:
        logger.info(f"[Planning] GA4 Measurement ID: {ga4_measurement_id}")
    logger.info(
        f"[Planning] 총 이벤트: {[e.get('data', {}).get('event') for e in all_events]}"
    )

    # 설계안 생성 루프 (HITL 피드백 반영)
    while True:
        plan = await _generate_plan(
            tag_type, all_events, existing_config, doc_context,
            hitl_feedback, dom_context,
            user_request=user_request,
            ga4_measurement_id=ga4_measurement_id,
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
    dom_context: str = "",
    user_request: str = "",
    ga4_measurement_id: str = "",
) -> dict:
    """LLM으로 GTM 설계안을 생성합니다."""
    # source 필드를 포함해서 LLM에 전달 (이벤트별 DL/DOM 판단 근거)
    events_summary = json.dumps(
        [{"source": e.get("source", "datalayer"), **e.get("data", e)} for e in all_events[:20]],
        ensure_ascii=False,
        indent=2,
    )

    content_parts = [f"태그 유형: {tag_type}"]
    if ga4_measurement_id:
        content_parts.append(
            f"GA4 측정 ID: {ga4_measurement_id}\n"
            f"→ 이 ID로 'GA4 Measurement ID' Constant Variable을 생성하고 "
            f"모든 GA4 Tag의 measurementIdOverride에 사용하세요."
        )
    if user_request:
        content_parts.append(f"사용자 요청 (반드시 이 이벤트들을 모두 설계에 포함할 것):\n{user_request}")
    content_parts.append(
        f"\n수집된 이벤트 (source 없음/datalayer → CE Trigger + DLV, source=dom_extraction → Click Trigger + DOM/CJS):\n{events_summary}"
    )
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
        SystemMessage(content=_PLANNING_SYSTEM),
        HumanMessage(content="\n".join(content_parts)),
    ]
    t_llm = time.perf_counter()
    try:
        response = await make_chat_llm(model=llm_model("planning")).ainvoke(messages)
    except Exception as e:
        logger.error(
            f"[Planning] LLM 호출 실패 wall_s={time.perf_counter() - t_llm:.2f} "
            f"→ 빈 설계안 반환: {e}"
        )
        return {"variables": [], "triggers": [], "tags": []}
    token_tracker.track("planning", response)
    raw_plan = response.content or ""
    logger.info(
        f"[Planning] LLM 완료 wall_s={time.perf_counter() - t_llm:.2f} reply_chars={len(raw_plan)}"
    )

    plan = parse_llm_json(raw_plan, fallback=None)
    if isinstance(plan, dict) and plan:
        return plan

    logger.warning(f"[Planning] JSON 파싱 실패: {raw_plan[:300]}")
    return {"variables": [], "triggers": [], "tags": []}
