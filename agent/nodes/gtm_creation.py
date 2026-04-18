"""Node 6: GTM Creation Agent.

신규 Workspace 생성 후 Variable → Trigger → Tag 순서로 GTM 리소스를 생성합니다.
이름 충돌 시 Update(덮어쓰기)를 호출합니다.
"""

from __future__ import annotations

import json
import time
from datetime import datetime

from agent.state import GTMAgentState
from gtm.client import GTMClient
from gtm.models import GTMParameter, GTMTag, GTMTrigger, GTMVariable
from utils import logger
from utils.ui_emitter import emit, update_state

GTM_WORKSPACE_LIMIT = 3
WORKSPACE_HITL_TIMEOUT_SEC = 300  # UI 폼 기반 응답 대기 (5분)


def _wait_for_workspace_decision(
    *,
    hitl_mode: str,
    workspaces: list[dict],
    ai_workspaces: list[dict],
    current_count: int,
    limit: int,
) -> tuple[str, str]:
    """워크스페이스 상한에 걸렸을 때 사용자 결정을 기다린다.

    반환값: (decision, workspace_id)
      - decision: "reuse" | "cancel"
      - workspace_id: decision == "reuse" 일 때 사용할 대상 Workspace ID.
                      선택값이 없으면 ai_workspaces[0] 를 기본값으로 사용한다.
    """
    from utils import logger as _logger

    # UI에 선택지 페이로드 전송 — plan 대신 워크스페이스 목록을 보낸다.
    ws_options = [
        {
            "workspaceId": w.get("workspaceId", ""),
            "name": w.get("name", ""),
            "description": w.get("description", ""),
            "ai_managed": (w.get("name", "") or "").startswith("gtm-ai-"),
        }
        for w in workspaces
    ]
    default_reuse_id = ai_workspaces[0].get("workspaceId", "") if ai_workspaces else (
        ws_options[0]["workspaceId"] if ws_options else ""
    )

    emit(
        "hitl_request",
        kind="workspace_full",
        current_count=current_count,
        limit=limit,
        workspaces=ws_options,
        default_reuse_id=default_reuse_id,
        message=(
            f"이 컨테이너의 워크스페이스가 {current_count}/{limit} 로 가득 찼습니다. "
            "기존 작업공간을 재사용할지, 실행을 중단할지 선택해 주세요."
        ),
    )
    update_state(nodes_status={"gtm_creation": "hitl_wait"})

    run_dir = _logger.run_dir()
    if hitl_mode == "file" and run_dir:
        response_file = run_dir / "hitl_response.json"
        response_file.unlink(missing_ok=True)
        print(
            f"[GTMCreation] UI HITL 대기 — 워크스페이스 {current_count}/{limit} "
            f"(최대 {WORKSPACE_HITL_TIMEOUT_SEC}s)"
        )
        deadline = time.time() + WORKSPACE_HITL_TIMEOUT_SEC
        while time.time() < deadline:
            if response_file.exists():
                try:
                    resp = json.loads(response_file.read_text(encoding="utf-8"))
                    response_file.unlink(missing_ok=True)
                except Exception:
                    time.sleep(1)
                    continue
                if resp.get("kind") != "workspace_full":
                    # 다른 HITL 응답(plan 승인 등) — 무시하고 계속 대기
                    continue
                decision = (resp.get("decision") or "").strip().lower()
                ws_id = (resp.get("workspace_id") or "").strip()
                if decision == "cancel":
                    print("[GTMCreation] UI 응답: 실행 중단")
                    return "cancel", ""
                if decision == "reuse":
                    target = ws_id or default_reuse_id
                    print(
                        f"[GTMCreation] UI 응답: 재사용 workspace_id="
                        f"{target or '(없음)'}"
                    )
                    return "reuse", target
                # unknown → 기본: cancel 로 처리하는 게 안전
                print(f"[GTMCreation] UI 응답 알 수 없음({decision}) → cancel 처리")
                return "cancel", ""
            time.sleep(1)
        print("[GTMCreation] HITL 타임아웃 — 안전하게 실행 중단")
        return "cancel", ""

    # CLI 모드
    print(
        f"\n[GTMCreation] 워크스페이스 {current_count}/{limit} 가 가득 찼습니다."
    )
    if ai_workspaces:
        print("재사용 후보 (gtm-ai-*):")
        for w in ai_workspaces[:5]:
            print(f"  - {w.get('name', '?')} (id={w.get('workspaceId', '?')})")
    else:
        print("gtm-ai-* 접두사 워크스페이스 없음 → 임의 기존 워크스페이스에 재사용 가능")

    try:
        ans = input("기존 작업공간을 재사용하시겠습니까? (y=재사용 / n=중단): ").strip().lower()
    except EOFError:
        print("[GTMCreation] 비대화형 모드 — 안전하게 중단 처리")
        return "cancel", ""
    if ans != "y":
        return "cancel", ""
    return "reuse", default_reuse_id


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

    def _sorted_ai_workspaces(ws_list: list[dict]) -> list[dict]:
        return sorted(
            [w for w in ws_list if w.get("name", "").startswith("gtm-ai-")],
            key=lambda w: w.get("workspaceId", "0"),
            reverse=True,
        )

    try:
        existing_ws = client.list_workspaces()
        n_ws = len(existing_ws)

        # 무료 컨테이너 워크스페이스 상한(3) — 꽉 찼으면 사용자에게 HITL로 물어본다.
        if n_ws >= GTM_WORKSPACE_LIMIT:
            ai_ws = _sorted_ai_workspaces(existing_ws)
            logger.info(
                f"[GTMCreation] 워크스페이스 {n_ws}개(한도 {GTM_WORKSPACE_LIMIT}) — "
                f"HITL로 재사용 여부 확인 (gtm-ai-* 후보 {len(ai_ws)}개)"
            )
            decision, target_ws_id = _wait_for_workspace_decision(
                hitl_mode=state.get("hitl_mode", "cli"),
                workspaces=existing_ws,
                ai_workspaces=ai_ws,
                current_count=n_ws,
                limit=GTM_WORKSPACE_LIMIT,
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
                ai_ws = _sorted_ai_workspaces(existing_ws)
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
