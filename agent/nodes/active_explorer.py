"""Node 3: Active Explorer (핵심).

LLM Navigator + Playwright 루프로 탐색 큐의 이벤트를 순서대로 캡처합니다.
Navigator는 액션 히스토리 기반으로 멀티스텝 탐색을 수행하며, 실패 시 manual_required로 이관합니다.

dataLayer가 없는 경우(extraction_method != "datalayer"):
  - 클릭 트리거를 실행한 뒤 DOM selector로 제품 데이터를 직접 추출
  - 추출된 데이터로 가상 이벤트 객체를 생성
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

from playwright.async_api import Page, async_playwright

import time

from agent.state import GTMAgentState
from browser.actions import click, close_popup, navigate
from browser.listener import (
    get_captured_events,
    inject_listener,
    peek_datalayer_raw,
    snapshot_datalayer_names,
)
from browser.navigator import LLMNavigator
from browser.url_context import url_looks_like_pdp
from utils import logger
from utils.ui_emitter import emit, update_state


async def _extract_dom_data(page: Page, dom_selectors: dict) -> dict:
    """DOM selector 기반으로 페이지에서 제품 데이터를 직접 추출합니다."""
    extracted: dict = {}
    for field, spec in dom_selectors.items():
        selector = spec.get("selector", "") if isinstance(spec, dict) else spec
        attribute = spec.get("attribute") if isinstance(spec, dict) else None
        if not selector:
            continue
        try:
            el = await page.query_selector(selector)
            if el is None:
                continue
            if attribute and attribute != "textContent":
                value = await el.get_attribute(attribute)
            else:
                value = await el.text_content()
            if value:
                extracted[field] = value.strip()
        except Exception:
            continue
    return extracted


def _build_synthetic_event(
    event_name: str,
    dom_data: dict,
    url: str,
) -> dict:
    """DOM에서 추출한 데이터로 dataLayer 형식의 가상 이벤트를 생성합니다."""
    item: dict = {}
    field_mapping = {
        "item_name": "item_name",
        "item_id": "item_id",
        "price": "price",
        "item_brand": "item_brand",
        "item_category": "item_category",
        "item_variant": "item_variant",
        "quantity": "quantity",
    }
    for dom_field, ga4_field in field_mapping.items():
        if dom_field in dom_data:
            value = dom_data[dom_field]
            if ga4_field in ("price", "quantity"):
                import re
                nums = re.findall(r"[\d,]+\.?\d*", str(value))
                if nums:
                    value = float(nums[0].replace(",", ""))
            item[ga4_field] = value

    ecommerce: dict = {}
    if item:
        ecommerce["items"] = [item]
    if "currency" in dom_data:
        ecommerce["currency"] = dom_data["currency"]
    if "price" in item:
        ecommerce["value"] = item["price"]

    return {
        "data": {
            "event": event_name,
            "ecommerce": ecommerce,
        },
        "timestamp": None,
        "url": url,
        "source": "dom_extraction",
    }


def _auto_capturable_with_cart_addition_order(
    auto: list[str],
    cart_addition_events: list[str],
) -> list[str]:
    """장바구니 담기가 뒤 노드에 있으면 `view_cart`를 맨 뒤로 — PDP에서 옵션·담기가 먼저."""
    if not cart_addition_events or "view_cart" not in auto:
        return list(auto)
    others = [e for e in auto if e != "view_cart"]
    return others + ["view_cart"]


def _surface_goal_reached(url: str, surface_goal: str) -> bool:
    u = (url or "").lower()
    goal = (surface_goal or "").lower()
    if goal in ("", "current", "unknown"):
        return True
    if goal == "pdp":
        return ("/product/" in u) or ("goods_view" in u) or ("product_no=" in u)
    if goal == "plp":
        return ("/category/" in u) or ("goods_list" in u) or ("catecd=" in u)
    if goal == "cart":
        return "/cart" in u or "/basket" in u
    if goal == "checkout":
        return "/checkout" in u or "/order" in u or "checkout" in u
    if goal == "home":
        return urlparse(u).path in ("", "/")
    return True


def _surface_seed_url(base_url: str, surface_goal: str) -> str | None:
    parsed = urlparse(base_url or "")
    if not parsed.scheme or not parsed.netloc:
        return None
    origin = f"{parsed.scheme}://{parsed.netloc}"
    goal = (surface_goal or "").lower()
    if goal == "cart":
        return origin + "/cart"
    if goal == "checkout":
        return origin + "/checkout"
    if goal == "home":
        return origin + "/"
    return None


def _url_to_observed_pattern(url: str, surface_goal: str) -> tuple[str, str] | None:
    """실제 방문한 URL을 관측 기반 정규식으로 요약.

    (key, regex) 반환. key는 surface_goal 또는 "current".
    """
    path = urlparse(url or "").path or "/"
    if not path:
        return None
    segs = [s for s in path.split("/") if s]
    if not segs:
        return (surface_goal or "home", r"^/?$")
    # 마지막 세그먼트가 수치/슬러그라면 `/prefix/[^/]+/?$` 형태로 일반화.
    prefix = "/".join(segs[:-1])
    key = (surface_goal or "current").lower()
    if prefix:
        regex = rf"^/{prefix}/[^/]+/?$"
    else:
        regex = rf"^/{segs[0]}/?$"
    return key, regex


def _attach_evidence(
    event_row: dict,
    *,
    page_url: str,
    dom_resolved: dict | None = None,
    json_ld_data: dict | None = None,
    failures: list[dict] | None = None,
) -> dict:
    """`captured_events[i].evidence`에 고정 포맷으로 판단 재료를 박는다(§Phase 1b Done-when)."""
    data = event_row.get("data") or {}
    url = event_row.get("url") or page_url or ""
    path = urlparse(url).path if url else ""
    evidence = {
        "url": url,
        "path": path,
        "datalayer": {"fired": event_row.get("source") != "dom_extraction", "sample": data},
        "dom": {"resolved": dict(dom_resolved or {})},
        "json_ld": {"extracted": dict(json_ld_data or {})},
        "failures": list(failures or []),
    }
    event_row.setdefault("evidence", evidence)
    return event_row


async def active_explorer(state: GTMAgentState) -> GTMAgentState:
    """Node 3: LLM Navigator + Playwright 루프."""
    emit("node_enter", node_id=3, node_key="active_explorer", title="Active Explorer")
    update_state(current_node=3, nodes_status={"active_explorer": "run"})
    _started = time.time()

    target_url = state["target_url"]
    auto_capturable = state.get("auto_capturable", [])
    manual_required = list(state.get("manual_required", []))

    captured_events: list[dict] = list(state.get("captured_events", []))
    exploration_log: list[str] = list(state.get("exploration_log", []))
    event_capture_log: list[dict] = list(state.get("event_capture_log", []))
    exploration_failures: list[dict] = list(state.get("exploration_failures") or [])
    observed_url_patterns: dict = dict(state.get("site_url_patterns") or {})
    json_ld_data = state.get("json_ld_data") or {}
    selector_validation = state.get("selector_validation") or {}

    extraction_method = state.get("extraction_method", "datalayer")
    dom_selectors = state.get("dom_selectors", {})
    click_triggers = state.get("click_triggers", {})
    use_dom = extraction_method != "datalayer"

    navigator = LLMNavigator()
    exploration_plan = list(state.get("exploration_plan") or [])
    playbook_by_event = {
        str(row.get("event", "")): row.get("playbook", {})
        for row in exploration_plan
        if isinstance(row, dict) and row.get("event")
    }
    last_pdp_url = (state.get("last_pdp_url") or "").strip()

    headless = os.environ.get("GTM_AI_HEADLESS", "").lower() in ("1", "true", "yes")
    logger.info(
        f"[ActiveExplorer] Playwright headless={headless} "
        f"(GTM_AI_HEADLESS={os.environ.get('GTM_AI_HEADLESS', '')!r})"
    )

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
            
            # 로드 직후 이벤트 수집 (page_view 포함)
            initial_events = await get_captured_events(
                page, log_tag="active_explorer/initial"
            )
            for e in initial_events:
                if e not in captured_events:
                    captured_events.append(e)

            _dl_snap = await snapshot_datalayer_names(page)
            logger.log_dl_state(
                "active_explorer/initial",
                page.url,
                _dl_snap,
                extra={
                    "initial_events_n": len(initial_events),
                    "auto_capturable": auto_capturable,
                },
            )

            try:
                live_page_url = page.url
                if url_looks_like_pdp(live_page_url):
                    last_pdp_url = live_page_url
            except Exception:
                live_page_url = target_url

            # DOM 모드: 페이지 로드 시 page_view + 현재 데이터 바로 추출
            if use_dom and dom_selectors:
                dom_data = await _extract_dom_data(page, dom_selectors)
                if dom_data:
                    pv_event = _build_synthetic_event("page_view", dom_data, page.url)
                    captured_events.append(pv_event)
                    exploration_log.append(f"page_view: DOM 추출 성공 ({list(dom_data.keys())})")
                    logger.info(f"[ActiveExplorer] DOM 추출 page_view: {list(dom_data.keys())}")
                    event_capture_log.append({
                        "event": "page_view",
                        "method": "dom_fallback",
                        "result": "success",
                        "selector": "",
                        "notes": f"dataLayer 미사용 사이트, DOM 직접 추출 (필드: {list(dom_data.keys())})",
                    })
            
            deferred = set(state.get("cart_addition_events") or []) | set(
                state.get("begin_checkout_events") or []
            )

            ordered_auto = _auto_capturable_with_cart_addition_order(
                auto_capturable,
                list(state.get("cart_addition_events") or []),
            )

            for target_event in ordered_auto:
                playbook = playbook_by_event.get(target_event, {})
                try:
                    u = page.url
                    if url_looks_like_pdp(u):
                        last_pdp_url = u
                except Exception:
                    pass

                surface_goal = str(playbook.get("surface_goal", "unknown"))
                if not _surface_goal_reached(page.url, surface_goal):
                    seed_url = _surface_seed_url(target_url, surface_goal)
                    if seed_url:
                        nav_surface = await navigate(page, seed_url)
                        if nav_surface.success:
                            await page.wait_for_timeout(1200)
                            exploration_log.append(
                                f"{target_event}: playbook surface_goal({surface_goal}) 선행 이동 {seed_url}"
                            )
                            logger.info(
                                f"[ActiveExplorer] {target_event} surface_goal={surface_goal} seed 이동 성공 {seed_url}"
                            )
                        else:
                            exploration_log.append(
                                f"{target_event}: playbook surface_goal({surface_goal}) 이동 실패 {seed_url}"
                            )
                    if not _surface_goal_reached(page.url, surface_goal):
                        exploration_failures.append(
                            {
                                "event": target_event,
                                "reason": "surface_unreached",
                                "detail": f"surface_goal={surface_goal} after seed attempt, url={page.url}",
                                "url": page.url,
                            }
                        )

                # 관측된 URL → site_url_patterns(observed) 누적.
                obs_pair = _url_to_observed_pattern(page.url, surface_goal)
                if obs_pair:
                    key, regex = obs_pair
                    observed_url_patterns.setdefault(key, regex)

                if target_event in deferred:
                    exploration_log.append(
                        f"{target_event}: 전용 탐색 노드로 이월 (Active Explorer 스킵)"
                    )
                    logger.info(
                        f"[ActiveExplorer] {target_event} → cart_addition / begin_checkout 전용 처리"
                    )
                    continue

                _pre_snap = await snapshot_datalayer_names(page)
                logger.log_dl_state(
                    "active_explorer/event-enter",
                    page.url,
                    _pre_snap,
                    target_event=target_event,
                    extra={"captured_n": len(captured_events)},
                )

                already_captured = any(
                    e.get("data", {}).get("event") == target_event
                    for e in captured_events
                )
                if already_captured:
                    exploration_log.append(f"{target_event}: 이미 캡처됨 (스킵)")
                    logger.info(f"[ActiveExplorer] {target_event} 이미 캡처됨, 스킵")
                    event_capture_log.append({
                        "event": target_event,
                        "method": "datalayer",
                        "result": "success",
                        "selector": "",
                        "notes": "페이지 로드 시점에 이미 dataLayer에서 캡처됨",
                    })
                    continue
            
                logger.info(f"[ActiveExplorer] 목표 이벤트: {target_event}")
                try:
                    live_page_url = page.url
                except Exception:
                    pass
            
                # ── 우선순위 1: 클릭 트리거 → 클릭 후 dataLayer 먼저 확인 (DL/DOM 무관) ──
                if target_event in click_triggers:
                    trigger_sel = click_triggers[target_event]
                    logger.info(f"[ActiveExplorer] DOM 모드: {target_event} → 클릭 {trigger_sel}")
                    await close_popup(page)
            
                    dom_data_before = await _extract_dom_data(page, dom_selectors)

                    _click_pre_snap = await snapshot_datalayer_names(page)
                    logger.log_dl_state(
                        "active_explorer/click_trigger/pre",
                        page.url,
                        _click_pre_snap,
                        target_event=target_event,
                        extra={"trigger_selector": trigger_sel},
                    )

                    click_result = await click(page, trigger_sel)
            
                    if click_result.success:
                        await page.wait_for_timeout(2000)
                        # 우선순위 1a: 클릭 후 dataLayer 이벤트 발화 여부 확인
                        dl_events = await get_captured_events(
                            page,
                            log_tag=f"active_explorer/click_trigger/{target_event}/post-2s",
                        )

                        _click_post_snap = await snapshot_datalayer_names(page)
                        _pre_signal = set(_click_pre_snap.get("signal_names", []))
                        _post_signal = set(_click_post_snap.get("signal_names", []))
                        _new_signal = sorted(_post_signal - _pre_signal)
                        logger.log_dl_state(
                            "active_explorer/click_trigger/post-2s",
                            page.url,
                            _click_post_snap,
                            target_event=target_event,
                            extra={
                                "trigger_selector": trigger_sel,
                                "new_signal_since_click": _new_signal,
                                "target_fired_within_2s": target_event in _new_signal,
                            },
                        )
                        if target_event not in _new_signal:
                            try:
                                _raw_ct = await peek_datalayer_raw(page, 12)
                                logger.log_dl_raw_peek(
                                    "active_explorer/click_trigger/post-2s-raw",
                                    page.url,
                                    _raw_ct,
                                    target_event=target_event,
                                    extra={"trigger_selector": trigger_sel},
                                )
                            except Exception:
                                pass

                        dl_match = [
                            e for e in dl_events
                            if e not in captured_events
                            and e.get("data", {}).get("event") == target_event
                        ]
                        if dl_match:
                            for e in dl_match:
                                captured_events.append(e)
                            exploration_log.append(f"{target_event}: 클릭 후 dataLayer 캡처 성공")
                            event_capture_log.append({
                                "event": target_event,
                                "method": "click_trigger_datalayer",
                                "result": "success",
                                "selector": trigger_sel,
                                "notes": f"버튼 클릭({trigger_sel}) 후 dataLayer.push() 발화 확인",
                            })
                        else:
                            # 우선순위 1b: dataLayer 미발화 → DOM에서 직접 추출
                            dom_data_after = await _extract_dom_data(page, dom_selectors)
                            data = dom_data_after if dom_data_after else dom_data_before
                            if data:
                                synth = _build_synthetic_event(target_event, data, page.url)
                                captured_events.append(synth)
                                exploration_log.append(f"{target_event}: 클릭 후 DOM 추출 성공")
                                logger.info(f"[ActiveExplorer] {target_event} DOM 추출 성공")
                                event_capture_log.append({
                                    "event": target_event,
                                    "method": "click_trigger_dom",
                                    "result": "success",
                                    "selector": trigger_sel,
                                    "notes": (
                                        f"버튼 클릭({trigger_sel}) 후 dataLayer 미발화 → "
                                        f"DOM에서 직접 데이터 추출"
                                    ),
                                })
                            else:
                                if target_event not in manual_required:
                                    manual_required.append(target_event)
                                exploration_log.append(f"{target_event}: DOM 추출 실패 → Manual")
                                event_capture_log.append({
                                    "event": target_event,
                                    "method": "click_trigger_dom",
                                    "result": "failed",
                                    "selector": trigger_sel,
                                    "notes": "버튼 클릭 후 dataLayer 미발화, DOM 추출도 실패 → Manual 이관",
                                })
                    else:
                        logger.info(f"[ActiveExplorer] {target_event} 클릭 실패: {click_result.error}")
                        if target_event not in manual_required:
                            manual_required.append(target_event)
                        exploration_log.append(f"{target_event}: 클릭 실패 → Manual")
                        event_capture_log.append({
                            "event": target_event,
                            "method": "click_trigger_dom",
                            "result": "failed",
                            "selector": trigger_sel,
                            "notes": f"버튼 클릭 실패 ({click_result.error}) → Manual 이관",
                        })
                    continue
            
                # ── 우선순위 2: LLM Navigator 루프 (dataLayer 기반) ──
                _nav_pre_snap = await snapshot_datalayer_names(page)
                logger.log_dl_state(
                    "active_explorer/navigator/pre",
                    page.url,
                    _nav_pre_snap,
                    target_event=target_event,
                )

                result = await navigator.run_for_event(
                    page,
                    target_event,
                    captured_events,
                    playbook=playbook,
                )

                _nav_post_snap = await snapshot_datalayer_names(page)
                logger.log_dl_state(
                    "active_explorer/navigator/post",
                    page.url,
                    _nav_post_snap,
                    target_event=target_event,
                    extra={"navigator_result": result},
                )
                if result != "captured":
                    try:
                        _rf = await peek_datalayer_raw(page, 14)
                        logger.log_dl_raw_peek(
                            f"active_explorer/navigator/fail/{target_event}",
                            page.url,
                            _rf,
                            target_event=target_event,
                            extra={"navigator_result": result},
                        )
                    except Exception:
                        pass

                if result == "captured":
                    all_events = await get_captured_events(
                        page, log_tag=f"active_explorer/navigator-success/{target_event}"
                    )
                    for e in all_events:
                        if e not in captured_events:
                            captured_events.append(e)
                    exploration_log.append(f"{target_event}: 캡처 성공")
            
                    # 우선순위 2a: dataLayer에서 캡처됐지만 ecommerce 데이터 부족 → DOM 보충
                    if use_dom and dom_selectors:
                        last_match = next(
                            (e for e in reversed(captured_events)
                             if e.get("data", {}).get("event") == target_event),
                            None,
                        )
                        if last_match and not last_match.get("data", {}).get("ecommerce"):
                            dom_data = await _extract_dom_data(page, dom_selectors)
                            if dom_data:
                                synth = _build_synthetic_event(target_event, dom_data, page.url)
                                last_match["data"]["ecommerce"] = synth["data"]["ecommerce"]
                                last_match["source"] = "datalayer+dom"
                                exploration_log.append(f"{target_event}: DOM 데이터 보충 완료")
                                event_capture_log.append({
                                    "event": target_event,
                                    "method": "datalayer_dom_supplement",
                                    "result": "success",
                                    "selector": "",
                                    "notes": "dataLayer 이벤트 캡처 성공, ecommerce 파라미터 부족 → DOM으로 보충",
                                })
                            else:
                                event_capture_log.append({
                                    "event": target_event,
                                    "method": "navigator_datalayer",
                                    "result": "success",
                                    "selector": "",
                                    "notes": "LLM Navigator로 dataLayer 이벤트 캡처",
                                })
                        else:
                            event_capture_log.append({
                                "event": target_event,
                                "method": "navigator_datalayer",
                                "result": "success",
                                "selector": "",
                                "notes": "LLM Navigator로 dataLayer 이벤트 캡처",
                            })
                else:
                    # 우선순위 3: Navigator 실패 → DOM 폴백
                    if use_dom and dom_selectors:
                        dom_data = await _extract_dom_data(page, dom_selectors)
                        if dom_data:
                            synth = _build_synthetic_event(target_event, dom_data, page.url)
                            captured_events.append(synth)
                            exploration_log.append(f"{target_event}: Navigator 실패 → DOM 폴백 성공")
                            logger.info(f"[ActiveExplorer] {target_event} DOM 폴백 성공")
                            event_capture_log.append({
                                "event": target_event,
                                "method": "dom_fallback",
                                "result": "success",
                                "selector": "",
                                "notes": "LLM Navigator 실패 → DOM 직접 추출로 폴백",
                            })
                            continue
            
                    if target_event not in manual_required:
                        manual_required.append(target_event)
                    exploration_log.append(f"{target_event}: 캡처 실패 → Manual로 이관")
                    event_capture_log.append({
                        "event": target_event,
                        "method": "manual",
                        "result": "pending",
                        "selector": "",
                        "notes": "자동 캡처 모든 방법 실패 → Manual Capture Gateway로 이관",
                    })
            
        finally:
            try:
                await browser.close()
            except Exception as e:
                logger.debug(f"[ActiveExplorer] browser.close() 예외 무시: {e}")

    # 이벤트에 evidence 고정 포맷 부착(없는 경우만).
    for ev in captured_events:
        _attach_evidence(
            ev,
            page_url=ev.get("url", ""),
            dom_resolved=selector_validation,
            json_ld_data=json_ld_data,
            failures=[
                f
                for f in exploration_failures
                if f.get("event") == (ev.get("data") or {}).get("event")
            ],
        )

    logger.info(f"[ActiveExplorer] 총 캡처 이벤트: {len(captured_events)}개")
    logger.info(f"[ActiveExplorer] Manual 이관: {manual_required}")
    logger.info(
        f"[ActiveExplorer] 노드 요약 wall_s={time.time() - _started:.1f}s "
        f"captured={len(captured_events)} manual_n={len(manual_required)}"
    )
    logger.save_events(captured_events)

    # 캡처된 datalayer 이벤트를 UI로 emit
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
    emit("node_exit", node_id=3, status="done", duration_ms=_dur)
    update_state(nodes_status={"active_explorer": "done"})
    # Manual Capture 노드는 그래프에서 건너뛰면 실행·emit이 없어 queued로 남음 → UI에서 skip 표시
    # 장바구니 전용 노드가 뒤에서 더 붙을 수 있으면 여기서 manual_capture 스킵하지 않음
    if (
        not manual_required
        and not state.get("cart_addition_events")
        and not state.get("begin_checkout_events")
    ):
        update_state(nodes_status={"manual_capture": "skip"})

    merged_url_patterns = dict(state.get("site_url_patterns") or {})
    merged_url_patterns.update(observed_url_patterns)

    return {
        **state,
        "captured_events": captured_events,
        "manual_required": manual_required,
        "current_url": live_page_url,
        "last_pdp_url": last_pdp_url,
        "exploration_log": exploration_log,
        "event_capture_log": event_capture_log,
        "exploration_failures": exploration_failures,
        "site_url_patterns": merged_url_patterns,
    }
