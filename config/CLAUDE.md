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

탐색 노드에서 LLM이 시도할 수 있는 **최대 스텝 수**를 조절한다.

- `navigator.max_llm_steps`       → Node 3 일반 `LLMNavigator` (기본 6)
- `cart_addition.max_llm_steps`   → Node 3.25 `CartAdditionNavigator` (기본 8)
- `begin_checkout.max_llm_steps`  → Node 3.5 `BeginCheckoutNavigator` (기본 8)

로더: `config/exploration_limits_loader.py` —
`read_exploration_limits`, `navigator_max_llm_steps`,
`cart_addition_max_llm_steps`, `begin_checkout_max_llm_steps`.

YAML 파일이 없거나 키가 빠지면 위 기본값이 적용된다. 일반 `navigator.py`의 `MAX_STEPS` 상수도 이 YAML에서 로드하므로, 코드 수정 없이 상한을 조절할 수 있다.

---

## llm_models.yaml

에이전트·Navigator **구역(zone)별 OpenAI 채팅 모델 ID**를 지정한다.

- `default` — 구역 키가 없거나 비어 있을 때 사용 (없으면 코드 기본 `gpt-5.4`)
- `page_classifier`, `structure_analyzer`, `planning`, `journey_planner`
- `navigator`, `cart_addition_navigator`, `begin_checkout_navigator`

로더: `config/llm_models_loader.py` — `read_llm_models`, `llm_model(zone)`, `reset_llm_models_cache` (테스트용).

OpenAI 문서 기준으로 복잡도에 맞게 기본 예시가 잡혀 있다(플래그십 `gpt-5.4`, 저비용 구간에 `gpt-5.4-mini` / `gpt-5.4-nano` 등). 계정에서 사용 가능한 모델 ID로만 바꾸면 된다.
