"""DraftPlan -> CanPlan deterministic normalization.

설계 문서 §4.5/§7 의 규칙을 코드로 박아 둔다.
- 스키마/참조 무결성 검사(§7-1, §7-2)
- 스코프/정책 검사(§7-3, §7-4): ga4_event 범위, in_set 금지, measurement_id 일치 등
- 소스 폴백 체인(§4.5.1): healthy DL 필드 무시 시 `DL_HEALTH_IGNORED` (retryable)
- 트리거 폴백(§4.5.3): 로드형 이벤트 + DL 미발화 + observed url_patterns 존재 → pageview 요구
- 알 수 없는 CJS template_id는 `TEMPLATE_UNKNOWN` 으로 거부
"""

from __future__ import annotations

import hashlib
import json

from .cjs_templates import REGISTERED_TEMPLATES, is_registered
from .schema import (
    BUILTIN_VARIABLES,
    CANPLAN_VERSION,
    TRIGGER_KINDS,
    TRIGGER_OPS,
    VARIABLE_KINDS,
    NormalizeIssue,
)

_LEGACY_TRIGGER_KIND = {
    "customEvent": "custom_event",
    "click": "click",
    "pageview": "pageview",
    "domReady": "dom_ready",
    "windowLoaded": "window_loaded",
    "historyChange": "history_change",
    "formSubmission": "form_submit",
    "elementVisibility": "element_visibility",
}

_LEGACY_VARIABLE_KIND = {
    "v": "datalayer",
    "d": "dom_id",
    "jsm": "cjs_template",
    "c": "constant",
}

# 로드형 이벤트 — 버튼/사용자 상호작용이 아니라 페이지 진입 시 발화되는 계열.
_LOAD_TIME_EVENTS = {
    "page_view",
    "view_item",
    "view_item_list",
    "view_promotion",
    "view_cart",
    "view_search_results",
    "begin_checkout",
}


def _issue(
    issues: list[NormalizeIssue],
    *,
    code: str,
    severity: str,
    rule_id: str,
    message: str,
    affected: list[str] | None = None,
    hint: str = "",
    retryable: bool = False,
    event: str | None = None,
) -> None:
    issues.append(
        NormalizeIssue(
            code=code,
            severity=severity,
            event=event,
            rule_id=rule_id,
            message=message,
            hint=hint,
            affected_names=affected or [],
            retryable=retryable,
        )
    )


def _to_canplan_variable(v: dict, issues: list[NormalizeIssue]) -> dict | None:
    name = str(v.get("name") or "").strip()
    if not name:
        _issue(
            issues,
            code="SCHEMA_VIOLATION",
            severity="error",
            rule_id="5.2#name",
            message="Variable name이 비어 있습니다.",
            hint="모든 변수에 고유 name을 지정하세요.",
        )
        return None

    if "kind" in v:
        kind = str(v.get("kind"))
        params = dict(v.get("params") or {})
        cast = v.get("cast")
        notes = v.get("notes", "")
    else:
        legacy_type = str(v.get("type") or "")
        kind = _LEGACY_VARIABLE_KIND.get(legacy_type, "")
        params = {}
        cast = None
        notes = "legacy 변환"
        for p in v.get("parameters", []):
            k = p.get("key")
            if k is None:
                continue
            params[str(k)] = p.get("value")
        if kind == "datalayer":
            params = {
                "path": str(params.get("name", "")),
                "version": int(params.get("dataLayerVersion") or 2),
            }
        elif kind == "dom_id":
            params = {
                "element_id": str(params.get("elementId", "")),
                "attribute": str(params.get("attributeName") or "textContent"),
            }
        elif kind == "constant":
            params = {"value": str(params.get("value", ""))}
        elif kind == "cjs_template":
            # legacy "jsm" type — 자유 JS 본문이 들어오면 안전 변환 불가, 드롭.
            _issue(
                issues,
                code="POLICY_VIOLATION",
                severity="error",
                rule_id="8#free-cjs-forbidden",
                message=f"자유 CJS 본문은 허용되지 않습니다: {name}",
                affected=[name],
                hint=(
                    "사전 등록된 템플릿(attr_from_selector, items_from_jsonld, "
                    "items_from_dom, build_single_item, text_to_number, json_ld_value, "
                    "meta_tag_value, cookie_value)만 사용하세요."
                ),
                retryable=True,
            )
            return None

    if kind not in VARIABLE_KINDS:
        _issue(
            issues,
            code="SCHEMA_VIOLATION",
            severity="error",
            rule_id="5.2#kind",
            message=f"지원하지 않는 Variable kind/type: {kind}",
            affected=[name],
            hint="datalayer/dom_selector/constant 등 canplan/1 kind를 사용하세요.",
            retryable=True,
        )
        return None

    return {"name": name, "kind": kind, "params": params, "cast": cast, "notes": notes}


def _extract_match_event(custom_event_filter: list) -> str:
    for cond in custom_event_filter:
        for p in cond.get("parameter", []):
            if p.get("key") == "arg1":
                return str(p.get("value", "")).strip()
    return ""


def _to_canplan_trigger(t: dict, issues: list[NormalizeIssue]) -> dict | None:
    name = str(t.get("name") or "").strip()
    if not name:
        return None
    if "kind" in t:
        kind = str(t.get("kind"))
        cond_logic = t.get("condition_logic", "all")
        conditions = list(t.get("conditions") or [])
        match_event = t.get("match_event")
    else:
        kind = _LEGACY_TRIGGER_KIND.get(str(t.get("type") or ""), "")
        cond_logic = "all"
        conditions = []
        match_event = None
        if kind == "custom_event":
            match_event = _extract_match_event(list(t.get("customEventFilter") or []))
        for cond in list(t.get("filter") or t.get("filters") or []):
            op = str(cond.get("type") or "equals")
            params = {p.get("key"): p.get("value") for p in cond.get("parameter", [])}
            lhs = params.get("arg0")
            rhs = params.get("arg1")
            if lhs and rhs:
                conditions.append({"lhs": lhs, "op": _from_legacy_op(op), "rhs": rhs})

    if kind not in TRIGGER_KINDS:
        _issue(
            issues,
            code="SCHEMA_VIOLATION",
            severity="error",
            rule_id="5.3#kind",
            message=f"지원하지 않는 Trigger kind/type: {kind}",
            affected=[name],
            retryable=True,
        )
        return None
    if cond_logic not in {"all", "any"}:
        cond_logic = "all"
    return {
        "name": name,
        "kind": kind,
        "condition_logic": cond_logic,
        "conditions": conditions,
        "match_event": match_event,
    }


def _to_canplan_tag(t: dict, issues: list[NormalizeIssue], ga4_measurement_id: str) -> dict | None:
    name = str(t.get("name") or "").strip()
    if not name:
        return None

    if "kind" in t:
        kind = str(t.get("kind"))
        measurement_id = str(t.get("measurement_id") or ga4_measurement_id)
        event_name = str(t.get("event_name") or "")
        event_parameters = list(t.get("event_parameters") or [])
        fires_on = list(t.get("fires_on") or [])
    else:
        kind = "ga4_event" if str(t.get("type") or "") == "gaawe" else ""
        pmap = {p.get("key"): p.get("value") for p in t.get("parameters", [])}
        measurement_id = str(pmap.get("measurementIdOverride") or ga4_measurement_id)
        event_name = str(pmap.get("eventName") or "")
        event_parameters = list(t.get("event_parameters") or [])
        fires_on = list(t.get("firing_trigger_names") or [])

    if kind != "ga4_event":
        _issue(
            issues,
            code="SCHEMA_VIOLATION",
            severity="error",
            rule_id="5.4#kind",
            message=f"Tag kind/type 지원 범위 밖: {kind}",
            affected=[name],
            hint="현재 스코프는 ga4_event만 지원합니다.",
        )
        return None

    norm_params = []
    for ep in event_parameters:
        key = str(ep.get("key") or "").strip()
        value_ref = str(ep.get("value_ref") or ep.get("value") or "").strip()
        cast = ep.get("cast")
        if key and value_ref:
            if not value_ref.startswith("{{"):
                value_ref = "{{" + value_ref + "}}"
            norm_params.append({"key": key, "value_ref": value_ref, "cast": cast})

    return {
        "name": name,
        "kind": "ga4_event",
        "measurement_id": measurement_id,
        "event_name": event_name,
        "event_parameters": norm_params,
        "fires_on": fires_on,
    }


def _from_legacy_op(op: str) -> str:
    op = op or "equals"
    mapping = {
        "equals": "equals",
        "contains": "contains",
        "startsWith": "starts_with",
        "endsWith": "ends_with",
        "matchRegex": "matches_regex",
        "cssSelector": "contains",
    }
    return mapping.get(op, "equals")


def _validate_refs(canplan: dict, issues: list[NormalizeIssue]) -> None:
    variables = list(canplan.get("variables") or [])
    triggers = list(canplan.get("triggers") or [])
    tags = list(canplan.get("tags") or [])

    var_names = {v.get("name") for v in variables}
    trig_names = {t.get("name") for t in triggers}

    if len(var_names) != len(variables):
        _issue(
            issues,
            code="SCHEMA_VIOLATION",
            severity="error",
            rule_id="5.2#unique-name",
            message="Variable name 중복이 있습니다.",
            hint="변수 이름을 고유하게 변경하세요.",
        )
    if len(trig_names) != len(triggers):
        _issue(
            issues,
            code="SCHEMA_VIOLATION",
            severity="error",
            rule_id="5.3#unique-name",
            message="Trigger name 중복이 있습니다.",
            hint="트리거 이름을 고유하게 변경하세요.",
        )

    # CJS 템플릿 사전 등록 여부(§7-4, §8).
    for var in variables:
        if var.get("kind") != "cjs_template":
            continue
        params = dict(var.get("params") or {})
        tpl = str(params.get("template_id", ""))
        if not tpl:
            _issue(
                issues,
                code="MISSING_REQUIRED_PARAM",
                severity="error",
                rule_id="5.2#cjs_template",
                message=f"cjs_template 변수 '{var.get('name')}'에 template_id가 없습니다.",
                affected=[str(var.get("name"))],
                retryable=True,
            )
            continue
        if not is_registered(tpl):
            _issue(
                issues,
                code="TEMPLATE_UNKNOWN",
                severity="error",
                rule_id="8#registered",
                message=f"등록되지 않은 CJS template_id: {tpl}",
                affected=[str(var.get("name"))],
                hint=f"사전 등록된 템플릿만 사용하세요: {sorted(REGISTERED_TEMPLATES)}",
                retryable=True,
            )

    # Trigger 검사.
    for trig in triggers:
        kind = trig.get("kind")
        if kind == "custom_event" and not trig.get("match_event"):
            _issue(
                issues,
                code="MISSING_REQUIRED_PARAM",
                severity="error",
                rule_id="5.3#custom_event",
                message=f"custom_event 트리거 '{trig.get('name')}'에 match_event가 없습니다.",
                affected=[str(trig.get("name"))],
                retryable=True,
            )
        for cond in trig.get("conditions", []):
            lhs = str(cond.get("lhs", ""))
            op = str(cond.get("op", "equals"))
            if op == "in_set":
                _issue(
                    issues,
                    code="SCHEMA_VIOLATION",
                    severity="error",
                    rule_id="5.3#op-in_set",
                    message=f"in_set op은 canplan/1에서 비지원: {trig.get('name')}",
                    affected=[str(trig.get("name"))],
                    hint='condition_logic="any" + equals 다중 조건으로 대체하세요.',
                    retryable=True,
                )
                continue
            if op not in TRIGGER_OPS:
                _issue(
                    issues,
                    code="SCHEMA_VIOLATION",
                    severity="error",
                    rule_id="5.3#op",
                    message=f"지원하지 않는 trigger op: {op}",
                    affected=[str(trig.get("name"))],
                    retryable=True,
                )
            if lhs and lhs not in BUILTIN_VARIABLES:
                lhs_name = lhs.strip("{} ")
                if lhs_name not in var_names:
                    _issue(
                        issues,
                        code="REF_NOT_FOUND",
                        severity="error",
                        rule_id="7#ref-trigger-lhs",
                        message=f"Trigger lhs 참조 변수 없음: {lhs}",
                        affected=[str(trig.get("name"))],
                        retryable=True,
                    )

    allowed_events = set(canplan.get("scope", {}).get("allowed_events") or [])
    target_mid = str(canplan.get("scope", {}).get("ga4_measurement_id") or "")
    for tag in tags:
        if allowed_events and tag.get("event_name") not in allowed_events:
            _issue(
                issues,
                code="POLICY_VIOLATION",
                severity="warning",
                rule_id="7#scope-event",
                message=f"허용 범위 밖 이벤트 태그: {tag.get('event_name')}",
                affected=[str(tag.get("name"))],
            )
        if target_mid and str(tag.get("measurement_id") or "") != target_mid:
            _issue(
                issues,
                code="TYPE_MISMATCH",
                severity="error",
                rule_id="5.4#measurement-id",
                message=f"측정 ID 불일치: {tag.get('name')}",
                affected=[str(tag.get("name"))],
                hint="scope.ga4_measurement_id와 같은 값으로 맞추세요.",
                retryable=True,
            )
        for f in tag.get("fires_on", []):
            if f not in trig_names:
                _issue(
                    issues,
                    code="REF_NOT_FOUND",
                    severity="error",
                    rule_id="7#ref-fires-on",
                    message=f"Tag firing trigger 참조 없음: {f}",
                    affected=[str(tag.get("name"))],
                    retryable=True,
                )
        for ep in tag.get("event_parameters", []):
            ref = str(ep.get("value_ref", ""))
            if ref in BUILTIN_VARIABLES:
                continue
            ref_name = ref.strip("{} ")
            if ref_name not in var_names:
                _issue(
                    issues,
                    code="REF_NOT_FOUND",
                    severity="error",
                    rule_id="7#ref-event-param",
                    message=f"event_parameters value_ref 참조 없음: {ref}",
                    affected=[str(tag.get("name"))],
                    retryable=True,
                )


def _validate_source_fallback(canplan: dict, evidence_pack: dict, issues: list[NormalizeIssue]) -> None:
    """§4.5.1 — healthy DL 필드를 LLM이 무시하고 하위 소스를 쓴 경우 거부.

    판정 기준:
    - EvidencePack의 `candidate_sources_per_field[field]` 상위가 `kind:datalayer, health:healthy`.
    - CanPlan의 어떤 tag에서도 해당 필드 `event_parameters.key==field`가 존재하지만
      `value_ref`가 healthy DL VariableSpec(datalayer + path)이 아니고,
      하위 kind(dom_selector/json_ld_path/cjs_template/constant)를 참조.
    """
    candidates_map = dict(evidence_pack.get("candidate_sources_per_field") or {})
    if not candidates_map:
        return

    # VariableSpec index by name.
    var_by_name: dict[str, dict] = {
        str(v.get("name")): v for v in (canplan.get("variables") or [])
    }

    # healthy DL 최우선 경로 맵.
    healthy_paths: dict[str, str] = {}
    for field, cands in candidates_map.items():
        for cand in cands:
            if cand.get("kind") == "datalayer" and cand.get("health") == "healthy":
                healthy_paths[field] = str(cand.get("path", ""))
                break

    if not healthy_paths:
        return

    for tag in canplan.get("tags") or []:
        for ep in tag.get("event_parameters") or []:
            field = str(ep.get("key") or "")
            if field not in healthy_paths:
                continue
            ref = str(ep.get("value_ref") or "").strip("{} ")
            if not ref:
                continue
            var = var_by_name.get(ref)
            if not var:
                continue
            kind = var.get("kind")
            path = str((var.get("params") or {}).get("path") or "")
            if kind == "datalayer" and path == healthy_paths[field]:
                continue  # 정책 준수.
            if kind == "datalayer":
                # 다른 DL 경로를 선택했는데 그게 healthy가 아니라면 우선순위 위반.
                _issue(
                    issues,
                    code="DL_HEALTH_IGNORED",
                    severity="warning",
                    rule_id="4.5.1#step1-healthy",
                    message=(
                        f"필드 '{field}'에 healthy DL 경로 '{healthy_paths[field]}'가 있는데 "
                        f"다른 DL 경로를 선택했습니다."
                    ),
                    affected=[str(tag.get("name"))],
                    hint=f"'{healthy_paths[field]}'를 가리키는 DLV 변수를 만들어 사용하세요.",
                )
                continue
            _issue(
                issues,
                code="DL_HEALTH_IGNORED",
                severity="error",
                rule_id="4.5.1#step1-healthy",
                message=(
                    f"필드 '{field}'에 healthy DL 경로가 있는데 "
                    f"하위 소스(kind={kind})를 선택했습니다."
                ),
                affected=[str(tag.get("name"))],
                hint=(
                    f"DLV 변수로 '{healthy_paths[field]}' 경로를 사용하는 것이 최우선입니다. "
                    "하위 소스가 더 적합하다면 근거를 포함해 다시 제안하세요."
                ),
                retryable=True,
            )


def _validate_trigger_fallback(canplan: dict, evidence_pack: dict, issues: list[NormalizeIssue]) -> None:
    """§4.5.3 — 로드형 이벤트인데 DL 미발화이고 url_patterns가 있으면 pageview 계열을 요구.

    조건:
    - tag.event_name ∈ `_LOAD_TIME_EVENTS`
    - 해당 이벤트 surfaces의 datalayer.fired == False OR events에 없음
    - site.url_patterns 비어있지 않음
    - 그런데 CanPlan이 그 태그에 커스텀 이벤트 트리거만 연결 → 에러
    """
    site = dict(evidence_pack.get("site") or {})
    url_patterns = dict(site.get("url_patterns") or {})
    if not url_patterns:
        return

    # 이벤트별 DL 발화 여부 인덱스.
    fired: dict[str, bool] = {}
    for ev in evidence_pack.get("events") or []:
        name = str(ev.get("event") or "").lower()
        if not name:
            continue
        fired[name] = any(
            (s.get("datalayer") or {}).get("fired") for s in (ev.get("surfaces") or [])
        )

    trig_by_name: dict[str, dict] = {
        str(t.get("name")): t for t in (canplan.get("triggers") or [])
    }

    for tag in canplan.get("tags") or []:
        ev_name = str(tag.get("event_name") or "").lower()
        if ev_name not in _LOAD_TIME_EVENTS:
            continue
        if fired.get(ev_name):
            continue  # DL이 발화 중이면 CE 트리거가 적절.
        # 연결된 트리거 종류 검사.
        kinds: list[str] = []
        for tname in tag.get("fires_on") or []:
            trig = trig_by_name.get(tname)
            if trig:
                kinds.append(str(trig.get("kind") or ""))
        has_load_trigger = any(
            k in ("pageview", "dom_ready", "window_loaded", "history_change") for k in kinds
        )
        if has_load_trigger:
            continue
        _issue(
            issues,
            code="POLICY_VIOLATION",
            severity="error",
            rule_id="4.5.3#loadtime-pageview",
            message=(
                f"로드형 이벤트 '{ev_name}'에 DL 발화가 없고 URL 패턴이 존재하는데 "
                "pageview 계열 트리거가 연결되어 있지 않습니다."
            ),
            affected=[str(tag.get("name"))],
            event=ev_name,
            hint=(
                "pageview(또는 history_change) 트리거에 {{Page Path}} matches_regex "
                f"'{list(url_patterns.values())[0]}' 조건을 추가하세요."
            ),
            retryable=True,
        )


def normalize_draft_plan(
    draft_plan: dict,
    *,
    allowed_events: list[str],
    ga4_measurement_id: str,
    evidence_pack: dict | None = None,
) -> tuple[dict, list[dict]]:
    """Normalize draft/legacy plan into canonical plan."""
    issues: list[NormalizeIssue] = []
    evidence_pack = evidence_pack or {}

    if not isinstance(draft_plan, dict):
        _issue(
            issues,
            code="SCHEMA_VIOLATION",
            severity="error",
            rule_id="5.1",
            message="DraftPlan이 객체 형태가 아닙니다.",
            hint="LLM 출력은 JSON object여야 합니다.",
            retryable=True,
        )
        return {}, [i.to_dict() for i in issues]

    if draft_plan.get("version") == CANPLAN_VERSION:
        canplan = dict(draft_plan)
    else:
        canplan = {
            "version": CANPLAN_VERSION,
            "scope": {
                "tag_type": "GA4",
                "allowed_events": list(allowed_events),
                "ga4_measurement_id": ga4_measurement_id,
            },
            "variables": [],
            "triggers": [],
            "tags": [],
            "evidence": {},
        }
        for var in draft_plan.get("variables", []):
            n = _to_canplan_variable(var, issues)
            if n:
                canplan["variables"].append(n)
        for trig in draft_plan.get("triggers", []):
            n = _to_canplan_trigger(trig, issues)
            if n:
                canplan["triggers"].append(n)
        for tag in draft_plan.get("tags", []):
            n = _to_canplan_tag(tag, issues, ga4_measurement_id)
            if n:
                canplan["tags"].append(n)

    canplan.setdefault("scope", {})
    canplan["scope"].setdefault("tag_type", "GA4")
    canplan["scope"].setdefault("allowed_events", list(allowed_events))
    canplan["scope"].setdefault("ga4_measurement_id", ga4_measurement_id)
    canplan["evidence"] = {
        "captured_events": len(evidence_pack.get("events", [])),
        "candidate_fields": sorted((evidence_pack.get("candidate_sources_per_field") or {}).keys()),
        "url_pattern_sources": dict((evidence_pack.get("site") or {}).get("url_pattern_sources") or {}),
    }

    _validate_refs(canplan, issues)
    _validate_source_fallback(canplan, evidence_pack, issues)
    _validate_trigger_fallback(canplan, evidence_pack, issues)
    return canplan, [i.to_dict() for i in issues]


def canplan_hash(canplan: dict) -> str:
    """Stable digest for HITL/APIs consistency checks."""
    payload = json.dumps(canplan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def summarize_issues(issues: list[dict]) -> dict:
    """정규화 이슈 요약 — Planning 재시도·리포터에서 공용으로 사용."""
    error_codes = sorted({i.get("code", "") for i in issues if i.get("severity") == "error"})
    warning_codes = sorted({i.get("code", "") for i in issues if i.get("severity") == "warning"})
    retryable = [i for i in issues if i.get("retryable")]
    return {
        "error_count": sum(1 for i in issues if i.get("severity") == "error"),
        "warning_count": sum(1 for i in issues if i.get("severity") == "warning"),
        "error_codes": error_codes,
        "warning_codes": warning_codes,
        "retryable_hints": [i.get("hint") for i in retryable if i.get("hint")],
    }
