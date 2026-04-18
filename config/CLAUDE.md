# config CLAUDE.md

에이전트 동작에 필요한 외부 설정 파일.

---

## media_sources.yaml

매체별 문서 URL 목록. `docs/fetcher.py`가 이 파일을 읽어 문서를 fetch한다.

### 포맷

```yaml
{media_key}:
  name: "{표시 이름}"
  urls:
    - "{공식 문서 URL 1}"
    - "{공식 문서 URL 2}"   # 여러 URL 조합 가능
```

### 현재 정의된 매체

```yaml
kakao_pixel:
  name: "Kakao Pixel"
  urls:
    - "https://developers.kakao.com/docs/latest/ko/pixel/devguide"

naver_analytics:
  name: "Naver Analytics"
  urls:
    - "https://naver.github.io/tagtool/"
```

### 새 매체 추가

1. `media_sources.yaml`에 항목 추가
2. `planning.py` fetch 분기에 `media_key` 추가
3. `docs/CLAUDE.md` 매체 목록 업데이트

URL이 변경되면 `media_sources.yaml`만 수정하면 된다 — 코드 변경 불필요.
