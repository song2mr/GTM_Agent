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

---

## exploration_limits.yaml

탐색 **전용 노드**에서 LLM이 시도할 수 있는 **최대 스텝 수** 등을 조절한다.

- `cart_addition.max_llm_steps` → Node 3.25 `CartAdditionNavigator`
- `begin_checkout.max_llm_steps` → Node 3.5 `BeginCheckoutNavigator`

로더: `config/exploration_limits_loader.py` (`read_exploration_limits`, `cart_addition_max_llm_steps`, `begin_checkout_max_llm_steps`).

YAML 파일이 없으면 기본값 8이 적용된다.
