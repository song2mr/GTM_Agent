"""UI/CLI 공통 에이전트 진입점.

main.py(CLI)와 미래 API 서버 모두 이 함수를 호출합니다.
GTM 자격 정보는 환경변수가 아닌 config dict에서만 읽습니다.
"""

from __future__ import annotations

import time
from pathlib import Path

from agent.graph import compile_graph
from agent.state import GTMAgentState
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
    try:
        preflight = GTMClient(account_id=account_id, container_id=container_id)
        resolved_container_id = preflight.verify_and_resolve_container_id()
        if resolved_container_id != container_id:
            logger.info(
                f"[runner] Container ID를 API용으로 확정: "
                f"{container_id!r} → {resolved_container_id!r}"
            )
            container_id = resolved_container_id
        # 워크스페이스 3개 한도 — Node 6 동작(신규 생성 vs 재사용)을 미리 짐작할 수 있게만 로그
        try:
            _n_ws = len(preflight.list_workspaces())
            if _n_ws >= 3:
                logger.info(
                    f"[runner] GTM 워크스페이스 {_n_ws}개(상한 3) — "
                    "Node 6 진입 시 `workspaces.list` 기준으로 한도면 HITL(Approvals)에서 "
                    "재사용/중단을 묻습니다. UI에 안 뜨면 해당 Run의 run.log 에 "
                    "`[GTMCreation] workspaces.list 개수=` 로 실제 API 개수를 확인하세요."
                )
        except Exception as _e_ws:
            logger.info(f"[runner] 워크스페이스 개수 사전 확인 생략: {_e_ws}")
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
