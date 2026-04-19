"""테스트 실행 스크립트 — CLI input() 대신 config를 직접 전달."""
import asyncio
import io
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

from agent.runner import run_agent

config = {
    "target_url":     "https://www.leekorea.co.kr",
    "user_request":   "GA4 이커머스 이벤트 설정",
    "tag_type":       "GA4",
    "account_id":     "6273779709",
    "container_id":   "208905963",
    "workspace_id":   "",
    "measurement_id": "G-KX82JQ4M1P",
    # UI 체크박스와 동일한 역할 — 이 목록만 탐색·설계 대상이 된다.
    "selected_events": [
        "view_item_list", "view_item", "add_to_cart",
        "add_to_wishlist", "view_cart", "begin_checkout",
    ],
}

async def main():
    print(f"실행 config: {config}")
    final = await run_agent(config)
    print(f"\n완료. 보고서: {final.get('report_path')}")
    if final.get("error"):
        print(f"오류: {final['error']}")

asyncio.run(main())
