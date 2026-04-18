# GTM Variable REST API 정리 (웹 컨테이너)

Node 6(`gtm_creation`)이 GTM에 보내는 Variable 리소스는 **REST v2** 스키마를 따른다.

## 공식 문서 (읽는 순서 권장)

1. [Variable 리소스](https://developers.google.com/tag-platform/tag-manager/api/reference/rest/v2/accounts.containers.workspaces.variables) — `name`, `type`, `parameter[]`
2. [Parameter 객체](https://developers.google.com/tag-platform/tag-manager/api/reference/rest/v2/Parameter) — `type`(`template` 등), `key`, `value`, `list`, `map`
3. 타입별 허용 `key` 목록은 Google이 **Tag / Variable Dictionary**로 안내한다(Parameter Reference 본문에서 링크). 링크가 바뀔 수 있으니 최신 검색으로 보완할 것.

## DOM Element 변수 (`type: "d"`)

LLM 설계안이 `selector`, `attribute`처럼 **UI 용어와 비슷한 키**를 쓰면, GTM 서버는 `elementId` 등을 비운 채 vendor template 검증에 걸려 **400**을 반환할 수 있다.

이 프로젝트에서는 **`gtm/dom_variable.py`**의 `normalize_dom_element_parameters`가 API에 맞게 정규화한다.

### REST에 맞춘 `parameter[]` 형태

**CSS 선택**

| key | type | value 예 |
|-----|------|-----------|
| `selectionMethod` | `template` | `CSS_SELECTOR` |
| `elementSelector` | `template` | `.price`, `[data-price]` 등 |
| `attributeName` | `template` | 속성 없이 텍스트만 쓸 때 `""` |

**Element ID 선택**

| key | type | value 예 |
|-----|------|-----------|
| `selectionMethod` | `template` | `ID` |
| `elementId` | `template` | HTML `id` 값(문자열) |
| `attributeName` | `template` | 선택, 텍스트만이면 `""` |

### 정규화 단계에서 인식하는 별칭 (템플릿 파라미터)

| 의미 | 허용 key (우선순위 순) |
|------|-------------------------|
| CSS 셀렉터 문자열 | `elementSelector`, `selector`, `cssSelector` |
| Element ID | `elementId`, `element_id` |
| 속성명 | `attributeName`, `attribute` |
| 선택 방식 | `selectionMethod` (`ID` / `CSS_SELECTOR` 및 일부 동의어) |

`selectionMethod`가 없으면, **셀렉터만 있으면 CSS**, **ID만 있으면 ID**로 추론한다.

### 실측 권장

Google이 노출하는 Dictionary와 실제 컨테이너 동작이 어긋날 수 있으므로, 한 번은 GTM UI에서 DOM 변수를 만든 뒤 **같은 워크스페이스에서 `variables.get`**으로 받은 JSON을 기준으로 `selectionMethod` 문자열을 검증하는 것이 가장 안전하다.

## 코드 연동

- 정규화: `gtm/dom_variable.py` → `normalize_dom_element_parameters`
- 호출: `agent/nodes/gtm_creation.py`의 `_build_variable` (`type`이 `"d"`일 때만)

## 관련 문서

- `gtm/CLAUDE.md` — GTM 클라이언트·모델 개요 및 위 모듈 안내
