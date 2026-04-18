"""GTM AI Agent — CLI 진입점.

사용법:
    python main.py

GTM 자격 정보(account_id, container_id)는 여기서 입력받아 에이전트에 전달합니다.
.env에는 OPENAI_API_KEY만 필요합니다. GTM 정보는 UI 또는 CLI 입력으로 전달됩니다.
"""

from __future__ import annotations

import asyncio
import io
import os
import sys

# Windows 콘솔 인코딩을 UTF-8로 강제 설정
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv()

# API 키만 필수 체크 (GTM 정보는 입력으로 받음)
if not os.environ.get("OPENAI_API_KEY"):
    print("[Error] .env에 OPENAI_API_KEY가 없습니다.")
    sys.exit(1)


async def main() -> None:
    from agent.runner import run_agent

    print("=" * 60)
    print("GTM AI Agent")
    print("=" * 60)

    def _sanitize(text: str) -> str:
        return text.encode("utf-8", errors="replace").decode("utf-8")

    target_url = _sanitize(input("분석할 페이지 URL을 입력하세요: ").strip())
    if not target_url:
        print("URL이 입력되지 않았습니다.")
        return

    user_request = _sanitize(
        input("요청 사항을 입력하세요 (예: GA4 이커머스 이벤트 전체 설정): ").strip()
    )
    if not user_request:
        user_request = "GA4 이커머스 이벤트 전체 설정"

    tag_type_input = _sanitize(
        input("태그 유형 (GA4/naver/kakao, 기본값 GA4): ").strip()
    )
    tag_type = tag_type_input if tag_type_input in ("GA4", "naver", "kakao") else "GA4"

    account_id = _sanitize(input("GTM Account ID: ").strip())
    if not account_id:
        print("[Error] GTM Account ID는 필수입니다.")
        return

    container_id = _sanitize(input("GTM Container ID (예: GTM-XXXXXXX): ").strip())
    if not container_id:
        print("[Error] GTM Container ID는 필수입니다.")
        return

    workspace_id = _sanitize(
        input("GTM Workspace ID (선택, 비워두면 자동 생성): ").strip()
    )
    measurement_id = _sanitize(
        input("GA4 Measurement ID (선택, G-XXXXXXXX): ").strip()
    )

    config = {
        "target_url": target_url,
        "user_request": user_request,
        "tag_type": tag_type,
        "account_id": account_id,
        "container_id": container_id,
        "workspace_id": workspace_id,
        "measurement_id": measurement_id,
    }

    print("\nAgent 실행 시작...\n")
    final_state = await run_agent(config)

    if final_state.get("error"):
        print(f"\n[Error] 실행 중 오류 발생: {final_state['error']}")

    report = final_state.get("report_path")
    if report:
        print(f"\n보고서: {report}")
    else:
        print("\n[완료] GTM AI Agent 실행이 완료되었습니다.")


if __name__ == "__main__":
    asyncio.run(main())
