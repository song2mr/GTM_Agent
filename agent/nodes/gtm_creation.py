"""Node 6: GTM Creation Agent.

신규 Workspace 생성 후 Variable → Trigger → Tag 순서로 GTM 리소스를 생성합니다.
이름 충돌 시 Update(덮어쓰기)를 호출합니다.
"""

from __future__ import annotations

from agent.state import GTMAgentState
from gtm.client import GTMClient
from gtm.models import GTMParameter, GTMTag, GTMTrigger, GTMVariable


async def gtm_creation(state: GTMAgentState) -> GTMAgentState:
    """Node 6: Workspace 생성 + Variable/Trigger/Tag 생성."""
    plan: dict = state.get("plan", {})
    if not plan:
        return {**state, "error": "설계안이 없습니다."}

    client = GTMClient()

    # 신규 Workspace 생성
    workspace = client.create_workspace("gtm-ai-workspace")
    workspace_id = workspace["workspaceId"]
    print(f"[GTMCreation] 신규 Workspace 생성: {workspace_id}")

    created_variables: list[dict] = []
    created_triggers: list[dict] = []
    created_tags: list[dict] = []
    trigger_name_to_id: dict[str, str] = {}

    try:
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
    return GTMTrigger(
        name=spec["name"],
        type=spec["type"],
        custom_event_filter=spec.get("customEventFilter", []),
        filter_=spec.get("filter", []),
        auto_event_filter=spec.get("autoEventFilter", []),
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
    return GTMTag(
        name=spec["name"],
        type=spec["type"],
        parameters=params,
        firing_trigger_ids=firing_ids,
    )
