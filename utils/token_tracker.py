"""LLM 토큰 사용량 추적기.

각 노드별 LLM 호출의 input/output 토큰을 누적 집계합니다.
실행 종료 시 reporter가 총 토큰량을 보고서에 포함합니다.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from langchain_core.messages import AIMessage


@dataclass
class _NodeUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0


_lock = threading.Lock()
_usage: dict[str, _NodeUsage] = {}


def track(node: str, response: AIMessage) -> None:
    """LLM 응답에서 토큰 사용량을 추출하여 누적합니다."""
    meta = getattr(response, "usage_metadata", None) or {}
    input_t = meta.get("input_tokens", 0)
    output_t = meta.get("output_tokens", 0)

    if not (input_t or output_t):
        raw = getattr(response, "response_metadata", None) or {}
        token_usage = raw.get("token_usage", {})
        input_t = token_usage.get("prompt_tokens", 0)
        output_t = token_usage.get("completion_tokens", 0)

    with _lock:
        if node not in _usage:
            _usage[node] = _NodeUsage()
        _usage[node].input_tokens += input_t
        _usage[node].output_tokens += output_t
        _usage[node].calls += 1


def summary() -> dict:
    """현재까지 누적된 토큰 사용량 요약을 반환합니다.

    Returns:
        {
            "by_node": { "node_name": { "input": int, "output": int, "calls": int } },
            "total_input": int,
            "total_output": int,
            "total": int,
            "total_calls": int,
        }
    """
    with _lock:
        by_node = {
            name: {
                "input": u.input_tokens,
                "output": u.output_tokens,
                "total": u.input_tokens + u.output_tokens,
                "calls": u.calls,
            }
            for name, u in _usage.items()
        }
        total_input = sum(u.input_tokens for u in _usage.values())
        total_output = sum(u.output_tokens for u in _usage.values())
        total_calls = sum(u.calls for u in _usage.values())

    return {
        "by_node": by_node,
        "total_input": total_input,
        "total_output": total_output,
        "total": total_input + total_output,
        "total_calls": total_calls,
    }


def reset() -> None:
    """추적 데이터를 초기화합니다 (테스트용)."""
    with _lock:
        _usage.clear()
