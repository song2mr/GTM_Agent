"""Node 6: GTM Creation Agent.

신규 Workspace 생성 후 Variable → Trigger → Tag 순서로 GTM 리소스를 생성합니다.
이름 충돌 시 Update(덮어쓰기)를 호출합니다.
"""

from __future__ import annotations

import time
from datetime import datetime

from agent.state import GTMAgentState
from gtm.client import GTMClient
from gtm.models import GTMParameter, GTMTag, GTMTrigger, GTMVariable


async def gtm_creation(state: GTMAgentState) -> GTMAgentState:
    """Node 6: Workspace 생성 + Variable/Trigger/Tag 생성."""
    plan: dict = state.get("plan", {})
    if not plan:
        return {**state, "error": "설계안이 없습니다."}

    client = GTMClient()

    created_variables: list[dict] = []
    created_triggers: list[dict] = []
    created_tags: list[dict] = []
    trigger_name_to_id: dict[str, str] = {}
    workspace_id = ""

    try:
        # 신규 Workspace 생성 — 실행마다 타임스탬프로 구분 (429 시 재시도 + fallback)
        run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        workspace_name = f"gtm-ai-{run_ts}"
        for attempt in range(3):
            try:
                workspace = client.create_workspace(workspace_name)
                workspace_id = workspace["workspaceId"]
                print(f"[GTMCreation] 신규 Workspace 생성: {workspace_name} (id={workspace_id})")
                break
            except Exception as e:
                if "rateLimitExceeded" in str(e) or "429" in str(e):
                    wait_sec = 30 * (attempt + 1)
                    print(f"[GTMCreation] 429 Rate Limit — {wait_sec}초 후 재시도 ({attempt+1}/3)...")
                    time.sleep(wait_sec)
                else:
                    raise
        else:
            # 3회 재시도 후 실패 → 기존 gtm-ai-* workspace 재사용 (Rate Limit 회피)
            print("[GTMCreation] Rate Limit 지속 → 기존 Workspace 재사용 시도...")
            existing_ws = client.list_workspaces()
            ai_ws = sorted(
                [w for w in existing_ws if w.get("name", "").startswith("gtm-ai-")],
                key=lambda w: w.get("workspaceId", "0"),
                reverse=True,
            )
            if ai_ws:
                workspace_id = ai_ws[0]["workspaceId"]
                print(f"[GTMCreation] 기존 Workspace 재사용: {ai_ws[0]['name']} (id={workspace_id})")
            else:
                return {**state, "error": "Workspace 생성 실패: Rate Limit 초과 + 재사용 가능한 Workspace 없음"}

        # 1. Variable 생성
        for var_spec in plan.get("variables", []):
            variable = _build_variable(var_spec)
            result = client.create_or_update_variable(workspace_id, variable)
            created_variables.append(result)

        # 2. Trigger 생성 (이름 → ID 매핑 저장)
        for trig_spec in plan.get("triggers", []):
            trigger = _build_trigger(trig_spec)
            result = client.create_or_update_trigger(workspace_id, trigger)
            created_triggers.append(result)
            trigger_name_to_id[result["name"]] = result["triggerId"]

        # 3. Tag 생성 (firing_trigger_names → IDs로 변환)
        for tag_spec in plan.get("tags", []):
            firing_names = tag_spec.get("firing_trigger_names", [])
            firing_ids = [
                trigger_name_to_id[name]
                for name in firing_names
                if name in trigger_name_to_id
            ]
            tag = _build_tag(tag_spec, firing_ids)
            result = client.create_or_update_tag(workspace_id, tag)
            created_tags.append(result)

    except Exception as e:
        error_msg = f"GTM 리소스 생성 중 오류: {e}"
        print(f"[GTMCreation] {error_msg}")
        return {
            **state,
            "workspace_id": workspace_id,
            "created_variables": created_variables,
            "created_triggers": created_triggers,
            "created_tags": created_tags,
            "error": error_msg,
        }

    print(
        f"[GTMCreation] 완료 — "
        f"Variable {len(created_variables)}개, "
        f"Trigger {len(created_triggers)}개, "
        f"Tag {len(created_tags)}개"
    )

    return {
        **state,
        "workspace_id": workspace_id,
        "created_variables": created_variables,
        "created_triggers": created_triggers,
        "created_tags": created_tags,
        "error": None,
    }


def _build_variable(spec: dict) -> GTMVariable:
    params = [
        GTMParameter(
            type=p["type"],
            key=p["key"],
            value=p.get("value", ""),
            list_=p.get("list", []),
            map_=p.get("map", []),
        )
        for p in spec.get("parameters", [])
    ]
    return GTMVariable(name=spec["name"], type=spec["type"], parameters=params)


def _build_trigger(spec: dict) -> GTMTrigger:
    # LLM이 "filters"(복수)로 생성하는 경우도 처리
    filter_list = spec.get("filter", spec.get("filters", []))
    return GTMTrigger(
        name=spec["name"],
        type=spec["type"],
        custom_event_filter=spec.get("customEventFilter", []),
        filter_=filter_list,
        auto_event_filter=spec.get("autoEventFilter", []),
        parameter=spec.get("parameter", []),  # elementVisibility 등에서 사용
    )


def _build_tag(spec: dict, firing_ids: list[str]) -> GTMTag:
    params = [
        GTMParameter(
            type=p["type"],
            key=p["key"],
            value=p.get("value", ""),
            list_=p.get("list", []),
            map_=p.get("map", []),
        )
        for p in spec.get("parameters", [])
    ]

    # event_parameters를 GTM API list/map 형식으로 변환
    # 플래닝 LLM 출력: [{"key": "items", "value": "{{CJS - ecommerce_items}}"}]
    # GTM API 형식: {"type": "list", "key": "eventParameters", "list": [{"type": "map", "map": [...]}]}
    event_params = spec.get("event_parameters", [])
    if event_params:
        param_maps = [
            {
                "type": "map",
                "map": [
                    {"type": "template", "key": "name", "value": ep["key"]},
                    {"type": "template", "key": "value", "value": ep["value"]},
                ],
            }
            for ep in event_params
            if "key" in ep and "value" in ep
        ]
        if param_maps:
            params.append(GTMParameter(
                type="list",
                key="eventParameters",
                list_=param_maps,
            ))

    return GTMTag(
        name=spec["name"],
        type=spec["type"],
        parameters=params,
        firing_trigger_ids=firing_ids,
    )
