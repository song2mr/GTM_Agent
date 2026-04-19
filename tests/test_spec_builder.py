"""Spec builder golden tests."""

from gtm.spec_builder import build_specs_from_canplan


def _base_canplan() -> dict:
    return {
        "version": "canplan/1",
        "scope": {
            "tag_type": "GA4",
            "allowed_events": ["view_item"],
            "ga4_measurement_id": "G-TEST1234",
        },
        "variables": [
            {"name": "DLV - ecommerce.items", "kind": "datalayer", "params": {"path": "ecommerce.items", "version": 2}},
            {"name": "Const - KRW", "kind": "constant", "params": {"value": "KRW"}},
        ],
        "triggers": [
            {"name": "CE - view_item", "kind": "custom_event", "condition_logic": "all", "conditions": [], "match_event": "view_item"},
        ],
        "tags": [
            {
                "name": "GA4 - view_item",
                "kind": "ga4_event",
                "measurement_id": "G-TEST1234",
                "event_name": "view_item",
                "event_parameters": [
                    {"key": "items", "value_ref": "{{DLV - ecommerce.items}}"},
                    {"key": "currency", "value_ref": "{{Const - KRW}}"},
                ],
                "fires_on": ["CE - view_item"],
            }
        ],
    }


def test_build_specs_from_canplan_minimal():
    canplan = _base_canplan()
    variables, triggers, tags = build_specs_from_canplan(canplan)
    assert len(variables) == 2
    assert len(triggers) == 1
    assert len(tags) == 1
    assert triggers[0].type == "customEvent"
    assert tags[0].type == "gaawe"
    tag_keys = [p.key for p in tags[0].parameters]
    assert "eventName" in tag_keys
    assert "measurementIdOverride" in tag_keys


def test_build_specs_with_page_path_regex_trigger():
    """§6.3 pageview + {{Page Path}} matches_regex → filter가 matchRegex로 빌드되는지."""
    canplan = {
        "version": "canplan/1",
        "scope": {
            "tag_type": "GA4",
            "allowed_events": ["view_item_list"],
            "ga4_measurement_id": "G-PG1234",
        },
        "variables": [],
        "triggers": [
            {
                "name": "PV - Category pages",
                "kind": "pageview",
                "condition_logic": "all",
                "conditions": [
                    {
                        "lhs": "{{Page Path}}",
                        "op": "matches_regex",
                        "rhs": r"^/category/[^/]+/?$",
                    }
                ],
                "match_event": None,
            }
        ],
        "tags": [
            {
                "name": "GA4 - view_item_list",
                "kind": "ga4_event",
                "measurement_id": "G-PG1234",
                "event_name": "view_item_list",
                "event_parameters": [],
                "fires_on": ["PV - Category pages"],
            }
        ],
    }
    variables, triggers, tags = build_specs_from_canplan(canplan)
    assert triggers[0].type == "pageview"
    assert triggers[0].filter_[0]["type"] == "matchRegex"
    params = triggers[0].filter_[0]["parameter"]
    arg0 = next(p for p in params if p["key"] == "arg0")
    arg1 = next(p for p in params if p["key"] == "arg1")
    assert arg0["value"] == "{{Page Path}}"
    assert arg1["value"] == r"^/category/[^/]+/?$"
    assert tags[0].firing_trigger_ids == ["PV - Category pages"]


def test_build_specs_with_click_trigger():
    """§6.3 Click Trigger — 숨김 `<select>` 옵션/버튼 CSS selector 기반 설계 검증."""
    canplan = {
        "version": "canplan/1",
        "scope": {
            "tag_type": "GA4",
            "allowed_events": ["add_to_cart"],
            "ga4_measurement_id": "G-CL1234",
        },
        "variables": [
            {
                "name": "CJS - single_item",
                "kind": "cjs_template",
                "params": {
                    "template_id": "build_single_item",
                    "args": {
                        "fields_from": {
                            "item_id": "{{DOM - item_id}}",
                            "price": "{{CJS - item_price}}",
                        }
                    },
                },
            }
        ],
        "triggers": [
            {
                "name": "Click - add to cart",
                "kind": "click",
                "condition_logic": "all",
                "conditions": [
                    {
                        "lhs": "{{Click Element}}",
                        "op": "matches_regex",
                        "rhs": r"button\[class\*='cart'\]",
                    }
                ],
                "match_event": None,
            }
        ],
        "tags": [
            {
                "name": "GA4 - add_to_cart",
                "kind": "ga4_event",
                "measurement_id": "G-CL1234",
                "event_name": "add_to_cart",
                "event_parameters": [
                    {"key": "items", "value_ref": "{{CJS - single_item}}"}
                ],
                "fires_on": ["Click - add to cart"],
            }
        ],
    }
    variables, triggers, tags = build_specs_from_canplan(canplan)
    assert len(variables) == 1
    assert variables[0].type == "jsm"
    assert triggers[0].type == "click"
    assert triggers[0].filter_[0]["type"] == "matchRegex"
    assert tags[0].type == "gaawe"


def _run():
    test_build_specs_from_canplan_minimal()
    test_build_specs_with_page_path_regex_trigger()
    test_build_specs_with_click_trigger()
    print("spec_builder tests OK")


if __name__ == "__main__":
    _run()
