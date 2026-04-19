"""사용자가 **명시한 이벤트 목록**을 결정하는 단일 진입점.

우선순위:
    1) ``state["selected_events"]`` (UI 체크박스 등에서 구조화된 입력)
    2) ``user_request`` 문자열의 **마지막** ``( … )`` 블록 파싱 (하위 호환)

둘 다 없으면 **None** 을 돌려주어, Journey Planner가 자유 텍스트 LLM 경로로
폴백하도록 한다. 설계·탐색 단 한 곳에서만 이 함수를 참조하도록 유지한다.
"""

from __future__ import annotations

import re
from typing import Mapping

_PAREN_BLOCK = re.compile(r"\(([^)]+)\)")
_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_MEASUREMENT_ID_RE = re.compile(r"G-[A-Z0-9]+", re.I)


def _normalize(names) -> list[str]:
    """대소문자·공백 정규화 + 순서 유지 중복 제거."""
    if names is None:
        return []
    if isinstance(names, str):
        names = [names]
    out: list[str] = []
    seen: set[str] = set()
    for n in names:
        if not isinstance(n, str):
            continue
        t = n.strip().lower()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def parse_parenthesized_event_list(user_request: str) -> list[str] | None:
    """요청 문자열의 **마지막** `( … )` 블록에서 이벤트명 후보를 추출한다.

    - 쉼표로 구분된 토큰만 사용한다.
    - ``G-XXXXXXXX`` 측정 ID는 제외한다.
    - ``[A-Za-z][A-Za-z0-9_]*`` 패턴만 허용한다.
    - 유효 토큰이 없으면 ``None``.
    """
    text = (user_request or "").strip()
    if not text:
        return None
    matches = list(_PAREN_BLOCK.finditer(text))
    for m in reversed(matches):
        parts = [p.strip() for p in m.group(1).split(",")]
        names: list[str] = []
        for p in parts:
            if not p or _MEASUREMENT_ID_RE.fullmatch(p):
                continue
            if _NAME_RE.fullmatch(p):
                names.append(p.lower())
        if names:
            return _normalize(names)
    return None


def resolve_selected_events(state: Mapping) -> list[str] | None:
    """state에서 사용자가 **명시한 이벤트 목록**을 해석한다.

    Returns:
        - list[str]: 설치/탐색 대상 이벤트명(소문자) — strict 모드
        - None: 명시 목록 없음 — 자유 텍스트/LLM 폴백 모드
    """
    sel = _normalize(state.get("selected_events") or [])
    if sel:
        return sel
    parsed = parse_parenthesized_event_list(state.get("user_request", "") or "")
    return parsed if parsed else None
