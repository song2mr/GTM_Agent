"""UI/CLI 공통 에이전트 진입점.

main.py(CLI)와 미래 API 서버 모두 이 함수를 호출합니다.
GTM 자격 정보는 환경변수가 아닌 config dict에서만 읽습니다.
"""

from __future__ import annotations

import time
from pathlib import Path

from agent.graph import compile_graph
from agent.state import GTMAgentState
from agent.workspace_hitl import (
    GTM_WORKSPACE_LIMIT,
    sorted_ai_workspaces,
    wait_for_workspace_full_decision,
)
from gtm.client import GTMClient
from utils import logger
from utils.ui_emitter import (
    emit,
    flush_stale_running_nodes,
    set_run_dir,
    update_state,
    write_history_index,
)


async def run_agent(config: dict) -> dict:
    """
    config 키:
        target_url      str   (필수)
        user_request    str   (필수)
        tag_type        str   "GA4"|"naver"|"kakao"  (기본 GA4)
        account_id      str   (필수)
        container_id    str   (필수)
        workspace_id    str   (선택, 비면 자동 생성)
        measurement_id  str   (선택, G-XXXXXXXX)

    반환: final_state dict
    """
    target_url = config["target_url"]
    user_request = config["user_request"]
    tag_type = config.get("tag_type", "GA4")
    account_id = config["account_id"]
    container_id = config["container_id"]
    workspace_id = config.get("workspace_id", "")
    measurement_id = config.get("measurement_id", "")

    run_id_override = config.get("run_id")
    hitl_mode = config.get("hitl_mode", "cli")

    run_dir = logger.setup(run_id=run_id_override)
    set_run_dir(run_dir)

    run_id = Path(run_dir).name

    # GTM 컨테이너 사전 검증 (브라우저·LLM 탐색 전, 비용·시간 절약)
    _preflight_workspaces: list[dict] | None = None
    try:
        preflight = GTMClient(account_id=account_id, container_id=container_id)
        resolved_container_id = preflight.verify_and_resolve_container_id()
        if resolved_container_id != container_id:
            logger.info(
                f"[runner] Container ID를 API용으로 확정: "
                f"{container_id!r} → {resolved_container_id!r}"
            )
            container_id = resolved_container_id
        # 워크스페이스 목록(한도 시 그래프 전 HITL에 사용)
        try:
            _preflight_workspaces = preflight.list_workspaces()
            _n_ws = len(_preflight_workspaces)
            if _n_ws >= GTM_WORKSPACE_LIMIT:
                logger.info(
                    f"[runner] GTM 워크스페이스 {_n_ws}개(상한 {GTM_WORKSPACE_LIMIT}) — "
                    "그래프 시작 전에 Approvals에서 재사용/중단을 묻습니다(폼에 workspace_id가 "
                    "이미 있으면 생략). Node 6에서는 같은 질문을 반복하지 않습니다."
                )
        except Exception as _e_ws:
            logger.info(f"[runner] 워크스페이스 목록 사전 조회 생략: {_e_ws}")
            _preflight_workspaces = None
    except Exception as e:
        err = str(e)
        logger.info(f"[runner] GTM 컨테이너 사전 검증 실패: {err}")
        emit(
            "run_end",
            report_path=None,
            duration_ms=0,
            token_usage={},
        )
        update_state(
            status="failed",
            current_node=0,
            error=err,
        )
        try:
            write_history_index(Path(run_dir).parent)
        except Exception:
            pass
        return {
            **({"run_id": run_id} if run_id else {}),
            "user_request": user_request,
            "target_url": target_url,
            "tag_type": tag_type,
            "account_id": account_id,
            "container_id": container_id,
            "workspace_id": workspace_id,
            "measurement_id": measurement_id,
            "error": err,
        }

    # 초기 state.json 스냅샷
    update_state(
        run_id=run_id,
        status="running",
        current_node=0,
        started_at=run_id,
        target_url=target_url,
        tag_type=tag_type,
        nodes=[
            {"id": 1,   "key": "page_classifier",    "title": "Page Classifier",    "status": "queued"},
            {"id": 1.5, "key": "structure_analyzer",  "title": "Structure Analyzer", "status": "queued"},
            {"id": 2,   "key": "journey_planner",     "title": "Journey Planner",    "status": "queued"},
            {"id": 3,   "key": "active_explorer",     "title": "Active Explorer",    "status": "queued"},
            {
                "id": 3.25,
                "key": "cart_addition_explorer",
                "title": "Cart Addition Explorer",
                "status": "queued",
            },
            {
                "id": 3.5,
                "key": "begin_checkout_explorer",
                "title": "Begin Checkout Explorer",
                "status": "queued",
            },
            {"id": 4,   "key": "manual_capture",      "title": "Manual Capture",     "status": "queued"},
            {"id": 5,   "key": "planning",            "title": "Planning · HITL",    "status": "queued"},
            {"id": 6,   "key": "gtm_creation",        "title": "GTM Creation",       "status": "queued"},
            {"id": 7,   "key": "publish",             "title": "Publish",            "status": "queued"},
            {"id": 8,   "key": "reporter",            "title": "Reporter",           "status": "queued"},
        ],
        token_usage={"in": 0, "out": 0, "usd": 0.0},
    )

    emit(
        "run_start",
        run_id=run_id,
        target_url=target_url,
        user_request=user_request,
        tag_type=tag_type,
        account_id=account_id,
        container_id=container_id,
    )
    logger.info(
        f"[runner] graph 준비 완료 run_id={run_id} tag_type={tag_type!r} "
        f"url_len={len(target_url)} req_len={len(user_request)}"
    )

    # 워크스페이스 한도(3) + 미지정 시: 브라우저·LLM 탐색 전에 재사용/중단 HITL
    if (
        _preflight_workspaces is not None
        and len(_preflight_workspaces) >= GTM_WORKSPACE_LIMIT
        and not (workspace_id or "").strip()
    ):
        logger.info(
            "[runner] 워크스페이스 한도 도달 — 그래프 전 workspace_full HITL 대기"
        )
        ai_ws = sorted_ai_workspaces(_preflight_workspaces)
        decision, chosen_wid = wait_for_workspace_full_decision(
            hitl_mode=hitl_mode,
            workspaces=_preflight_workspaces,
            ai_workspaces=ai_ws,
            current_count=len(_preflight_workspaces),
            limit=GTM_WORKSPACE_LIMIT,
            mark_gtm_node_hitl_wait=False,
            log_prefix="[runner]",
        )
        if decision == "cancel":
            msg = (
                f"워크스페이스가 {len(_preflight_workspaces)}개로 가득 차 "
                "실행 시작 전에 사용자가 중단했습니다."
            )
            emit("hitl_decision", approved=False, feedback="workspace_full_cancel_preflight")
            emit("run_end", report_path=None, duration_ms=0, token_usage={})
            update_state(
                status="failed",
                current_node=0,
                error=msg,
            )
            try:
                write_history_index(Path(run_dir).parent)
            except Exception:
                pass
            return {
                "run_id": run_id,
                "user_request": user_request,
                "target_url": target_url,
                "tag_type": tag_type,
                "account_id": account_id,
                "container_id": container_id,
                "workspace_id": workspace_id,
                "measurement_id": measurement_id,
                "error": msg,
            }
        if not chosen_wid:
            msg = "재사용할 워크스페이스가 지정되지 않았습니다."
            emit("hitl_decision", approved=False, feedback="workspace_full_no_target_preflight")
            emit("run_end", report_path=None, duration_ms=0, token_usage={})
            update_state(status="failed", current_node=0, error=msg)
            try:
                write_history_index(Path(run_dir).parent)
            except Exception:
                pass
            return {
                "run_id": run_id,
                "user_request": user_request,
                "target_url": target_url,
                "tag_type": tag_type,
                "account_id": account_id,
                "container_id": container_id,
                "workspace_id": "",
                "measurement_id": measurement_id,
                "error": msg,
            }
        chosen_name = next(
            (
                w.get("name", "")
                for w in _preflight_workspaces
                if w.get("workspaceId") == chosen_wid
            ),
            "",
        )
        workspace_id = chosen_wid
        emit(
            "hitl_decision",
            approved=True,
            feedback=f"reuse_preflight:{chosen_name or workspace_id}",
        )
        emit(
            "thought",
            who="tool",
            label="GTM Workspace",
            text=(
                f"실행 시작 전 사용자 승인 → 작업공간 `{chosen_name or workspace_id}` "
                "에 이후 설계안을 적용합니다."
            ),
            kind="plain",
        )
        logger.info(
            f"[runner] 사전 HITL 완료 → workspace_id={workspace_id!r} 로 그래프 시작"
        )

    initial_state: GTMAgentState = {
        "user_request": user_request,
        "target_url": target_url,
        "tag_type": tag_type,
        "account_id": account_id,
        "container_id": container_id,
        "workspace_id": workspace_id,
        "measurement_id": measurement_id,
        # 나머지 초기화
        "page_type": "",
        "existing_gtm_config": {},
        "datalayer_status": "none",
        "datalayer_events_found": [],
        "extraction_method": "datalayer",
        "dom_selectors": {},
        "selector_validation": {},
        "json_ld_data": {},
        "click_triggers": {},
        "exploration_queue": [],
        "auto_capturable": [],
        "cart_addition_events": [],
        "begin_checkout_events": [],
        "manual_required": [],
        "captured_events": [],
        "exploration_log": [],
        "current_url": "",
        "last_pdp_url": "",
        "manual_capture_results": {},
        "skipped_events": [],
        "doc_context": "",
        "doc_fetch_failed": False,
        "plan": {},
        "plan_approved": False,
        "hitl_feedback": "",
        "created_variables": [],
        "created_triggers": [],
        "created_tags": [],
        "publish_result": {},
        "error": None,
        "publish_warning": None,
        "event_capture_log": [],
        "token_usage": {},
        "report_path": None,
        "hitl_mode": hitl_mode,
    }

    graph = compile_graph()
    _wall0 = time.perf_counter()
    try:
        final_state = await graph.ainvoke(initial_state)
    except Exception as e:
        logger.warning(
            f"[runner] graph 예외 run_id={run_id} wall_s={time.perf_counter() - _wall0:.1f}: {e}"
        )
        flush_stale_running_nodes()
        emit("run_end", report_path=None, duration_ms=0, token_usage={})
        update_state(
            status="failed",
            current_node=8,
            error=str(e),
        )
        try:
            write_history_index(Path(run_dir).parent)
        except Exception:
            pass
        return {**initial_state, "error": str(e)}

    _wall = time.perf_counter() - _wall0
    n_ev = len(final_state.get("captured_events") or [])
    logger.info(
        f"[runner] graph 완료 run_id={run_id} wall_s={_wall:.1f} "
        f"captured_events={n_ev} final_error={final_state.get('error')!r}"
    )

    # 종료 이벤트 emit
    usage = final_state.get("token_usage", {})
    emit(
        "run_end",
        report_path=final_state.get("report_path"),
        duration_ms=0,
        token_usage=usage,
    )
    update_state(
        status="done" if not final_state.get("error") else "failed",
        current_node=8,
    )

    # logs/index.json 갱신
    try:
        write_history_index(Path(run_dir).parent)
    except Exception:
        pass

    return final_state
