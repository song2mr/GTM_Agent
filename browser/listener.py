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


async def get_captured_events(page: Page, log_tag: str | None = None) -> list[dict]:
    """push로 쌓인 __gtm_captured와, 현재 window.dataLayer 배열을 합친 목록을 반환합니다.

    log_tag가 있으면 병합·노이즈 필터 전후 개수와 이벤트명 꼬리를 DEBUG로 남긴다.
    """
    events = await page.evaluate(_MERGE_CAPTURED_AND_ARRAY_SCRIPT)
    if not isinstance(events, list):
        events = []
    merged_n = len(events)
    filtered = filter_signal_datalayer_events(events)
    if log_tag:
        try:
            from utils import logger as _log

            names: list[str] = []
            for e in filtered:
                d = e.get("data") if isinstance(e, dict) else None
                if isinstance(d, dict):
                    evn = d.get("event")
                    if isinstance(evn, str):
                        names.append(evn)
            _log.debug(
                f"[get_captured_events] tag={log_tag!r} merged_n={merged_n} "
                f"filtered_n={len(filtered)} events_tail={names[-25:]!r}"
            )
        except Exception:
            pass
    return filtered


_DL_SNAPSHOT_SCRIPT = """
() => {
    const cap = Array.isArray(window.__gtm_captured) ? window.__gtm_captured : [];
    const dl  = Array.isArray(window.dataLayer) ? window.dataLayer : null;
    const names = [];
    const seen = new Set();
    function add(name) {
        if (typeof name !== 'string' || !name) return;
        if (seen.has(name)) return;
        seen.add(name);
        names.push(name);
    }
    for (let i = 0; i < cap.length; i++) {
        const d = cap[i] && cap[i].data;
        if (d && typeof d === 'object') add(d.event);
    }
    if (dl) {
        for (let j = 0; j < dl.length; j++) {
            const it = dl[j];
            if (it && typeof it === 'object') add(it.event);
        }
    }
    return {
        cap_n: cap.length,
        dl_n: dl ? dl.length : -1,
        has_dl: dl !== null,
        has_gtm: Boolean(window.google_tag_manager),
        listener_injected: Boolean(window.__gtm_listener_injected),
        names: names,
    };
}
"""


_DL_PEEK_RAW_SCRIPT = """
(n) => {
    const dl = Array.isArray(window.dataLayer) ? window.dataLayer : [];
    const take = Math.max(1, Math.min(n || 8, 40));
    const tail = dl.slice(Math.max(0, dl.length - take));
    const out = [];
    for (let i = 0; i < tail.length; i++) {
        try {
            out.push(JSON.parse(JSON.stringify(tail[i])));
        } catch (e) {
            try { out.push({ __peek_error: String(e), keys: Object.keys(tail[i] || {}) }); } catch (_) {}
        }
    }
    return out;
}
"""


async def peek_datalayer_raw(page: Page, last_n: int = 8) -> list:
    """window.dataLayer 배열 꼬리 N개 원본 payload (JSON 직렬화 가능 형태).

    snapshot_datalayer_names가 'event' 문자열만 건네는 것과 달리,
    여기선 payload 전체를 돌려줘 "이름은 맞는데 구조가 달라 필터에 걸림" 같은
    병리적 케이스를 사후에 확인할 수 있게 한다.
    """
    try:
        items = await page.evaluate(_DL_PEEK_RAW_SCRIPT, last_n)
    except Exception as e:
        return [{"__peek_error": str(e)[:200]}]
    return items if isinstance(items, list) else []


async def snapshot_datalayer_names(page: Page) -> dict:
    """현재 __gtm_captured + window.dataLayer의 event 이름 목록을 요약합니다.

    로그/진단 전용. get_captured_events와 달리 dedupe만 event명 기준으로 하고
    원본 payload는 돌려주지 않아 직렬화가 싸다.

    Returns:
        {
            "cap_n": int,                    # __gtm_captured 길이
            "dl_n": int,                     # window.dataLayer 길이 (-1이면 배열 아님)
            "has_dl": bool,
            "has_gtm": bool,
            "listener_injected": bool,
            "names": [event명...],           # 중복 제거 + 등장 순서 (cap → dl)
            "signal_names": [...],           # 노이즈 제거 결과
            "noise_names": [...],            # denylist에 걸린 이름들
            "signal_n": int,
            "noise_n": int,
        }
    """
    try:
        snap = await page.evaluate(_DL_SNAPSHOT_SCRIPT)
    except Exception as e:
        return {
            "error": str(e)[:200],
            "cap_n": 0, "dl_n": -1, "has_dl": False, "has_gtm": False,
            "listener_injected": False,
            "names": [], "signal_names": [], "noise_names": [],
            "signal_n": 0, "noise_n": 0,
        }
    if not isinstance(snap, dict):
        snap = {}
    raw_names = snap.get("names") or []
    signal = [n for n in raw_names if not is_datalayer_noise_event_name(n)]
    noise = [n for n in raw_names if is_datalayer_noise_event_name(n)]
    snap["signal_names"] = signal
    snap["noise_names"] = noise
    snap["signal_n"] = len(signal)
    snap["noise_n"] = len(noise)
    return snap


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
