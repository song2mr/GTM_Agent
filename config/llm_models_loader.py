"""`llm_models.yaml` 로더 — 구역별 LLM 모델 ID.

리포지토리 루트의 `config/llm_models.yaml`을 읽는다.
프로세스 수명 동안 한 번 파싱해 캐시한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_YAML = Path(__file__).resolve().parent / "llm_models.yaml"
_cache: dict[str, Any] | None = None

# YAML 없음/손상 시; 공식 문서 기본 권장과 동일 계열
_FALLBACK_MODEL = "gpt-5.4"


def read_llm_models() -> dict[str, Any]:
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


def _coerce_model(value: Any) -> str | None:
    if isinstance(value, str):
        s = value.strip()
        return s or None
    return None


def llm_model(zone: str) -> str:
    """구역 키에 해당하는 모델 ID. 없거나 비어 있으면 `default` 키, 그것도 없으면 gpt-5.4."""
    data = read_llm_models()
    default_m = _coerce_model(data.get("default")) or _FALLBACK_MODEL
    if zone == "default":
        return default_m
    z = _coerce_model(data.get(zone))
    if z is not None:
        return z
    return default_m


def reset_llm_models_cache() -> None:
    """테스트용: 다음 read에서 디스크를 다시 읽는다."""
    global _cache
    _cache = None
