"""Node 5: Planning Agent.

수집된 이벤트를 분석하고 Variable/Trigger/Tag 설계안을 생성합니다.
HITL(Human-in-the-loop): 터미널에서 y/n으로 승인을 받고,
n이면 피드백을 받아 재설계합니다.
"""

from __future__ import annotations

import json

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from agent.state import GTMAgentState
from docs.fetcher import fetch_docs_for_media

_llm = ChatAnthropic(model="claude-sonnet-4-6")

_PLANNING_SYSTEM = """당신은 GTM(Google Tag Manager) 전문가입니다.
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
        {"type": "template", "key": "measurementId", "value": "{{GA4 Measurement ID}}"}
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


async def planning(state: GTMAgentState) -> GTMAgentState:
    """Node 5: GTM 설계안 생성 + HITL."""
    tag_type = state.get("tag_type", "GA4")
    captured_events = state.get("captured_events", [])
    manual_capture_results = state.get("manual_capture_results", {})
    existing_config = state.get("existing_gtm_config", {})
    hitl_feedback = state.get("hitl_feedback", "")

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

    # 설계안 생성 루프 (HITL 피드백 반영)
    while True:
        plan = await _generate_plan(
            tag_type, all_events, existing_config, doc_context, hitl_feedback
        )

        # 설계안 출력
        print("\n" + "="*60)
        print("[GTM 설계안]")
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        print("="*60)

        approval = input("\n이 설계안으로 GTM을 생성하시겠습니까? (y/n): ").strip().lower()

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
            hitl_feedback = input("수정 요청 사항을 입력하세요: ").strip()
            print("[Planning] 피드백 반영하여 재설계합니다...")


async def _generate_plan(
    tag_type: str,
    all_events: list[dict],
    existing_config: dict,
    doc_context: str,
    feedback: str,
) -> dict:
    """LLM으로 GTM 설계안을 생성합니다."""
    events_summary = json.dumps(
        [e.get("data", e) for e in all_events[:20]],
        ensure_ascii=False,
        indent=2,
    )

    content_parts = [
        f"태그 유형: {tag_type}",
        f"\n수집된 이벤트:\n{events_summary}",
    ]
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
    response = await _llm.ainvoke(messages)
    raw = response.content.strip()

    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        print(f"[Planning] JSON 파싱 실패: {raw[:300]}")
        return {"variables": [], "triggers": [], "tags": []}
