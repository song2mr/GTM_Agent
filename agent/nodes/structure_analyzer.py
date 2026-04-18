"""Node 1.5: Structure Analyzer.

dataLayer가 없거나 불완전한 사이트에서 HTML 구조를 분석하여
제품 정보(상품명, 가격, ID 등)의 CSS selector를 추출하고,
Playwright로 실제 값 추출 가능 여부를 검증합니다.

또한 JSON-LD 구조화 데이터가 있으면 이를 우선 활용합니다.
"""

from __future__ import annotations

import json
import os
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from playwright.async_api import Page, async_playwright

import time

from agent.state import GTMAgentState
from browser.actions import get_page_snapshot, navigate
from browser.listener import inject_listener
from utils import logger, token_tracker
from utils.ui_emitter import emit, update_state

_llm = ChatOpenAI(model="gpt-5.1")

# 페이지 타입별로 추출해야 할 필드 정의
PAGE_TYPE_FIELDS: dict[str, list[str]] = {
    "pdp": [
        "item_name", "item_id", "price", "currency",
        "item_brand", "item_category", "item_variant",
        "quantity_selector", "add_to_cart_button", "wishlist_button",
    ],
    "plp": [
        "item_name", "item_id", "price",
        "item_list_name", "product_card", "wishlist_button",
    ],
    "cart": [
        "item_name", "item_id", "price", "quantity",
        "cart_total", "checkout_button", "remove_button",
    ],
    "checkout": [
        "item_name", "item_id", "price", "quantity",
        "order_total", "shipping_cost",
    ],
}

# 클릭 트리거로 잡아야 할 버튼 매핑 (이벤트명 → 필드명)
CLICK_TRIGGER_FIELDS: dict[str, str] = {
    "add_to_cart": "add_to_cart_button",
    "begin_checkout": "checkout_button",
    "remove_from_cart": "remove_button",
    "add_to_wishlist": "wishlist_button",
}

_ANALYZER_SYSTEM = """당신은 웹 페이지 HTML 구조를 분석하는 전문가입니다.
ecommerce 사이트에서 제품 정보를 추출할 수 있는 CSS selector를 찾아야 합니다.

다음 JSON 형식으로만 응답하세요:
{
  "selectors": {
    "필드명": {
      "selector": "CSS selector",
      "attribute": "textContent | href | data-* | value | null",
      "transform": "정규식 또는 변환 설명 (필요 없으면 null)"
    }
  },
  "click_triggers": {
    "이벤트명": "CSS selector (클릭 대상 버튼/링크)"
  },
  "confidence": "high" | "medium" | "low",
  "notes": "특이사항이나 주의점"
}

selector 규칙:
- 가능하면 data-* 속성이나 고유 클래스 사용 (깨지기 쉬운 nth-child 지양)
- 가격은 숫자만 추출 가능한 selector 우선 (data-price 등)
- 텍스트에서 추출 시 transform에 정규식 명시
- 버튼은 실제 클릭 가능한 요소 (button, a, [role=button])
- attribute가 null이면 textContent 사용

주의:
- JSON-LD 데이터가 있으면 DOM selector보다 JSON-LD를 우선 권장
- 동적 로딩(lazy load) 요소는 가시 영역 기준으로 판단
"""

_JSONLD_SYSTEM = """당신은 JSON-LD 구조화 데이터 분석 전문가입니다.
제공된 JSON-LD에서 GA4 이커머스 파라미터에 매핑 가능한 필드를 추출하세요.

다음 JSON 형식으로만 응답하세요:
{
  "mappings": {
    "item_name": "JSON-LD 경로 (예: name)",
    "item_id": "JSON-LD 경로 (예: sku)",
    "price": "JSON-LD 경로 (예: offers.price)",
    "currency": "JSON-LD 경로 (예: offers.priceCurrency)",
    "item_brand": "JSON-LD 경로 (예: brand.name)",
    "item_category": "JSON-LD 경로 (예: category)"
  },
  "extraction_js": "window.__extractFromJsonLd = function() { ... } 형태의 JS 코드",
  "completeness": "full" | "partial"
}

extraction_js는 JSON-LD script 태그를 파싱해서
GA4 items 배열 형식으로 반환하는 함수여야 합니다.
"""


async def structure_analyzer(state: GTMAgentState) -> GTMAgentState:
    """Node 1.5: HTML 구조 분석 + selector 추출 + 검증."""
    emit("node_enter", node_id=1.5, node_key="structure_analyzer", title="Structure Analyzer")
    update_state(current_node=1.5, nodes_status={"structure_analyzer": "run"})
    _started = time.time()

    datalayer_status = state.get("datalayer_status", "none")

    if datalayer_status == "full":
        logger.info("[StructureAnalyzer] dataLayer 완전 → 분석 스킵")
        emit("thought", who="agent", label="StructureAnalyzer",
             text="dataLayer 완전 (full) → 분석 스킵")
        _dur = int((time.time() - _started) * 1000)
        emit("node_exit", node_id=1.5, status="skipped", duration_ms=_dur)
        update_state(nodes_status={"structure_analyzer": "done"})
        return {
            **state,
            "extraction_method": "datalayer",
            "dom_selectors": {},
            "selector_validation": {},
            "json_ld_data": {},
            "click_triggers": {},
        }

    target_url = state["target_url"]
    page_type = state.get("page_type", "unknown")
    json_ld_raw = state.get("json_ld_data", {})

    dom_selectors: dict = {}
    selector_validation: dict = {}
    click_triggers: dict = {}
    extraction_method = "dom"
    headless = os.environ.get("GTM_AI_HEADLESS", "").lower() in ("1", "true", "yes")
    logger.info(
        f"[StructureAnalyzer] Playwright headless={headless} "
        f"(GTM_AI_HEADLESS={os.environ.get('GTM_AI_HEADLESS', '')!r})"
    )

    result: GTMAgentState | None = None
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=headless,
            args=["--ignore-certificate-errors", "--ignore-ssl-errors"],
        )
        context = None
        try:
            context = await browser.new_context(ignore_https_errors=True)
            page = await context.new_page()
            await inject_listener(page)
            await navigate(page, target_url)
            await page.wait_for_timeout(2000)
            
            # Phase 1: JSON-LD 분석 (있으면 우선)
            if json_ld_raw:
                logger.info("[StructureAnalyzer] JSON-LD 발견 → 우선 분석")
                json_ld_result = await _analyze_json_ld(json_ld_raw, page)
                if json_ld_result.get("completeness") == "full":
                    extraction_method = "json_ld"
                    dom_selectors = json_ld_result.get("mappings", {})
                    selector_validation = json_ld_result.get("validated", {})
                    logger.info("[StructureAnalyzer] JSON-LD만으로 충분 → DOM 분석 스킵")
                    # 클릭 트리거는 여전히 DOM에서 찾아야 함
                    click_triggers = await _find_click_triggers(page, page_type)
                    result = {
                        **state,
                        "extraction_method": extraction_method,
                        "dom_selectors": dom_selectors,
                        "selector_validation": selector_validation,
                        "json_ld_data": json_ld_raw,
                        "click_triggers": click_triggers,
                    }

            if result is None:
                # Phase 2: DOM 구조 분석
                logger.info(f"[StructureAnalyzer] DOM 분석 시작 (page_type={page_type})")
                fields = PAGE_TYPE_FIELDS.get(page_type, PAGE_TYPE_FIELDS["pdp"])
                snapshot = await get_page_snapshot(page, max_chars=12000)

                analysis = await _analyze_html(snapshot, page_type, fields, page.url)
                raw_selectors = analysis.get("selectors", {})
                click_triggers = analysis.get("click_triggers", {})

                # Phase 3: Playwright로 selector 검증
                logger.info(f"[StructureAnalyzer] selector 검증 시작 ({len(raw_selectors)}개)")
                for field, spec in raw_selectors.items():
                    selector = spec.get("selector", "") if isinstance(spec, dict) else spec
                    attribute = spec.get("attribute") if isinstance(spec, dict) else None
                    if not selector:
                        continue

                    value = await _validate_selector(page, selector, attribute)
                    if value is not None:
                        dom_selectors[field] = spec
                        selector_validation[field] = value
                        logger.info(f"  [OK] {field}: {selector} → {str(value)[:80]}")
                    else:
                        logger.info(f"  [FAIL] {field}: {selector} → 요소 없음")

                # 검증 실패한 selector에 대해 LLM에 재시도 요청
                missing_fields = [f for f in fields if f not in selector_validation
                                  and f not in CLICK_TRIGGER_FIELDS.values()]
                if missing_fields:
                    logger.info(f"[StructureAnalyzer] 미발견 필드 재시도: {missing_fields}")
                    retry = await _retry_missing(snapshot, missing_fields, selector_validation, page.url)
                    for field, spec in retry.get("selectors", {}).items():
                        selector = spec.get("selector", "") if isinstance(spec, dict) else spec
                        attribute = spec.get("attribute") if isinstance(spec, dict) else None
                        if not selector:
                            continue
                        value = await _validate_selector(page, selector, attribute)
                        if value is not None:
                            dom_selectors[field] = spec
                            selector_validation[field] = value
                            logger.info(f"  [OK retry] {field}: {selector} → {str(value)[:80]}")

                # 클릭 트리거 검증
                verified_triggers: dict = {}
                for event_name, sel in click_triggers.items():
                    exists = await _validate_selector(page, sel) is not None
                    if exists:
                        verified_triggers[event_name] = sel
                        logger.info(f"  [TRIGGER OK] {event_name}: {sel}")
                    else:
                        logger.info(f"  [TRIGGER FAIL] {event_name}: {sel}")
                click_triggers = verified_triggers

                if json_ld_raw and dom_selectors:
                    extraction_method = "json_ld+dom"
                elif dom_selectors:
                    extraction_method = "dom"
                else:
                    extraction_method = "custom_js"

                result = {
                    **state,
                    "extraction_method": extraction_method,
                    "dom_selectors": dom_selectors,
                    "selector_validation": selector_validation,
                    "json_ld_data": json_ld_raw if json_ld_raw else {},
                    "click_triggers": click_triggers,
                }

        finally:
            if context is not None:
                try:
                    await context.close()
                except Exception:
                    pass
            try:
                await browser.close()
            except Exception:
                pass

    if result is None:
        raise RuntimeError("[StructureAnalyzer] 분석 결과가 없습니다 (내부 오류).")

    logger.info(
        f"[StructureAnalyzer] 완료: method={result['extraction_method']}, "
        f"selectors={len(result['dom_selectors'])}, triggers={len(result['click_triggers'])}"
    )
    emit("thought", who="agent", label="StructureAnalyzer",
         text=f"완료: method={result['extraction_method']}, "
         f"selectors={len(result['dom_selectors'])}, triggers={len(result['click_triggers'])}")
    _dur = int((time.time() - _started) * 1000)
    emit("node_exit", node_id=1.5, status="done", duration_ms=_dur)
    update_state(nodes_status={"structure_analyzer": "done"})

    return result


async def _analyze_html(
    snapshot: str,
    page_type: str,
    fields: list[str],
    url: str,
) -> dict:
    """LLM으로 HTML 스냅샷에서 selector를 추출합니다."""
    content = f"""페이지 타입: {page_type}
URL: {url}
추출 대상 필드: {json.dumps(fields, ensure_ascii=False)}

페이지 HTML:
{snapshot}
"""
    messages = [
        SystemMessage(content=_ANALYZER_SYSTEM),
        HumanMessage(content=content),
    ]
    response = await _llm.ainvoke(messages)
    token_tracker.track("structure_analyzer", response)
    return _parse_json_response(response.content)


async def _analyze_json_ld(json_ld_data: Any, page: Page) -> dict:
    """JSON-LD 데이터에서 GA4 매핑을 추출합니다."""
    content = f"JSON-LD 데이터:\n{json.dumps(json_ld_data, ensure_ascii=False, indent=2)}"
    messages = [
        SystemMessage(content=_JSONLD_SYSTEM),
        HumanMessage(content=content),
    ]
    response = await _llm.ainvoke(messages)
    token_tracker.track("structure_analyzer", response)
    result = _parse_json_response(response.content)

    # extraction_js가 있으면 페이지에서 실행해서 검증
    validated: dict = {}
    extraction_js = result.get("extraction_js", "")
    if extraction_js:
        try:
            await page.evaluate(extraction_js)
            extracted = await page.evaluate("window.__extractFromJsonLd ? window.__extractFromJsonLd() : null")
            if extracted and isinstance(extracted, dict):
                validated = extracted
        except Exception as e:
            logger.info(f"[StructureAnalyzer] JSON-LD extraction JS 실행 실패: {e}")

    result["validated"] = validated
    return result


async def _find_click_triggers(page: Page, page_type: str) -> dict:
    """페이지에서 클릭 트리거 대상 버튼을 찾습니다."""
    common_patterns: dict[str, list[str]] = {
        "add_to_cart": [
            "[data-action='add-to-cart']", "button[class*='cart']",
            "button[class*='Cart']", ".btn-cart", ".add-to-cart",
            "#addToCart", "button:has-text('장바구니')", "button:has-text('담기')",
        ],
        "begin_checkout": [
            "a[href*='checkout']", "button[class*='checkout']",
            "button:has-text('구매')", "button:has-text('주문')",
        ],
        "remove_from_cart": [
            "button[class*='remove']", "button[class*='delete']",
            ".btn-remove", "button:has-text('삭제')",
        ],
        # 한국 쇼핑몰 찜/위시리스트 버튼 패턴
        "add_to_wishlist": [
            "button[class*='wish']", "button[class*='Wish']",
            "button[class*='like']", "button[class*='Like']",
            "button[class*='heart']", "button[class*='Heart']",
            "button[class*='favorite']", "button[class*='Favorite']",
            "button[class*='bookmark']",
            "[class*='wish-btn']", "[class*='btn-wish']",
            "[class*='btn-like']", "[class*='btn-heart']",
            "button:has-text('찜')", "button:has-text('찜하기')",
            "button:has-text('관심상품')", "button:has-text('좋아요')",
            "a:has-text('찜하기')", "[data-action*='wish']",
            "[aria-label*='찜']", "[title*='찜']",
        ],
    }

    triggers: dict = {}
    for event_name, selectors in common_patterns.items():
        for sel in selectors:
            try:
                el = await page.query_selector(sel)
                if el:
                    triggers[event_name] = sel
                    break
            except Exception:
                continue
    return triggers


async def _validate_selector(
    page: Page,
    selector: str,
    attribute: str | None = None,
) -> str | None:
    """Playwright로 CSS selector가 실제 값을 반환하는지 검증합니다."""
    try:
        el = await page.query_selector(selector)
        if el is None:
            return None
        if attribute and attribute != "textContent":
            value = await el.get_attribute(attribute)
        else:
            value = await el.text_content()
        if value:
            return value.strip()
        return None
    except Exception:
        return None


async def _retry_missing(
    snapshot: str,
    missing_fields: list[str],
    found_so_far: dict,
    url: str,
) -> dict:
    """검증 실패한 필드에 대해 LLM에 재시도를 요청합니다."""
    content = f"""이전 시도에서 다음 필드를 찾지 못했습니다: {missing_fields}
이미 찾은 필드: {json.dumps(found_so_far, ensure_ascii=False)}
URL: {url}

다른 CSS selector로 다시 시도하세요.
- class 대신 data-* 속성이나 aria-label 시도
- 부모 요소부터 탐색
- meta 태그나 hidden input도 확인

페이지 HTML:
{snapshot}
"""
    messages = [
        SystemMessage(content=_ANALYZER_SYSTEM),
        HumanMessage(content=content),
    ]
    response = await _llm.ainvoke(messages)
    token_tracker.track("structure_analyzer", response)
    return _parse_json_response(response.content)


def _parse_json_response(raw: str) -> dict:
    """LLM 응답에서 JSON을 파싱합니다."""
    raw = raw.strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}
