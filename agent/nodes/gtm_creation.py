"""Node 6: GTM Creation Agent.

신규 Workspace 생성 후 Variable → Trigger → Tag 순서로 GTM 리소스를 생성합니다.
이름 충돌 시 Update(덮어쓰기)를 호출합니다.
"""

from __future__ import annotations

import time
from datetime import datetime
import os

from agent.state import GTMAgentState
from gtm.client import GTMClient
from gtm.dom_variable import normalize_dom_element_parameters
from gtm.models import GTMParameter, GTMTag, GTMTrigger, GTMVariable
from gtm.spec_builder import build_specs_from_canplan
from utils import logger
from utils.ui_emitter import emit, update_state

from agent.workspace_hitl import (
    GTM_WORKSPACE_LIMIT,
    sorted_ai_workspaces,
    wait_for_workspace_full_decision,
)


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
    canplan: dict = state.get("canplan", {})
    effective_plan = canplan if canplan else plan
    if not effective_plan:
        emit("node_exit", node_id=6, status="failed", duration_ms=0)
        update_state(nodes_status={"gtm_creation": "failed"})
        return {**state, "error": "설계안이 없습니다."}
    strict_mode = os.environ.get("STRICT_CANPLAN", "0").lower() in ("1", "true", "yes")

    client = GTMClient(
        account_id=state.get("account_id", ""),
        container_id=state.get("container_id", ""),
    )

    created_variables: list[dict] = []
    created_triggers: list[dict] = []
    created_tags: list[dict] = []
    trigger_name_to_id: dict[str, str] = {}
    workspace_id = (state.get("workspace_id") or "").strip()

    try:
        if workspace_id:
            logger.info(
                f"[GTMCreation] workspace_id 이미 지정됨(runner 사전 HITL 또는 폼) → "
                f"한도·신규 생성·HITL 생략, id={workspace_id}"
            )
        else:
            existing_ws = client.list_workspaces()
            n_ws = len(existing_ws)
            _preview = ", ".join(
                w.get("name", w.get("workspaceId", "?")) for w in existing_ws[:5]
            )
            logger.info(
                f"[GTMCreation] workspaces.list 개수={n_ws} (한도 {GTM_WORKSPACE_LIMIT}) "
                f"— {'HITL 분기' if n_ws >= GTM_WORKSPACE_LIMIT else '신규 생성 분기'} "
                f"| 이름 샘플: {_preview or '(없음)'}"
            )

            # 무료 컨테이너 워크스페이스 상한(3) — 꽉 찼으면 사용자에게 HITL로 물어본다.
            if n_ws >= GTM_WORKSPACE_LIMIT:
                ai_ws = sorted_ai_workspaces(existing_ws)
                logger.info(
                    f"[GTMCreation] 워크스페이스 {n_ws}개(한도 {GTM_WORKSPACE_LIMIT}) — "
                    f"HITL로 재사용 여부 확인 (gtm-ai-* 후보 {len(ai_ws)}개)"
                )
                decision, target_ws_id = wait_for_workspace_full_decision(
                    hitl_mode=state.get("hitl_mode", "cli"),
                    workspaces=existing_ws,
                    ai_workspaces=ai_ws,
                    current_count=n_ws,
                    limit=GTM_WORKSPACE_LIMIT,
                    mark_gtm_node_hitl_wait=True,
                    log_prefix="[GTMCreation]",
                )
                if decision == "cancel":
                    msg = (
                        f"워크스페이스가 {n_ws}개로 가득 차 사용자가 실행을 중단했습니다. "
                        "GTM에서 불필요한 작업공간을 삭제한 뒤 다시 시도해 주세요."
                    )
                    emit("hitl_decision", approved=False, feedback="workspace_full_cancel")
                    emit("node_exit", node_id=6, status="failed", duration_ms=0)
                    update_state(nodes_status={"gtm_creation": "failed"})
                    return {**state, "error": msg}

                # reuse — target_ws_id 는 사용자가 고른 워크스페이스(없으면 ai_ws[0])
                workspace_id = target_ws_id or (ai_ws[0]["workspaceId"] if ai_ws else "")
                if not workspace_id:
                    msg = (
                        "재사용할 수 있는 `gtm-ai-*` 또는 사용자 지정 워크스페이스가 없습니다. "
                        "GTM에서 워크스페이스를 비우고 다시 시도해 주세요."
                    )
                    emit("hitl_decision", approved=False, feedback="workspace_full_no_target")
                    emit("node_exit", node_id=6, status="failed", duration_ms=0)
                    update_state(nodes_status={"gtm_creation": "failed"})
                    return {**state, "error": msg}
                chosen_name = next(
                    (w.get("name", "") for w in existing_ws if w.get("workspaceId") == workspace_id),
                    "",
                )
                emit("hitl_decision", approved=True, feedback=f"reuse:{chosen_name or workspace_id}")
                emit(
                    "thought",
                    who="tool",
                    label="GTM Workspace",
                    text=(
                        f"사용자 승인 → 기존 작업공간 `{chosen_name or workspace_id}` 에 설계안을 적용합니다."
                    ),
                    kind="plain",
                )
                print(
                    f"[GTMCreation] HITL 승인 → 기존 Workspace 재사용: "
                    f"{chosen_name or workspace_id} (id={workspace_id})"
                )

            else:
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
                    ai_ws = sorted_ai_workspaces(existing_ws)
                    if ai_ws:
                        workspace_id = ai_ws[0]["workspaceId"]
                        print(f"[GTMCreation] 기존 Workspace 재사용: {ai_ws[0]['name']} (id={workspace_id})")
                        emit(
                            "thought",
                            who="tool",
                            label="GTM Workspace",
                            text=(
                                "API Rate Limit으로 신규 작업공간 생성에 실패해, "
                                f"기존 `{ai_ws[0].get('name', '')}` 에 설계안을 적용합니다."
                            ),
                            kind="plain",
                        )
                    else:
                        emit("node_exit", node_id=6, status="failed", duration_ms=0)
                        update_state(nodes_status={"gtm_creation": "failed"})
                        return {
                            **state,
                            "error": "Workspace 생성 실패: Rate Limit 초과 + 재사용 가능한 Workspace 없음",
                        }

        use_canplan = isinstance(effective_plan, dict) and effective_plan.get("version") == "canplan/1"

        if use_canplan:
            variables, triggers, tags = build_specs_from_canplan(effective_plan)
        else:
            if strict_mode:
                raise RuntimeError("STRICT_CANPLAN=1 이지만 CanPlan이 없어 레거시 경로를 차단했습니다.")
            # 레거시 호환 경로: 기존 plan 보정 후 빌드 (공식 경로는 CanPlan, 향후 제거 예정).
            logger.warning(
                "[GTMCreation] 레거시 경로 사용 중 — STRICT_CANPLAN=1 설정을 권장합니다. "
                "(레거시 경로는 Phase 5에서 제거될 예정)"
            )
            emit(
                "thought",
                who="agent",
                label="GTM Creation",
                text=(
                    "⚠ 레거시 DraftPlan 경로로 리소스를 생성합니다. 다음 실행부터는 "
                    "STRICT_CANPLAN=1 로 CanPlan 전환을 권장합니다."
                ),
                kind="plain",
            )
            _reject_in_set_in_legacy(plan)
            compat_plan = _fix_plan(plan, state.get("captured_events", []))
            variables = []
            for var_spec in compat_plan.get("variables", []):
                variable = _build_variable(var_spec)
                if variable is not None:
                    variables.append(variable)
            triggers = [_build_trigger(trig_spec) for trig_spec in compat_plan.get("triggers", [])]
            tags = []
            for tag_spec in compat_plan.get("tags", []):
                firing_names = tag_spec.get("firing_trigger_names", [])
                tags.append((tag_spec, firing_names))

        # 1. Variable 생성
        for variable in variables:
            result = client.create_or_update_variable(workspace_id, variable)
            created_variables.append(result)

        # 2. Trigger 생성 (이름 → ID 매핑 저장)
        for trigger in triggers:
            result = client.create_or_update_trigger(workspace_id, trigger)
            created_triggers.append(result)
            trigger_name_to_id[result["name"]] = result["triggerId"]

        # 3. Tag 생성 (firing trigger 이름을 실제 ID로 치환)
        if use_canplan:
            for tag in tags:
                tag.firing_trigger_ids = [
                    trigger_name_to_id.get(name, "")
                    for name in tag.firing_trigger_ids
                    if trigger_name_to_id.get(name)
                ]
                result = client.create_or_update_tag(workspace_id, tag)
                created_tags.append(result)
        else:
            for tag_spec, firing_names in tags:
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


def _build_variable(spec: dict) -> GTMVariable | None:
    """설계안 1건을 GTM 리소스로 변환.

    - ``type: "d"`` (DOM Element) 는 공식 스펙상 ``elementId``(HTML id) 기반만 지원.
      CSS selector가 필요한 케이스는 ``gtm.dom_variable.normalize_dom_element_parameters``
      가 자동으로 ``type: "jsm"`` (Custom JavaScript) 변수로 변환한 튜플을 돌려준다.
    - 정규화 불가(예: CSS selector도 id도 비어있음)면 ``None`` — 상위에서 드롭.
    """
    raw_type = spec["type"]
    var_type = _VARIABLE_TYPE_MAP.get(raw_type, raw_type)
    raw_params = spec.get("parameters", [])

    if var_type == "d":
        normalized = normalize_dom_element_parameters(raw_params)
        if normalized is None:
            print(
                f"[GTMCreation] DOM 변수 '{spec.get('name', '?')}' 드롭: "
                "elementId/CSS selector 값이 비어 정규화 불가"
            )
            return None
        var_type, param_dicts = normalized
    else:
        param_dicts = raw_params

    params = [
        GTMParameter(
            type=p["type"],
            key=p["key"],
            value=p.get("value", ""),
            list_=p.get("list", []),
            map_=p.get("map", []),
        )
        for p in param_dicts
    ]
    return GTMVariable(name=spec["name"], type=var_type, parameters=params)


_INTERNAL_EVENTS = {"gtm.js", "gtm.dom", "gtm.load"}


def _reject_in_set_in_legacy(plan: dict) -> None:
    """레거시 경로에서는 `in_set` / canplan-only op가 섞여 들어오면 즉시 차단(§Phase 3).

    CanPlan 정규화가 비활성화(STRICT_CANPLAN=0)된 경로에서 LLM이 canplan 스타일 op를
    섞어 보내는 경우를 잡는다. 발견 시 RuntimeError를 던져 파이프라인을 멈춘다.
    """
    for trig in plan.get("triggers", []) or []:
        if trig.get("kind") and trig.get("conditions"):
            for cond in trig.get("conditions", []):
                if cond.get("op") == "in_set":
                    raise RuntimeError(
                        f"레거시 경로에서 in_set op는 허용되지 않습니다: {trig.get('name')}. "
                        "STRICT_CANPLAN=1 로 CanPlan 경로를 사용하세요."
                    )


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
