"""실시간 문서 fetch 모듈.

Naver Analytics, Kakao Pixel 등 매체별 공식 문서를 실시간으로 가져와
LLM 컨텍스트에 투입합니다. fetch 실패 시 경고 후 빈 문자열 반환 (내장 지식 폴백).
"""

from __future__ import annotations

from pathlib import Path

import httpx
import yaml
from bs4 import BeautifulSoup

CONFIG_PATH = Path(__file__).parent.parent / "config" / "media_sources.yaml"


def load_media_config() -> dict:
    """media_sources.yaml을 로드합니다."""
    with CONFIG_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def fetch_url(url: str, timeout: int = 15) -> str:
    """URL에서 텍스트 본문을 가져옵니다. 실패 시 빈 문자열 반환."""
    try:
        resp = httpx.get(url, timeout=timeout, follow_redirects=True,
                         headers={"User-Agent": "Mozilla/5.0 (compatible; GTM-AI-Agent/1.0)"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # 불필요한 태그 제거
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        text = soup.get_text(separator="\n")
        # 빈 줄 정리
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        return "\n".join(lines)
    except Exception as e:
        print(f"[DocFetcher] fetch 실패: {url} — {e}")
        return ""


def fetch_docs_for_media(media_key: str) -> tuple[str, bool]:
    """
    매체 키(naver_analytics, kakao_pixel)에 해당하는 문서를 fetch합니다.

    Returns:
        (doc_text, fetch_failed)
        fetch_failed=True 이면 내장 지식 폴백 필요.
    """
    config = load_media_config()
    media_config = config.get(media_key)

    if not media_config:
        print(f"[DocFetcher] '{media_key}' 설정 없음 — 내장 지식 폴백")
        return "", True

    urls: list[str] = media_config.get("urls", [])
    texts: list[str] = []

    for url in urls:
        if not url:
            continue
        text = fetch_url(url)
        if text:
            texts.append(f"=== {url} ===\n{text}")

    if not texts:
        print(f"[DocFetcher] '{media_key}' 모든 URL fetch 실패 — 내장 지식 폴백")
        return "", True

    combined = "\n\n".join(texts)
    # 너무 길면 앞부분만 사용 (LLM 컨텍스트 제한)
    max_chars = 20000
    if len(combined) > max_chars:
        combined = combined[:max_chars] + "\n...(이하 생략)"

    return combined, False
