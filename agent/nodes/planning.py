"""Node 5: Planning Agent.

수집된 이벤트를 분석하고 Variable/Trigger/Tag 설계안을 생성합니다.
HITL(Human-in-the-loop): 터미널에서 y/n으로 승인을 받고,
n이면 피드백을 받아 재설계합니다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

import time

from agent.canplan import (
    build_evidence_pack,
    canplan_json_schema,
    normalize_draft_plan,
    summarize_issues,
)
from agent.canplan.normalize import canplan_hash
from agent.request_events import resolve_selected_events
from agent.state import GTMAgentState
from browser.listener import filter_signal_datalayer_events
from config.llm_models_loader import llm_model
from docs.fetcher import fetch_docs_for_media
from utils import logger, token_tracker
from utils.llm_json import make_chat_llm, parse_llm_json
from utils.ui_emitter import emit, update_state, write_plan

_PLANNING_SYSTEM = """당신은 GTM(Google Tag Manager) 전문가입니다.
수집된 이벤트를 분석하고 GTM DraftPlan(JSON)을 생성하세요.

우선 목표:
- 가능하면 CanPlan 스키마(`version=canplan/1`) 형태로 출력하세요.
- 어려우면 legacy(variables/triggers/tags) 형태도 허용되며, 후처리 정규화가 수행됩니다.

== 핵심 판단 규칙: 이벤트별 source 필드를 보고 트리거 타입을 결정하세요 ==

각 이벤트의 source 필드:
- source가 없거나 "datalayer" 또는 "datalayer+dom" → dataLayer에서 발화한 이벤트
  → Custom Event Trigger (type: customEvent) + DLV Variable 사용
- source = "dom_extraction" → dataLayer 미발화, DOM에서 추출한 이벤트
  → Click Trigger (type: click) + DOM/CJS Variable 사용

이벤트 이름이 GA4 공식 명칭(add_to_cart)이 아니더라도(addToCart, AddCart 등)
dataLayer에서 실제 발화된 이벤트라면 해당 이름 그대로 CE Trigger를 만드세요.
(customEventFilter의 arg1에 실제 이벤트명을 그대로 사용)

아래로 전달되는 **수집 이벤트 JSON**은 `gtm.*`, `ajax*` 등 시스템·기술용 `event` 이름을 **제외(denylist)** 한 뒤의 목록입니다.
비표준 이름은 제외하지 않으므로, 그중에서 GTM 태그 설계에 필요한 이벤트와 페이로드만 골라 반영하세요.

== Variable 타입 가이드 ==

dataLayer 이벤트용:
- DLV (type "v"): dataLayer.push된 값 참조
  parameters: [{"type":"integer","key":"dataLayerVersion","value":"2"}, {"type":"template","key":"name","value":"ecommerce.items"}]

DOM 추출 이벤트용:
- DOM Element Variable (type "d"): **공식 GTM REST API는 ID 기반 선택만 지원**.
  - parameters: [{"type":"template","key":"elementId","value":"myId"}, {"type":"template","key":"attributeName","value":""}]
  - (attributeName 빈 문자열이면 textContent)
- CSS selector로 값을 추출해야 하면 **type "d" 대신 처음부터 type "jsm"** (Custom JavaScript)로 설계하세요.
  Node 6에서 type "d" + CSS 셀렉터 설계는 자동으로 "jsm"으로 변환되지만, 설계 단계에서 이미 jsm으로 내놓는 편이 가독성이 좋습니다.
- Custom JavaScript Variable (type "jsm"): JS 함수로 값 가공
  - **집계 CJS(예: ecommerce_items)는 개별 DOM/CJS 변수를 {{변수명}}으로 참조**하고
    `document.querySelector`는 개별 변수 안에서만 호출하세요. 셀렉터가 두 곳에 중복되면
    유지보수 비용이 커집니다.

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
    },
    {
      "name": "DOM - item_name",
      "type": "jsm",
      "parameters": [
        {
          "type": "template",
          "key": "javascript",
          "value": "function(){var el=document.querySelector(\"meta[property='og:title']\");if(!el)return '';return el.getAttribute('content')||'';}"
        }
      ]
    },
    {
      "name": "CJS - ecommerce_items",
      "type": "jsm",
      "parameters": [
        {
          "type": "template",
          "key": "javascript",
          "value": "function(){return [{item_name:{{DOM - item_name}}, price:{{CJS - item_price}}}];}"
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
2. **GTM Custom JS Variable 안의 `{{변수명}}`은 JS 실행 전에 GTM이 값으로 치환**합니다(문자열/숫자 리터럴로 삽입).
   → 집계 CJS는 개별 DOM/CJS 변수를 `{{변수명}}`으로 참조하고, 같은 selector를 `document.querySelector`로 또 쓰지 마세요.
   (문자열 값이 따옴표를 포함해 JS 파싱을 깨뜨릴 수 있는 경우에만 예외적으로 직접 querySelector 사용)
3. GA4 측정 ID(G-XXXXXXXX)가 있으면 Constant Variable "GA4 Measurement ID"를 만들고 모든 GA4 Tag에 사용
4. DOM 추출 이벤트의 가격은 CJS로 숫자만 추출 (parseFloat), items도 CJS로 별도 구성
5. DOM Element 변수(type "d")는 **HTML id 기반일 때만** 사용. CSS selector가 필요하면 **type "jsm"**으로 개별 변수를 만들고 집계 CJS는 그 변수를 참조.
"""


def _planning_entry_event_name(entry: dict) -> str | None:
    """수집/수동 이벤트 엔트리에서 GA4 `event` 문자열 추출(소문자)."""
    if entry.get("source") == "manual" and entry.get("manual_event_name"):
        t = str(entry["manual_event_name"]).strip()
        return t.lower() if t else None
    d = entry.get("data")
    if not isinstance(d, dict):
        return None
    ev = d.get("event")
    if ev is None or not isinstance(ev, str):
        return None
    t = ev.strip()
    return t.lower() if t else None


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
        all_events.append(
            {
                "data": schema,
                "source": "manual",
                "manual_event_name": event_name,
            }
        )

    explicit_scope = resolve_selected_events(state)
    if explicit_scope is not None:
        allowed = set(explicit_scope)
        scope_src = "UI 선택" if state.get("selected_events") else "요청 괄호"
        before_n = len(all_events)
        all_events = [
            e
            for e in all_events
            if (n := _planning_entry_event_name(e)) is not None and n in allowed
        ]
        if before_n != len(all_events):
            logger.info(
                f"[Planning] {scope_src} 기준 이벤트 풀 필터: {before_n} → {len(all_events)} "
                f"(허용={sorted(allowed)})"
            )

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
    signal_events = filter_signal_datalayer_events(all_events)
    evidence_pack = build_evidence_pack({**state, "captured_events": signal_events})
    logger.info(
        f"[Planning] 총 이벤트(raw): {[e.get('data', {}).get('event') for e in all_events]}"
    )
    logger.info(
        f"[Planning] 시그널 이벤트(노이즈 제외): {[e.get('data', {}).get('event') for e in signal_events]}"
    )

    # 설계안 생성 루프 (HITL 피드백 반영).
    # 재설계 시 이전 CanPlan + normalize_errors를 LLM에 재주입(§Phase 2 Done-when).
    normalize_retry_count = 0
    prev_canplan: dict | None = None
    prev_normalize_errors: list[dict] = []
    while True:
        draft_plan = await _generate_plan(
            tag_type,
            signal_events,
            existing_config,
            doc_context,
            hitl_feedback,
            dom_context,
            user_request=user_request,
            ga4_measurement_id=ga4_measurement_id,
            explicit_event_scope=explicit_scope,
            evidence_pack=evidence_pack,
            previous_canplan=prev_canplan,
            previous_normalize_errors=prev_normalize_errors,
        )
        canplan, normalize_errors = normalize_draft_plan(
            draft_plan,
            allowed_events=explicit_scope
            or [
                e.get("event", "")
                for e in evidence_pack.get("events", [])
                if e.get("event")
            ],
            ga4_measurement_id=ga4_measurement_id,
            evidence_pack=evidence_pack,
        )
        _dump_canplan_artifacts(
            draft_plan=draft_plan,
            canplan=canplan,
            normalize_errors=normalize_errors,
        )

        strict_mode = os.environ.get("STRICT_CANPLAN", "0").lower() in ("1", "true", "yes")
        has_blocking_errors = any(err.get("severity") == "error" for err in normalize_errors)

        if strict_mode and has_blocking_errors:
            if normalize_retry_count >= 1:
                _dur = int((time.time() - _started) * 1000)
                emit("node_exit", node_id=5, status="failed", duration_ms=_dur)
                update_state(nodes_status={"planning": "failed"})
                return {
                    **state,
                    "draft_plan": draft_plan,
                    "evidence_pack": evidence_pack,
                    "canplan": canplan,
                    "normalize_errors": normalize_errors,
                    "error": "CanPlan 정규화 오류로 설계안을 확정할 수 없습니다.",
                }
            normalize_retry_count += 1
            hitl_feedback = (
                "정규화 오류를 수정하세요: "
                + json.dumps(normalize_errors, ensure_ascii=False)
            )
            prev_canplan = canplan or prev_canplan
            prev_normalize_errors = list(normalize_errors)
            logger.warning(
                f"[Planning] STRICT_CANPLAN=1 정규화 오류 → LLM 재시도 "
                f"errors={summarize_issues(normalize_errors).get('error_codes')}"
            )
            continue
        plan = canplan if canplan else draft_plan

        # 설계안 출력
        print("\n" + "="*60)
        print("[GTM 설계안]")
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        print("="*60)

        # UI에 HITL 요청 emit
        write_plan(plan)
        emit(
            "hitl_request",
            kind="plan",
            plan=plan,
            normalize_errors=normalize_errors,
            canplan_hash=canplan_hash(canplan) if canplan else "",
        )
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
                "draft_plan": draft_plan,
                "evidence_pack": evidence_pack,
                "canplan": canplan,
                "normalize_errors": normalize_errors,
                "canplan_hash": canplan_hash(canplan) if canplan else "",
                "plan_approved": True,
                "hitl_feedback": "",
            }
        else:
            hitl_feedback = hitl_feedback_new
            prev_canplan = canplan or prev_canplan
            prev_normalize_errors = list(normalize_errors)
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
                except Exception:
                    time.sleep(1)
                    continue
                # workspace_full 등 타 HITL 응답이면 계속 대기 (다른 노드가 처리)
                kind = resp.get("kind", "plan")
                if kind != "plan":
                    continue
                approved = resp.get("approved", True)
                feedback = resp.get("feedback", "")
                print(f"[Planning] UI 응답 수신: {'승인' if approved else '거부'}")
                return ("y" if approved else "n"), feedback
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
    signal_events: list[dict],
    existing_config: dict,
    doc_context: str,
    feedback: str,
    dom_context: str = "",
    user_request: str = "",
    ga4_measurement_id: str = "",
    explicit_event_scope: list[str] | None = None,
    evidence_pack: dict | None = None,
    previous_canplan: dict | None = None,
    previous_normalize_errors: list[dict] | None = None,
) -> dict:
    """LLM으로 GTM 설계안을 생성합니다."""
    # source 필드를 포함해서 LLM에 전달 (이벤트별 DL/DOM 판단 근거)
    # 노이즈는 filter_signal_datalayer_events에서 이미 제거된 목록만 받음
    events_summary = json.dumps(
        [{"source": e.get("source", "datalayer"), **e.get("data", e)} for e in signal_events[:50]],
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
        content_parts.append(f"사용자 요청:\n{user_request}")
    if explicit_event_scope:
        content_parts.append(
            "중요: 요청에 `(이벤트1, …)` 형태의 **명시 목록**이 있습니다. "
            "GTM 설계(tags/triggers)는 **이 목록에 있는 이벤트만** 다루세요. "
            "목록에 없는 GA4 이벤트용 태그·트리거는 만들지 마세요.\n"
            f"허용 이벤트: {', '.join(explicit_event_scope)}"
        )
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
    if evidence_pack:
        content_parts.append(
            "\nEvidencePack (요약):\n"
            + json.dumps(evidence_pack, ensure_ascii=False)[:5000]
        )
    if previous_canplan:
        content_parts.append(
            "\n직전 CanPlan (참고; 동일한 구성요소는 이름/의미 유지하며 수정):\n"
            + json.dumps(previous_canplan, ensure_ascii=False)[:4000]
        )
    if previous_normalize_errors:
        summary = summarize_issues(previous_normalize_errors)
        content_parts.append(
            "\n직전 정규화 결과(반드시 해결):\n"
            + json.dumps(
                {
                    "summary": summary,
                    "issues": previous_normalize_errors[:25],
                },
                ensure_ascii=False,
            )
        )
    content_parts.append(
        "\nCanPlan JSON Schema:\n"
        + json.dumps(canplan_json_schema(), ensure_ascii=False)
    )

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


def _dump_canplan_artifacts(
    *,
    draft_plan: dict,
    canplan: dict,
    normalize_errors: list[dict],
) -> None:
    run_dir = logger.run_dir()
    if run_dir is None:
        return
    try:
        _write_json(run_dir / "canplan.json", canplan or {})
        _write_json(run_dir / "normalize_errors.json", normalize_errors or [])
        _write_json(
            run_dir / "plan_vs_canplan.diff.json",
            _build_plan_vs_canplan_diff(draft_plan or {}, canplan or {}),
        )
    except Exception as e:
        logger.warning(f"[Planning] canplan 아티팩트 덤프 실패: {e}")


def _write_json(path: Path, payload: dict | list) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _extract_legacy_names(draft_plan: dict) -> dict:
    return {
        "variables": sorted(
            str(v.get("name", "")).strip()
            for v in (draft_plan.get("variables") or [])
            if isinstance(v, dict) and str(v.get("name", "")).strip()
        ),
        "triggers": sorted(
            str(v.get("name", "")).strip()
            for v in (draft_plan.get("triggers") or [])
            if isinstance(v, dict) and str(v.get("name", "")).strip()
        ),
        "tags": sorted(
            str(v.get("name", "")).strip()
            for v in (draft_plan.get("tags") or [])
            if isinstance(v, dict) and str(v.get("name", "")).strip()
        ),
    }


def _extract_canplan_names(canplan: dict) -> dict:
    return {
        "variables": sorted(
            str(v.get("name", "")).strip()
            for v in (canplan.get("variables") or [])
            if isinstance(v, dict) and str(v.get("name", "")).strip()
        ),
        "triggers": sorted(
            str(v.get("name", "")).strip()
            for v in (canplan.get("triggers") or [])
            if isinstance(v, dict) and str(v.get("name", "")).strip()
        ),
        "tags": sorted(
            str(v.get("name", "")).strip()
            for v in (canplan.get("tags") or [])
            if isinstance(v, dict) and str(v.get("name", "")).strip()
        ),
    }


def _build_plan_vs_canplan_diff(draft_plan: dict, canplan: dict) -> dict:
    legacy = _extract_legacy_names(draft_plan)
    canon = _extract_canplan_names(canplan)
    out: dict = {}
    for key in ("variables", "triggers", "tags"):
        lhs = set(legacy.get(key, []))
        rhs = set(canon.get(key, []))
        out[key] = {
            "legacy_count": len(lhs),
            "canplan_count": len(rhs),
            "added_in_canplan": sorted(rhs - lhs),
            "missing_in_canplan": sorted(lhs - rhs),
        }
    out["legacy_has_canplan_version"] = draft_plan.get("version") == "canplan/1"
    out["canplan_hash"] = canplan_hash(canplan) if canplan else ""
    return out
