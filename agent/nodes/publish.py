"""Node 7: Publish Agent.

Workspace에서 컨테이너 버전을 생성하고 Publish합니다.
결과 리포트를 출력합니다.
"""

from __future__ import annotations

from agent.state import GTMAgentState
from gtm.client import GTMClient
from utils.ui_emitter import emit, update_state


async def publish(state: GTMAgentState) -> GTMAgentState:
    """Node 7: Version 생성 + Publish."""
    emit("node_enter", node_id=7, node_key="publish", title="Publish")
    update_state(current_node=7, nodes_status={"publish": "run"})
    workspace_id = state.get("workspace_id", "")
    if not workspace_id:
        return {**state, "error": "workspace_id가 없습니다."}

    if state.get("error"):
        print(f"[Publish] 이전 단계 오류로 Publish 스킵: {state['error']}")
        return state

    client = GTMClient(
        account_id=state.get("account_id", ""),
        container_id=state.get("container_id", ""),
    )

    try:
        # Version 생성
        version_response = client.create_version(
            workspace_id,
            name="GTM AI Agent 자동 생성",
            notes=(
                f"자동 생성: Variable {len(state.get('created_variables', []))}개, "
                f"Trigger {len(state.get('created_triggers', []))}개, "
                f"Tag {len(state.get('created_tags', []))}개"
            ),
        )
        version = version_response.get("containerVersion", {})
        version_path = version.get("path", "")
        version_id = version.get("containerVersionId", "unknown")
        print(f"[Publish] 버전 생성: {version_id}")

        # Publish
        publish_result = client.publish_version(version_path)
        print(f"[Publish] Publish 완료: version={version_id}")
        emit("publish_result", success=True, version_id=version_id)
        emit("node_exit", node_id=7, status="done", duration_ms=0)
        update_state(nodes_status={"publish": "done"})

        return {
            **state,
            "publish_result": publish_result,
            "error": None,
        }

    except Exception as e:
        err_str = str(e)
        # 403 Insufficient Scopes — GTM 리소스 생성은 성공했으나 Publish 권한 없음
        # Google Cloud Console → OAuth 동의 화면 → 범위에 tagmanager.publish 추가 후 재인증 필요
        if "403" in err_str or "insufficient" in err_str.lower() or "insufficientPermissions" in err_str:
            print(
                "\n[Publish] ⚠️  Publish 실패 (403 Insufficient Permission)\n"
                "GTM 리소스(Variable/Trigger/Tag)는 모두 생성되었습니다.\n"
                "가능한 원인 및 해결 방법:\n"
                "  1. [GTM 계정 권한 부족] GTM UI → 관리 → 사용자 관리\n"
                "     → 해당 계정에 'Publish' 권한이 있는지 확인\n"
                "  2. [OAuth 토큰 스코프 부족] credentials/token.json 삭제 후\n"
                "     python gtm/auth.py 재실행 (tagmanager.publish 스코프 재동의)\n"
                "  3. GTM UI에서 직접 Publish 가능:\n"
                "     https://tagmanager.google.com/\n"
            )
            emit("publish_result", success=False,
                 warning="Publish 권한 부족 (403) — GTM UI에서 수동 Publish 필요")
            emit("node_exit", node_id=7, status="done", duration_ms=0)
            update_state(nodes_status={"publish": "done"})
            return {
                **state,
                "publish_result": None,
                "publish_warning": "Publish 권한 부족 (403) — GTM UI에서 수동 Publish 필요",
                "error": None,  # 치명적 오류 아님 — reporter 정상 실행
            }

        error_msg = f"Publish 오류: {e}"
        print(f"[Publish] {error_msg}")
        emit("publish_result", success=False, warning=error_msg)
        emit("node_exit", node_id=7, status="failed", duration_ms=0)
        update_state(nodes_status={"publish": "failed"})
        return {**state, "publish_result": None, "error": error_msg}


