"""LLM Navigator 루프.

LLM이 HTML 스냅샷과 목표 이벤트를 보고 다음 액션을 결정하면,
Playwright가 해당 액션을 실행합니다. 최대 3회 재시도 후 실패 시 포기합니다.
"""

from __future__ import annotations

import json
from typing import Literal

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from playwright.async_api import Page

from playwright.actions import (
    ActionResult,
    click,
    close_popup,
    form_fill,
    get_page_snapshot,
    navigate,
    scroll,
)
from playwright.listener import get_captured_events

MAX_RETRIES = 3

_SYSTEM_PROMPT = """당신은 웹 브라우저 자동화 에이전트입니다.
목표 이벤트를 캡처하기 위해 페이지를 탐색합니다.

다음 JSON 형식으로만 응답하세요:
{
  "action": "click" | "navigate" | "scroll" | "form_fill" | "captured" | "impossible",
  "selector": "CSS selector (click/form_fill 시 필수)",
  "url": "URL (navigate 시 필수)",
  "direction": "down" | "up" (scroll 시, 기본 down)",
  "value": "입력값 (form_fill 시 필수, 더미 데이터만)",
  "reason": "이 액션을 선택한 이유"
}

action 설명:
- click: 버튼/링크/상품 클릭
- navigate: URL 직접 이동
- scroll: 페이지 스크롤
- form_fill: 폼 입력 (더미 데이터만 사용)
- captured: 이미 목표 이벤트가 캡처됨
- impossible: 이 페이지에서 목표 이벤트 캡처 불가능

보안 규칙:
- 실제 개인정보(이름, 전화번호, 신용카드 등) 절대 입력 금지
- form_fill 시 항상 더미 데이터 사용
"""


class LLMNavigator:
    def __init__(self, model: str = "claude-sonnet-4-6"):
        self._llm = ChatAnthropic(model=model)

    async def decide_next_action(
        self,
        page: Page,
        target_event: str,
        captured_so_far: list[dict],
        attempt: int = 1,
        last_error: str = "",
    ) -> dict:
        """현재 페이지 상태를 분석하고 다음 액션을 결정합니다."""
        snapshot = await get_page_snapshot(page)
        captured_names = [e.get("data", {}).get("event", "") for e in captured_so_far]

        user_content = f"""
현재 URL: {page.url}
목표 이벤트: {target_event}
이미 캡처된 이벤트: {captured_names}
시도 횟수: {attempt}/{MAX_RETRIES}
{f'이전 시도 오류: {last_error}' if last_error else ''}

페이지 HTML (축약):
{snapshot}
"""
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=user_content),
        ]
        response = await self._llm.ainvoke(messages)
        raw = response.content.strip()

        # JSON 파싱
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"action": "impossible", "reason": f"LLM 응답 파싱 실패: {raw[:200]}"}

    async def run_for_event(
        self,
        page: Page,
        target_event: str,
        captured_so_far: list[dict],
    ) -> Literal["captured", "manual_required", "skipped"]:
        """목표 이벤트 캡처를 시도합니다. 최대 MAX_RETRIES회 재시도."""
        last_error = ""

        for attempt in range(1, MAX_RETRIES + 1):
            decision = await self.decide_next_action(
                page, target_event, captured_so_far, attempt, last_error
            )
            action = decision.get("action", "impossible")

            if action == "captured":
                print(f"[Navigator] {target_event} 이미 캡처됨")
                return "captured"

            if action == "impossible":
                print(f"[Navigator] {target_event} 캡처 불가: {decision.get('reason')}")
                return "manual_required"

            # 팝업 먼저 처리
            await close_popup(page)

            # 액션 실행
            result = await self._execute_action(page, decision)

            if not result.success:
                last_error = result.error
                print(f"[Navigator] 시도 {attempt} 실패: {result.error}")
                continue

            # 이벤트 발화 확인
            await page.wait_for_timeout(1000)
            events = await get_captured_events(page)
            new_events = [
                e for e in events
                if e not in captured_so_far
                and e.get("data", {}).get("event") == target_event
            ]
            if new_events:
                print(f"[Navigator] {target_event} 캡처 성공 (시도 {attempt})")
                return "captured"

            last_error = f"액션 실행 성공했으나 이벤트 미발화"

        print(f"[Navigator] {target_event} {MAX_RETRIES}회 실패 → Manual로 이관")
        return "manual_required"

    async def _execute_action(self, page: Page, decision: dict) -> ActionResult:
        action = decision.get("action")

        if action == "click":
            return await click(page, decision.get("selector", ""))
        elif action == "navigate":
            return await navigate(page, decision.get("url", ""))
        elif action == "scroll":
            return await scroll(page, decision.get("direction", "down"))
        elif action == "form_fill":
            return await form_fill(
                page,
                decision.get("selector", ""),
                decision.get("value", ""),
            )
        else:
            return ActionResult(success=False, error=f"알 수 없는 액션: {action}")
