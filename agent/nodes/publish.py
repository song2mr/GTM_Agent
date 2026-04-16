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
        print(f"[Publish] Publish 완료: {publish_result}")

        # 결과 리포트
        _print_report(state, version_id, publish_result)

        return {
            **state,
            "publish_result": publish_result,
            "error": None,
        }

    except Exception as e:
        error_msg = f"Publish 오류: {e}"
        print(f"[Publish] {error_msg}")
        return {**state, "error": error_msg}


def _print_report(state: GTMAgentState, version_id: str, publish_result: dict) -> None:
    """최종 결과 리포트를 출력합니다."""
    print("\n" + "="*60)
    print("GTM AI Agent — 실행 완료 리포트")
    print("="*60)
    print(f"대상 URL: {state.get('target_url')}")
    print(f"태그 유형: {state.get('tag_type')}")
    print(f"페이지 타입: {state.get('page_type')}")
    print(f"캡처된 이벤트: {len(state.get('captured_events', []))}개")
    print(f"수동 캡처: {list(state.get('manual_capture_results', {}).keys())}")
    print(f"스킵된 이벤트: {state.get('skipped_events', [])}")
    print(f"생성된 Variable: {len(state.get('created_variables', []))}개")
    print(f"생성된 Trigger: {len(state.get('created_triggers', []))}개")
    print(f"생성된 Tag: {len(state.get('created_tags', []))}개")
    print(f"Workspace ID: {state.get('workspace_id')}")
    print(f"Published Version: {version_id}")
    print("="*60)
