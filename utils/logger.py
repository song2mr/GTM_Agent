"""실행 로그 유틸리티.

logs/{run_id}/ 폴더에 다음을 저장합니다:
  run.log                    — 타임스탬프 포함 전체 실행 로그 (콘솔과 동시 출력)
  llm_decisions.jsonl        — Navigator LLM 결정 내역 (event / attempt / decision / snapshot)
  events.json                — 최종 캡처된 dataLayer 이벤트
  screenshots/               — 각 Navigator 시도별 스크린샷
  datalayer_trace.jsonl      — dataLayer 이름 스냅샷(시그널/노이즈, cap/dl 길이)
  datalayer_diagnose.jsonl   — diagnose_datalayer() 요약(JSON-LD는 타입만)
  datalayer_raw_tail.jsonl   — window.dataLayer 꼬리 N개 원본 payload(병리 분석용)
  page_state.jsonl           — URL·readyState·body 길이 등 브라우저 상태
  captured_mutations.jsonl   — 캡처 목록 변경 이벤트(선택적)
  llm_raw.jsonl              — LLM 원문(선택적)
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


async def capture_page_state(page) -> dict:
    """현재 페이지 메타데이터 스냅샷 (URL / title / readyState / body_n / frames).

    log_page_state / log_dl_state와 짝지어 쓰기 위한 경량 수집기.
    예외는 삼키고 부분 데이터라도 돌려준다.
    """
    state: dict = {"url": "", "doc_url": "", "title": "", "ready": "", "body_n": -1, "frames": 0, "scripts": 0}
    try:
        state["url"] = page.url
    except Exception:
        pass
    try:
        meta = await page.evaluate(
            """() => ({
                doc_url: (document && document.URL) || '',
                title: (document && document.title) || '',
                ready: (document && document.readyState) || '',
                body_n: (document && document.body && document.body.innerHTML && document.body.innerHTML.length) || -1,
                scripts: (document && document.scripts && document.scripts.length) || 0,
            })"""
        )
        if isinstance(meta, dict):
            state.update(meta)
    except Exception as e:
        state["meta_error"] = str(e)[:120]
    try:
        state["frames"] = len(page.frames)
    except Exception:
        pass
    return state


def log_page_state(tag: str, page_state: dict, *, extra: dict | None = None) -> None:
    """페이지 메타 스냅샷을 run.log + `page_state.jsonl`에 기록."""
    if _run_dir is None:
        return
    _get().info(
        f"[Page] tag={tag!r} url={page_state.get('url', '')!r} "
        f"ready={page_state.get('ready', '')!r} title={(page_state.get('title', '') or '')[:60]!r} "
        f"body_n={page_state.get('body_n', -1)} frames={page_state.get('frames', 0)} "
        f"scripts={page_state.get('scripts', 0)}"
        + (" " + " ".join(f"{k}={v!r}" for k, v in (extra or {}).items()) if extra else "")
    )
    record = {
        "ts": datetime.now().isoformat(),
        "tag": tag,
        **page_state,
    }
    if extra:
        record["extra"] = extra
    try:
        with open(_run_dir / "page_state.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        _get().debug(f"[Page] page_state 기록 실패: {e}")


def log_captured_mutation(
    tag: str,
    event_name: str,
    *,
    action: str = "append",
    source: str = "",
    url: str = "",
    reason: str = "",
    total_after: int = -1,
) -> None:
    """captured_events의 추가/스킵을 일관된 포맷으로 기록.

    action: 'append' | 'skip' | 'supplement' | 'manual'
    """
    if _run_dir is None:
        return
    _get().info(
        f"[Capture] tag={tag!r} action={action} event={event_name!r} source={source!r} "
        f"url={url!r} total={total_after} reason={(reason or '')[:160]!r}"
    )
    try:
        record = {
            "ts": datetime.now().isoformat(),
            "tag": tag,
            "action": action,
            "event": event_name,
            "source": source,
            "url": url,
            "total_after": total_after,
            "reason": reason,
        }
        with open(_run_dir / "captured_mutations.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        _get().debug(f"[Capture] captured_mutations 기록 실패: {e}")


def log_llm_raw(
    tag: str,
    prompt_chars: int,
    response_raw: str,
    *,
    wall_s: float = 0.0,
    extra: dict | None = None,
) -> None:
    """LLM 원문 응답 전체를 `llm_raw.jsonl`에 기록 (llm_decisions와 다름)."""
    if _run_dir is None:
        return
    record = {
        "ts": datetime.now().isoformat(),
        "tag": tag,
        "prompt_chars": prompt_chars,
        "response_chars": len(response_raw or ""),
        "response_raw": response_raw or "",
        "wall_s": round(wall_s, 3),
    }
    if extra:
        record["extra"] = extra
    try:
        with open(_run_dir / "llm_raw.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        _get().debug(f"[LLMRaw] llm_raw 기록 실패: {e}")


def log_datalayer_diagnose(
    tag: str,
    url: str,
    diagnosis: dict,
    *,
    extra: dict | None = None,
) -> None:
    """diagnose_datalayer() 결과를 run.log + datalayer_diagnose.jsonl에 기록.

    json_ld 전체는 파일에 넣지 않고 개수·@type 샘플만 남긴다.
    """
    if _run_dir is None:
        return
    slim: dict = {}
    for k, v in diagnosis.items():
        if k == "json_ld":
            continue
        slim[k] = v
    jld = diagnosis.get("json_ld")
    if isinstance(jld, list):
        slim["json_ld_n"] = len(jld)
        head_types: list = []
        for item in jld[:10]:
            if isinstance(item, dict):
                t = item.get("@type")
                head_types.append(t if t else list(item.keys())[:5])
            else:
                head_types.append(type(item).__name__)
        slim["json_ld_head_types"] = head_types
    elif jld is not None:
        slim["json_ld_n"] = 1
        slim["json_ld_head_types"] = [type(jld).__name__]
    if extra:
        slim["extra"] = extra
    evs = slim.get("events") or []
    evs_n = len(evs) if isinstance(evs, list) else 0
    _get().info(
        f"[DL-Diag] tag={tag!r} url={url!r} status={slim.get('status')!r} "
        f"has_datalayer={slim.get('has_datalayer')} has_gtm={slim.get('has_gtm')} "
        f"has_ecommerce={slim.get('has_ecommerce')} events_n={evs_n} "
        f"json_ld_n={slim.get('json_ld_n', 0)}"
    )
    try:
        record = {"ts": datetime.now().isoformat(), "tag": tag, "url": url, **slim}
        with open(_run_dir / "datalayer_diagnose.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        _get().debug(f"[DL-Diag] 기록 실패: {e}")


def log_dl_raw_peek(
    tag: str,
    url: str,
    items: list,
    *,
    target_event: str = "",
    extra: dict | None = None,
) -> None:
    """peek_datalayer_raw() 결과를 datalayer_raw_tail.jsonl + DEBUG 한 줄."""
    if _run_dir is None:
        return
    record: dict = {
        "ts": datetime.now().isoformat(),
        "tag": tag,
        "url": url,
        "target_event": target_event,
        "items": items if isinstance(items, list) else [],
    }
    if extra:
        record["extra"] = extra
    try:
        line = json.dumps(record, ensure_ascii=False)
        if len(line) > 120_000:
            record["items"] = (items or [])[:4]
            record["truncated"] = True
            line = json.dumps(record, ensure_ascii=False)
        _get().debug(
            f"[DL-Raw] tag={tag!r} url={url!r} target={target_event or '-'} "
            f"items_n={len(record.get('items') or [])} chars={len(line)}"
        )
        with open(_run_dir / "datalayer_raw_tail.jsonl", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:
        _get().debug(f"[DL-Raw] 기록 실패: {e}")


async def probe_datalayer_verbose(
    page,
    tag: str,
    url: str | None = None,
    target_event: str = "",
    *,
    extra: dict | None = None,
    raw_tail_n: int = 12,
    log_page: bool = True,
) -> None:
    """snapshot_datalayer_names + (선택) raw_tail + page_state를 한 번에 기록."""
    from browser.listener import peek_datalayer_raw, snapshot_datalayer_names

    try:
        u = url or page.url
    except Exception:
        u = url or ""
    if log_page:
        try:
            ps = await capture_page_state(page)
            merged_extra = {**(extra or {}), "target_event": target_event}
            log_page_state(f"{tag}/browser", ps, extra=merged_extra)
        except Exception as e:
            _get().debug(f"[DL-Probe] page_state 실패 tag={tag!r}: {e}")
    try:
        snap = await snapshot_datalayer_names(page)
        merged: dict = dict(snap) if isinstance(snap, dict) else {}
        if raw_tail_n > 0:
            try:
                merged["raw_tail"] = await peek_datalayer_raw(page, raw_tail_n)
            except Exception as e:
                merged["raw_tail"] = [{"__peek_error": str(e)[:200]}]
        log_dl_state(tag, u, merged, target_event=target_event, extra=extra)
    except Exception as e:
        _get().warning(f"[DL-Probe] probe 실패 tag={tag!r}: {e}")


def log_dl_state(
    tag: str,
    url: str,
    snapshot: dict,
    *,
    target_event: str = "",
    extra: dict | None = None,
) -> None:
    """dataLayer 조회 시점 스냅샷을 run.log + datalayer_trace.jsonl에 기록.

    Args:
        tag: "page_classifier/post-load", "active_explorer/initial",
             "navigator/step1/after-action", "navigator/impossible" 등.
        url: 해당 시점 page.url.
        snapshot: listener.snapshot_datalayer_names()의 반환값.
        target_event: (선택) 현재 추적 중인 이벤트 이름.
        extra: (선택) 추가 메타. 예: {"step": 3, "action": "click"}.

    run.log 한 줄 예:
        [DL] tag='navigator/step3/after-action' url='…/goods_view.php?goodsNo=1' \
             target=view_item has=True listener=True cap=14 dl=17 \
             signal=['view_item','view_item_list'] noise_n=12 target_present=True
    """
    if _run_dir is None:
        return

    signal = snapshot.get("signal_names", []) or []
    noise_n = snapshot.get("noise_n", 0)
    cap_n = snapshot.get("cap_n", 0)
    dl_n = snapshot.get("dl_n", -1)
    has_dl = snapshot.get("has_dl", False)
    has_gtm = snapshot.get("has_gtm", False)
    listener_injected = snapshot.get("listener_injected", False)
    target_present = bool(target_event and target_event in signal)

    extra_str = ""
    if extra:
        try:
            extra_str = " " + " ".join(f"{k}={v!r}" for k, v in extra.items())
        except Exception:
            extra_str = ""

    _get().info(
        f"[DL] tag={tag!r} url={url!r} target={target_event or '-'} "
        f"has_dl={has_dl} listener={listener_injected} has_gtm={has_gtm} "
        f"cap={cap_n} dl={dl_n} "
        f"signal={signal[:12]}{' …' if len(signal) > 12 else ''} "
        f"noise_n={noise_n} target_present={target_present}{extra_str}"
    )

    record = {
        "ts": datetime.now().isoformat(),
        "tag": tag,
        "url": url,
        "target_event": target_event,
        "target_present": target_present,
        "has_dl": has_dl,
        "has_gtm": has_gtm,
        "listener_injected": listener_injected,
        "cap_n": cap_n,
        "dl_n": dl_n,
        "signal_names": signal,
        "noise_names": snapshot.get("noise_names", []),
        "signal_n": snapshot.get("signal_n", len(signal)),
        "noise_n": noise_n,
    }
    if "raw_tail" in snapshot:
        record["raw_tail"] = snapshot["raw_tail"]
    if extra:
        record["extra"] = extra
    if "error" in snapshot:
        record["snapshot_error"] = snapshot["error"]
    try:
        with open(_run_dir / "datalayer_trace.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        _get().debug(f"[DL] datalayer_trace 기록 실패: {e}")


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
