"""Persistent Event Listener 주입 유틸.

page.add_init_script()로 주입하므로 페이지 이동 후에도 리스너가 유지됩니다.
모든 dataLayer.push 이벤트를 window.__gtm_captured에 누적합니다.

또한 get_captured_events 시점에 window.dataLayer 배열을 훑어,
`event` 키가 있는 객체를 병합합니다(push 훅만으로 놓치는 초기·교체 배열 항목 보완).
"""

from __future__ import annotations

import json

from playwright.async_api import Page

# LLM 사용자 메시지에 넣는 dataLayer 요약 상한
_DATALAYER_LLM_MAX_OBJECTS = 35
_DATALAYER_LLM_MAX_CHARS = 8000

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

# push 로그(__gtm_captured)와 배열 본문(dataLayer) 병합 — 동일 항목은 gtm.uniqueEventId 우선으로 제외
_MERGE_CAPTURED_AND_ARRAY_SCRIPT = """
() => {
    const cap = window.__gtm_captured || [];
    const dl = window.dataLayer;
    const seen = new Set();

    function stableKey(d) {
        if (!d || typeof d !== 'object') return '';
        if (typeof d['gtm.uniqueEventId'] === 'number') {
            return 'g:' + d['gtm.uniqueEventId'];
        }
        try {
            return 'e:' + String(d.event) + ':' + JSON.stringify(d).slice(0, 240);
        } catch (e) {
            return 'x:' + String(d.event);
        }
    }

    const out = [];
    for (let i = 0; i < cap.length; i++) {
        const e = cap[i];
        const d = e && e.data;
        if (!d || typeof d !== 'object') continue;
        const k = stableKey(d);
        if (seen.has(k)) continue;
        seen.add(k);
        out.push(e);
    }

    if (Array.isArray(dl)) {
        for (let j = 0; j < dl.length; j++) {
            const item = dl[j];
            if (!item || typeof item !== 'object' || typeof item.event !== 'string') continue;
            const k = stableKey(item);
            if (seen.has(k)) continue;
            seen.add(k);
            const ts = typeof item['gtm.uniqueEventId'] === 'number'
                ? item['gtm.uniqueEventId']
                : (1000000000 + j);
            try {
                out.push({
                    data: JSON.parse(JSON.stringify(item)),
                    timestamp: ts,
                    url: (typeof window.location !== 'undefined' && window.location.href) || ''
                });
            } catch (err) {}
        }
    }
    return out;
}
"""


def is_datalayer_noise_event_name(event_name: str) -> bool:
    """GTM 내부·Ajax·스크립트 경로 등 — Planning/Navigator 요약에서 제외(denylist).

    허용 목록을 두지 않는 이유: 비표준/광고주 전용 이벤트명은 그대로 통과시키기 위함.
    """
    if not isinstance(event_name, str):
        return True
    s = event_name.strip()
    if not s:
        return True
    low = s.lower()
    if low.startswith("gtm."):
        return True
    if low.startswith("ajax"):
        return True
    # GTM이 event 자리에 스크립트 URL·짧은 토큰을 넣는 경우
    if low in (".js", "js", "config"):
        return True
    if s.startswith("/") and (".js" in low or "gtm" in low):
        return True
    if low.startswith("http://") or low.startswith("https://"):
        return True
    return False


def is_signal_captured_event(ev: dict) -> bool:
    """리스너/병합 항목 중 시맨틱 측정에 쓸 만한 dataLayer 이벤트인지."""
    if ev.get("source") == "manual":
        return True
    data = ev.get("data")
    if not isinstance(data, dict):
        return False
    evn = data.get("event")
    if not isinstance(evn, str):
        return False
    return not is_datalayer_noise_event_name(evn)


def filter_signal_datalayer_events(events: list[dict]) -> list[dict]:
    """노이즈 제거 후 목록 (Planning 요약·후속 파이프라인 공통)."""
    return [e for e in events if is_signal_captured_event(e)]


async def inject_listener(page: Page) -> None:
    """Playwright 페이지에 Persistent Event Listener를 주입합니다."""
    await page.add_init_script(_LISTENER_SCRIPT)


async def get_captured_events(page: Page) -> list[dict]:
    """push로 쌓인 __gtm_captured와, 현재 window.dataLayer 배열을 합친 목록을 반환합니다."""
    events = await page.evaluate(_MERGE_CAPTURED_AND_ARRAY_SCRIPT)
    if not isinstance(events, list):
        return []
    return filter_signal_datalayer_events(events)


_DATALAYER_EVENT_ROWS_FOR_LLM_SCRIPT = f"""
() => {{
    const dl = window.dataLayer;
    if (!Array.isArray(dl)) return [];
    const rows = [];
    for (let i = 0; i < dl.length; i++) {{
        const item = dl[i];
        if (!item || typeof item !== 'object' || typeof item.event !== 'string') continue;
        try {{
            rows.push(JSON.parse(JSON.stringify(item)));
        }} catch (e) {{}}
    }}
    return rows.slice(-{_DATALAYER_LLM_MAX_OBJECTS});
}}
"""


async def get_datalayer_event_context_for_llm(page: Page) -> str:
    """`event` 문자열이 있는 dataLayer 객체만 JSON 배열로 요약 (Navigator LLM 컨텍스트).

    토큰·메시지 상한을 위해 최근 일부만 포함합니다.
    """
    rows = await page.evaluate(_DATALAYER_EVENT_ROWS_FOR_LLM_SCRIPT)
    if not isinstance(rows, list) or not rows:
        return ""
    rows = [
        r
        for r in rows
        if isinstance(r, dict)
        and isinstance(r.get("event"), str)
        and not is_datalayer_noise_event_name(r["event"])
    ]
    try:
        s = json.dumps(rows, ensure_ascii=False)
    except (TypeError, ValueError):
        return ""
    if len(s) > _DATALAYER_LLM_MAX_CHARS:
        s = s[: _DATALAYER_LLM_MAX_CHARS - 24] + "\n…(이하 잘림)"
    return s


def event_fingerprint(ev: dict) -> tuple:
    """captured_events 중복 판정을 위한 고유 키.

    기존 `e in captured_so_far` (dict 전체 동등성) 비교는:
      - 느리고(O(N*M) 필드 비교),
      - 향후 메타 필드(`source`, 기타) 추가되면 같은 이벤트가 "다른 것"으로 보일 위험.

    listener JS는 모든 이벤트에 `timestamp`를 찍어주므로 (ts, event명, url) 튜플이면
    실용적 고유성이 확보된다. ts가 없는 외부 경로(manual 등)는 id()로 폴백해
    최소한 객체 단위로는 구분되게 한다.
    """
    data = ev.get("data") or {}
    ts = ev.get("timestamp")
    if ts is None:
        return ("noid", id(ev))
    return (ts, data.get("event", ""), ev.get("url", ""))


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
