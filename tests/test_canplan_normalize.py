"""CanPlan normalization + Evidence + policy golden tests."""

from agent.canplan.evidence import build_evidence_pack, healthy_dl_fields
from agent.canplan.normalize import normalize_draft_plan


def _evidence_for_unhealthy_dl() -> dict:
    state = {
        "user_request": "add_to_cart test",
        "selected_events": ["add_to_cart"],
        "tag_type": "GA4",
        "measurement_id": "G-UH1",
        "target_url": "https://shop.example.com/product/abc",
        "page_type": "pdp",
        "datalayer_status": "partial",
        "captured_events": [
            {
                "data": {
                    "event": "add_to_cart",
                    "ecommerce": {
                        "currency": "",
                        "value": 0,
                        "items": [
                            {"item_id": "", "price": "undefined"}
                        ],
                    },
                },
                "url": "https://shop.example.com/product/abc",
                "source": "datalayer",
            }
        ],
        "dom_selectors": {
            "item_id": {"selector": "#product-id", "attribute": "value"},
            "price": {"selector": ".price", "attribute": "textContent"},
        },
        "selector_validation": {"price": "19900원"},
        "click_triggers": {"add_to_cart": "button[class*='cart']"},
        "json_ld_data": {},
        "site_url_patterns": {"pdp": r"^/product/[^/]+/?$"},
        "site_spa": False,
    }
    return build_evidence_pack(state)


def test_dl_health_unhealthy_path_detected():
    """ecommerce.value = 0, item_id = '' 인 상황 → paths_health에 unhealthy 라벨."""
    pack = _evidence_for_unhealthy_dl()
    paths_health = pack["datalayer"]["paths_health"]
    # ecommerce.value is 0 → unhealthy zero_price.
    assert any(
        p for p, h in paths_health.items()
        if p.endswith("value") and h["health"] == "unhealthy"
    )
    # items[0].item_id = '' → unhealthy.
    candidates = pack["candidate_sources_per_field"]
    assert "item_id" in candidates
    # healthy DL map must NOT include item_id (all unhealthy).
    healthy_map = healthy_dl_fields(pack)
    assert "item_id" not in healthy_map


def test_normalize_rejects_dl_health_ignored():
    """healthy DL 필드가 있는데 LLM이 dom_selector 변수를 선택 → DL_HEALTH_IGNORED 에러."""
    state = {
        "captured_events": [
            {
                "data": {
                    "event": "view_item",
                    "ecommerce": {
                        "currency": "KRW",
                        "value": 29900,
                        "items": [
                            {"item_id": "SKU-1", "item_name": "멋진 가방", "price": 29900}
                        ],
                    },
                },
                "url": "https://shop.example.com/product/abc",
                "source": "datalayer",
            }
        ],
        "dom_selectors": {"item_id": {"selector": "#pid", "attribute": "value"}},
        "selector_validation": {"item_id": "SKU-1"},
        "click_triggers": {},
        "json_ld_data": {},
        "selected_events": ["view_item"],
        "tag_type": "GA4",
        "measurement_id": "G-HE1",
        "target_url": "https://shop.example.com/product/abc",
        "page_type": "pdp",
        "datalayer_status": "full",
    }
    pack = build_evidence_pack(state)

    draft = {
        "version": "canplan/1",
        "scope": {"tag_type": "GA4", "allowed_events": ["view_item"], "ga4_measurement_id": "G-HE1"},
        "variables": [
            {"name": "DOM - item_id", "kind": "dom_selector",
             "params": {"selector": "#pid", "attribute": "value"}},
        ],
        "triggers": [
            {"name": "CE - view_item", "kind": "custom_event",
             "condition_logic": "all", "conditions": [], "match_event": "view_item"},
        ],
        "tags": [
            {
                "name": "GA4 - view_item",
                "kind": "ga4_event",
                "measurement_id": "G-HE1",
                "event_name": "view_item",
                "event_parameters": [
                    {"key": "item_id", "value_ref": "{{DOM - item_id}}"}
                ],
                "fires_on": ["CE - view_item"],
            }
        ],
    }
    canplan, issues = normalize_draft_plan(
        draft, allowed_events=["view_item"], ga4_measurement_id="G-HE1",
        evidence_pack=pack,
    )
    codes = [i.get("code") for i in issues]
    assert "DL_HEALTH_IGNORED" in codes


def test_normalize_bans_in_set_op():
    draft = {
        "version": "canplan/1",
        "scope": {"tag_type": "GA4", "allowed_events": ["x"], "ga4_measurement_id": "G-X"},
        "variables": [],
        "triggers": [
            {"name": "PV - category", "kind": "pageview", "condition_logic": "all",
             "conditions": [{"lhs": "{{Page Path}}", "op": "in_set",
                             "rhs": ["/a", "/b"]}], "match_event": None}
        ],
        "tags": [],
    }
    _, issues = normalize_draft_plan(draft, allowed_events=["x"], ga4_measurement_id="G-X")
    assert any(i.get("rule_id") == "5.3#op-in_set" for i in issues)


def test_normalize_rejects_unknown_cjs_template():
    draft = {
        "version": "canplan/1",
        "scope": {"tag_type": "GA4", "allowed_events": ["view_item"], "ga4_measurement_id": "G-T"},
        "variables": [
            {"name": "CJS - random", "kind": "cjs_template",
             "params": {"template_id": "definitely_not_registered", "args": {}}}
        ],
        "triggers": [],
        "tags": [],
    }
    _, issues = normalize_draft_plan(draft, allowed_events=["view_item"], ga4_measurement_id="G-T")
    codes = [i.get("code") for i in issues]
    assert "TEMPLATE_UNKNOWN" in codes


def test_negative_sample_url_not_matched_policy():
    """`/product/123/review` 는 `^/product/[^/]+/?$` 에 매치되면 안된다(§6.5.5 반례).

    Evidence URL 패턴 레지스트리 자체에는 영향 없지만, pageview 트리거 폴백 테스트에서
    LLM이 반례 URL까지 포함하는 정규식을 쓰면 정책 위반으로 분류되는지 확인.
    """
    import re

    pattern = r"^/product/[^/]+/?$"
    assert re.match(pattern, "/product/123") is not None
    assert re.match(pattern, "/product/123/") is not None
    # Negative sample — review 하위 경로는 PDP 정규식에 매치되면 안됨.
    assert re.match(pattern, "/product/123/review") is None


def test_normalize_trigger_fallback_when_dl_not_fired():
    """로드형 view_item_list가 DL 미발화 + url_patterns 존재 → pageview 요구."""
    pack = {
        "site": {"url_patterns": {"plp": r"^/category/[^/]+/?$"}, "url_pattern_sources": {"plp": "observed"}},
        "events": [],
        "candidate_sources_per_field": {},
    }
    draft = {
        "version": "canplan/1",
        "scope": {"tag_type": "GA4", "allowed_events": ["view_item_list"], "ga4_measurement_id": "G-P"},
        "variables": [],
        "triggers": [
            {"name": "CE - view_item_list", "kind": "custom_event",
             "condition_logic": "all", "conditions": [], "match_event": "view_item_list"}
        ],
        "tags": [
            {
                "name": "GA4 - view_item_list",
                "kind": "ga4_event",
                "measurement_id": "G-P",
                "event_name": "view_item_list",
                "event_parameters": [],
                "fires_on": ["CE - view_item_list"],
            }
        ],
    }
    _, issues = normalize_draft_plan(
        draft, allowed_events=["view_item_list"], ga4_measurement_id="G-P",
        evidence_pack=pack,
    )
    codes = [i.get("code") for i in issues]
    assert "POLICY_VIOLATION" in codes
    rules = [i.get("rule_id") for i in issues]
    assert "4.5.3#loadtime-pageview" in rules


def _run():
    test_dl_health_unhealthy_path_detected()
    test_normalize_rejects_dl_health_ignored()
    test_normalize_bans_in_set_op()
    test_normalize_rejects_unknown_cjs_template()
    test_negative_sample_url_not_matched_policy()
    test_normalize_trigger_fallback_when_dl_not_fired()
    print("canplan normalize tests OK")


if __name__ == "__main__":
    _run()
