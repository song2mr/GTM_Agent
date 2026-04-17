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


_DIAGNOSE_SCRIPT = """
() => {
    const result = {
        has_datalayer: Boolean(window.dataLayer),
        has_gtm: Boolean(window.google_tag_manager),
        events: [],
        has_ecommerce: false,
        ecommerce_fields: [],
        json_ld: []
    };

    // dataLayer 이벤트 수집
    if (window.dataLayer && Array.isArray(window.dataLayer)) {
        for (const item of window.dataLayer) {
            if (item && typeof item === 'object' && item.event) {
                result.events.push(item.event);
                if (item.ecommerce) {
                    result.has_ecommerce = true;
                    result.ecommerce_fields = Object.keys(item.ecommerce);
                }
            }
        }
    }

    // JSON-LD 구조화 데이터 수집
    const ldScripts = document.querySelectorAll('script[type="application/ld+json"]');
    for (const s of ldScripts) {
        try {
            const parsed = JSON.parse(s.textContent);
            result.json_ld.push(parsed);
        } catch {}
    }

    return result;
}
"""


async def diagnose_datalayer(page: Page) -> dict:
    """dataLayer 상태를 진단합니다.

    Returns:
        {
            "has_datalayer": bool,
            "has_gtm": bool,
            "events": ["page_view", ...],
            "has_ecommerce": bool,
            "ecommerce_fields": ["items", "currency", ...],
            "json_ld": [{ "@type": "Product", ... }, ...],
            "status": "full" | "partial" | "none"
        }
    """
    result = await page.evaluate(_DIAGNOSE_SCRIPT)

    ecommerce_events = {
        "view_item_list", "view_item", "select_item",
        "add_to_cart", "remove_from_cart", "view_cart",
        "begin_checkout", "add_shipping_info", "add_payment_info",
        "purchase", "refund",
    }
    found = set(result.get("events", []))
    ecom_found = found & ecommerce_events

    if result.get("has_ecommerce") and len(ecom_found) >= 3:
        result["status"] = "full"
    elif result.get("has_datalayer") and (ecom_found or result.get("has_ecommerce")):
        result["status"] = "partial"
    else:
        result["status"] = "none"

    return result
