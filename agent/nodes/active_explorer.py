"""Node 3: Active Explorer (핵심).

LLM Navigator + Playwright 루프로 탐색 큐의 이벤트를 순서대로 캡처합니다.
각 이벤트마다 최대 3회 재시도, 실패 시 manual_required로 이관합니다.
"""

from __future__ import annotations

from playwright.async_api import async_playwright

from agent.state import GTMAgentState
from playwright.actions import close_popup, navigate
from playwright.listener import get_captured_events, inject_listener
from playwright.navigator import LLMNavigator


async def active_explorer(state: GTMAgentState) -> GTMAgentState:
    """Node 3: LLM Navigator + Playwright 루프."""
    target_url = state["target_url"]
    auto_capturable = state.get("auto_capturable", [])
    manual_required = list(state.get("manual_required", []))

    captured_events: list[dict] = list(state.get("captured_events", []))
    exploration_log: list[str] = list(state.get("exploration_log", []))

    navigator = LLMNavigator()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        page = await browser.new_page()

        # Persistent Listener 주입
        await inject_listener(page)

        # 시작 페이지 이동
        await navigate(page, target_url)
        await page.wait_for_timeout(2000)

        # 로드 직후 이벤트 수집 (page_view 포함)
        initial_events = await get_captured_events(page)
        for e in initial_events:
            if e not in captured_events:
                captured_events.append(e)

        # 탐색 큐 순서대로 이벤트 캡처
        for target_event in auto_capturable:
            already_captured = any(
                e.get("data", {}).get("event") == target_event
                for e in captured_events
            )
            if already_captured:
                exploration_log.append(f"{target_event}: 이미 캡처됨 (스킵)")
                print(f"[ActiveExplorer] {target_event} 이미 캡처됨, 스킵")
                continue

            print(f"[ActiveExplorer] 목표 이벤트: {target_event}")
            result = await navigator.run_for_event(page, target_event, captured_events)

            if result == "captured":
                # 새로 캡처된 이벤트 수집
                all_events = await get_captured_events(page)
                for e in all_events:
                    if e not in captured_events:
                        captured_events.append(e)
                exploration_log.append(f"{target_event}: 캡처 성공")
            else:
                # manual_required로 이관
                if target_event not in manual_required:
                    manual_required.append(target_event)
                exploration_log.append(f"{target_event}: 캡처 실패 → Manual로 이관")

        await browser.close()

    print(f"[ActiveExplorer] 총 캡처 이벤트: {len(captured_events)}개")
    print(f"[ActiveExplorer] Manual 이관: {manual_required}")

    return {
        **state,
        "captured_events": captured_events,
        "manual_required": manual_required,
        "current_url": target_url,
        "exploration_log": exploration_log,
    }
