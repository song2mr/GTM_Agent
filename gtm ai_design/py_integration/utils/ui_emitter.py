"""UI가 구독할 수 있도록 logs/{run_id}/ 아래 JSONL/JSON 파일로 이벤트를 emit.

설계 원칙:
- 별도 서버/프로세스 없음. 파일 시스템만 사용.
- append-only JSONL (`events.jsonl`) + 덮어쓰기 스냅샷 (`state.json`, `plan.json`).
- 스레드 안전 (lock 하나로 보호).

사용 예:
    from utils.ui_emitter import emit, set_run_dir, update_state

    set_run_dir(run_dir)  # logger.setup()이 반환한 경로
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
    """현재 run_id의 로그 폴더를 지정. main.py 초기화 시점에 1회 호출."""
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
    """events.jsonl에 한 줄 append."""
    if _run_dir is None:
        return
    record = {"ts": _now_iso(), "type": event_type, **payload}
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with _lock:
        with (_run_dir / "events.jsonl").open("a", encoding="utf-8") as f:
            f.write(line)


def update_state(**fields: Any) -> None:
    """state.json을 partial merge로 갱신 (덮어쓰기)."""
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
        current.update(fields)
        path.write_text(
            json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def write_plan(plan: dict) -> None:
    """HITL 시 설계안을 plan.json으로 저장."""
    if _run_dir is None:
        return
    (_run_dir / "plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def write_history_index(logs_root: str | Path) -> None:
    """logs/ 하위를 스캔해서 logs/index.json 생성 (History 화면용).

    각 run_dir의 state.json을 읽어 요약 레코드 배열로 저장.
    run 종료 시 또는 주기적으로 호출.
    """
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
