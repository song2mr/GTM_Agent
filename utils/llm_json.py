"""LLM 응답 공통 유틸 — JSON 파싱, lazy LLM 팩토리.

**목적**
- 각 노드·Navigator에 흩어진 ```json ... ``` 파싱 로직을 한 곳에 모은다.
- LLM이 비정상(한 쌍이 아닌 펜스·설명 텍스트 혼재·빈 응답 등)을 내도 IndexError로
  파이프라인이 통째로 죽지 않도록 방어한다.
- `ChatOpenAI` 인스턴스의 **모듈 레벨 즉시 생성**을 피하기 위해 lazy 팩토리를 제공한다.
  환경변수(OPENAI_API_KEY) 주입 전에 import되어도 문제가 없어야 한다.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_openai import ChatOpenAI


def parse_llm_json(raw: str | None, *, fallback: Any | None = None) -> Any:
    """LLM 응답에서 JSON 객체를 안전하게 추출한다.

    다음 순서로 시도하고, 모두 실패하면 `fallback`을 반환한다(기본 `{}`).

    1. 마크다운 펜스(``` 또는 ```json) 쌍이 하나 이상이면 **모든 코드블록**을 순서대로 파싱.
    2. 본문 전체를 그대로 `json.loads`.
    3. 최외곽 `{ ... }` 블록만 잘라 재시도 (LLM이 앞뒤에 설명을 붙인 경우).

    기존 `split("```")[1]` 패턴은 펜스가 하나뿐일 때 IndexError를 낸다 —
    이 함수는 어떤 상황에서도 예외를 던지지 않는다.
    """
    if fallback is None:
        fallback = {}
    if not raw:
        return fallback

    text = raw.strip()

    # 1) 마크다운 코드 블록 안을 우선 시도 (```json ... ```, ``` ... ```)
    if "```" in text:
        parts = text.split("```")
        # 홀수 인덱스 = 코드 블록 내부
        for block in parts[1::2]:
            candidate = block.lstrip()
            if candidate.lower().startswith("json"):
                candidate = candidate[4:].lstrip()
            candidate = candidate.strip()
            if not candidate:
                continue
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue

    # 2) 본문 그대로 파싱
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 3) 최외곽 중괄호 블록 추출
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    return fallback


def make_chat_llm(model: str = "gpt-5.4-mini", *, timeout: float = 120.0, **kwargs: Any) -> ChatOpenAI:
    """`ChatOpenAI` 인스턴스를 **호출 시점에** 만들어 반환한다.

    모듈 최상단에서 `_llm = ChatOpenAI(...)`로 즉시 만들면, 임포트 타이밍에
    OPENAI_API_KEY가 아직 로드되지 않았을 때 크래시하거나 키 없는 클라이언트가
    굳어버린다. 각 노드는 함수 진입 시 이 팩토리를 호출해 그때그때 생성한다.
    """
    return ChatOpenAI(model=model, timeout=timeout, **kwargs)
