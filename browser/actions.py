"""Playwright 액션 래퍼.

모든 브라우저 조작은 이 모듈을 통해 실행합니다.
실패 시 예외 대신 ActionResult를 반환하여 LLM Navigator가 처리할 수 있게 합니다.
"""

from __future__ import annotations

from dataclasses import dataclass

from playwright.async_api import Page, TimeoutError as PWTimeoutError


@dataclass
class ActionResult:
    success: bool
    message: str = ""
    error: str = ""


async def click(page: Page, selector: str, timeout: int = 5000) -> ActionResult:
    """CSS/XPath selector로 요소를 클릭합니다."""
    try:
        await page.wait_for_selector(selector, timeout=timeout)
        await page.click(selector, timeout=timeout)
        return ActionResult(success=True, message=f"클릭 성공: {selector}")
    except PWTimeoutError:
        return ActionResult(
            success=False,
            error=f"타임아웃: selector를 찾을 수 없음 — {selector}",
        )
    except Exception as e:
        return ActionResult(success=False, error=f"클릭 실패: {e}")


async def navigate(page: Page, url: str, timeout: int = 15000) -> ActionResult:
    """지정 URL로 이동합니다."""
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        return ActionResult(success=True, message=f"이동 성공: {url}")
    except PWTimeoutError:
        return ActionResult(success=False, error=f"이동 타임아웃: {url}")
    except Exception as e:
        return ActionResult(success=False, error=f"이동 실패: {e}")


async def scroll(
    page: Page,
    direction: str = "down",
    amount: int = 600,
) -> ActionResult:
    """페이지를 스크롤합니다. direction: 'down' | 'up'"""
    try:
        delta = amount if direction == "down" else -amount
        await page.mouse.wheel(0, delta)
        return ActionResult(success=True, message=f"스크롤 {direction} {amount}px")
    except Exception as e:
        return ActionResult(success=False, error=f"스크롤 실패: {e}")


async def form_fill(
    page: Page, selector: str, value: str, timeout: int = 5000
) -> ActionResult:
    """폼 필드에 더미 데이터를 입력합니다."""
    try:
        await page.wait_for_selector(selector, timeout=timeout)
        await page.fill(selector, value, timeout=timeout)
        return ActionResult(success=True, message=f"폼 입력 성공: {selector} = {value}")
    except PWTimeoutError:
        return ActionResult(
            success=False,
            error=f"타임아웃: 폼 필드를 찾을 수 없음 — {selector}",
        )
    except Exception as e:
        return ActionResult(success=False, error=f"폼 입력 실패: {e}")


async def get_page_snapshot(page: Page, max_chars: int = 15000) -> str:
    """현재 페이지의 HTML 스냅샷을 반환합니다 (LLM 입력용으로 축약).

    상품 목록 / 상품 상세 링크가 페이지 중간 이후에 등장하는 경우를 위해
    max_chars를 넉넉히 잡습니다.
    """
    try:
        content = await page.content()
        # 스크립트·스타일 제거 후 축약
        import re
        content = re.sub(r"<script[^>]*>.*?</script>", "", content, flags=re.DOTALL)
        content = re.sub(r"<style[^>]*>.*?</style>", "", content, flags=re.DOTALL)
        content = re.sub(r"\s+", " ", content)
        return content[:max_chars]
    except Exception as e:
        return f"스냅샷 실패: {e}"


async def close_popup(page: Page) -> ActionResult:
    """팝업/모달 닫기를 시도합니다."""
    close_selectors = [
        "[aria-label='close']",
        "[aria-label='닫기']",
        ".modal-close",
        ".popup-close",
        ".close-btn",
        "button[class*='close']",
        "button[class*='Close']",
    ]
    for sel in close_selectors:
        result = await click(page, sel, timeout=1500)
        if result.success:
            return ActionResult(success=True, message=f"팝업 닫기 성공: {sel}")
    return ActionResult(success=False, error="닫을 팝업 없음 또는 닫기 버튼 미발견")
