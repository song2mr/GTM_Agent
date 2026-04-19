# agent/canplan CLAUDE.md

CanPlan(Canonical Plan, `version: "canplan/1"`)는 Planning LLM이 낸 초안(`draft_plan`)을
실제 GTM API를 때리기 전에 통과시키는 **단일 불변 표현**이다.
설계 근거는 루트 `docs/VARIABLE_PIPELINE_REDESIGN.md` (특히 §4.5 / §7 / §8 / §16).

---

## 파일 구성

| 파일 | 역할 |
|------|------|
| `schema.py` | CanPlan 상수·enum·`NormalizeIssue` dataclass, `canplan_json_schema()` |
| `evidence.py` | `build_evidence_pack(state)`, DL health 판정, URL 패턴 머지, 헬퍼 |
| `normalize.py` | `normalize_draft_plan(...)`, 참조·정책 검증, 폴백 체인 강제, `canplan_hash`, `summarize_issues` |
| `cjs_templates.py` | **등록된 CJS 템플릿만** 허용(자유 JS 금지) + `render_template(id, args)` |
| `__init__.py` | 상위 모듈용 공개 심볼 재노출 |

---

## CanPlan 구조 (요약)

```json
{
  "version": "canplan/1",
  "scope": {
    "tag_type": "GA4",
    "allowed_events": ["view_item", "add_to_cart", ...],
    "ga4_measurement_id": "G-XXXXXXX"
  },
  "variables": [
    { "name": "DLV - ecommerce.value", "kind": "datalayer",
      "params": {"path": "ecommerce.value"} },
    { "name": "CJS - items", "kind": "cjs_template",
      "params": {"template_id": "items_from_jsonld", "args": {...}} }
  ],
  "triggers": [
    { "name": "CE - view_item", "kind": "custom_event",
      "match_event": "view_item", "filters": [...] }
  ],
  "tags": [
    { "name": "GA4 - view_item", "event_name": "view_item",
      "firing_trigger_names": ["CE - view_item"],
      "event_parameters": [...] }
  ],
  "evidence": { "captured_events": 3, "candidate_fields": [...], ... }
}
```

- `VARIABLE_KINDS`: `datalayer`, `dom_id`, `dom_selector`, `cjs_template`, `json_ld_path`, `constant`, `builtin`
- `TRIGGER_KINDS`: `custom_event`, `click`, `pageview`, `dom_ready`, `window_loaded`, `history_change`, `form_submit`, `element_visibility`
- `TRIGGER_OPS`: equals/contains/starts_with/ends_with/matches_regex + 각각의 `not_` 변형 — **`in_set` 없음**.

---

## normalize.py — `normalize_draft_plan(draft, *, allowed_events, ga4_measurement_id, evidence_pack)`

DraftPlan(LLM 초안 또는 레거시 plan) → `(canplan, issues)` 반환.
예외를 던지지 않고 항상 튜플을 반환한다. `issues`는 직접 list of dict(`NormalizeIssue.to_dict()`).

### 처리 순서
1. **레거시 변환**: 입력이 이미 `canplan/1`이면 그대로, 아니면 `variables/triggers/tags`를 `_to_canplan_*`로 정규화.
   - `_LEGACY_VARIABLE_KIND` (`"v"→datalayer` 등), `_LEGACY_TRIGGER_KIND` (`"customEvent"→custom_event` 등) 매핑.
2. **참조 무결성** (`_validate_refs`) — 변수/트리거 이름 충돌·미정의 참조(`REF_NOT_FOUND`), CJS 미등록 `template_id`(`TEMPLATE_UNKNOWN`), `in_set` 사용(`POLICY_VIOLATION`) 등.
3. **소스 폴백 체인** (`_validate_source_fallback`) — EvidencePack의 healthy DL 경로가 있는데 Plan이 DOM/JSON-LD/CJS를 선택하면 `DL_HEALTH_IGNORED` (`retryable=True`).
4. **트리거 폴백** (`_validate_trigger_fallback`) — 로드형 이벤트(`_LOAD_TIME_EVENTS`)에서 DL 미발화 + `url_patterns` 존재인데 custom_event 트리거만 있으면 `POLICY_VIOLATION` 으로 pageview 요구.
5. `evidence_pack` 요약을 `canplan.evidence`에 박는다(captured_events 수, candidate 필드, URL pattern 출처).

### 주요 이슈 코드

| code | severity | 의미 |
|------|----------|------|
| `SCHEMA_VIOLATION` | error | 필수 필드 누락·타입 어긋남 |
| `REF_NOT_FOUND` | error | 존재하지 않는 변수/트리거 참조 |
| `MISSING_REQUIRED_PARAM` | error | 변수/트리거의 필수 파라미터 누락 |
| `POLICY_VIOLATION` | error | 자유 JS·`in_set`·트리거 폴백 불일치 등 |
| `TEMPLATE_UNKNOWN` | error | `cjs_templates.REGISTERED_TEMPLATES`에 없는 template_id |
| `TYPE_MISMATCH` | error | 경로/값 타입 불일치 |
| `DL_HEALTH_IGNORED` | error(retryable) | healthy DL 경로 무시 — LLM 재시도 가치 있음 |

### 헬퍼

```python
canplan_hash(canplan) -> str          # JSON 정렬 직렬화 → sha256
summarize_issues(issues) -> dict      # {error_count, warning_count, error_codes, retryable_hints}
```

`canplan_hash`는 UI(`HitlScreen`)·Reporter·GTM API 호출 로그에 동일 값이 찍혀 **같은 plan인지 한눈에 대조**할 수 있게 한다.

---

## evidence.py — `build_evidence_pack(state) -> dict`

`captured_events` / `dom_selectors` / `selector_validation` / `json_ld_data` / `site_url_patterns` /
`exploration_failures` / `page_type` 등을 단일 dict로 번들링해 Planning LLM에 주입한다.

### DL Health 판정

- GA4 공식 필드(`_FIELD_EXPECT`: items / value / price / currency / quantity / item_id 등)에 대해
  `_classify_value(expect, value)` 가 `(healthy|unhealthy|unknown, reason)`을 반환.
- 중첩 배열도 평탄화: `ecommerce.items[0].item_id` 같은 경로까지 내려가서 샘플 수집(리스트는 **첫 원소**가 동일 스키마라는 가정 하에 `[0]` 경로만 생성).
- `paths_health[path] = {"health", "reason", "samples"}`로 반환.

### URL 패턴 병합 (observed > seed)

- `_pick_url_patterns(page_type, target_url)` — 현재 페이지 타입·호스트에서 뽑은 seed regex.
- `_merge_url_patterns(observed, seed)` — Active Explorer가 실제 방문한 URL을 `_url_to_observed_pattern`로 canonical regex화한 것이 **seed보다 우선**. 출처는 `url_pattern_sources = {key: "observed"|"seed"}` 로 남긴다.

### 반환 구조 (요약)

```python
{
  "request": { user_request, selected_events, tag_type, ga4_measurement_id },
  "site":    { base_url, spa, page_types_seen, url_patterns, url_pattern_sources },
  "datalayer": { present, pushes_sample, paths_seen, paths_health },
  "dom":     { selectors: {field: {selector, attribute, validated_value}}, click_triggers },
  "json_ld": { present, mappings },
  "events":  [ {event, surfaces: [...], failures: [...]} ],
  "candidate_sources_per_field": { "items": [...], "price": [...], ... },
}
```

### 헬퍼

```python
healthy_dl_fields(evidence_pack) -> dict[str, str]   # {ga4_field: 최우선 healthy DL 경로}
fired_events(evidence_pack)       -> set[str]        # 실제 DL로 발화된 이벤트명 집합
```

Planning은 이 두 함수를 통해 "이 필드는 DL에서 얻어야 한다"·"이 이벤트는 이미 fire된다"를 판단한다.

---

## cjs_templates.py — 허용 목록 + 렌더러

`REGISTERED_TEMPLATES` 에 있는 `template_id`만 CanPlan `cjs_template` 변수로 사용 가능.
정규화는 미등록 ID를 `TEMPLATE_UNKNOWN`으로, 자유 JS(`javascript` 인자 직접 주입)를 `POLICY_VIOLATION`으로 반려한다.

| template_id | 용도 |
|-------------|------|
| `attr_from_selector` | CSS selector + attribute(또는 `textContent`)에서 값 추출 |
| `text_to_number` | `"₩12,000"` 같은 텍스트 → 숫자 파싱 |
| `json_ld_value` | JSON-LD 단일 경로에서 값 읽기 |
| `items_from_jsonld` | GA4 `items[]`를 JSON-LD `offers`/`isVariantOf`로부터 합성 |
| `items_from_dom` | PLP/카트 카드 반복에서 `items[]` 배열 합성 (GA4 필드별 {selector, attribute} 매핑) |
| `build_single_item` | 단일 상품(PDP 등) → `items[0]` 객체 |
| `meta_tag_value` | `<meta name|property="...">` 값 |
| `cookie_value` | `document.cookie`에서 키로 값 추출 |

`render_template(template_id, args)` 는 에러 시 **`return undefined;`를 반환하는 안전 함수**를 낸다
— GTM Preview에서 값 없음으로 보일지언정 Tag를 터뜨리지 않는다.

새 템플릿은:
1. `REGISTERED_TEMPLATES` 에 ID 추가.
2. `render_template`의 분기 추가 + `_js_quote`/`_safe_obj_ref` 등 헬퍼 사용.
3. `tests/test_canplan_normalize.py` 에 `cjs_template` 사용 케이스 추가.

---

## STRICT_CANPLAN 토글

- `STRICT_CANPLAN=1` → Planning은 정규화 에러가 남으면 LLM 1회 재시도 후 실패. GTM Creation은 무조건 `spec_builder` 경로. 레거시 plan 거부.
- `STRICT_CANPLAN=0` (기본) → 정규화 경고만 노출하고 `plan`(레거시) 경로로 폴백 가능. `gtm_creation._reject_in_set_in_legacy` 등 최소 방어선은 유지.

전환 상태는 `docs/VARIABLE_PIPELINE_REDESIGN.md` §16 체크리스트에서 추적한다.
