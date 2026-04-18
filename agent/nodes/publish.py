"""Node 7: Publish Agent.

Workspace에서 컨테이너 버전을 생성하고 Publish합니다.
결과 리포트를 출력합니다.
"""

from __future__ import annotations

from agent.state import GTMAgentState
from gtm.client import GTMClient


async def publish(state: GTMAgentState) -> GTMAgentState:
    """Node 7: Version 생성 + Publish."""
    workspace_id = state.get("workspace_id", "")
    if not workspace_id:
        return {**state, "error": "workspace_id가 없습니다."}

    if state.get("error"):
        print(f"[Publish] 이전 단계 오류로 Publish 스킵: {state['error']}")
        return state

    client = GTMClient()

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
            return {
                **state,
                "publish_result": None,
                "publish_warning": "Publish 권한 부족 (403) — GTM UI에서 수동 Publish 필요",
                "error": None,  # 치명적 오류 아님 — reporter 정상 실행
            }

        error_msg = f"Publish 오류: {e}"
        print(f"[Publish] {error_msg}")
        return {**state, "publish_result": None, "error": error_msg}


