"""`exploration_limits.yaml` 로더.

리포지토리 루트의 `config/exploration_limits.yaml`을 읽는다.
프로세스 수명 동안 한 번 파싱해 캐시한다(에이전트 1회 실행 기준).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_YAML = Path(__file__).resolve().parent / "exploration_limits.yaml"
_cache: dict[str, Any] | None = None


def read_exploration_limits() -> dict[str, Any]:
    """YAML 전체를 dict로 반환. 파일 없으면 {}."""
    global _cache
    if _cache is not None:
        return _cache
    if _YAML.exists():
        raw = yaml.safe_load(_YAML.read_text(encoding="utf-8"))
        _cache = raw if isinstance(raw, dict) else {}
    else:
        _cache = {}
    return _cache


def cart_addition_max_llm_steps() -> int:
    """Node 3.25 장바구니 담기 전용 Navigator 스텝 상한."""
    v = (read_exploration_limits().get("cart_addition") or {}).get("max_llm_steps", 8)
    return max(1, int(v))


def begin_checkout_max_llm_steps() -> int:
    """Node 3.5 begin_checkout 전용 Navigator 스텝 상한."""
    v = (read_exploration_limits().get("begin_checkout") or {}).get("max_llm_steps", 8)
    return max(1, int(v))


def reset_exploration_limits_cache() -> None:
    """테스트용: 다음 read에서 디스크를 다시 읽는다."""
    global _cache
    _cache = None
