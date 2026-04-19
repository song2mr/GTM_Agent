"""Playbook loader for event exploration plan.

§6.5 Playbook 실행 계약을 로드·정규화해 Journey Planner가 state에 주입한다.
존재하지 않는 이벤트는 합리적 기본값(Fallback Playbook)으로 채운다.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_PLAYBOOK_FILE = Path(__file__).with_name("ga4_ecommerce.yaml")

_DEFAULT_PLAYBOOK: dict = {
    "surface_goal": "unknown",
    "entry_hints": {"url_patterns": [], "click_hints": [], "from_surfaces": []},
    "observation": {
        "datalayer_events": [],
        "required_fields": [],
        "optional_fields": [],
        "settle_ms": 1000,
    },
    "trigger_fallbacks": ["custom_event", "click", "pageview"],
}


def _empty_playbook(event: str) -> dict:
    """이벤트 이름만 가지고 만드는 기본 Playbook(커스텀 이벤트 seed)."""
    pb = _copy_playbook(_DEFAULT_PLAYBOOK)
    pb["observation"]["datalayer_events"] = [event]
    return pb


def _copy_playbook(pb: dict) -> dict:
    """얕은 중첩 구조 복사 — state에 주입 후 외부 수정이 원본에 반영되지 않도록."""
    entry = dict(pb.get("entry_hints") or {})
    entry.setdefault("url_patterns", [])
    entry.setdefault("click_hints", [])
    entry.setdefault("from_surfaces", [])
    obs = dict(pb.get("observation") or {})
    obs.setdefault("datalayer_events", [])
    obs.setdefault("required_fields", [])
    obs.setdefault("optional_fields", [])
    obs.setdefault("settle_ms", 1000)
    return {
        "surface_goal": pb.get("surface_goal", "unknown"),
        "entry_hints": {
            "url_patterns": list(entry.get("url_patterns") or []),
            "click_hints": list(entry.get("click_hints") or []),
            "from_surfaces": list(entry.get("from_surfaces") or []),
        },
        "observation": {
            "datalayer_events": list(obs.get("datalayer_events") or []),
            "required_fields": list(obs.get("required_fields") or []),
            "optional_fields": list(obs.get("optional_fields") or []),
            "settle_ms": int(obs.get("settle_ms") or 1000),
        },
        "trigger_fallbacks": list(pb.get("trigger_fallbacks") or []),
    }


def load_ga4_playbooks() -> dict:
    if not _PLAYBOOK_FILE.exists():
        return {}
    with _PLAYBOOK_FILE.open("r", encoding="utf-8") as f:
        payload = yaml.safe_load(f) or {}
    events = dict(payload.get("events") or {})
    return {name: _copy_playbook(pb or {}) for name, pb in events.items()}


def playbook_for_event(event: str, registry: dict | None = None) -> dict:
    registry = registry if registry is not None else load_ga4_playbooks()
    if event in registry:
        return _copy_playbook(registry[event])
    return _empty_playbook(event)


def build_exploration_plan(events: list[str]) -> list[dict]:
    """각 이벤트를 Playbook으로 확장. Journey Planner가 state에 저장한다."""
    registry = load_ga4_playbooks()
    return [
        {"event": event, "playbook": playbook_for_event(event, registry)}
        for event in events
        if event
    ]
