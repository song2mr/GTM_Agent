# agent/playbooks CLAUDE.md

이벤트별 **탐색 실행 계약(Playbook)**. Journey Planner가 이 계약을 `state["exploration_plan"]`에
실어 Active Explorer / LLM Navigator에 전달한다.
설계 근거: `docs/VARIABLE_PIPELINE_REDESIGN.md` §6.5.1 ~ §6.5.2.

---

## 파일 구성

| 파일 | 역할 |
|------|------|
| `ga4_ecommerce.yaml` | GA4 이커머스 12개 이벤트(`page_view`, `view_item_list`, `select_item`, `view_item`, `add_to_wishlist`, `add_to_cart`, `view_cart`, `remove_from_cart`, `begin_checkout`, `add_shipping_info`, `add_payment_info`, `view_promotion`) |
| `loader.py` | YAML 로드 + 기본값 병합 + `exploration_plan` 빌더 |
| `__init__.py` | `build_exploration_plan`, `load_ga4_playbooks`, `playbook_for_event` 재노출 |

---

## Playbook 스키마

```yaml
events:
  view_item_list:
    surface_goal: plp                   # 진입 목표 page_type (없으면 "current")
    entry_hints:
      url_patterns:                     # 관측/이동 힌트 regex 또는 substring
        - "^/category/[^/]+/?$"
      click_hints:                      # LLM Navigator가 선호할 셀렉터·텍스트
        - "a[href*='category']"
      from_surfaces: ["home", "plp"]    # 어느 표면에서 진입 가능한가
    observation:
      datalayer_events: ["view_item_list"]  # 캡처 대상 GA4 이벤트명
      required_fields: ["item_name"]    # DL/DOM/JSON-LD에서 반드시 확보
      optional_fields: ["item_id", "item_list_name"]
      settle_ms: 1200                   # 진입 후 DL 발화 대기(ms)
    trigger_fallbacks:
      - custom_event                    # CanPlan이 허용하는 트리거 우선순위
      - pageview
      - history_change
```

### 필드별 소비 지점

| 필드 | 사용 노드/모듈 | 의미 |
|------|----------------|------|
| `surface_goal` | Node 3 `active_explorer` | 목표 표면 미도달 시 `exploration_failures`에 `surface_unreached` 기록 |
| `entry_hints.url_patterns` | Node 3, `evidence.build_evidence_pack` | 관측/이동 후보 + EvidencePack seed URL 패턴(observed가 없을 때 폴백) |
| `entry_hints.click_hints` | `browser/navigator.py`, `cart_addition_navigator`, `begin_checkout_navigator` | LLM이 선호할 클릭 후보 |
| `entry_hints.from_surfaces` | Journey Planner | 진입 경로 판단 |
| `observation.datalayer_events` | Node 3, `browser/listener.py` | 캡처 대상 이름 집합 |
| `observation.required_fields` / `optional_fields` | Node 3 / Planning | DL/DOM/JSON-LD에서 확보해야 할 필드 우선순위 |
| `observation.settle_ms` | Node 3 / Navigator | 진입 후 DL push 대기 상한 |
| `trigger_fallbacks` | `canplan/normalize.py` | 로드형 이벤트 + DL 미발화일 때 허용되는 트리거 kind 순서 |

---

## loader.py

```python
load_ga4_playbooks() -> dict[str, dict]      # {event_name: normalized_playbook}
playbook_for_event(event, registry=None) -> dict
build_exploration_plan(events: list[str]) -> list[{event, playbook}]
```

### 기본값 (fallback) 정책

- YAML에 **정의되지 않은 이벤트**는 `_empty_playbook(event)`로 채운다.
  - `surface_goal: "unknown"`
  - `entry_hints` 전부 빈 리스트
  - `observation.datalayer_events = [event]` (커스텀 이벤트명을 그대로 seed로 사용)
  - `trigger_fallbacks: [custom_event, click, pageview]`
- YAML의 이벤트에 일부 필드가 누락돼도 `_copy_playbook`이 전 키를 채워 **state에 항상 동일 스키마**가 들어간다.
- 반환값은 항상 **딥카피**에 준하는 새 dict — 호출자가 수정해도 레지스트리에 영향 없음.

---

## Journey Planner ↔ Active Explorer 계약

1. Node 2 `journey_planner`는 `_normalize_and_sort_exploration_queue`로 정리된 이벤트 큐의 각 항목에
   `build_exploration_plan(events)`를 적용해 `state["exploration_plan"]`에 저장.
2. Node 3 `active_explorer`는 현재 이벤트의 playbook에서
   - `entry_hints` → Navigator 프롬프트와 URL 이동 후보,
   - `surface_goal` → 도달 실패 시 `exploration_failures` 기록,
   - `observation.settle_ms` → 이벤트 fire 대기 상한,
   - `observation.required_fields` → DL/DOM 확보 실패 시 failure 사유,
   를 읽는다.
3. Node 5 `planning`은 `evidence_pack` + playbook의 `trigger_fallbacks`를 참고하고,
   `canplan/normalize.py`의 `_validate_trigger_fallback`가 **로드형 이벤트에서 DL 미발화 + URL 패턴 있음 → pageview 우선**을 강제한다.

---

## 새 이벤트 / 매체 추가 순서

1. `ga4_ecommerce.yaml`에 `events.{name}` 블록 추가 (위 스키마 엄수).
2. 필요하면 `browser/navigator.py` `EVENT_CAPTURE_GUIDE`, `_strategy_kind`에 이벤트명 추가.
3. 특수 표면(cart_addition, begin_checkout) 대상이면 해당 Navigator 파일(`cart_addition_navigator.py` 등)에
   클릭 우선순위/정착 시간을 맞춘다.
4. Naver/Kakao 등 **매체별 playbook**을 분리하고 싶으면 `{vendor}_{domain}.yaml`로 새 파일을 만들고
   `loader._PLAYBOOK_FILE` / `load_ga4_playbooks`를 벤더별로 확장한다(현재는 GA4 하나만 로드).
