"""Playwright 액션 래퍼.

모든 브라우저 조작은 이 모듈을 통해 실행합니다.
실패 시 예외 대신 ActionResult를 반환하여 LLM Navigator가 처리할 수 있게 합니다.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from playwright.async_api import Page, TimeoutError as PWTimeoutError

from utils import logger
from utils.ui_emitter import emit


@dataclass
class ActionResult:
    success: bool
    message: str = ""
    error: str = ""


async def click(page: Page, selector: str, timeout: int = 5000) -> ActionResult:
    """CSS/XPath selector로 요소를 클릭합니다."""
    emit("thought", who="tool", label="playwright.click", text=selector, kind="tool")
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
    emit("thought", who="tool", label="playwright.navigate", text=f"GET {url}", kind="tool")
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

    page.content()는 일부 무거운 페이지에서 응답이 끝나지 않아 무한 대기처럼
    보일 수 있으므로 상한 시간을 둡니다.
    """
    import re

    url = ""
    try:
        url = page.url
    except Exception:
        pass
    t0 = time.perf_counter()
    logger.info(f"[Snapshot] page.content() 시작 url={url!r} max_chars={max_chars}")
    try:
        content = await asyncio.wait_for(page.content(), timeout=30.0)
    except asyncio.TimeoutError:
        dt = time.perf_counter() - t0
        logger.error(f"[Snapshot] page.content() 타임아웃 ({dt:.1f}s) url={url!r}")
        return (
            "스냅샷 타임아웃: HTML 수집이 30초 내에 완료되지 않았습니다. "
            "페이지가 매우 무겁거나 브라우저가 응답하지 않는 상태일 수 있습니다."
        )
    except Exception as e:
        dt = time.perf_counter() - t0
        logger.error(f"[Snapshot] page.content() 예외 ({dt:.1f}s) url={url!r}: {e}")
        return f"스냅샷 실패: {e}"
    raw_len = len(content)
    try:
        content = re.sub(r"<script[^>]*>.*?</script>", "", content, flags=re.DOTALL)
        content = re.sub(r"<style[^>]*>.*?</style>", "", content, flags=re.DOTALL)
        content = re.sub(r"\s+", " ", content)
        out = content[:max_chars]
        dt = time.perf_counter() - t0
        logger.info(
            f"[Snapshot] 완료 raw_bytes~{raw_len} out_chars={len(out)} "
            f"elapsed={dt:.2f}s url={url!r}"
        )
        return out
    except Exception as e:
        dt = time.perf_counter() - t0
        logger.error(f"[Snapshot] 가공 실패 ({dt:.1f}s) url={url!r}: {e}")
        return f"스냅샷 가공 실패: {e}"


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
