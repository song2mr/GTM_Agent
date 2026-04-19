"""Convert CanPlan into GTM model specs."""

from __future__ import annotations

from agent.canplan.cjs_templates import render_template
from gtm.models import GTMParameter, GTMTag, GTMTrigger, GTMVariable

_TRIGGER_TYPE_MAP = {
    "custom_event": "customEvent",
    "click": "click",
    "pageview": "pageview",
    "dom_ready": "domReady",
    "window_loaded": "windowLoaded",
    "history_change": "historyChange",
    "form_submit": "formSubmission",
    "element_visibility": "elementVisibility",
}

_OP_MAP = {
    "equals": ("equals", False),
    "contains": ("contains", False),
    "starts_with": ("startsWith", False),
    "ends_with": ("endsWith", False),
    "matches_regex": ("matchRegex", False),
    "not_equals": ("equals", True),
    "not_contains": ("contains", True),
    "not_starts_with": ("startsWith", True),
    "not_ends_with": ("endsWith", True),
    "not_matches_regex": ("matchRegex", True),
}


def _param(type_: str, key: str, value: str = "") -> GTMParameter:
    return GTMParameter(type=type_, key=key, value=value)


def _build_variable(spec: dict) -> GTMVariable | None:
    name = spec["name"]
    kind = spec.get("kind")
    params = dict(spec.get("params") or {})

    if kind == "builtin":
        return None
    if kind == "datalayer":
        return GTMVariable(
            name=name,
            type="v",
            parameters=[
                _param("integer", "dataLayerVersion", str(params.get("version", 2))),
                _param("template", "name", str(params.get("path", ""))),
            ],
        )
    if kind == "dom_id":
        return GTMVariable(
            name=name,
            type="d",
            parameters=[
                _param("template", "elementId", str(params.get("element_id", ""))),
                _param("template", "attributeName", str(params.get("attribute", "textContent"))),
            ],
        )
    if kind == "dom_selector":
        js = render_template("attr_from_selector", params)
        return GTMVariable(
            name=name,
            type="jsm",
            parameters=[_param("template", "javascript", js)],
        )
    if kind == "json_ld_path":
        js = render_template("json_ld_value", params)
        return GTMVariable(
            name=name,
            type="jsm",
            parameters=[_param("template", "javascript", js)],
        )
    if kind == "cjs_template":
        template_id = str(params.get("template_id", ""))
        args = dict(params.get("args") or {})
        js = render_template(template_id, args)
        return GTMVariable(
            name=name,
            type="jsm",
            parameters=[_param("template", "javascript", js)],
        )
    if kind == "constant":
        return GTMVariable(
            name=name,
            type="c",
            parameters=[_param("template", "value", str(params.get("value", "")))],
        )
    return None


def _build_trigger(spec: dict) -> GTMTrigger:
    kind = spec["kind"]
    trigger_type = _TRIGGER_TYPE_MAP[kind]
    match_event = str(spec.get("match_event", "")).strip()

    custom_event_filter = []
    if kind == "custom_event":
        custom_event_filter = [
            {
                "type": "equals",
                "parameter": [
                    {"type": "template", "key": "arg0", "value": "{{_event}}"},
                    {"type": "template", "key": "arg1", "value": match_event},
                ],
            }
        ]

    condition_list = []
    for cond in spec.get("conditions", []):
        op_name, negate = _OP_MAP.get(str(cond.get("op", "equals")), ("equals", False))
        row = {
            "type": op_name,
            "parameter": [
                {"type": "template", "key": "arg0", "value": str(cond.get("lhs", ""))},
                {"type": "template", "key": "arg1", "value": str(cond.get("rhs", ""))},
            ],
        }
        if negate:
            row["negate"] = True
        condition_list.append(row)

    return GTMTrigger(
        name=spec["name"],
        type=trigger_type,
        custom_event_filter=custom_event_filter,
        filter_=condition_list,
    )


def _build_tag(spec: dict, trigger_name_to_id: dict[str, str]) -> GTMTag:
    firing_ids = [trigger_name_to_id[n] for n in spec.get("fires_on", []) if n in trigger_name_to_id]

    params = [
        _param("template", "eventName", str(spec.get("event_name", ""))),
        _param("template", "measurementIdOverride", str(spec.get("measurement_id", ""))),
    ]
    param_maps = []
    for ep in spec.get("event_parameters", []):
        param_maps.append(
            {
                "type": "map",
                "map": [
                    {"type": "template", "key": "name", "value": str(ep.get("key", ""))},
                    {"type": "template", "key": "value", "value": str(ep.get("value_ref", ""))},
                ],
            }
        )
    if param_maps:
        params.append(GTMParameter(type="list", key="eventParameters", list_=param_maps))

    return GTMTag(
        name=spec["name"],
        type="gaawe",
        parameters=params,
        firing_trigger_ids=firing_ids,
    )


def build_specs_from_canplan(canplan: dict) -> tuple[list[GTMVariable], list[GTMTrigger], list[GTMTag]]:
    variables = []
    triggers = []
    tags = []

    for var in canplan.get("variables", []):
        built = _build_variable(var)
        if built is not None:
            variables.append(built)
    for trig in canplan.get("triggers", []):
        triggers.append(_build_trigger(trig))

    trig_id_map = {t.name: t.name for t in triggers}
    for tag in canplan.get("tags", []):
        tags.append(_build_tag(tag, trig_id_map))
    return variables, triggers, tags
