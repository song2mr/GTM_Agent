# GTM 설계 파이프라인 재설계 계획

> **한 줄 요약**  
> **“GTM API 호출 직전에, 트리거·변수·태그가 완전히 정리되고 검증된 단일 정규형(Canonical Plan)이 존재한다”**를 시스템의 불변식(invariant)으로 만든다.  
> LLM은 **정리의 재료와 판단**을 제공하고, 그 결과는 **정규형 스키마**로 고정되어 **검증을 통과한 뒤에만** GTM API로 간다.

---

## 1. 지금의 문제 (진단)

### 1.1 “정리된 상태”가 파이프라인에 존재하지 않음

```
LLM(Planning) ─▶ {variables, triggers, tags} JSON(초안)
                        │
                        ▼
           gtm_creation에서 뒤늦게 보정
              - customEventFilter.arg0 강제 {{_event}}
              - type "d" + CSS selector → "jsm" 강제 변환
              - _fix_plan : 트리거/태그 이름 매핑·누락 보완
                        │
                        ▼
                    GTM API 호출
```

즉 **API 호출 직전 “검증된 단일 표현”이 없고**, LLM JSON이 그 역할을 겸하다가 `gtm_creation`이 **런타임에 수선**한다. 결과:

- 동일 입력에 **매 실행 결과가 살짝씩 다름**
- 실패 원인이 **프롬프트/보정/API 3층에 분산**돼 디버깅 어려움
- HITL에 보여주는 JSON이 곧 **실제로 API에 가는 JSON이 아님** (보정 뒤가 다름)

### 1.2 LLM이 “판단하기 위한 정보”가 파편적

LLM이 보는 것은 있지만 **한 장으로 정리되어 있지 않다.**

| 필요한 판단 | 지금 주어지는 정보 | 부족한 점 |
|-------------|--------------------|-----------|
| 이 이벤트의 트리거 종류(CE / Click / Page View+Path / History) | `captured_events[].source`, `click_triggers`, `page_type` | **URL 패턴 후보, SPA 여부, DL 발화 여부**가 이벤트 단위로 붙어 있지 않음 |
| 각 파라미터를 DL/DOM/JSON-LD/CJS/Constant 중 어디서 뽑을지 | `dom_selectors`, `selector_validation`, `json_ld_data`, 이벤트 payload | 같은 필드에 대해 **여러 소스를 한 표로 비교**한 자료가 없음 |
| 실패 사유·불가 판정 | 로그에 분산 | **구조화된 evidence**로 LLM에 전달되지 않음 |
| PDP/PLP/Cart 표면 확인 | `page_type`(한 번 분류) | 탐색 중 표면이 바뀌어도 **이벤트별 표면 스냅샷**이 없음 |

### 1.3 LLM 출력 스키마가 “느슨”함

Planning LLM이 만드는 JSON은 자유도가 커서:

- `type: "js"` vs `"jsm"` 혼용
- `customEventFilter.arg0`에 DLV 참조가 들어오기도
- `firing_trigger_names`에 존재하지 않는 이름 등장
- CJS 본문을 LLM이 **직접 작성** → 인젝션/안전성 리뷰가 어렵다

이걸 `_fix_plan`/`_build_variable`이 사후 수리하는 지금 구조는 **“LLM이 틀릴 권리”를 설계상 허용**하는 꼴.

---

## 2. 현재 가능 범위 vs 목표 범위 (대조)

> **스코프 선언**  
> **본 재설계의 1차 범위는 GA4(웹) 태그 타입에 한정**한다. `TagSpec.kind`는 `ga4_event`만 지원.  
> Naver Wcs / Meta Pixel / Criteo 등 다른 태그 타입은 **후속 PR**에서 동일 골격(CanPlan + 레지스트리)을 따라 추가한다 (§12-4).  
> 따라서 아래 표·이후 섹션의 모든 예시는 GA4 기준.

| 기능 | 지금 | 목표(구현 후) |
|------|------|---------------|
| DL 있음 → **DLV + Custom Event 트리거** | O (프롬프트 규칙) | O + **정규화 규칙**으로 강제 |
| DL 없음 → **Click 트리거** (버튼 기반 이벤트) | O (프롬프트 규칙) | O, `click_triggers` 증거 부착 |
| DL 없음 → **Page View + Page Path 트리거** (로드형 이벤트) | **거의 없음** | **1급 후보**. `url_patterns`로 조건 자동 제시 |
| SPA → **History Change 트리거** | 없음 | `site.spa=true`일 때 선택지로 제시 |
| JSON-LD에서 변수 자동 추출 | O (full / partial) | O + `candidate_sources_per_field`에 병렬 제시 |
| DOM selector 검증·DOM 변수 자동 생성 | O | O, `dom_selector` kind를 **정규화가 `jsm` 템플릿**으로 확장 |
| 클릭 대상 자동 탐색 (한국 쇼핑몰 패턴 포함) | O | O + 이벤트 단위 증거 부착 |
| **이벤트별 탐색 플레이북** (view_item→PDP, view_item_list→PLP 등) | △ (`add_to_cart`·`begin_checkout`만 전용) | **전 이벤트 Playbook 선언**(§6.5) |
| `items` 배열 **DOM에서 조립** | △ (LLM이 CJS 자유 작성) | **CJS 템플릿 레지스트리**로 안전 조립 (§8) |
| 동일 필드에 대한 **여러 소스 비교표** | X | EvidencePack `candidate_sources_per_field` (§6) |
| 이벤트별 **소스 폴백 체인** 명시 | 암묵적/부분적 | **명시적 체인**(§4.5), 검증 실패 시 다음 후보 |
| `datalayer_status=full`일 때 DOM/JSON-LD 재료 확보 | 스킵 | **얕은 수집 유지** (재료 고갈 방지) |

이 표의 “목표” 열 **전부를 구현 범위**로 잡는다.

---

## 3. 설계 원칙

1. **단일 정규형(Canonical Plan, “CanPlan”)**이 존재한다.  
   LLM → CanPlan → (검증) → GTM API. CanPlan을 거치지 않은 것은 **API로 갈 수 없다.**
2. **LLM은 “판단자”지 “조립자”가 아니다.**  
   이름·타입·파라미터 바인딩을 LLM이 정하되, **문법·API 규칙 위반은 정규화 단계에서 거부**된다.  
   자바스크립트 본문 같은 위험 생성물은 **템플릿 + LLM 파라미터**로 대체.
3. **정보는 번들로 간다.**  
   LLM이 판단하려면 **표면(어떤 화면) + 데이터 출처 증거 + URL 패턴 + 실패 사유**가 **이벤트별로 한 번에** 주어진다.
4. **HITL에 보여주는 것과 API에 보내는 것이 동일**하다.  
   UI/보고서는 **CanPlan**을 렌더링하고, 승인된 CanPlan이 그대로 빌더로 간다.
5. **소스 폴백 체인은 코드에 박는다.**  
   “DL 있으면 DL 우선, 없으면 HTML 기반으로 알아서”라는 정책을 **프롬프트 힌트**가 아니라 **정규화 규칙**으로 강제한다 (§4.5).

---

## 4. 파이프라인 (After)

```
[Discovery]         [Context Bundle]           [LLM Planning]         [Normalize+Validate]      [Build+Dispatch]
─────────────       ──────────────────         ───────────────        ─────────────────────     ─────────────────
Explorer ──▶ captured_events(+evidence)
Structure ─▶ dom/jsonld/click candidates     ─▶  EvidencePack
Crawler  ──▶ url patterns, spa flags                │
                                                   ▼
                                         LLM이 Draft Plan 작성(JSON Schema 강제)
                                                   │
                                                   ▼
                                            normalize(DraftPlan) → CanPlan
                                                   │        (스키마 검증 + 참조 검증)
                                                   ▼
                                           HITL(CanPlan 그대로 표시)
                                                   │
                                                   ▼
                                           spec_builder(CanPlan) → GTM payload
                                                   │
                                                   ▼
                                             gtm_creation(API 호출)
```

정보 흐름의 불변식:

- **EvidencePack**은 “LLM이 판단에 필요한 모든 근거의 패키지”. (§6)
- **DraftPlan**은 LLM 출력(JSON Schema로 제약, 하지만 아직 “신뢰 못 함”).
- **CanPlan**은 정규화 + 교차검증 통과 후 생긴 **1급 데이터**. 이 순간 이후로는 **아무도 수선하지 않는다**.
- `gtm_creation`은 **빌더/디스패처**로 축소 — 보정 로직 제거(또는 assert로 강등).

### 4.5 소스 폴백 체인 (코드에 박는 정책)

이 시스템에서 가장 중요한 규칙. **“dataLayer가 있으면 그걸로, 없으면 HTML 기반으로 알아서”**를 코드가 보장하도록 만든다.

#### 4.5.1 **변수**의 필드 소스 폴백 (Top-down)

하나의 GA4 파라미터(예: `items`, `item_id`, `value`, `currency`)에 대해 후보를 아래 순서로 시도한다. 중간에 **검증**(값이 실제로 나오는지)을 통과한 첫 후보가 채택된다.

```
1. datalayer (healthy) — EvidencePack.datalayer.paths_seen 에 해당 경로가 있고,
                         샘플 값이 타입/스키마 검증을 통과(§4.5.2)
2. json_ld_path        — EvidencePack.json_ld.mappings 에 매핑이 있고 값이 실재
3. dom_id              — dom_selectors 중 selector가 '#id' 형태
4. dom_selector        — validated_value 가 있는 selector가 존재 (정규화가 jsm으로 확장)
5. cjs_template        — §8 레지스트리의 사전 등록 템플릿으로 조립 가능
6. constant            — GA4 currency=KRW 같은 합리적 기본값
7. DROP + 리포트       — 어디서도 못 뽑으면 해당 event_parameter는 설계에서 제거, evidence에 사유 기록
```

LLM은 위 후보 목록을 **보고 선택**한다(§6의 `candidate_sources_per_field`). **체인 자체는 코드가 보장**한다:

- 정규화는 TagSpec의 `event_parameters[*].value_ref`가 **실존하는 VariableSpec**을 가리키는지 확인.
- LLM이 상위 후보를 무시하고 하위를 골랐다면 **정규화가 경고**를 남기고, 정책상 **DL이 “건전(healthy)”하게 존재하는 필드를 무시하는 선택은 거부**(재시도 1회).

#### 4.5.2 DL의 “존재(present)” vs “건전(healthy)”

DL이 **페이로드 자체가 깨진** 사이트에서 “DL 존재 = 최우선”은 오히려 독이 된다. 따라서 **건전성** 개념을 도입한다.

**DL 경로가 건전하다의 판정**(모두 만족):
1. **존재**: `paths_seen`에 경로가 있음.
2. **샘플 수**: 최근 샘플 ≥ 1건 (같은 이벤트에서 해당 경로가 비어있지 않은 적 있음).
3. **타입 일치**: 해당 필드의 기대 타입에 부합.  
   - `items` → 비어있지 않은 **배열**  
   - `value` → **숫자** 또는 **숫자로 파싱 가능한 문자열**  
   - `currency` → ISO-4217 3자리 **문자열**  
   - `item_id` / `item_name` → 비어있지 않은 **문자열**
4. **무의미 값 아님**: `"undefined"`, `""`, `null`, `0`(가격 필드 기준)은 실패로 간주.

**불건전(unhealthy) DL 경로는 체인의 `1` 단계에서 제외**되고, LLM에게 제시되는 `candidate_sources_per_field`에서도 **“kind: datalayer, health: unhealthy, reason: ...”** 로 표시해 LLM이 회피할 수 있게 한다.

#### 4.5.3 **트리거**의 종류 폴백 (Per-event)

이벤트마다 아래 순서로 트리거 종류를 선택한다. 선택 결과는 `TriggerSpec.kind`로 들어간다.

```
1. custom_event (CE)
   조건: EvidencePack.events[e].surfaces[*].datalayer.fired == true
   → TriggerSpec.kind=custom_event, match_event=이벤트명

2. click
   조건: EvidencePack.dom.click_triggers[e] 에 유효 selector
   → TriggerSpec.kind=click + {{Click Element}}/{{Page Path}} 조건

3. pageview | dom_ready | window_loaded  (로드형 이벤트의 대체)
   조건: 이벤트가 "페이지 로드 시점" 의미 (view_item/view_item_list/view_promotion/page_view 등)
        AND EvidencePack.site.url_patterns 에 해당 표면 패턴 존재
   → TriggerSpec.kind=pageview, conditions=[{{Page Path}} matches_regex <패턴>]
   (SPA면 history_change, 비-SPA면 pageview)

4. history_change
   조건: EvidencePack.site.spa == true AND 위 어느 것에도 안 걸림
   → 라우트 변경 기반 트리거

5. DROP + 리포트
   조건: 어디서도 근거 없음 → 해당 이벤트는 태그/트리거 생성 스킵, 사유 기록.
```

핵심: **“무 DL `view_item` → Page View + Page Path”가 1급 경로**가 되고, **Click은 “버튼 기반” 이벤트(add_to_cart 등)**의 주 경로.

#### 4.5.4 “판단의 이원성”

- **LLM**: 후보 중 **어느 소스가 의미상 맞는지** 선택 (예: `item_id`는 DL의 `ecommerce.items[0].item_id`가 맞다, 혹은 `[data-pid]` DOM selector가 맞다).
- **코드(정규화)**: **체인의 순서·검증·거부**를 강제. LLM이 근거 없는 선택을 하면 재시도, 그래도 실패면 HITL 에러.

---

## 5. CanPlan 스키마 (핵심)

모든 식별자 참조는 **이름(name) 기반**으로만. ID는 GTM API 호출 결과로만 채워짐.

### 5.1 최상위

```jsonc
{
  "version": "canplan/1",
  "scope": {
    "tag_type": "GA4",
    "allowed_events": ["view_item", "add_to_cart", "..."],  // selected_events와 1:1
    "ga4_measurement_id": "G-XXXXXXX"
  },
  "variables": [ /* VariableSpec */ ],
  "triggers":  [ /* TriggerSpec  */ ],
  "tags":      [ /* TagSpec      */ ],
  "evidence":  { /* 판단 근거 요약 (리포트용, API 미사용) */ }
}
```

### 5.2 VariableSpec

```jsonc
{
  "name": "DLV - ecommerce.items",
  "kind": "datalayer" | "dom_id" | "dom_selector" | "cjs_template" | "json_ld_path" | "constant" | "builtin",
  "params": {
    // kind별 필드. 아래는 예시:
    // datalayer:
    "path": "ecommerce.items", "version": 2
    // dom_id:
    // "element_id": "product-price", "attribute": "textContent"
    // dom_selector (→ jsm로 빌드됨):
    // "selector": "[data-pid]", "attribute": "data-pid"
    // cjs_template:
    // "template_id": "extract_items_from_jsonld", "args": {...}
    // json_ld_path:
    // "path": "offers.price"
    // constant:
    // "value": "KRW"
    // builtin:
    // "name": "Page Path"
  },
  "cast": "auto" | "string" | "number" | "boolean" | null,
  "notes": "..."                // 자유 서술(선택)
}
```

핵심 규칙:

- `kind=cjs_template`: **자유 JS 본문 금지**. 사전 등록된 템플릿(§8)과 인자만 허용.
- `kind=dom_selector`: 정규화 단계에서 실제 GTM `jsm` 변수로 확장(템플릿 JS 사용).
- `kind=dom_id`: `attribute`가 없으면 `textContent` 기본.
- **이름 충돌·미참조 변수**는 정규화에서 오류.

### 5.3 TriggerSpec

```jsonc
{
  "name": "CE - view_item",
  "kind": "custom_event" | "click" | "pageview" | "dom_ready" | "window_loaded" | "history_change" | "form_submit" | "element_visibility",
  "condition_logic": "all" | "any", // 기본값 all
  "conditions": [
    // 모든 조건은 (lhs_variable, op, rhs) 3-튜플.
    // condition_logic="all"이면 AND, "any"이면 OR.
    // lhs는 반드시 "변수 참조" — builtin(Page Path/URL/Hostname) 또는 위 VariableSpec 중 하나.
    { "lhs": "{{Page Path}}", "op": "matches_regex", "rhs": "^/product/[^/]+/?$" }
  ],
  "match_event": "view_item"   // kind=custom_event일 때만
}
```

핵심 규칙:

- **op 화이트리스트**: `equals`, `contains`, `starts_with`, `ends_with`, `matches_regex`, `not_*`.
- `in_set`은 **`canplan/1`에서 비지원**. 필요하면 `condition_logic="any"` + `equals` 다중 조건으로 표현.
- `kind=custom_event`: `match_event`는 필수, 정규화에서 `customEventFilter(arg0={{_event}}, arg1=match_event)`로 직렬화.
- `kind=click`: `conditions`에는 `{{Click Element}}`/`{{Click Classes}}`/`{{Page Path}}` 등만.
- `kind=pageview` (또는 `dom_ready`/`window_loaded`): `conditions`는 0개 이상 — **무 DL `view_item` 같은 케이스**는 여기서 처리된다.
- `kind=history_change`: SPA용. Structure/Explorer가 `spa=true`로 표시한 사이트에서만 허용.
- `kind=form_submit`, `kind=element_visibility`는 Playbook 표와 정합을 맞추기 위해 **스키마에 선반영**한다. 구현은 Phase 4에서 활성화(Phase 1~3에서는 CE/Click/PageView/History 중심).

### 5.4 TagSpec

```jsonc
{
  "name": "GA4 - view_item",
  "kind": "ga4_event",        // 현재 스코프는 GA4에 한정
  "measurement_id": "G-XXXXXXX",
  "event_name": "view_item",
  "event_parameters": [
    { "key": "items",    "value_ref": "{{DLV - ecommerce.items}}" },
    { "key": "value",    "value_ref": "{{DLV - ecommerce.value}}", "cast": "number" },
    { "key": "currency", "value_ref": "{{Const - KRW}}" }
  ],
  "fires_on": ["CE - view_item"]   // TriggerSpec.name만 허용
}
```

핵심 규칙:

- `measurement_id`는 **문자열 리터럴**로 저장한다. (`scope.ga4_measurement_id`와 값 일치 검증)
- `value_ref`는 **반드시 존재하는 VariableSpec(또는 builtin) 이름**이어야 함.
- `fires_on`은 **존재하는 TriggerSpec 이름**이어야 함. 존재하지 않으면 정규화 에러.
- **event_parameters의 key는 이벤트별 스펙 테이블과 교차검증** (GA4 표준 이벤트는 필수 키 체크).

---

## 6. EvidencePack (LLM이 보는 “판단 재료”)

LLM은 DraftPlan을 만들기 전에 **이 번들 하나만** 본다. 흩어진 state 필드를 직접 참조하지 않는다.

```jsonc
{
  "request": {
    "user_request": "...",
    "selected_events": ["view_item", "add_to_cart"],
    "tag_type": "GA4",
    "ga4_measurement_id": "G-..."
  },
  "site": {
    "base_url": "https://shop.example.com/",
    "spa": true | false,
    "page_types_seen": { "home": ["/"], "pdp": ["/product/123"], "plp": ["/category/..."], "cart": ["/cart"] },
    "url_patterns": {       // 탐색 로그에서 추론
      "pdp":  "^/product/[^/]+/?$",
      "plp":  "^/category/[^/]+/?$",
      "cart": "^/cart/?$"
    }
  },
  "datalayer": {
    "present": true,
    "pushes_sample": [ { "event": "view_item", "ecommerce": { "items": [...] } }, ... ],
    "paths_seen": ["ecommerce.items", "ecommerce.value", "ecommerce.currency"]
  },
  "dom": {
    "selectors": { "item_name": { "selector": "...", "attribute": "...", "validated_value": "..." }, ... },
    "click_triggers": { "add_to_cart": "button.add-to-cart" }
  },
  "json_ld": { "present": true, "mappings": { "name": "item_name", "offers.price": "price" } },
  "events": [
    {
      "event": "view_item",
      "surfaces": [
        {
          "url": "https://shop.example.com/product/123",
          "path": "/product/123",
          "matched_pattern": "^/product/[^/]+/?$",
          "datalayer": { "fired": true, "sample": {...}, "source": "datalayer" },
          "dom": { "selectors_resolved": {"item_id": "SKU-1234", "item_name": "..."} },
          "json_ld": { "found": true, "extracted": {...} },
          "notes": "PDP 진입 직후 DL 발화 확인"
        }
      ],
      "failures": [
        { "url": "...", "reason": "snapshot_truncated", "detail": "..." }
      ]
    }
  ],
  "candidate_sources_per_field": {
    // LLM이 한눈에 비교할 수 있도록 같은 필드에 대해 여러 소스 병렬 표시
    "items":    [ {"kind":"datalayer","path":"ecommerce.items"}, {"kind":"cjs_template","template_id":"items_from_jsonld"} ],
    "item_id":  [ {"kind":"datalayer","path":"ecommerce.items[0].item_id"}, {"kind":"dom_selector","selector":"[data-pid]","validated_value":"SKU-1234"}, {"kind":"json_ld_path","path":"sku"} ],
    "value":    [ {"kind":"datalayer","path":"ecommerce.value"}, {"kind":"json_ld_path","path":"offers.price"} ],
    "currency": [ {"kind":"datalayer","path":"ecommerce.currency"}, {"kind":"constant","value":"KRW"} ]
  }
}
```

이 구조의 의미:

- LLM은 **이벤트마다 “어디서 값이 실제로 나왔는지”**를 증거와 함께 본다.
- **URL 패턴**이 이미 추론돼 있으므로 **Page View + Page Path** 트리거를 선택하는 데 근거가 충분하다.
- **후보 소스 병렬표**가 있어서 DL/DOM/JSON-LD/Constant 중 **골라 달기만** 하면 된다.

### 6.5 이벤트별 탐색 플레이북 (Per-Event Playbook)

현재는 `add_to_cart`(Node 3.25)와 `begin_checkout`(Node 3.5)만 **전용 탐색 절차**를 가지고, 나머지는 일반 Active Explorer가 일괄 처리한다. 하지만 이벤트마다 **“어디로 가서 무엇을 관찰해야 하는지”가 다르다** — 이 차이를 명문화하지 않으면 EvidencePack이 빈약해지고 LLM 판단이 흔들린다.

각 이벤트를 **Playbook** 객체로 선언하고, Explorer/Navigator는 이 Playbook을 따른다. Playbook은 “프롬프트 힌트”가 아니라 **실행 계약**이다.

> **권한 경계 (중요)**  
> - **Playbook의 권한** = “어디로 갈지(surface_goal), 무엇을 관찰할지(observation), 어떤 트리거 후보를 열어둘지(trigger_fallbacks)”라는 **탐색·관찰 프로토콜**.  
> - **LLM의 권한** = “Playbook이 관찰해 모은 EvidencePack을 보고, **어떤 소스가 의미상 맞는지** 해석·선택”.  
> 즉 Playbook은 결정적 실행 계약, LLM은 의미 해석자. 두 영역이 섞이지 않아야 재현성·디버깅이 가능하다.

#### 6.5.1 Playbook 스키마

```jsonc
{
  "event": "view_item",
  "surface_goal": "pdp",                       // 진입 목표 표면(page_type)
  "entry_hints": {                             // LLMNavigator/휴리스틱 힌트
    "url_patterns": ["^/product/[^/]+/?$", "/goods/", "/p/"],
    "click_hints":  ["상품 카드", "product card", "a[href*='product']"],
    "from_surfaces": ["plp", "home"]           // 어느 표면에서 진입 가능한가
  },
  "observation": {                             // 캡처·확인할 신호
    "datalayer_events": ["view_item"],
    "required_fields":  ["item_name", "item_id", "price"],
    "optional_fields":  ["currency", "item_brand", "item_category"],
    "settle_ms": 1500                          // 진입 후 DL 발화 대기
  },
  "trigger_fallbacks": ["custom_event", "pageview_pagepath", "history_change"],
  "notes": "PDP 진입 직후에만 발화. 클릭형 아님."
}
```

#### 6.5.2 초기 내장 Playbook (구현 1차 범위)

| 이벤트 | surface_goal | 진입 방식 | 주 관찰 | 트리거 폴백 |
|--------|--------------|-----------|---------|-------------|
| `page_view` | 현재 페이지 | 없음 | 로드 시 DL push | `pageview` |
| `view_item_list` | `plp` | 카테고리/목록 링크 클릭 | DL `view_item_list`, 상품카드 selector | `pageview + path` / `ce` |
| `select_item` | `plp` → 상품카드 클릭 직전 | PLP에서 카드 hover/click 직전 관찰 | DL `select_item`, 클릭 대상 selector | `click` / `ce` |
| `view_item` | `pdp` | PLP 상품 카드 클릭 or 직접 URL 진입 | DL `view_item`, PDP 필드 | `ce` / `pageview + path` |
| `add_to_wishlist` | `pdp` 또는 `plp` | 찜/하트 버튼 클릭 | DL 이벤트 or 버튼 selector | `ce` / `click` |
| `add_to_cart` | `pdp` | 옵션 선택 → 담기 (현행 Node 3.25) | DL `add_to_cart`, 버튼/옵션 | `ce` / `click` |
| `view_cart` | `cart` | 장바구니 페이지 진입 | DL `view_cart`, 카트 요약 | `ce` / `pageview + path` |
| `remove_from_cart` | `cart` | 카트 아이템 삭제 버튼 | DL or 버튼 selector | `ce` / `click` |
| `begin_checkout` | `checkout` | 결제 진입 (현행 Node 3.5) | DL `begin_checkout`, 주문 요약 | `ce` / `pageview + path` |
| `add_shipping_info` | `checkout` | 배송지 입력(더미) | DL `add_shipping_info` | `ce` / `form_submit` |
| `add_payment_info` | `checkout` | 결제수단 선택(더미) | DL `add_payment_info` | `ce` / `form_submit` |
| `view_promotion` | `home`/`plp` | 배너 노출 영역 관찰 | DL or 배너 selector | `ce` / `element_visibility` |

> `purchase`, `refund`는 기존대로 **Manual Capture**(자동 탐색 제외) 유지.  
> `form_submit`/`element_visibility` 폴백은 Playbook에서 힌트로 허용하되, **Phase 1~3 정규화는 경고 후 CE/Click/PageView 대체안을 우선 채택**한다.

#### 6.5.3 Playbook을 쓰는 주체

- **`Journey Planner`(Node 2)**: 각 이벤트에 Playbook을 붙여 **`exploration_queue`의 각 엔트리를 `{event, playbook}`**로 확장.  
- **`LLMNavigator`/전용 Navigator**: Playbook의 `surface_goal`·`entry_hints`를 사용해 **목표 표면까지 이동**. 표면 미달 시 `failures.reason="surface_unreached"`로 기록(드롭 판정에 활용).
- **`Active Explorer`**: Playbook의 `observation`대로 캡처·필드 검증 수행, 결과를 `captured_events[i].evidence`에 고정 포맷으로 남김.
- **`EvidencePack` 합성**: 이벤트 단위 `surfaces/failures`가 Playbook 기준으로 정리되므로, LLM이 **“왜 이 트리거 폴백을 써야 하는지”**를 근거로 판단할 수 있음.
- **`Planning` 프롬프트**: Playbook의 `trigger_fallbacks`를 그대로 제시 → LLM이 **각 이벤트마다 다른 규칙**을 적용.

#### 6.5.4 구현 위치

- `agent/playbooks/` (신설) — 이벤트별 Playbook YAML/JSON 선언.
  - `agent/playbooks/ga4_ecommerce.yaml` 한 파일로 시작.
  - 커스텀 이벤트는 사용자 요청/selected_events 입력 시 **LLM이 Playbook 초안을 제안** → HITL 확인.
- `agent/playbooks/loader.py` — 내장 Playbook 로드 + 커스텀 이벤트 합성.
- Journey Planner가 각 이벤트에 Playbook 주입 → state에 `exploration_plan: [{event, playbook}]` 저장.
- Explorer/Navigator는 `exploration_plan`을 순차 소비.

#### 6.5.5 확장 원칙

1. **이벤트 하나 = Playbook 하나.** 없는 이벤트는 큐에 못 들어간다(기본 Playbook 생성 강제).
2. **현행 전용 노드(3.25 `add_to_cart` / 3.5 `begin_checkout`)는 Playbook의 “특수화 구현”**으로 간주. Playbook이 주도권을 갖고, 노드는 실행 엔진 역할만.
3. **커스텀 이벤트**(예: `naver_wcs_purchase`, `custom_cart_push`)는 **사용자 요청 분석** + **LLM 제안** → HITL 확인 → 세션 Playbook으로 등록.

#### 6.5.6 URL 패턴: seed vs observed 우선순위

`entry_hints.url_patterns`(Playbook seed)와 `EvidencePack.site.url_patterns`(탐색 관측 결과)가 **둘 다 존재할 수 있음.** 정규화·판단 시 아래 규칙을 **코드로 박는다**:

```
priority: observed  >  seed  >  DROP
```

구체적으로:

- **관측값 존재**: Explorer가 실제로 해당 표면(예: PDP)에 도달해 URL을 기록했으면, 해당 관측 기반 정규식이 **최우선**. Playbook seed는 힌트로만 남음.
- **관측값 없음, seed만 존재**: Playbook seed를 사용. 다만 `candidate_sources_per_field`/리포트에는 `source: "seed"` 라벨을 남겨 **신뢰도 낮음**을 LLM/사용자에게 알림.
- **둘 다 없음**: 해당 이벤트의 pageview 폴백(§4.5.2)은 **DROP**. Click·CE가 있으면 그쪽으로만 폴백.

---

## 7. 정규화·검증 (Normalize + Validate)

DraftPlan(LLM 출력) → CanPlan으로 가는 **결정적**(deterministic) 단계. 실패 시 예외 또는 **한정된 자동 교정**(로그 남김).

필수 검사 항목:

1. **스키마 검증** — JSON Schema로 `VariableSpec/TriggerSpec/TagSpec` 각 필드 타입/enum 확인.
2. **참조 무결성**
   - `TagSpec.event_parameters[*].value_ref` → VariableSpec 또는 builtin에 존재?
   - `TagSpec.fires_on[*]` → TriggerSpec에 존재?
   - `TriggerSpec.conditions[*].lhs` → VariableSpec 또는 builtin에 존재?
3. **스코프 검증**
   - `TagSpec.event_name` ∈ `scope.allowed_events`?
   - EvidencePack에 근거 없는 트리거/태그 생성 금지(warning).
4. **정책 검증**
   - `VariableSpec.kind=cjs_template` → `template_id`가 사전 등록 목록(§8)에 있는가?
   - `TriggerSpec.kind=custom_event`의 `match_event`는 리터럴 문자열인가?
   - `TriggerSpec.conditions[*].op`에 `in_set`이 등장하면 `SCHEMA_VIOLATION`(canplan/1 비지원).
   - `TagSpec.kind=ga4_event`의 필수 파라미터 존재(이벤트별 테이블).
   - `TagSpec.measurement_id == scope.ga4_measurement_id` 여부 확인(불일치 시 오류).
5. **필드 변환**
   - `VariableSpec.kind=dom_selector` → `jsm` + 템플릿 JS 바인딩으로 확장.
   - `TriggerSpec.kind=custom_event` → `customEventFilter(arg0={{_event}}, arg1=match_event)` 직렬화.
6. **자동 교정(최소화)**
   - `type: "js"`처럼 명백한 오타는 거부(초안 단계 오류). **지금 `_build_variable`이 하던 암묵적 교정은 없음**.
   - 대신 LLM에 **재시도 요청**(한 번)과 실패 시 HITL 에러 보고.

정규화가 통과하지 못한 CanPlan은 **API로 갈 수 없다.**

---

## 8. CJS 템플릿 레지스트리

LLM이 자바스크립트 본문을 쓰게 두지 않는다. 대신 **검증된 템플릿 라이브러리**를 둔다.

### 8.1 초기 등록 템플릿 (Phase 0~1 범위)

| template_id | 목적 | 주요 인자 |
|-------------|------|-----------|
| `attr_from_selector` | 단일 DOM 값(`textContent` or `attribute`) 추출 — `dom_selector` 변수의 `jsm` 확장 본체 | `selector`, `attribute?` |
| `text_to_number` | 가격/수량 등 문자열을 숫자로 (천단위 콤마·통화기호 제거) | `selector?` or `source_var`, `strip_regex?` |
| `json_ld_value` | JSON-LD의 경로(`offers.price` 등)에서 값 하나 뽑기 | `type?`, `path` |
| `items_from_jsonld` | JSON-LD → GA4 `items` 배열 (단일 상품 / itemListElement 모두) | `mapping`(GA4 필드 ↔ JSON-LD 경로) |
| `items_from_dom` | PLP/카트 리스트 DOM → `items` 배열 | `list_selector`, `item_fields`(필드별 하위 selector) |
| `build_single_item` | PDP에서 `item_id`/`item_name`/`price` 등을 모아 **`items` 1건짜리 배열** 만들기 | `fields_from`(각 필드의 source 참조) |
| `meta_tag_value` | `<meta property="..." content="...">` 추출 (OG 태그 등) | `property` or `name` |
| `cookie_value` | `document.cookie`에서 값 파싱 (client_id·session 등) | `cookie_name` |

각 템플릿은 **인자 스키마 + 사전 컴파일된 안전한 본문**을 가진다. VariableSpec에는 `template_id`와 `args`만 들어간다. 새 템플릿 추가는 **코드 리뷰 단계**에서만.

### 8.2 운영 원칙

- 템플릿 본문은 `try/catch`로 감싸 **항상 `undefined`를 반환**(태그 전체가 멎지 않도록).
- 외부 리소스 접근 금지(`fetch`, `XMLHttpRequest`, `import()`, `eval`, `new Function`).
- 런타임 비용: `items_from_dom` 등 루프·다중 `querySelector`가 있는 템플릿은 **해당 트리거 발화 시점 1회**만 실행됨을 상정. 빈번한 페이지에서는 캐시 레이어가 없음을 주의(§9.4 참고).
- 새 템플릿 추가 PR은 **입력 스키마 + 골든 테스트 + 악성 입력 거부 테스트** 3종이 필수.

---

## 9. 컴포넌트 설계

### 9.1 신규

- `agent/canplan/schema.py` — `CanPlan`, `VariableSpec`, `TriggerSpec`, `TagSpec` 데이터클래스 + JSON Schema.
- `agent/canplan/normalize.py` — `DraftPlan(dict) → CanPlan` 변환·검증.
- `agent/canplan/evidence.py` — state에서 `EvidencePack`을 합성.
- `agent/canplan/cjs_templates.py` — 템플릿 레지스트리.
- `gtm/spec_builder.py` — `CanPlan → GTMVariable/Trigger/Tag` (현재 `_build_*`를 이 파일로 이동, 보정 로직 삭제).

### 9.2 기존 수정

- `agent/nodes/planning.py`
  - LLM 프롬프트 → **EvidencePack + DraftPlan JSON Schema**를 출력으로 강제.
  - LLM 호출 후 **`normalize()` 호출**해서 CanPlan 확정.
  - HITL에 **CanPlan**을 그대로 전달.
  - 재설계/피드백 루프 시 **EvidencePack + 이전 CanPlan + 피드백**으로 다시 LLM.
- `agent/nodes/gtm_creation.py`
  - `_fix_plan`, `_fix_custom_event_filter`, `_build_variable`의 `d→jsm` 암묵 변환 **삭제** (또는 assert로 강등).
  - `spec_builder(CanPlan)` 결과를 그대로 API 호출.
- `agent/nodes/structure_analyzer.py`
  - `datalayer_status=="full"`이어도 DOM/JSON-LD 후보 **얕게 수집** (EvidencePack용).
  - `url_patterns` 추론(간단한 path 정규식 합성)을 추가.
- `agent/nodes/active_explorer.py` / `cart` / `checkout` 계열
  - `captured_events[i].evidence`에 `{url, path, datalayer.sample, dom.resolved, json_ld.extracted, failures}` 고정 포맷으로 저장.

### 9.3 상태(state.py) 변경

- 추가: `evidence_pack: dict`, `draft_plan: dict`, `canplan: dict`, `exploration_plan: list[dict]`(이벤트·Playbook 페어).
- 기존 `plan`은 **호환 필드**로만 남기고, 내부 경로는 `canplan`만 사용.
- **변경 타이밍**: Phase 1a 시작 직후(Playbook loader가 `exploration_plan`을 써야 하므로) 1회에 몰아서 적용. 이후 Phase마다 새 필드를 추가하지 않는다.

### 9.4 성능·비용 메모

- **런타임 비용 회귀**: `dom_selector` 변수를 `jsm` 템플릿으로 확장하면 태그 실행 시마다 `document.querySelector`가 실행된다. 같은 DOM 값을 여러 파라미터가 참조하면 **동일 변수를 공유**하도록 정규화가 보장(변수 dedup, 이름 기반).
- **LLM 호출 비용**: Planning이 DraftPlan → (실패 시) 재시도 1회 = **이벤트 세트 1개당 최대 2회** LLM 호출. 커스텀 이벤트 Playbook 초안 생성(§6.5.5)도 별도 LLM 호출로 계수.
- **토큰 절감**: EvidencePack에 불필요한 raw snapshot을 넣지 않음(요약·경로·검증값 중심). `datalayer.pushes_sample`은 이벤트별 최근 3건으로 제한.

### 9.5 UI 계약 (HITL/리포터)

문서 수준에서 UI를 명시해 두지 않으면, 구현 단계에서 “무엇을 보여줘야 불변식이 유지되는가”가 흔들린다. 따라서 아래를 **필수 UI 계약**으로 둔다.

1. **입력 모델 단일화**  
   - HITL 화면의 단일 입력은 `canplan` + `normalize_errors` + `evidence_pack` 3종.  
   - 기존 `plan` 렌더는 Phase 4 완료 시 제거.
2. **관계 시각화**  
   - 최소 뷰: `variables` / `triggers` / `tags` 3개 섹션 카드 + `fires_on`, `value_ref` 링크.
   - 오류가 있는 이름(`affected_names`)은 즉시 하이라이트.
3. **정책 위반 가시화**  
   - `severity=error`는 배포 차단 배지, `warning`은 진행 가능 배지로 분리.
   - `rule_id`, `hint`를 UI에서 바로 확인 가능해야 함.
4. **전환기 모드 표시**  
   - `STRICT_CANPLAN=0`이면 배너에 “Legacy mutation possible” 표시.
   - `STRICT_CANPLAN=1`이면 “CanPlan invariant enforced” 표시.
5. **리포터 출력 정합**  
   - 리포터는 UI에 표시한 CanPlan과 동일 객체 해시를 로그(`canplan_hash`)에 기록.
   - UI 표시와 API 전송 객체가 다르면 즉시 오류로 간주.

---

## 10. 마이그레이션 (단계)

큰 수술을 피하기 위해 **그림자 경로**로 병행 가동하고, 로그로 차이를 확인한 뒤 전환한다.  
**각 Phase의 “산출물(Deliverable)”과 “완료 기준(Done when)”을 명시**해서, 체크만 보면 구현 가능한 수준까지 내려간다.

**전체 예상 기간**: Phase 0 (2~3일) + 1a (3~4일) + 1b (5~6일) + 2 (3~4일) + 3 (3~4일) + 4 (4~5일) + 5 (1~2일) = **21~28일**. 일정은 사이트 샘플 품질·UI 개편 폭에 따라 변동.

### Phase 0 — 스키마·빌더 골격 (2~3일)
**산출물**  
- [ ] `agent/canplan/schema.py` — `VariableSpec/TriggerSpec/TagSpec/CanPlan` 데이터클래스 + JSON Schema(dict).
- [ ] `gtm/spec_builder.py` — `CanPlan` → `list[GTMVariable]`, `list[GTMTrigger]`, `list[GTMTag]`.  
  현재 `gtm_creation._build_variable/_build_trigger/_build_tag` 로직을 **이 파일로 이동**(보정 로직은 제거).
- [ ] `tests/test_spec_builder.py` 골든 테스트 3종:
  - GA4 `view_item` + Custom Event (DL 있음).
  - GA4 `view_item` + **Page View + Page Path** (DL 없음 + URL 패턴).
  - GA4 `add_to_cart` + **Click 트리거**.

**완료 기준**  
- 세 픽스처 모두 `CanPlan → spec_builder → GTM payload dict` 변환이 문자열 diff 0으로 고정.
- 기존 파이프라인은 **무변경**으로 유지.

---

### Phase 1a — Playbook · Journey · State 골격 (3~4일)
**산출물**  
- [ ] `agent/state.py` **선행 변경**: `evidence_pack`, `draft_plan`, `canplan`, `exploration_plan` 필드 한 번에 추가. 기존 필드 삭제 없음(호환).
- [ ] `agent/playbooks/ga4_ecommerce.yaml` — §6.5.2 표의 12개 이벤트 Playbook 선언.
- [ ] `agent/playbooks/loader.py` — 내장 Playbook 로드 + 커스텀 이벤트 초안 생성(LLM, HITL 확인).
- [ ] `Journey Planner` 수정: 이벤트별 Playbook을 붙여 `exploration_plan: [{event, playbook}]` 상태에 저장. 기존 `exploration_queue`는 호환으로 유지.
- [ ] `Structure Analyzer` **얕은 수집 모드** 구현:
  - `datalayer_status=="full"` 시에도 **스킵하지 않고**, 아래 정의에 따른 “얕은 수집”만 수행.
  - **얕은 수집의 정의**: 현재 URL에 대해서만, 각 이벤트 Playbook의 `observation.required_fields`에 한해 selector 추출·검증(+ JSON-LD 스캔). 페이지 전체 분석/재시도 프롬프트는 스킵.
  - `url_patterns`(pdp/plp/cart/checkout 정규식) 합성 추가 — **관측 우선, Playbook seed 차선**(§6.5.6). 관측 없으면 seed, 둘 다 없으면 필드 생략.
  - `site.spa` 플래그 추정(History API/라우터 힌트 등 간단 휴리스틱).

**완료 기준**  
- `state.exploration_plan`이 비지 않고, 각 항목이 Playbook 스키마를 만족.
- `datalayer_status=="full"`인 사이트에서도 `site.url_patterns`·`dom.selectors`가 비어있지 않음(얕은 수집).
- 기존 파이프라인은 **여전히 동작**(그림자 경로).

---

### Phase 1b — Navigator · Explorer · Evidence (5~6일)
**산출물**  
- [ ] `LLMNavigator`/전용 Navigator가 Playbook의 `surface_goal`·`entry_hints`·`settle_ms`를 사용하도록 수정.
- [ ] **스냅샷 한계 대응**: `surface_goal` 미도달 시 Navigator가 아래 순서로 **2회까지** 재시도한 뒤에만 `failures.reason="surface_unreached"`를 기록:
  1. `prefer_bottom=True`로 스냅샷 재요청(긴 홈페이지 대응).  
  2. 페이지를 ¼씩 스크롤하며 스냅샷 chunking(상·하 2개로 나눠 판단).  
  이 정책은 LLMNavigator에 **플래그로 도입**(기본 ON).
- [ ] `Active/Cart/Checkout Explorer` 수정:  
  `captured_events[i].evidence = {url, path, datalayer: {fired, sample}, dom: {resolved}, json_ld: {extracted}, failures: [...]}` **고정 포맷**으로 저장.  
  Playbook의 `observation.required_fields`/`optional_fields`로 필드 검증, DL 건전성(§4.5.4) 판정 실행.
- [ ] `agent/canplan/evidence.py` — `build_evidence_pack(state) -> dict`.
- [ ] `logs/<run>/evidence.json` 덤프.

**완료 기준**  
- 네 가지 실사이트 로그 샘플에서 `evidence.json` 필수 필드가 채워짐:  
  - **DL 풍부** / **DL 건전성 실패**(items가 문자열 등 의도 주입) / **무 DL + JSON-LD** / **무 DL + 로그인 필요**(비로그인 홈까지만 접근).
- `view_item`·`view_item_list`·`select_item`·`view_cart` 중 **최소 3종**이 Playbook 기반 진입·관찰 성공.
- **스냅샷 한계 재시도**가 로그에 남고, 긴 홈페이지 샘플 1건에서 `surface_unreached` → 재시도 → 성공으로 기록됨.

---

### Phase 2 — 그림자 Planning (3일)
**산출물**  
- [ ] Planning 노드에 **두 번째 LLM 경로** 추가:
  - 입력: EvidencePack + CanPlan JSON Schema.
  - 출력: DraftPlan(dict).
  - **기존 LLM 경로(`_generate_plan`)는 그대로 병행 가동**.
- [ ] `agent/canplan/normalize.py` — DraftPlan → CanPlan 변환/검증 **부분 구현**(스키마 + 참조 무결성 + 소스 폴백 체인 §4.5).
- [ ] 결과를 `logs/<run>/canplan.json` 과 `logs/<run>/plan_vs_canplan.diff.json` 으로 덤프.
- [ ] 기존 플로우는 여전히 기존 `plan`을 사용(API 호출 변경 없음).

**완료 기준**  
- 동일 EvidencePack에서 **CanPlan이 기존 `plan`과 의미상 동치** 또는 더 안전. 판정은 **정규화된 해시 비교 유틸**(이름·순서 정규화 → 타입·파라미터 키·값 해시)로 자동화. 골든 샘플 3개 이상에서 해시 일치 또는 “더 안전” 라벨.
- 무 DL `view_item`에서 **Page Path 트리거 자동 선택**되는 케이스 최소 1건 확인.

---

### Phase 3 — 정규화 엄격 모드 (2~3일)
**산출물**  
- [ ] `normalize()` 완성 — §7의 모든 검사 통과.
- [ ] **폴백 체인 규칙 강제**:
  - `DL 있음 + LLM이 DL 무시` → LLM 재시도 1회, 그래도 실패면 HITL 에러.
  - 로드형 이벤트(`view_item` 계열) + DL 미발화 + `url_patterns` 존재 → **pageview 트리거 필수**(LLM이 다른 걸 골랐으면 재시도 or 자동 교정).
- [ ] `gtm_creation`의 사후 보정 함수(`_fix_plan`, `_fix_custom_event_filter`, `_build_variable`의 `d→jsm` 암묵 변환)를 **assert-only 모드** 플래그로 전환:  
  `STRICT_CANPLAN=1`이면 위반 시 **예외**, 아니면 기존 동작(호환).

**완료 기준**  
- `STRICT_CANPLAN=1` 환경에서 CanPlan 경로만 켜고, 대표 케이스(무 DL / DL 풍부)에서 API 호출 성공.

---

### Phase 4 — 전환 (4~5일)
**산출물**  
- [ ] Planning 출력 경로를 **CanPlan 단일화**. `plan` 필드는 CanPlan에서 파생(호환).
- [ ] `gtm_creation`은 `spec_builder(CanPlan)` 결과만 사용.
- [ ] HITL UI가 CanPlan의 **변수–트리거–태그 관계**를 표/그래프로 렌더(최소: 섹션별 카드) + `normalize_errors` 하이라이트/툴팁(`rule_id`, `hint`).
- [ ] 리포터는 CanPlan + EvidencePack을 사용.

**완료 기준**  
- 레거시 LLM 경로(구 `_generate_plan`) 호출 제거 후 **회귀 테스트 통과**.
- UI에 표시된 `canplan_hash`와 API 호출 직전 `canplan_hash`가 항상 동일.

---

### Phase 5 — 정리 (1~2일)
- [ ] `_fix_plan` 등 레거시 함수 **삭제**.
- [ ] Planning 시스템 프롬프트 대폭 축소(자바스크립트 본문/네이밍 규칙 제거; EvidencePack과 CanPlan Schema로 대체).
- [ ] `gtm/dom_variable.normalize_dom_element_parameters` → spec_builder 내부로 이관하고 외부 노출 제거.

---

## 11. 테스트 전략

1. **스키마 테스트** — 잘못된 DraftPlan(미지 참조, 금지 op, 자유 CJS 본문 등)이 모두 거부되는지.
2. **Builder 골든 테스트** — CanPlan 픽스처 → GTM payload JSON(이름/타입/파라미터 고정).
3. **EvidencePack 합성 테스트** — 다양한 state(무 DL, DL 풍부, JSON-LD만 등)에서 기대 필드가 모두 채워지는지.
4. **트리거 오탐(부정) 테스트** — Page View + Page Path 트리거가 **의도한 표면에서만 발화**하는지 검증. 예: `view_item` 트리거가 `/product/123/review` 같은 서브패스에서 발화되지 않아야 함. 정규식 경계(`/?$`)·부정 샘플 fixture를 고정.
5. **DL 건전성 테스트** — `items`가 문자열·빈 배열, `value`가 `"undefined"` 같은 **불건전 페이로드**를 주입했을 때, `candidate_sources_per_field`에서 해당 DL 후보가 `health: unhealthy`로 내려가고 LLM이 차순위를 선택하는지.
6. **LLM 회귀 테스트**(온라인) — 같은 EvidencePack으로 여러 번 돌려 CanPlan의 **핵심 필드 안정성**을 측정. 판정은 **정규화 해시 비교**(§Phase 2 완료 기준의 유틸 재사용) — 변수/트리거/태그를 이름 정규화 후 정렬하고, 타입·파라미터 키·값을 해시.
7. **엔드투엔드 드라이런** — `GTMClient` 목으로 API 호출 시 보내는 payload 전문을 스냅샷으로 고정.

---

## 12. 확정된 결정 사항 (구현 기본값)

이전 버전의 “열린 질문” 중 **본 계획에서 일단 확정**하고 가는 항목. 필요시 나중에 변경.

1. **정책을 코드에 박는다.** “DL 있으면 DL 우선 / 로드형 이벤트 무 DL은 Page Path”는 정규화 규칙(§4.5).  
   LLM이 어긴 경우 재시도 1회 → 실패 시 HITL 에러.
2. **CJS는 자유 생성 금지, 템플릿 레지스트리만 허용** (§8).
3. **HITL 스키마 = CanPlan**. UI는 CanPlan을 직접 렌더한다(편집은 Phase 4에서 시도, 불가 시 피드백 문자열 fallback).
4. **TagSpec.kind는 `ga4_event`로 한정**하고 시작. Naver/Meta 등은 이후 별도 PR로 추가.
5. **`STRICT_CANPLAN` 환경 변수**로 Phase 3/4 전환을 제어한다(점진 전환 장치).
6. **전환기 불변식 범위**: “HITL 표시 = API 전송” 불변식은 `STRICT_CANPLAN=1`에서 강제 보장. `STRICT_CANPLAN=0`에서는 UI 배너로 잠재적 레거시 변이를 명시.

### 남은 열린 질문

- **SPA 판정 로직의 신뢰도** — 간이 휴리스틱으로 시작. 오판 시 Planning이 수동으로 보정 가능하게 HITL에 “SPA: true/false” 토글 노출 여부.
- **HITL UI에서 CanPlan 편집 허용 범위** — 변수/트리거/태그 이름·타입만 변경 허용할지, `conditions`·`event_parameters`까지 편집 허용할지. Phase 4 결정.
- **실패 이벤트 처리 기본값** — 기본은 DROP + 리포트. HITL 강제 중단은 옵션 플래그로.
- **`url_patterns` 합성의 LLM 보조 여부** — 관측만으로 부족할 때(샘플 수 < 임계) LLM에게 정규식 일반화를 요청할지, 아니면 seed fallback으로 끝낼지.

---

## 13. 즉시 착수 체크리스트 (이 순서대로)

1. **Phase 0**: `agent/canplan/schema.py` + `gtm/spec_builder.py` 골격 및 골든 테스트 3종(DL 있음 / 무 DL + Page Path / Click).
2. **Phase 1a**: `state.py` 선행 변경 → `agent/playbooks/ga4_ecommerce.yaml` + `loader.py` → Journey Planner 주입 → Structure Analyzer **얕은 수집** 모드.
3. **Phase 1b**: Navigator의 Playbook 소비 + 스냅샷 재시도(`prefer_bottom`·chunking) → Explorer의 `evidence` 포맷 고정·DL 건전성 판정 → `evidence.py` 완성.
4. **Phase 2**: Planning 그림자 경로(DraftPlan → CanPlan), 정규화 해시 비교 유틸, `logs/<run>/canplan.json` + `plan_vs_canplan.diff.json`.
5. **Phase 3**: 정규화 엄격 모드 + `STRICT_CANPLAN` 플래그 + 정규화 에러 구조체(§15) 도입.
6. **Phase 4**: CanPlan 단일화 + HITL UI 전환 + 리포터.
7. **Phase 5**: 레거시 삭제·프롬프트 축소.

---

## 14. 부록 A — CanPlan kind ↔ GTM API type 매핑

정규화·spec_builder가 결정적으로 따라야 하는 매핑. 이 표를 벗어나는 조합은 **정규화 에러**로 거부.

### 14.1 VariableSpec.kind → GTM `variable.type`

| CanPlan kind | GTM `type` | 주요 파라미터 (GTM) | 비고 |
|--------------|-----------|----------------------|------|
| `datalayer` | `v` | `name=<path>`, `dataLayerVersion=2` | 기본 v2 |
| `dom_id` | `d` | `elementId`, `attribute?` | `attribute` 생략 시 `textContent` |
| `dom_selector` | `jsm` | `javascript=<attr_from_selector 템플릿 바디>` | 템플릿 `attr_from_selector` args 주입 |
| `cjs_template` | `jsm` | `javascript=<템플릿 본문 + args>` | 레지스트리(§8) 내 템플릿만 허용 |
| `json_ld_path` | `jsm` | `javascript=<json_ld_value 템플릿>` | 실행 시 JSON-LD `<script>` 파싱 |
| `constant` | `c` | `value` | 문자열 |
| `builtin` | (GTM 빌트인 그대로) | `{{Page Path}}` 등 | GTM 기본 변수 목록에 있는 것만 |

### 14.2 TriggerSpec.kind → GTM `trigger.type`

| CanPlan kind | GTM `type` | 조건 필드 | 비고 |
|--------------|-----------|------------|------|
| `custom_event` | `customEvent` | `customEventFilter` (arg0=`{{_event}}`, arg1=match_event) + 추가 `filter[]` | `match_event`는 문자열 리터럴 |
| `click` | `click` (Just Links이면 `linkClick`, 모든 요소면 `click`) | `filter[]` with `{{Click Element}}`/`{{Click Classes}}`/`{{Page Path}}` | 기본은 All Elements |
| `pageview` | `pageview` | `filter[]` with `{{Page Path}}`·`{{Page URL}}`·`{{Page Hostname}}` | Page Path 정규식은 `matchRegex` |
| `dom_ready` | `domReady` | 동일 | — |
| `window_loaded` | `windowLoaded` | 동일 | — |
| `history_change` | `historyChange` | 동일 (SPA) | `site.spa=true`일 때만 허용 |
| `form_submit` | `formSubmission` | `filter[]` | Phase 4 활성화 |
| `element_visibility` | `elementVisibility` | `filter[]` + element selector/ID | Phase 4 활성화 |

### 14.3 TagSpec.kind → GTM `tag.type`

| CanPlan kind | GTM `type` | 필수 파라미터 |
|--------------|-----------|---------------|
| `ga4_event` | `gaawe` | `measurementIdOverride`(String) + `eventName`(String) + `eventParameters`(List<Map>) + `firingTriggerId[]` |

### 14.4 `op` ↔ GTM filter/condition type

| CanPlan op | GTM `type` |
|------------|------------|
| `equals` | `equals` |
| `contains` | `contains` |
| `starts_with` | `startsWith` |
| `ends_with` | `endsWith` |
| `matches_regex` | `matchRegex` |
| `in_set` | `canplan/1` 비지원 (`condition_logic="any"` + `equals` 다중 조건으로 대체) |
| `not_*` | `negate: true` 플래그 |

---

## 15. 부록 B — 정규화 에러 구조체

정규화 실패 시 반환되는 표준 구조체. UI·로그·재시도 로직이 모두 이걸 보고 동작.

```jsonc
{
  "code": "REF_NOT_FOUND" | "SCHEMA_VIOLATION" | "POLICY_VIOLATION"
        | "DL_HEALTH_IGNORED" | "TEMPLATE_UNKNOWN" | "TYPE_MISMATCH"
        | "MISSING_REQUIRED_PARAM" | "UNKNOWN",
  "severity": "error" | "warning",
  "event": "view_item",                 // 연관 이벤트 (없으면 null)
  "rule_id": "4.5.1#step1-healthy",     // 이 문서의 규칙 위치
  "message": "사람이 읽는 설명(한국어)",
  "hint":    "사용자/LLM에게 주는 한 줄 힌트",
  "affected_names": ["GA4 - view_item", "DLV - ecommerce.items"],
  "retryable": true                     // 재시도 가치가 있는가
}
```

처리 규칙:

- 정규화는 위 구조체의 **리스트**를 반환. 하나라도 `severity=error`이면 CanPlan 무효.
- `retryable=true`만 LLM 재시도(1회). 나머지는 즉시 HITL 에러 보고.
- HITL UI는 `affected_names`를 CanPlan 렌더에서 하이라이트, `hint`를 툴팁으로 노출.
- 리포터는 모든 에러·경고를 `logs/<run>/normalize_errors.json`에 저장.

---

### 참고 — 현재 코드 앵커

- `agent/nodes/planning.py` — LLM이 트리거/변수/태그 JSON을 통째로 생성, HITL에 그대로 노출.
- `agent/nodes/gtm_creation.py:278-312, 318-407, 430-484` — `_build_variable`, `_fix_plan`, `_fix_custom_event_filter`, `_build_trigger`, `_build_tag`(현재 사후 보정 혼재).
- `agent/nodes/structure_analyzer.py:117-133` — `datalayer_status=="full"` 시 분석 스킵(EvidencePack 품질 저하 원인).
- `agent/state.py` — `selected_events`, `extraction_method`, `dom_selectors`, `click_triggers`, `captured_events`.
- `gtm/dom_variable.py::normalize_dom_element_parameters` — `d → jsm` 암묵 변환(정규화로 이관 예정).

---

## 16. 구현 진행 상태 (2026-04-19)

아래는 현재 코드 반영 기준의 체크포인트.

- [x] `agent/canplan/schema.py` 추가 (`canplan/1`, 정규화 이슈 구조)
- [x] `agent/canplan/normalize.py` 추가 (Draft/legacy -> CanPlan, 참조 검증)
- [x] `agent/canplan/evidence.py` 추가 (EvidencePack 합성)
- [x] `agent/canplan/cjs_templates.py` 추가 (템플릿 레지스트리 기본형)
- [x] `gtm/spec_builder.py` 추가 (CanPlan -> GTM models 변환)
- [x] `planning.py`에 `draft_plan`, `canplan`, `normalize_errors`, `canplan_hash` 경로 연결
- [x] `gtm_creation.py`에 CanPlan 우선 경로 연결, `STRICT_CANPLAN` 차단 분기 추가
- [x] `state.py`/`runner.py`에 신규 상태 필드 추가
- [x] `agent/playbooks/ga4_ecommerce.yaml`, `agent/playbooks/loader.py` 추가
- [x] `journey_planner.py`에서 `exploration_plan` 저장
- [ ] Structure Analyzer의 `datalayer_status=full` 얕은 수집 모드
- [ ] Explorer/Navigator의 Playbook `surface_goal` 본격 소비
- [ ] `logs/<run>/canplan.json`, `plan_vs_canplan.diff.json` 자동 덤프
                           