"""Node 3: Active Explorer (핵심).

LLM Navigator + Playwright 루프로 탐색 큐의 이벤트를 순서대로 캡처합니다.
Navigator는 액션 히스토리 기반으로 멀티스텝 탐색을 수행하며, 실패 시 manual_required로 이관합니다.

dataLayer가 없는 경우(extraction_method != "datalayer"):
  - 클릭 트리거를 실행한 뒤 DOM selector로 제품 데이터를 직접 추출
  - 추출된 데이터로 가상 이벤트 객체를 생성
"""

from __future__ import annotations

from playwright.async_api import Page, async_playwright

import time

from agent.state import GTMAgentState
from browser.actions import click, close_popup, navigate
from browser.listener import get_captured_events, inject_listener
from browser.navigator import LLMNavigator
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

    extraction_method = state.get("extraction_method", "datalayer")
    dom_selectors = state.get("dom_selectors", {})
    click_triggers = state.get("click_triggers", {})
    use_dom = extraction_method != "datalayer"

    navigator = LLMNavigator()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--ignore-certificate-errors", "--ignore-ssl-errors"],
        )
        context = await browser.new_context(ignore_https_errors=True)
        page = await context.new_page()

        await inject_listener(page)
        await navigate(page, target_url)
        await page.wait_for_timeout(2000)

        # 로드 직후 이벤트 수집 (page_view 포함)
        initial_events = await get_captured_events(page)
        for e in initial_events:
            if e not in captured_events:
                captured_events.append(e)

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

        for target_event in auto_capturable:
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

            # ── 우선순위 1: 클릭 트리거 → 클릭 후 dataLayer 먼저 확인 (DL/DOM 무관) ──
            if target_event in click_triggers:
                trigger_sel = click_triggers[target_event]
                logger.info(f"[ActiveExplorer] DOM 모드: {target_event} → 클릭 {trigger_sel}")
                await close_popup(page)

                dom_data_before = await _extract_dom_data(page, dom_selectors)
                click_result = await click(page, trigger_sel)

                if click_result.success:
                    await page.wait_for_timeout(2000)
                    # 우선순위 1a: 클릭 후 dataLayer 이벤트 발화 여부 확인
                    dl_events = await get_captured_events(page)
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
            result = await navigator.run_for_event(page, target_event, captured_events)

            if result == "captured":
                all_events = await get_captured_events(page)
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

        await context.close()
        await browser.close()

    logger.info(f"[ActiveExplorer] 총 캡처 이벤트: {len(captured_events)}개")
    logger.info(f"[ActiveExplorer] Manual 이관: {manual_required}")
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
    if not manual_required:
        update_state(nodes_status={"manual_capture": "skip"})

    return {
        **state,
        "captured_events": captured_events,
        "manual_required": manual_required,
        "current_url": target_url,
        "exploration_log": exploration_log,
        "event_capture_log": event_capture_log,
    }
