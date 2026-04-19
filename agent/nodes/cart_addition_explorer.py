"""Node 3.25: 장바구니·바스켓 담기 계열 전용 탐색.

Journey Planner가 `cart_addition_events`에 넣은 이름만 처리합니다.
일반 Active Explorer는 동일 이벤트를 건너뛰고, 여기서만 `CartAdditionNavigator`를 사용합니다.
"""

from __future__ import annotations

import os
import time

from playwright.async_api import async_playwright

from agent.nodes.active_explorer import _build_synthetic_event, _extract_dom_data
from agent.state import GTMAgentState
from browser.actions import click, close_popup, navigate
from browser.cart_addition_navigator import CartAdditionNavigator
from browser.listener import (
    event_fingerprint,
    get_captured_events,
    inject_listener,
    snapshot_datalayer_names,
)
from browser.url_context import url_looks_like_cart_resume, url_looks_like_pdp
from utils import logger
from utils.ui_emitter import emit, update_state


async def cart_addition_explorer(state: GTMAgentState) -> GTMAgentState:
    """장바구니 담기 계열 이벤트만 별도 브라우저 세션으로 재시도."""
    emit(
        "node_enter",
        node_id=3.25,
        node_key="cart_addition_explorer",
        title="Cart Addition Explorer",
    )
    update_state(current_node=3.25, nodes_status={"cart_addition_explorer": "run"})
    _started = time.time()

    targets = list(state.get("cart_addition_events") or [])
    if not targets:
        _dur = int((time.time() - _started) * 1000)
        emit("node_exit", node_id=3.25, status="skip", duration_ms=_dur)
        update_state(nodes_status={"cart_addition_explorer": "skip"})
        return state

    resume = state.get("current_url") or state["target_url"]
    last_pdp_url = (state.get("last_pdp_url") or "").strip()
    if url_looks_like_cart_resume(resume) and last_pdp_url:
        target_url = last_pdp_url
        logger.info(
            f"[CartAdditionExplorer] resume가 장바구니형 → last_pdp_url로 PDP 재개: {target_url!r}"
        )
    else:
        target_url = resume

    manual_required = list(state.get("manual_required", []))
    captured_events: list[dict] = list(state.get("captured_events", []))
    exploration_log: list[str] = list(state.get("exploration_log", []))
    event_capture_log: list[dict] = list(state.get("event_capture_log", []))

    extraction_method = state.get("extraction_method", "datalayer")
    dom_selectors = state.get("dom_selectors", {})
    click_triggers = state.get("click_triggers", {})
    use_dom = extraction_method != "datalayer"

    headless = os.environ.get("GTM_AI_HEADLESS", "").lower() in ("1", "true", "yes")
    logger.info(
        f"[CartAdditionExplorer] 시작 events={targets!r} resume_url={target_url!r} "
        f"headless={headless}"
    )

    last_live_url = target_url

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=headless,
            args=["--ignore-certificate-errors", "--ignore-ssl-errors"],
        )
        try:
            context = await browser.new_context(ignore_https_errors=True)
            page = await context.new_page()
            await inject_listener(page)
            await navigate(page, target_url)
            await page.wait_for_timeout(2000)
            try:
                await logger.probe_datalayer_verbose(
                    page,
                    "cart_addition_explorer/initial",
                    page.url,
                    "",
                    extra={"targets": targets},
                    raw_tail_n=12,
                )
            except Exception as e:
                logger.debug(f"[CartAdditionExplorer] initial DL probe 실패: {e}")
            try:
                last_live_url = page.url
                if url_looks_like_pdp(last_live_url):
                    last_pdp_url = last_live_url
            except Exception:
                pass

            for target_event in targets:
                try:
                    last_live_url = page.url
                    if url_looks_like_pdp(last_live_url):
                        last_pdp_url = last_live_url
                except Exception:
                    pass

                already = any(
                    e.get("data", {}).get("event") == target_event for e in captured_events
                )
                if already:
                    exploration_log.append(f"{target_event}: 이미 캡처됨 (cart 노드 스킵)")
                    event_capture_log.append(
                        {
                            "event": target_event,
                            "method": "datalayer",
                            "result": "success",
                            "selector": "",
                            "notes": "이전 노드에서 이미 캡처됨",
                        }
                    )
                    continue

                logger.info(f"[CartAdditionExplorer] 목표: {target_event}")
                try:
                    _ent = await snapshot_datalayer_names(page)
                    logger.log_dl_state(
                        "cart_addition_explorer/event-enter",
                        page.url,
                        _ent,
                        target_event=target_event,
                        extra={"captured_n": len(captured_events)},
                    )
                except Exception:
                    pass

                if target_event in click_triggers:
                    trigger_sel = click_triggers[target_event]
                    await close_popup(page)
                    try:
                        _pre_ct = await snapshot_datalayer_names(page)
                        logger.log_dl_state(
                            "cart_addition_explorer/click_trigger/pre",
                            page.url,
                            _pre_ct,
                            target_event=target_event,
                            extra={"trigger_selector": trigger_sel},
                        )
                    except Exception:
                        pass
                    click_result = await click(page, trigger_sel, timeout=8000)
                    if click_result.success:
                        await page.wait_for_timeout(2000)
                        dl_events = await get_captured_events(
                            page,
                            log_tag=f"cart_addition_explorer/click_trigger/{target_event}",
                        )
                        try:
                            _post_ct = await snapshot_datalayer_names(page)
                            logger.log_dl_state(
                                "cart_addition_explorer/click_trigger/post-2s",
                                page.url,
                                _post_ct,
                                target_event=target_event,
                                extra={"trigger_selector": trigger_sel},
                            )
                        except Exception:
                            pass
                        seen_fps = {event_fingerprint(e) for e in captured_events}
                        dl_match = [
                            e
                            for e in dl_events
                            if event_fingerprint(e) not in seen_fps
                            and e.get("data", {}).get("event") == target_event
                        ]
                        if dl_match:
                            for e in dl_match:
                                captured_events.append(e)
                            exploration_log.append(
                                f"{target_event}: 클릭 트리거 후 dataLayer 성공 (cart 노드)"
                            )
                            event_capture_log.append(
                                {
                                    "event": target_event,
                                    "method": "click_trigger_datalayer",
                                    "result": "success",
                                    "selector": trigger_sel,
                                    "notes": "Cart Addition 노드: 구조분석 트리거 클릭 후 발화",
                                }
                            )
                            continue

                nav = CartAdditionNavigator()
                result = await nav.run_for_event(page, target_event, captured_events)

                if result == "captured":
                    seen_fps = {event_fingerprint(e) for e in captured_events}
                    for e in await get_captured_events(
                        page, log_tag=f"cart_addition_explorer/nav-success/{target_event}"
                    ):
                        if event_fingerprint(e) not in seen_fps:
                            captured_events.append(e)
                            seen_fps.add(event_fingerprint(e))
                    exploration_log.append(f"{target_event}: CartAdditionNavigator 캡처 성공")
                    event_capture_log.append(
                        {
                            "event": target_event,
                            "method": "cart_navigator_datalayer",
                            "result": "success",
                            "selector": "",
                            "notes": "장바구니 담기 전용 Navigator로 dataLayer 캡처",
                        }
                    )
                    continue

                if use_dom and dom_selectors:
                    dom_data = await _extract_dom_data(page, dom_selectors)
                    if dom_data:
                        synth = _build_synthetic_event(target_event, dom_data, page.url)
                        captured_events.append(synth)
                        exploration_log.append(
                            f"{target_event}: Cart Navigator 실패 → DOM 폴백 (cart 노드)"
                        )
                        event_capture_log.append(
                            {
                                "event": target_event,
                                "method": "dom_fallback",
                                "result": "success",
                                "selector": "",
                                "notes": "Cart Addition 노드에서 DOM 폴백",
                            }
                        )
                        continue

                if target_event not in manual_required:
                    manual_required.append(target_event)
                exploration_log.append(f"{target_event}: cart 노드 실패 → Manual")
                event_capture_log.append(
                    {
                        "event": target_event,
                        "method": "manual",
                        "result": "pending",
                        "selector": "",
                        "notes": "Cart Addition 전용 절차 실패 → Manual",
                    }
                )

            try:
                last_live_url = page.url
                if url_looks_like_pdp(last_live_url):
                    last_pdp_url = last_live_url
            except Exception:
                pass

        finally:
            try:
                await browser.close()
            except Exception as e:
                # MVP 단계에서도 브라우저 종료 실패는 디버그에 남긴다 (디스크/좀비 탐지용)
                logger.debug(f"[CartAdditionExplorer] browser.close() 예외 무시: {e}")

    for ev in captured_events:
        data = ev.get("data", {})
        event_name = data.get("event", "")
        if event_name and not event_name.startswith("gtm."):
            emit(
                "datalayer_event",
                event=event_name,
                url=ev.get("url", ""),
                source=ev.get("source", "datalayer"),
                params={k: v for k, v in data.items() if k != "event"},
            )

    _dur = int((time.time() - _started) * 1000)
    emit("node_exit", node_id=3.25, status="done", duration_ms=_dur)
    update_state(nodes_status={"cart_addition_explorer": "done"})

    if not manual_required and not state.get("begin_checkout_events"):
        update_state(nodes_status={"manual_capture": "skip"})

    return {
        **state,
        "captured_events": captured_events,
        "manual_required": manual_required,
        "current_url": last_live_url,
        "last_pdp_url": last_pdp_url,
        "exploration_log": exploration_log,
        "event_capture_log": event_capture_log,
    }
