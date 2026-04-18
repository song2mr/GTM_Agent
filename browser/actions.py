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
    t0 = time.perf_counter()
    logger.info(f"[Navigate] page.goto 시작 url={url!r} wait_until=domcontentloaded pw_timeout_ms={timeout}")
    try:
        # 일부 사이트에서 page.goto가 PW 타임아웃을 넘겨도 끝나지 않는 경우가 있어 이중 상한
        await asyncio.wait_for(
            page.goto(url, wait_until="domcontentloaded", timeout=timeout),
            timeout=max(float(timeout) / 1000.0 + 5.0, 25.0),
        )
        dt = time.perf_counter() - t0
        logger.info(f"[Navigate] page.goto 완료 ({dt:.2f}s) url={url!r}")
        return ActionResult(success=True, message=f"이동 성공: {url}")
    except asyncio.TimeoutError:
        dt = time.perf_counter() - t0
        logger.error(f"[Navigate] page.goto asyncio 상한 초과 ({dt:.1f}s) url={url!r}")
        return ActionResult(success=False, error=f"이동 상한 초과(비정상 지연): {url}")
    except PWTimeoutError:
        dt = time.perf_counter() - t0
        logger.error(f"[Navigate] Playwright 이동 타임아웃 ({dt:.1f}s) url={url!r}")
        return ActionResult(success=False, error=f"이동 타임아웃: {url}")
    except Exception as e:
        dt = time.perf_counter() - t0
        logger.error(f"[Navigate] page.goto 예외 ({dt:.1f}s) url={url!r}: {e}")
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


async def select_option(
    page: Page, selector: str, value: str, timeout: int = 8000
) -> ActionResult:
    """native <select>에 값을 선택하고 input/change를 한 번 더 보냅니다 (카페24 등)."""
    emit(
        "thought",
        who="tool",
        label="playwright.select_option",
        text=f"{selector} = {value!r}",
        kind="tool",
    )
    try:
        loc = page.locator(selector).first
        await loc.wait_for(state="attached", timeout=timeout)
        await loc.scroll_into_view_if_needed(timeout=timeout)
        await loc.select_option(value, timeout=timeout)
        handle = await loc.element_handle()
        if handle:
            await page.evaluate(
                """(el) => {
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                }""",
                handle,
            )
        return ActionResult(success=True, message=f"옵션 선택: {selector} = {value!r}")
    except PWTimeoutError:
        return ActionResult(
            success=False,
            error=f"타임아웃: select 옵션 실패 — {selector} = {value!r}",
        )
    except Exception as e:
        return ActionResult(success=False, error=f"옵션 선택 실패: {e}")


async def set_location_hash(page: Page, hash_fragment: str) -> ActionResult:
    """앵커/탭 전환용 location.hash 설정 (# 없이 fragment만, 예: cart_tab_option)."""
    frag = (hash_fragment or "").strip().lstrip("#")
    emit("thought", who="tool", label="playwright.hash", text=f"#{frag}", kind="tool")
    try:
        await page.evaluate(
            """(f) => {
                if (f) window.location.hash = '#' + f;
            }""",
            frag,
        )
        return ActionResult(success=True, message=f"hash 설정: #{frag}")
    except Exception as e:
        return ActionResult(success=False, error=f"hash 설정 실패: {e}")


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


async def get_page_snapshot(
    page: Page,
    max_chars: int = 15000,
    *,
    prefer_bottom: bool = False,
) -> str:
    """현재 페이지의 HTML 스냅샷을 반환합니다 (LLM 입력용으로 축약).

    상품 목록 / 상품 상세 링크가 페이지 중간 이후에 등장하는 경우를 위해
    max_chars를 넉넉히 잡습니다.

    prefer_bottom=True(조작형 PDP 등): 앞부분만 자르면 옵션·담기 버튼이 잘리므로
    **문서 앞 일부 + 뒤쪽(하단 근처)** 를 합쳐 max_chars 안에 넣습니다.

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
    logger.info(
        f"[Snapshot] page.content() 시작 url={url!r} max_chars={max_chars} "
        f"prefer_bottom={prefer_bottom}"
    )
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
        compact = content
        if len(compact) <= max_chars:
            out = compact
        elif prefer_bottom:
            sep = "\n...[생략: HTML 앞·중간]...\n"
            rest = max_chars - len(sep)
            tail_len = (rest * 2) // 3
            head_len = rest - tail_len
            out = compact[:head_len] + sep + compact[-tail_len:]
        else:
            out = compact[:max_chars]
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
