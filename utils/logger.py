"""실행 로그 유틸리티.

logs/{run_id}/ 폴더에 다음을 저장합니다:
  run.log              — 타임스탬프 포함 전체 실행 로그 (콘솔과 동시 출력)
  llm_decisions.jsonl  — Navigator LLM 결정 내역 (event / attempt / decision / snapshot)
  events.json          — 최종 캡처된 dataLayer 이벤트
  screenshots/         — 각 Navigator 시도별 스크린샷
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

# 모듈 레벨 싱글톤
_logger: logging.Logger | None = None
_run_dir: Path | None = None


def setup(run_id: str | None = None) -> Path:
    """로거를 초기화하고 run 디렉토리 경로를 반환합니다."""
    global _logger, _run_dir

    if run_id is None:
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    _run_dir = Path("logs") / run_id
    _run_dir.mkdir(parents=True, exist_ok=True)
    (_run_dir / "screenshots").mkdir(exist_ok=True)

    _logger = logging.getLogger("gtm_ai")
    _logger.setLevel(logging.DEBUG)
    _logger.handlers.clear()

    # 파일 핸들러 (UTF-8)
    fh = logging.FileHandler(_run_dir / "run.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    _logger.addHandler(fh)

    # 콘솔 핸들러 (UTF-8, errors=replace)
    ch = logging.StreamHandler(
        stream=open(sys.stdout.fileno(), mode="w", encoding="utf-8", errors="replace", closefd=False)
    )
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(ch)

    _logger.info(f"=== GTM AI Agent 실행 시작: {run_id} ===")
    _logger.info(f"로그 디렉토리: {_run_dir.resolve()}")
    return _run_dir


def _get() -> logging.Logger:
    if _logger is None:
        raise RuntimeError("logger.setup()을 먼저 호출하세요.")
    return _logger


def info(msg: str) -> None:
    _get().info(msg)


def debug(msg: str) -> None:
    _get().debug(msg)


def warning(msg: str) -> None:
    _get().warning(msg)


def error(msg: str) -> None:
    _get().error(msg)


def log_llm_decision(
    event: str,
    attempt: int,
    decision: dict,
    snapshot: str,
    current_url: str = "",
) -> None:
    """Navigator LLM 결정 1건을 llm_decisions.jsonl에 기록합니다."""
    if _run_dir is None:
        return
    record = {
        "ts": datetime.now().isoformat(),
        "event": event,
        "attempt": attempt,
        "url": current_url,
        "decision": decision,
        "snapshot_chars": len(snapshot),
        "snapshot_head": snapshot[:500],
    }
    with open(_run_dir / "llm_decisions.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    _get().debug(
        f"[LLM] {event} 시도{attempt} → action={decision.get('action')} "
        f"reason={decision.get('reason', '')[:80]}"
    )


async def save_screenshot(page: "Page", event: str, attempt: int, label: str = "") -> None:
    """현재 페이지 스크린샷을 screenshots/ 에 저장합니다."""
    if _run_dir is None:
        return
    suffix = f"_{label}" if label else ""
    filename = f"{event}_attempt{attempt}{suffix}.png"
    path = _run_dir / "screenshots" / filename
    try:
        await page.screenshot(path=str(path), full_page=False)
        _get().debug(f"[Screenshot] 저장: {filename}")
    except Exception as e:
        _get().debug(f"[Screenshot] 실패: {e}")


def save_events(events: list[dict]) -> None:
    """캡처된 이벤트 목록을 events.json에 저장합니다."""
    if _run_dir is None:
        return
    path = _run_dir / "events.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(events, f, ensure_ascii=False, indent=2)
    _get().info(f"[Events] {len(events)}개 이벤트 저장 → {path}")


def run_dir() -> Path | None:
    return _run_dir
