"""UI가 구독할 수 있도록 logs/{run_id}/ 아래 JSONL/JSON 파일로 이벤트를 emit.

사용 예:
    from utils.ui_emitter import emit, set_run_dir, update_state

    set_run_dir(run_dir)
    emit("run_start", run_id=run_id, target_url=url, user_request=req)
    emit("node_enter", node_id=1, node_key="page_classifier", title="Page Classifier")
    emit("thought", who="agent", label="PageClassifier", text="dataLayer full 확인")
    emit("datalayer_event", event="view_item", url="/product/3481",
         source="datalayer", params={"item_id": "3481"})
    update_state(current_node=3, status="running")
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_lock = threading.Lock()
_run_dir: Path | None = None


def set_run_dir(path: str | Path) -> None:
    global _run_dir
    _run_dir = Path(path)
    _run_dir.mkdir(parents=True, exist_ok=True)
    events = _run_dir / "events.jsonl"
    if not events.exists():
        events.touch()


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def emit(event_type: str, **payload: Any) -> None:
    if _run_dir is None:
        return
    record = {"ts": _now_iso(), "type": event_type, **payload}
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with _lock:
        with (_run_dir / "events.jsonl").open("a", encoding="utf-8") as f:
            f.write(line)


def update_state(**fields: Any) -> None:
    """state.json partial merge. nodes_status={"node_key": "status"} 로 nodes 배열 업데이트."""
    if _run_dir is None:
        return
    path = _run_dir / "state.json"
    nodes_status: dict = fields.pop("nodes_status", {})
    with _lock:
        current: dict = {}
        if path.exists():
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                current = {}
        current.update(fields)
        if nodes_status:
            nodes = current.get("nodes", [])
            for n in nodes:
                if n.get("key") in nodes_status:
                    n["status"] = nodes_status[n["key"]]
            current["nodes"] = nodes
        path.write_text(
            json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def write_plan(plan: dict) -> None:
    if _run_dir is None:
        return
    (_run_dir / "plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def reconcile_timeline_at_reporter(*, has_error: bool) -> None:
    """Reporter 진입 직전: 분기로 실행되지 않은 노드가 queued/run으로 남는 현상 보정.

    - queued → skip (예: Manual Capture 경로 미진입, GTM 실패 후 Publish 미진입)
    - run → failed(has_error) / done(비정상 잔류 복구)
    """
    if _run_dir is None:
        return
    path = _run_dir / "state.json"
    with _lock:
        current: dict = {}
        if path.exists():
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return
        nodes = current.get("nodes", [])
        for n in nodes:
            if n.get("key") == "reporter":
                continue
            st = n.get("status", "")
            if st == "queued":
                n["status"] = "skip"
            elif st == "run":
                n["status"] = "failed" if has_error else "done"
        current["nodes"] = nodes
        path.write_text(
            json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def update_node_status(node_key: str, status: str) -> None:
    """state.json의 nodes 배열에서 특정 node_key의 status를 업데이트."""
    if _run_dir is None:
        return
    path = _run_dir / "state.json"
    with _lock:
        current: dict = {}
        if path.exists():
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                current = {}
        nodes = current.get("nodes", [])
        for n in nodes:
            if n.get("key") == node_key:
                n["status"] = status
                break
        current["nodes"] = nodes
        path.write_text(
            json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def write_history_index(logs_root: str | Path) -> None:
    """logs/ 하위를 스캔해 logs/index.json 생성 (History 화면용)."""
    root = Path(logs_root)
    items = []
    for d in sorted(root.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        state_file = d / "state.json"
        if not state_file.exists():
            continue
        try:
            s = json.loads(state_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        items.append(
            {
                "run_id": d.name,
                "t": s.get("started_at") or d.name,
                "url": s.get("target_url", ""),
                "pageType": s.get("page_type", ""),
                "tagType": s.get("tag_type", ""),
                "events": s.get("events_count", 0),
                "status": s.get("status", "unknown"),
                "dur": s.get("duration", "—"),
            }
        )
    (root / "index.json").write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )
