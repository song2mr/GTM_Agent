"""Node 1: Page Classifier.

페이지를 로드하고 Persistent Event Listener를 주입한 뒤,
LLM으로 페이지 타입(PLP/PDP/cart/checkout/기타)을 판단합니다.
로드타임 발화 이벤트도 수집합니다.
"""

from __future__ import annotations

import os
import time

from langchain_core.messages import HumanMessage, SystemMessage
from playwright.async_api import async_playwright

from agent.state import GTMAgentState
from config.llm_models_loader import llm_model
from gtm.client import GTMClient
from browser.actions import get_page_snapshot
from browser.listener import diagnose_datalayer, get_captured_events, inject_listener
from utils import logger, token_tracker
from utils.llm_json import make_chat_llm
from utils.ui_emitter import emit, update_state

_CLASSIFY_SYSTEM = """당신은 웹 페이지를 분석하는 전문가입니다.
HTML 스냅샷을 보고 페이지 타입을 판단하세요.

다음 중 하나만 응답하세요:
PLP - 상품 목록 페이지 (카테고리, 검색 결과)
PDP - 상품 상세 페이지
cart - 장바구니 페이지
checkout - 결제/체크아웃 페이지
home - 메인/홈 페이지
unknown - 판단 불가
"""


async def page_classifier(state: GTMAgentState) -> GTMAgentState:
    """Node 1: 페이지 로드, Listener 주입, 페이지 타입 판단."""
    emit("node_enter", node_id=1, node_key="page_classifier", title="Page Classifier")
    update_state(current_node=1, nodes_status={"page_classifier": "run"})
    _started = time.time()

    target_url = state["target_url"]
    headless = os.environ.get("GTM_AI_HEADLESS", "").lower() in ("1", "true", "yes")
    logger.info(
        f"[PageClassifier] Playwright headless={headless} "
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

            # Persistent Event Listener 주입 (페이지 이동 후에도 유지)
            await inject_listener(page)

            # 페이지 이동
            emit("thought", who="tool", label="playwright.navigate",
                 text=f"GET {target_url}", kind="tool")
            await page.goto(target_url, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)  # SPA 이벤트 대기

            # 로드타임 이벤트 수집
            load_events = await get_captured_events(page)

            # dataLayer 상태 진단
            dl_diagnosis = await diagnose_datalayer(page)
            datalayer_status = dl_diagnosis.get("status", "none")
            datalayer_events_found = dl_diagnosis.get("events", [])
            json_ld_data = dl_diagnosis.get("json_ld", [])
            print(
                f"[PageClassifier] dataLayer 상태: {datalayer_status}, "
                f"이벤트: {datalayer_events_found}, "
                f"JSON-LD: {len(json_ld_data)}개"
            )

            # 페이지 타입 판단
            snapshot = await get_page_snapshot(page)
            messages = [
                SystemMessage(content=_CLASSIFY_SYSTEM),
                HumanMessage(content=f"URL: {target_url}\n\nHTML:\n{snapshot}"),
            ]
            llm = make_chat_llm(model=llm_model("page_classifier"), timeout=120.0)
            response = await llm.ainvoke(messages)
            token_tracker.track("page_classifier", response)
            page_type = response.content.strip().split()[0].lower()
            valid_types = {"plp", "pdp", "cart", "checkout", "home", "unknown"}
            if page_type not in valid_types:
                page_type = "unknown"

            print(f"[PageClassifier] 페이지 타입: {page_type}, 로드 이벤트: {len(load_events)}개")
            emit("thought", who="agent", label="PageClassifier",
                 text=f"datalayer_status='{datalayer_status}', page_type='{page_type}', 로드 이벤트 {len(load_events)}개")

            # 기존 GTM 컨테이너 설정 조회
            existing_config: dict = {}
            try:
                client = GTMClient(
                    account_id=state.get("account_id", ""),
                    container_id=state.get("container_id", ""),
                )
                workspace_id = state.get("workspace_id", "")
                if workspace_id:
                    existing_config = {
                        "tags": client.list_tags(workspace_id),
                        "triggers": client.list_triggers(workspace_id),
                        "variables": client.list_variables(workspace_id),
                    }
            except Exception as e:
                logger.warning(f"[PageClassifier] GTM 설정 조회 실패 (무시): {e}")
        finally:
            try:
                await browser.close()
            except Exception as e:
                logger.debug(f"[PageClassifier] browser.close() 예외 무시: {e}")

    _dur = int((time.time() - _started) * 1000)
    emit("node_exit", node_id=1, status="done", duration_ms=_dur)
    update_state(nodes_status={"page_classifier": "done"})
    # dataLayer full 이면 그래프가 Structure Analyzer를 건너뛰므로 타임라인에서 queued로 남지 않게 함
    if datalayer_status == "full":
        update_state(nodes_status={"structure_analyzer": "skip"})

    return {
        **state,
        "page_type": page_type,
        "captured_events": load_events,
        "current_url": target_url,
        "existing_gtm_config": existing_config,
        "datalayer_status": datalayer_status,
        "datalayer_events_found": datalayer_events_found,
        "json_ld_data": json_ld_data,
        "exploration_log": [f"페이지 로드 완료: {target_url}, 타입: {page_type}, DL: {datalayer_status}"],
    }
