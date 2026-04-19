"""Canonical Plan schema constants and helpers."""

from __future__ import annotations

from dataclasses import dataclass

CANPLAN_VERSION = "canplan/1"

VARIABLE_KINDS = {
    "datalayer",
    "dom_id",
    "dom_selector",
    "cjs_template",
    "json_ld_path",
    "constant",
    "builtin",
}

TRIGGER_KINDS = {
    "custom_event",
    "click",
    "pageview",
    "dom_ready",
    "window_loaded",
    "history_change",
    "form_submit",
    "element_visibility",
}

TRIGGER_OPS = {
    "equals",
    "contains",
    "starts_with",
    "ends_with",
    "matches_regex",
    "not_equals",
    "not_contains",
    "not_starts_with",
    "not_ends_with",
    "not_matches_regex",
}

BUILTIN_VARIABLES = {
    "{{Page Path}}",
    "{{Page URL}}",
    "{{Page Hostname}}",
    "{{Click Element}}",
    "{{Click Classes}}",
    "{{Click Text}}",
    "{{_event}}",
}


@dataclass
class NormalizeIssue:
    code: str
    severity: str
    event: str | None
    rule_id: str
    message: str
    hint: str
    affected_names: list[str]
    retryable: bool = False

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "event": self.event,
            "rule_id": self.rule_id,
            "message": self.message,
            "hint": self.hint,
            "affected_names": self.affected_names,
            "retryable": self.retryable,
        }


def canplan_json_schema() -> dict:
    """Lightweight JSON schema used for prompt constraints and logging."""
    return {
        "type": "object",
        "required": ["version", "scope", "variables", "triggers", "tags"],
        "properties": {
            "version": {"const": CANPLAN_VERSION},
            "scope": {
                "type": "object",
                "required": ["tag_type", "allowed_events", "ga4_measurement_id"],
                "properties": {
                    "tag_type": {"type": "string", "enum": ["GA4"]},
                    "allowed_events": {"type": "array", "items": {"type": "string"}},
                    "ga4_measurement_id": {"type": "string"},
                },
            },
            "variables": {"type": "array", "items": {"type": "object"}},
            "triggers": {"type": "array", "items": {"type": "object"}},
            "tags": {"type": "array", "items": {"type": "object"}},
            "evidence": {"type": "object"},
        },
    }
