"""EvidencePack synthesis from runtime state.

설계 문서 §4.5.2 DL 건전성 판정과 §6.5.6 URL pattern 우선순위를 여기서 처리한다.
- DL 경로에 대해 healthy/unhealthy/unknown 3상태 라벨을 붙인다.
- url_patterns는 observed(`state.site_url_patterns`) > seed(Playbook/기본 휴리스틱) 순으로 병합.
- 이벤트별 surfaces/failures를 `captured_events[i].evidence`(있다면) 기반으로 채운다.
"""

from __future__ import annotations

from collections import defaultdict
from urllib.parse import urlparse


# GA4 필드별 기대 타입/의미 — DL health 판정 기준.
_FIELD_EXPECT: dict[str, dict] = {
    "items": {"type": "non_empty_array"},
    "value": {"type": "number_like"},
    "price": {"type": "number_like"},
    "currency": {"type": "currency_code"},
    "quantity": {"type": "number_like"},
    "item_id": {"type": "non_empty_string"},
    "item_name": {"type": "non_empty_string"},
    "item_brand": {"type": "non_empty_string"},
    "item_category": {"type": "non_empty_string"},
    "item_list_id": {"type": "non_empty_string"},
    "item_list_name": {"type": "non_empty_string"},
}


def _classify_value(expect: str, value) -> tuple[str, str]:
    """(health, reason) 반환 — health ∈ {healthy, unhealthy, unknown}."""
    if value is None:
        return "unhealthy", "null"
    if isinstance(value, str):
        stripped = value.strip()
        if stripped == "" or stripped.lower() in ("undefined", "null", "nan"):
            return "unhealthy", "empty_or_placeholder"
        if expect == "non_empty_string":
            return "healthy", "ok"
        if expect == "number_like":
            try:
                float(stripped.replace(",", "").replace("₩", "").replace("$", ""))
            except ValueError:
                return "unhealthy", "not_numeric"
            if float(stripped.replace(",", "").replace("₩", "").replace("$", "")) == 0:
                return "unhealthy", "zero_price"
            return "healthy", "ok"
        if expect == "currency_code":
            if len(stripped) == 3 and stripped.isalpha():
                return "healthy", "ok"
            return "unhealthy", "invalid_currency"
        if expect == "non_empty_array":
            return "unhealthy", "string_where_array_expected"
        return "healthy", "ok"
    if isinstance(value, (int, float)):
        if expect == "number_like":
            if value == 0:
                return "unhealthy", "zero_price"
            return "healthy", "ok"
        if expect == "non_empty_array":
            return "unhealthy", "number_where_array_expected"
        if expect in ("non_empty_string", "currency_code"):
            return "unhealthy", "number_where_string_expected"
        return "healthy", "ok"
    if isinstance(value, list):
        if expect == "non_empty_array":
            if not value:
                return "unhealthy", "empty_array"
            if all(isinstance(x, str) for x in value):
                return "unhealthy", "array_of_strings_not_items"
            return "healthy", "ok"
        return "unhealthy", "array_where_scalar_expected"
    if isinstance(value, dict):
        return "unhealthy", "object_where_scalar_expected"
    return "unknown", "unrecognized_type"


def _expect_for_path(path: str) -> str:
    """`ecommerce.items[0].item_id` 같은 경로 → 기대 타입 키 찾기."""
    if not path:
        return ""
    leaf = path.split(".")[-1].split("[")[0]
    return _FIELD_EXPECT.get(leaf, {}).get("type", "")


def _get_path(obj, path: str):
    """`ecommerce.items[0].item_id` 같은 경로 탐색."""
    if not isinstance(obj, dict) or not path:
        return None
    parts = path.split(".")
    cur = obj
    for part in parts:
        if part.endswith("]"):
            name, _, idx = part.partition("[")
            idx = idx.rstrip("]")
            try:
                i = int(idx)
            except ValueError:
                return None
            if name:
                if not isinstance(cur, dict):
                    return None
                cur = cur.get(name)
            if not isinstance(cur, list) or i >= len(cur):
                return None
            cur = cur[i]
        else:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(part)
        if cur is None:
            return None
    return cur


def _collect_dl_paths(data, prefix: str = "") -> list[tuple[str, object]]:
    """(path, sample_value) 튜플 수집 — dict + list[first] 평탄화.

    `ecommerce.items[0].item_id` 같은 실제 GA4 경로까지 추적한다. 리스트는 첫 원소만
    관찰(나머지도 동일 스키마라고 가정)해 경로 폭증을 막는다.
    """
    out: list[tuple[str, object]] = []
    if isinstance(data, dict):
        for k, v in data.items():
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                out.append((path, v))
                out.extend(_collect_dl_paths(v, path))
            elif isinstance(v, list):
                out.append((path, v))
                if v and isinstance(v[0], (dict, list)):
                    out.extend(_collect_dl_paths(v[0], f"{path}[0]"))
                elif v and not isinstance(v[0], (dict, list)):
                    out.append((f"{path}[0]", v[0]))
            else:
                out.append((path, v))
    elif isinstance(data, list):
        if data and isinstance(data[0], (dict, list)):
            out.extend(_collect_dl_paths(data[0], prefix))
    return out


def _health_for_dl_path(path: str, samples: list[object]) -> tuple[str, str]:
    """여러 샘플 중 **하나라도 healthy면 healthy**로 판정.

    어느 하나도 healthy가 아니면 가장 구체적인 unhealthy 이유를 리턴.
    samples가 비어있으면 ("unknown", "no_sample").
    """
    expect = _expect_for_path(path)
    if not expect or not samples:
        return ("unknown", "no_expectation") if not expect else ("unknown", "no_sample")
    last_reason = "no_sample"
    for sample in samples:
        health, reason = _classify_value(expect, sample)
        if health == "healthy":
            return "healthy", reason
        last_reason = reason
    return "unhealthy", last_reason


def _pick_url_patterns(page_type: str, target_url: str) -> dict:
    base = {}
    if page_type == "pdp":
        base["pdp"] = r"^/product/[^/]+/?$"
    elif page_type == "plp":
        base["plp"] = r"^/(category|products?)/[^/]+/?$"
    elif page_type == "cart":
        base["cart"] = r"^/cart/?$"
    elif page_type == "checkout":
        base["checkout"] = r"^/(checkout|order)/?.*$"
    if not base and target_url:
        base["current"] = r"^/.*$"
    return base


def _merge_url_patterns(observed: dict, seed: dict) -> tuple[dict, dict]:
    """observed > seed 병합. (merged, sources) 반환 — sources[key] = 'observed'|'seed'."""
    merged: dict = {}
    sources: dict = {}
    for k, v in (observed or {}).items():
        if v:
            merged[k] = v
            sources[k] = "observed"
    for k, v in (seed or {}).items():
        if v and k not in merged:
            merged[k] = v
            sources[k] = "seed"
    return merged, sources


def build_evidence_pack(state: dict) -> dict:
    """Build compact EvidencePack consumed by planning."""
    selected_events = list(state.get("selected_events") or [])
    captured_events = list(state.get("captured_events") or [])
    dom_selectors = dict(state.get("dom_selectors") or {})
    selector_validation = dict(state.get("selector_validation") or {})
    click_triggers = dict(state.get("click_triggers") or {})
    json_ld_data = state.get("json_ld_data") or {}
    page_type = str(state.get("page_type", "")).lower()
    observed_url_patterns = dict(state.get("site_url_patterns") or {})
    site_spa = bool(state.get("site_spa", False))
    target_url = state.get("target_url", "")

    # 이벤트별 샘플 수집.
    paths_samples: dict[str, list[object]] = defaultdict(list)
    events_group: dict[str, list[dict]] = defaultdict(list)
    for row in captured_events:
        data = row.get("data") or {}
        ev_name = str(data.get("event") or "").strip()
        if not ev_name:
            continue
        for path, value in _collect_dl_paths(data):
            if path == "event":
                continue
            paths_samples[path].append(value)
        events_group[ev_name].append(row)

    # paths_seen 및 health 판정.
    paths_seen = sorted(paths_samples.keys())
    paths_health: dict[str, dict] = {}
    for path in paths_seen:
        health, reason = _health_for_dl_path(path, paths_samples[path])
        paths_health[path] = {"health": health, "reason": reason, "samples": len(paths_samples[path])}

    # candidate_sources_per_field — 이벤트별 GA4 공식 필드 중심으로 엮는다.
    candidate_sources: dict[str, list[dict]] = defaultdict(list)
    for path in paths_seen:
        field = path.split(".")[-1].split("[")[0]
        if field not in _FIELD_EXPECT:
            continue
        entry = {"kind": "datalayer", "path": path}
        entry.update(paths_health.get(path, {"health": "unknown"}))
        candidate_sources[field].append(entry)

    for field, spec in dom_selectors.items():
        if isinstance(spec, dict):
            selector = spec.get("selector", "")
            attr = spec.get("attribute", "textContent")
        else:
            selector = str(spec)
            attr = "textContent"
        candidate_sources[field].append(
            {
                "kind": "dom_selector",
                "selector": selector,
                "attribute": attr,
                "validated_value": selector_validation.get(field),
            }
        )
    if json_ld_data:
        for ga_field, path in (
            {"items": None, "item_name": "name", "item_id": "sku", "price": "offers.price"}
        ).items():
            if path and path in (json_ld_data or {}):
                candidate_sources[ga_field].append(
                    {"kind": "json_ld_path", "path": path}
                )
        candidate_sources["items"].append(
            {"kind": "cjs_template", "template_id": "items_from_jsonld"}
        )

    # 이벤트별 surfaces/failures.
    events_payload = []
    for event_name, rows in events_group.items():
        surfaces = []
        failures_from_rows: list[dict] = []
        for row in rows[:3]:
            data = row.get("data") or {}
            url = row.get("url", "") or ""
            path = urlparse(url).path if url else ""
            evidence = row.get("evidence") if isinstance(row, dict) else None
            if isinstance(evidence, dict):
                failures_from_rows.extend(evidence.get("failures") or [])
            surfaces.append(
                {
                    "url": url,
                    "path": path,
                    "datalayer": {
                        "fired": True,
                        "sample": data,
                        "source": row.get("source", "datalayer"),
                    },
                    "dom": {"selectors_resolved": selector_validation},
                    "json_ld": {"found": bool(json_ld_data), "extracted": json_ld_data},
                    "notes": "",
                }
            )
        # 상태에 기록된 드롭/실패 목록 활용.
        failure_list = list(failures_from_rows)
        for f in list(state.get("exploration_failures") or []):
            if not isinstance(f, dict):
                continue
            if f.get("event") and f.get("event") != event_name:
                continue
            failure_list.append(
                {
                    "url": f.get("url", ""),
                    "reason": f.get("reason", ""),
                    "detail": f.get("detail", ""),
                }
            )
        events_payload.append({"event": event_name, "surfaces": surfaces, "failures": failure_list})

    # URL 패턴 병합 — observed > seed.
    seed_url_patterns = _pick_url_patterns(page_type, target_url)
    merged_patterns, pattern_sources = _merge_url_patterns(observed_url_patterns, seed_url_patterns)

    return {
        "request": {
            "user_request": state.get("user_request", ""),
            "selected_events": selected_events,
            "tag_type": state.get("tag_type", "GA4"),
            "ga4_measurement_id": state.get("measurement_id", ""),
        },
        "site": {
            "base_url": target_url,
            "spa": site_spa,
            "page_types_seen": {page_type or "unknown": [target_url]},
            "url_patterns": merged_patterns,
            "url_pattern_sources": pattern_sources,
        },
        "datalayer": {
            "present": state.get("datalayer_status") in ("full", "partial"),
            "pushes_sample": [r.get("data", {}) for r in captured_events[:3]],
            "paths_seen": paths_seen,
            "paths_health": paths_health,
        },
        "dom": {
            "selectors": {
                key: {
                    "selector": (val.get("selector") if isinstance(val, dict) else str(val)),
                    "attribute": (val.get("attribute") if isinstance(val, dict) else "textContent"),
                    "validated_value": selector_validation.get(key),
                }
                for key, val in dom_selectors.items()
            },
            "click_triggers": click_triggers,
        },
        "json_ld": {
            "present": bool(json_ld_data),
            "mappings": json_ld_data if isinstance(json_ld_data, dict) else {},
        },
        "events": events_payload,
        "candidate_sources_per_field": dict(candidate_sources),
    }


def healthy_dl_fields(evidence_pack: dict) -> dict[str, str]:
    """GA4 필드별 **healthy한 최우선 DL 경로** 맵.

    정규화가 "healthy DL 무시" 판정을 내릴 때 기준으로 사용.
    """
    out: dict[str, str] = {}
    for field, candidates in (evidence_pack.get("candidate_sources_per_field") or {}).items():
        for cand in candidates:
            if cand.get("kind") != "datalayer":
                continue
            if cand.get("health") != "healthy":
                continue
            out.setdefault(field, cand.get("path", ""))
            break
    return out


def fired_events(evidence_pack: dict) -> set[str]:
    """EvidencePack.events 중 DL 발화가 기록된 이벤트 이름 집합."""
    out: set[str] = set()
    for ev in evidence_pack.get("events") or []:
        name = str(ev.get("event") or "").strip()
        if not name:
            continue
        for surface in ev.get("surfaces") or []:
            dl = surface.get("datalayer") or {}
            if dl.get("fired"):
                out.add(name)
                break
    return out
