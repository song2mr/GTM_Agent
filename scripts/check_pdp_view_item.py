"""PDP 접속 후 dataLayer에 view_item이 쌓이는지 샘플 확인.

프로젝트의 listener(훅 + 병합)와 동일한 방식으로 측정합니다.

실행 (저장소 루트에서):
  py -3 scripts/check_pdp_view_item.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# repo root on path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from playwright.async_api import async_playwright

from browser.listener import (
    get_captured_events,
    inject_listener,
    peek_datalayer_raw,
    snapshot_datalayer_names,
)

PDP_URL = (
    "https://www.snowpeakstore.co.kr/goods/goods_view.php?goodsNo=1000010861"
    "&mtn=72%5E%7C%5E%E2%AD%90%EF%B8%8F%5B%EB%A9%94%EC%9D%B8%ED%8E%98%EC%9D%B4%EC%A7%80"
    "%2B%EC%83%81%EB%8B%A8%5D%2BBEST%2BITEM%5E%7C%5En"
)


async def _js_has_view_item(page) -> dict:
    """브라우저에서 dataLayer 배열을 직접 훑어 view_item 존재 여부."""
    return await page.evaluate(
        """() => {
            const dl = window.dataLayer;
            if (!Array.isArray(dl)) return { ok: false, reason: 'no array', len: -1, hits: [] };
            const hits = [];
            for (let i = 0; i < dl.length; i++) {
                const x = dl[i];
                if (x && typeof x === 'object' && x.event === 'view_item') {
                    hits.push({ index: i, keys: Object.keys(x) });
                }
            }
            return { ok: true, len: dl.length, hits };
        }"""
    )


async def main() -> None:
    headless = "--headed" not in sys.argv
    print(f"headless={headless} (add --headed for visible browser)")
    print(f"URL:\n{PDP_URL}\n")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        try:
            page = await browser.new_page()
            await inject_listener(page)
            await page.goto(PDP_URL, wait_until="domcontentloaded", timeout=45_000)

            checkpoints = (2_000, 5_000, 10_000)  # ms from navigation start (cumulative waits below)

            waited = 0
            for i, ms in enumerate(checkpoints):
                add = ms - waited
                if add > 0:
                    await page.wait_for_timeout(add)
                    waited += add
                print(f"--- t~{waited/1000:.0f}s after domcontentloaded ---")
                print(f"page.url: {page.url!r}")

                direct = await _js_has_view_item(page)
                print(f"JS scan view_item hits: {json.dumps(direct, ensure_ascii=False)}")

                snap = await snapshot_datalayer_names(page)
                sig = snap.get("signal_names", [])
                print(
                    f"snapshot_datalayer_names: signal_names={sig!r} "
                    f"cap_n={snap.get('cap_n')} dl_n={snap.get('dl_n')}"
                )

                cap = await get_captured_events(page, log_tag=f"sample/checkpoint-{i}")
                names = [(e.get("data") or {}).get("event") for e in cap]
                print(f"get_captured_events (filtered): {[n for n in names if n]!r}")

                tail = await peek_datalayer_raw(page, 8)
                evs = [x.get("event") if isinstance(x, dict) else None for x in tail]
                print(f"dataLayer raw tail events (last 8): {evs!r}")
                print()

            if direct.get("hits") or "view_item" in (snap.get("signal_names") or []):
                print("RESULT: view_item observed in dataLayer on this PDP URL.")
            else:
                print("RESULT: no view_item in dataLayer (or filtered) within waits.")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
