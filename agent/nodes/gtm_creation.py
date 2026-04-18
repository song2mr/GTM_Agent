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
from utils.ui_emitter import emit, update_state


def _sync_created_resources_ui(
    workspace_id: str,
    created_variables: list[dict],
    created_triggers: list[dict],
    created_tags: list[dict],
    *,
    gtm_node_status: str,
) -> None:
    """Resources 탭(state.json)이 report.md와 동일 스냅샷을 보도록 GTM 생성 결과를 기록."""
    update_state(
        nodes_status={"gtm_creation": gtm_node_status},
        workspace_id=workspace_id or "",
        created_variables=[
            {"name": v.get("name", ""), "id": v.get("variableId", "")}
            for v in created_variables
        ],
        created_triggers=[
            {"name": t.get("name", ""), "id": t.get("triggerId", "")}
            for t in created_triggers
        ],
        created_tags=[
            {"name": t.get("name", ""), "id": t.get("tagId", "")} for t in created_tags
        ],
    )


async def gtm_creation(state: GTMAgentState) -> GTMAgentState:
    """Node 6: Workspace 생성 + Variable/Trigger/Tag 생성."""
    emit("node_enter", node_id=6, node_key="gtm_creation", title="GTM Creation")
    update_state(current_node=6, nodes_status={"gtm_creation": "run"})
    plan: dict = state.get("plan", {})
    if not plan:
        emit("node_exit", node_id=6, status="failed", duration_ms=0)
        update_state(nodes_status={"gtm_creation": "failed"})
        return {**state, "error": "설계안이 없습니다."}

    # Plan 자동 보정: 누락 트리거 생성 + 잘못된 firing_trigger_names 수정
    plan = _fix_plan(plan, state.get("captured_events", []))

    client = GTMClient(
        account_id=state.get("account_id", ""),
        container_id=state.get("container_id", ""),
    )

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
                emit("node_exit", node_id=6, status="failed", duration_ms=0)
                update_state(nodes_status={"gtm_creation": "failed"})
                return {
                    **state,
                    "error": "Workspace 생성 실패: Rate Limit 초과 + 재사용 가능한 Workspace 없음",
                }

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
        emit("node_exit", node_id=6, status="failed", duration_ms=0)
        _sync_created_resources_ui(
            workspace_id,
            created_variables,
            created_triggers,
            created_tags,
            gtm_node_status="failed",
        )
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

    for v in created_variables:
        emit("gtm_created", kind="variable", name=v.get("name", ""), operation="create")
    for t in created_triggers:
        emit("gtm_created", kind="trigger", name=t.get("name", ""), operation="create")
    for t in created_tags:
        emit("gtm_created", kind="tag", name=t.get("name", ""), operation="create")

    emit("node_exit", node_id=6, status="done", duration_ms=0)
    _sync_created_resources_ui(
        workspace_id,
        created_variables,
        created_triggers,
        created_tags,
        gtm_node_status="done",
    )

    return {
        **state,
        "workspace_id": workspace_id,
        "created_variables": created_variables,
        "created_triggers": created_triggers,
        "created_tags": created_tags,
        "error": None,
    }


_VARIABLE_TYPE_MAP = {
    "js": "jsm",   # LLM이 "js"로 생성하는 경우 GTM API의 정식 타입으로 보정
}


def _build_variable(spec: dict) -> GTMVariable:
    raw_type = spec["type"]
    var_type = _VARIABLE_TYPE_MAP.get(raw_type, raw_type)
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
    return GTMVariable(name=spec["name"], type=var_type, parameters=params)


_INTERNAL_EVENTS = {"gtm.js", "gtm.dom", "gtm.load"}


def _fix_plan(plan: dict, captured_events: list[dict]) -> dict:
    """LLM이 생성한 plan의 구조적 오류를 자동 보정합니다.

    1. DL 이벤트마다 CE Trigger가 없으면 자동 생성
    2. Tag의 firing_trigger_names가 비어 있으면 이벤트명 기반으로 수정
    3. 잘못된 firing_trigger_names 참조 수정
    """
    dl_event_names = [
        e.get("data", {}).get("event")
        for e in captured_events
        if e.get("source") not in ("dom_extraction",)
        and e.get("data", {}).get("event") not in _INTERNAL_EVENTS
        and e.get("data", {}).get("event")
    ]
    # 중복 제거, 순서 유지
    seen: set = set()
    dl_event_names = [x for x in dl_event_names if x and not (x in seen or seen.add(x))]

    triggers: list[dict] = list(plan.get("triggers", []))
    existing_trigger_names = {t.get("name", "") for t in triggers}

    # DL 이벤트별 CE Trigger 누락 시 자동 생성
    for event_name in dl_event_names:
        expected_name = f"CE - {event_name}"
        if expected_name not in existing_trigger_names:
            print(f"[GTMCreation] Trigger 누락 감지 → 자동 생성: {expected_name}")
            triggers.append({
                "name": expected_name,
                "type": "customEvent",
                "customEventFilter": [
                    {
                        "type": "equals",
                        "parameter": [
                            {"type": "template", "key": "arg0", "value": "{{_event}}"},
                            {"type": "template", "key": "arg1", "value": event_name},
                        ],
                    }
                ],
            })
            existing_trigger_names.add(expected_name)

    dl_event_name_set = set(dl_event_names)

    # Tag의 firing_trigger_names 보정
    tags: list[dict] = list(plan.get("tags", []))
    for tag in tags:
        # parameters에서 eventName 추출
        event_name_val = next(
            (p.get("value") for p in tag.get("parameters", []) if p.get("key") == "eventName"),
            None,
        )
        if not event_name_val:
            continue

        expected_ce = f"CE - {event_name_val}"
        firing = tag.get("firing_trigger_names", [])

        # DL 이벤트 태그는 반드시 CE Trigger 사용
        if event_name_val in dl_event_name_set:
            if expected_ce in existing_trigger_names:
                if firing != [expected_ce]:
                    print(
                        f"[GTMCreation] DL 이벤트 태그 '{tag.get('name')}' → "
                        f"firing_trigger_names를 [{expected_ce}]로 교정"
                    )
                    tag["firing_trigger_names"] = [expected_ce]
            continue

        # 비DL 이벤트 (Click Trigger 대상)
        if not firing:
            # 빈 경우 → 이벤트명 기반 CE Trigger 또는 Click Trigger로 대입
            if expected_ce in existing_trigger_names:
                print(f"[GTMCreation] Tag '{tag.get('name')}' firing_trigger_names 비어 있음 → {expected_ce} 자동 연결")
                tag["firing_trigger_names"] = [expected_ce]
        else:
            # 존재하지 않는 트리거 참조 수정
            corrected = []
            for tname in firing:
                if tname in existing_trigger_names:
                    corrected.append(tname)
                else:
                    fallback = expected_ce
                    if fallback in existing_trigger_names:
                        print(f"[GTMCreation] Tag '{tag.get('name')}': '{tname}' 없음 → {fallback}로 교체")
                        corrected.append(fallback)
            if corrected:
                tag["firing_trigger_names"] = corrected

    return {**plan, "triggers": triggers, "tags": tags}


def _fix_custom_event_filter(custom_event_filter: list[dict]) -> list[dict]:
    """customEventFilter의 arg0를 GTM API 규격인 '{{_event}}'로 강제 수정합니다.

    GTM API는 customEventFilter의 첫 번째 파라미터(arg0)가 반드시 '{{_event}}'여야 합니다.
    LLM이 DLV 변수 참조를 넣는 경우가 있어 여기서 교정합니다.
    """
    fixed = []
    for condition in custom_event_filter:
        params = condition.get("parameter", [])
        new_params = []
        for p in params:
            if p.get("key") == "arg0":
                # 항상 {{_event}} 로 강제
                new_params.append({"type": "template", "key": "arg0", "value": "{{_event}}"})
            else:
                new_params.append(p)
        fixed.append({**condition, "parameter": new_params})
    return fixed


def _build_trigger(spec: dict) -> GTMTrigger:
    # LLM이 "filters"(복수)로 생성하는 경우도 처리
    filter_list = spec.get("filter", spec.get("filters", []))
    raw_cef = spec.get("customEventFilter", [])
    fixed_cef = _fix_custom_event_filter(raw_cef) if raw_cef else []
    return GTMTrigger(
        name=spec["name"],
        type=spec["type"],
        custom_event_filter=fixed_cef,
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
