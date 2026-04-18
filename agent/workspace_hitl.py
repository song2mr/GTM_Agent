"""GTM 워크스페이스 상한(무료 컨테이너 3개) 시 사용자 HITL.

`serve_ui` + `hitl_mode=file` 일 때 `logs/{run_id}/hitl_response.json` 을 폴링한다.
`runner`(사전)와 `gtm_creation`(Node 6)에서 공유한다.
"""

from __future__ import annotations

import json
import time

from utils import logger as _logger
from utils.ui_emitter import emit, update_state

GTM_WORKSPACE_LIMIT = 3
WORKSPACE_HITL_TIMEOUT_SEC = 300


def sorted_ai_workspaces(ws_list: list[dict]) -> list[dict]:
    return sorted(
        [w for w in ws_list if w.get("name", "").startswith("gtm-ai-")],
        key=lambda w: w.get("workspaceId", "0"),
        reverse=True,
    )


def wait_for_workspace_full_decision(
    *,
    hitl_mode: str,
    workspaces: list[dict],
    ai_workspaces: list[dict],
    current_count: int,
    limit: int = GTM_WORKSPACE_LIMIT,
    mark_gtm_node_hitl_wait: bool = False,
    log_prefix: str = "[WorkspaceHITL]",
) -> tuple[str, str]:
    """워크스페이스 상한에 걸렸을 때 사용자 결정을 기다린다.

    반환: (decision, workspace_id)
      - decision: "reuse" | "cancel"
      - workspace_id: reuse 일 때 대상 ID (없으면 빈 문자열)
    """
    ws_options = [
        {
            "workspaceId": w.get("workspaceId", ""),
            "name": w.get("name", ""),
            "description": w.get("description", ""),
            "ai_managed": (w.get("name", "") or "").startswith("gtm-ai-"),
        }
        for w in workspaces
    ]
    default_reuse_id = (
        ai_workspaces[0].get("workspaceId", "")
        if ai_workspaces
        else (ws_options[0]["workspaceId"] if ws_options else "")
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
    if mark_gtm_node_hitl_wait:
        update_state(nodes_status={"gtm_creation": "hitl_wait"})

    run_dir = _logger.run_dir()
    if hitl_mode == "file" and run_dir:
        response_file = run_dir / "hitl_response.json"
        response_file.unlink(missing_ok=True)
        print(
            f"{log_prefix} UI HITL 대기 — 워크스페이스 {current_count}/{limit} "
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
                    continue
                decision = (resp.get("decision") or "").strip().lower()
                ws_id = (resp.get("workspace_id") or "").strip()
                if decision == "cancel":
                    print(f"{log_prefix} UI 응답: 실행 중단")
                    return "cancel", ""
                if decision == "reuse":
                    target = ws_id or default_reuse_id
                    print(f"{log_prefix} UI 응답: 재사용 workspace_id={target or '(없음)'}")
                    return "reuse", target
                print(f"{log_prefix} UI 응답 알 수 없음({decision}) → cancel 처리")
                return "cancel", ""
            time.sleep(1)
        print(f"{log_prefix} HITL 타임아웃 — 안전하게 실행 중단")
        return "cancel", ""

    print(f"\n{log_prefix} 워크스페이스 {current_count}/{limit} 가 가득 찼습니다.")
    if ai_workspaces:
        print("재사용 후보 (gtm-ai-*):")
        for w in ai_workspaces[:5]:
            print(f"  - {w.get('name', '?')} (id={w.get('workspaceId', '?')})")
    else:
        print("gtm-ai-* 접두사 워크스페이스 없음 → 목록에서 직접 선택·재사용")

    try:
        ans = input(
            "기존 작업공간을 재사용하시겠습니까? (y=재사용 / n=중단): "
        ).strip().lower()
    except EOFError:
        print(f"{log_prefix} 비대화형 모드 — 안전하게 중단 처리")
        return "cancel", ""
    if ans != "y":
        return "cancel", ""
    return "reuse", default_reuse_id
