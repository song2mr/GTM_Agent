"""Persistent Event Listener 주입 유틸.

page.add_init_script()로 주입하므로 페이지 이동 후에도 리스너가 유지됩니다.
모든 dataLayer.push 이벤트를 window.__gtm_captured에 누적합니다.
"""

from __future__ import annotations

from playwright.async_api import Page

_LISTENER_SCRIPT = """
(function() {
    window.__gtm_captured = window.__gtm_captured || [];
    window.__gtm_listener_injected = window.__gtm_listener_injected || false;

    function installListener() {
        if (window.__gtm_listener_injected) return;
        if (!window.dataLayer) {
            window.dataLayer = [];
        }
        const _originalPush = window.dataLayer.push.bind(window.dataLayer);
        window.dataLayer.push = function() {
            for (var i = 0; i < arguments.length; i++) {
                var item = arguments[i];
                if (item && typeof item === 'object') {
                    window.__gtm_captured.push({
                        data: JSON.parse(JSON.stringify(item)),
                        timestamp: Date.now(),
                        url: window.location.href
                    });
                }
            }
            return _originalPush.apply(window.dataLayer, arguments);
        };
        window.__gtm_listener_injected = true;
    }

    installListener();

    // dataLayer가 나중에 정의되는 경우를 위한 폴링
    if (!window.__gtm_listener_injected) {
        var _checkInterval = setInterval(function() {
            if (window.dataLayer) {
                installListener();
                clearInterval(_checkInterval);
            }
        }, 50);
    }
})();
"""


async def inject_listener(page: Page) -> None:
    """Playwright 페이지에 Persistent Event Listener를 주입합니다."""
    await page.add_init_script(_LISTENER_SCRIPT)


async def get_captured_events(page: Page) -> list[dict]:
    """현재까지 캡처된 dataLayer 이벤트 목록을 반환합니다."""
    events = await page.evaluate("window.__gtm_captured || []")
    return events


async def clear_captured_events(page: Page) -> None:
    """캡처된 이벤트 버퍼를 초기화합니다."""
    await page.evaluate("window.__gtm_captured = []")
