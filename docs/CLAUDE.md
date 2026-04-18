# docs CLAUDE.md

매체별 공식 문서를 실시간으로 fetch해 LLM 컨텍스트에 투입하는 모듈.

---

## 파일 구성

| 파일 | 역할 |
|------|------|
| `fetcher.py` | URL fetch, 텍스트 추출, 매체별 문서 조합 |
| `gtm-variable-api.md` | GTM Variable REST(특히 DOM `type: "d"`) 키·정규화·공식 문서 링크 |

설정은 `../config/media_sources.yaml`에서 로드한다.

---

## fetcher.py

### fetch_docs_for_media(media_key) -> (str, bool)

```python
doc_text, fetch_failed = fetch_docs_for_media("naver_analytics")
doc_text, fetch_failed = fetch_docs_for_media("kakao_pixel")
```

- `fetch_failed=True` → 내장 LLM 지식으로 폴백 필요 (호출 측 책임)
- `fetch_failed=False` → `doc_text`를 LLM 프롬프트에 주입

반환되는 `doc_text`는 최대 20,000자로 잘린다.

### fetch_url(url) -> str

- 불필요한 태그(`script`, `style`, `nav`, `footer`, `header`) 제거 후 텍스트 추출
- 실패 시 빈 문자열 반환 (예외 전파 없음)
- `User-Agent`: `GTM-AI-Agent/1.0`

---

## 태그 유형별 문서 처리 방식

| 태그 유형 | 출처 | 비고 |
|----------|------|------|
| GA4 | LLM 내장 지식 | TODO: 공식 문서 fetch로 통일 예정 |
| Naver Analytics | 실시간 fetch | `media_sources.yaml` → `naver_analytics` |
| Kakao Pixel | 실시간 fetch | `media_sources.yaml` → `kakao_pixel` |

GA4도 GTM 공식 문서를 fetch해 모든 vendor를 동일하게 처리하는 방향으로 통일 예정.
(`config/media_sources.yaml`에 GA4 URL 추가 + `planning.py` 분기 제거)

---

## 새 매체 추가 방법

1. `config/media_sources.yaml`에 항목 추가
2. `planning.py`의 fetch 분기에 매체 키 추가
3. 필요 시 `fetcher.py`에 매체별 파싱 커스터마이징 추가

코드 수정 없이 `media_sources.yaml`만 편집해도 기존 매체의 URL 변경이 가능하다.
