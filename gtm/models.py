"""GTM API 리소스 데이터 모델."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class GTMParameter:
    type: str        # "template", "boolean", "integer", "list", "map"
    key: str
    value: str = ""
    list_: list = field(default_factory=list)
    map_: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"type": self.type, "key": self.key}
        if self.type in ("template", "boolean", "integer"):
            d["value"] = self.value
        if self.type == "list":
            d["list"] = self.list_
        if self.type == "map":
            d["map"] = self.map_
        return d


@dataclass
class GTMVariable:
    name: str
    type: str           # "v" = dataLayer variable, "u" = URL variable 등
    parameters: list[GTMParameter] = field(default_factory=list)
    variable_id: str | None = None  # 생성 후 채워짐

    def to_api_body(self, workspace_path: str) -> dict:
        return {
            "name": self.name,
            "type": self.type,
            "parameter": [p.to_dict() for p in self.parameters],
        }


@dataclass
class GTMTrigger:
    name: str
    type: str           # "pageview", "customEvent", "click" 등
    custom_event_filter: list = field(default_factory=list)
    filter_: list = field(default_factory=list)
    auto_event_filter: list = field(default_factory=list)
    trigger_id: str | None = None

    def to_api_body(self, workspace_path: str) -> dict:
        body: dict[str, Any] = {
            "name": self.name,
            "type": self.type,
        }
        if self.custom_event_filter:
            body["customEventFilter"] = self.custom_event_filter
        if self.filter_:
            body["filter"] = self.filter_
        if self.auto_event_filter:
            body["autoEventFilter"] = self.auto_event_filter
        return body


@dataclass
class GTMTag:
    name: str
    type: str           # "gaawe" = GA4 event, "html" = Custom HTML 등
    parameters: list[GTMParameter] = field(default_factory=list)
    firing_trigger_ids: list[str] = field(default_factory=list)
    tag_id: str | None = None

    def to_api_body(self, workspace_path: str) -> dict:
        return {
            "name": self.name,
            "type": self.type,
            "parameter": [p.to_dict() for p in self.parameters],
            "firingTriggerId": self.firing_trigger_ids,
        }
