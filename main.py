"""GTM AI Agent — 진입점.

사용법:
    python main.py

실행 전 .env 파일에 다음 환경 변수를 설정하세요:
    ANTHROPIC_API_KEY=
    GTM_ACCOUNT_ID=
    GTM_CONTAINER_ID=
"""

from __future__ import annotations

import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()

# 필수 환경 변수 체크
_REQUIRED_ENV = ["ANTHROPIC_API_KEY", "GTM_ACCOUNT_ID", "GTM_CONTAINER_ID"]
missing = [k for k in _REQUIRED_ENV if not os.environ.get(k)]
if missing:
    print(f"[Error] .env에 다음 환경 변수가 없습니다: {', '.join(missing)}")
    sys.exit(1)


async def main() -> None:
    from agent.graph import compile_graph
    from agent.state import GTMAgentState

    print("="*60)
    print("GTM AI Agent")
    print("="*60)

    target_url = input("분석할 페이지 URL을 입력하세요: ").strip()
    if not target_url:
        print("URL이 입력되지 않았습니다.")
        return

    user_request = input(
        "요청 사항을 입력하세요 (예: GA4 이커머스 이벤트 전체 설정): "
    ).strip()
    if not user_request:
        user_request = "GA4 이커머스 이벤트 전체 설정"

    tag_type_input = input("태그 유형 (GA4/naver/kakao, 기본값 GA4): ").strip()
    tag_type = tag_type_input if tag_type_input in ("GA4", "naver", "kakao") else "GA4"

    initial_state: GTMAgentState = {
        "user_request": user_request,
        "target_url": target_url,
        "tag_type": tag_type,
        "account_id": os.environ["GTM_ACCOUNT_ID"],
        "container_id": os.environ["GTM_CONTAINER_ID"],
        "workspace_id": os.environ.get("GTM_WORKSPACE_ID", ""),
        # 나머지 필드 초기화
        "page_type": "",
        "existing_gtm_config": {},
        "exploration_queue": [],
        "auto_capturable": [],
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
    }

    graph = compile_graph()

    print("\nAgent 실행 시작...\n")
    final_state = await graph.ainvoke(initial_state)

    if final_state.get("error"):
        print(f"\n[Error] 실행 중 오류 발생: {final_state['error']}")
    else:
        print("\n[완료] GTM AI Agent 실행이 성공적으로 완료되었습니다.")


if __name__ == "__main__":
    asyncio.run(main())
