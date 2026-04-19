# gtm CLAUDE.md

GTM API v2 클라이언트, 인증, 데이터 모델.

---

## 파일 구성

| 파일 | 역할 |
|------|------|
| `auth.py` | OAuth2 인증, `credentials/token.json` 관리 |
| `client.py` | GTM API v2 래퍼 (`GTMClient`) |
| `models.py` | GTMVariable / GTMTrigger / GTMTag / GTMParameter 데이터클래스 |
| `dom_variable.py` | DOM Element 변수(`type: "d"`) `parameter[]` 정규화(LLM 별칭 → REST 키) |
| `spec_builder.py` | CanPlan(`canplan/1`) → GTM 모델 스펙 직렬화 |

---

## auth.py

```python
get_credentials() -> Credentials
```

- `credentials/token.json` 존재 시 로드·갱신
- 없거나 만료 시 브라우저 OAuth 팝업 → 저장
- `credentials/` 폴더는 절대 커밋하지 않는다 (`.gitignore` 처리 필수)

최초 인증:
```bash
python gtm/auth.py
```

---

## client.py — GTMClient

```python
client = GTMClient(account_id="...", container_id="...")
```

### 주요 메서드

```python
# Workspace
create_workspace(name: str) -> dict
list_workspaces() -> list[dict]

# Variable
create_or_update_variable(workspace_id, variable: GTMVariable) -> dict

# Trigger
create_or_update_trigger(workspace_id, trigger: GTMTrigger) -> dict

# Tag
create_or_update_tag(workspace_id, tag: GTMTag) -> dict

# Publish
create_version(workspace_id, name="") -> dict
publish_version(version_id) -> dict
```

### 이름 충돌 처리

`create_or_update_*` 메서드는 내부적으로:
1. 동일 이름 리소스 조회
2. 존재하면 `update` 호출 (덮어쓰기)
3. 없으면 `create` 호출

### Workspace 한도 초과

GTM 무료 계정은 워크스페이스를 최대 3개까지 허용한다.

- `create_workspace`는 **목록 조회에 성공한 경우에만** 개수를 보고, 한도에 도달하면
  `RuntimeError`를 던진다. 목록 조회 자체가 실패하면 한도를 건너뛸 수 없으므로
  같은 예외 계열로 실패 처리한다(이전에는 조회 실패를 무시하는 버그가 있었다).
- `agent/nodes/gtm_creation.py`는 **이미 3개면 신규 `create`를 호출하지 않고**,
  이름이 `gtm-ai-*`인 기존 작업공간이 있으면 그중 최신에 설계안을 적용한다.
  해당 `gtm-ai-*`가 없으면 Node 6에서 실패하고, UI `thought`로 이유를 남긴다.

### Rate Limit (429)

GTM API는 분당 요청 수 제한이 있다. `gtm_creation.py`에서 3회 재시도 로직으로 처리.
client 레벨에서는 그대로 예외를 던진다 — 재시도 로직은 호출 측 책임.

---

## models.py — 데이터클래스

### GTMParameter

```python
GTMParameter(
    type="template",  # "template" | "boolean" | "integer" | "list" | "map"
    key="name",
    value="event",
)
```

`to_dict()` → GTM API body에 직접 삽입 가능한 dict 반환.

### GTMVariable

```python
GTMVariable(
    name="DLV - event",
    type="v",           # "v"=DL Variable, "c"=Constant, "d"=DOM, "jsm"=Custom JS 등
    parameters=[...]
)
```

### DOM Element 변수 (`type: "d"`)

- 공식 Variable Dictionary 기준 DOM 변수는 `elementId` + `attributeName`(HTML id 기반)만 지원한다. CSS Selector 모드는 REST에 공개 스펙 없음.
- `gtm.dom_variable.normalize_dom_element_parameters`가 설계안 1건을 정규화해 `(new_type, parameters)` 튜플 또는 `None`을 반환한다:
  - ID 모드 → `("d", [elementId, attributeName])`
  - CSS 모드 → `("jsm", [javascript])` (Custom JavaScript로 자동 변환, 변수 이름은 유지)
  - 값 비어 있음 → `None` (상위에서 드롭)
- 공식 Variable 리소스·Parameter 객체: [Variables (REST v2)](https://developers.google.com/tag-platform/tag-manager/api/reference/rest/v2/accounts.containers.workspaces.variables), [Parameter](https://developers.google.com/tag-platform/tag-manager/api/reference/rest/v2/Parameter)
- 설계안·별칭·자동 변환 규칙 상세: `docs/gtm-variable-api.md`

### GTMTrigger

```python
GTMTrigger(
    name="CE - view_item",
    type="customEvent",
    custom_event_filter=[...],
    filter_=[...],          # Click Trigger 조건
    parameter=[...],        # elementVisibility 등 body-level 파라미터
)
```

### GTMTag

```python
GTMTag(
    name="GA4 - view_item",
    type="gaawe",           # "gaawe"=GA4 Event, "html"=Custom HTML 등
    parameters=[...],
    firing_trigger_ids=["triggerId1"],
)
```

---

## 네이밍 컨벤션

| 리소스 | 패턴 | 예시 |
|--------|------|------|
| DL Variable | `DLV - {필드명}` | `DLV - ecommerce.value` |
| Constant Variable | `GA4 Measurement ID` | — |
| DOM Variable | `DOM - {필드명}` | `DOM - item_name` |
| Custom JS Variable | `CJS - {필드명}` | `CJS - item_price` |
| Custom Event Trigger | `CE - {event_name}` | `CE - view_item` |
| Click Trigger | `Click - {설명}` | `Click - 찜하기 버튼` |
| GA4 Tag | `GA4 - {event_name}` | `GA4 - add_to_cart` |
| Naver Tag | `Naver - {event_name}` | — |
| Kakao Tag | `Kakao - {event_name}` | — |

---

## spec_builder.py — CanPlan → GTM 모델 스펙

`agent/canplan`의 `canplan/1`을 그대로 받아 `GTMVariable/GTMTrigger/GTMTag` 리스트로 직렬화한다.
레거시 `_fix_plan`·`_build_*` 경로와 완전히 분리돼 있으며, **정규화를 통과한 CanPlan만 입력**으로 받는다(재검증 없음).

```python
from gtm.spec_builder import build_specs_from_canplan

variables, triggers, tags = build_specs_from_canplan(canplan)
```

### 내부 매핑

- `_TRIGGER_TYPE_MAP` — CanPlan `kind`(`custom_event`) → GTM API type(`customEvent`) 등 1:1.
- `_OP_MAP` — 필터 연산자를 `(gtm_op, negate)` 튜플로 변환. `not_*` 변형은 `negate=True`로 처리하고, `matches_regex`는 `matchRegex`.
- 변수 kind별 처리:
  - `datalayer` → `type: "v"` + `name` 파라미터(`params.path`)
  - `dom_id` → `type: "d"` + `elementId`/`attributeName`
  - `dom_selector` → **`type: "jsm"` CJS로 자동 변환** (공식 API에 CSS selector 모드가 없음)
  - `cjs_template` → `agent.canplan.cjs_templates.render_template(id, args)` 결과를 `type: "jsm"`의 `javascript`로 주입
  - `json_ld_path` → 현재 `jsm`로 렌더(path 기반 안전 접근 함수)
  - `constant` → `type: "c"`
  - `builtin` → GTM Built-in 이름 그대로 참조(`{{Page Path}}` 등)
- 태그는 `firing_trigger_names` → 생성된 트리거 ID로 치환(`trigger_name_to_id` 맵).

### 주의

- **CanPlan이 담지 못하는 GTM 고급 옵션**(ex: consent, exception tags)은 현재 미지원. 필요 시 스키마(`agent/canplan/schema.py`)에 필드를 추가한 뒤 이 모듈에서 매핑한다.
- 입력이 `canplan/1`이 아니면 `gtm_creation`에서 바로 레거시 경로로 폴백 — 이 모듈은 방어 로직을 두지 않는다.

---

## 2026-04-19 변경점

- `spec_builder.py`를 추가해 CanPlan 기반 빌드 경로를 분리. `gtm_creation`이 CanPlan이 있으면 `_fix_plan` 보정 없이 API 스펙으로 직렬화.
- 레거시 `plan` 경로는 `STRICT_CANPLAN=0` 환경에서만 허용되며, `gtm_creation._reject_in_set_in_legacy`가 `in_set` 조건을 런타임에 차단한다.
- CJS 자유 JS 작성은 `agent/canplan/cjs_templates.REGISTERED_TEMPLATES`로 사전 제한. `spec_builder`는 미등록 템플릿이 들어올 가능성을 **CanPlan 통과 시점**에 이미 정규화가 걸러 줬다고 가정한다.
