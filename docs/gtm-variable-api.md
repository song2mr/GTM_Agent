# GTM Variable REST API 정리 (웹 컨테이너)

Node 6(`gtm_creation`)이 GTM에 보내는 Variable 리소스는 **REST v2** 스키마를 따른다.

## 공식 문서 (읽는 순서 권장)

1. [Variable 리소스](https://developers.google.com/tag-platform/tag-manager/api/reference/rest/v2/accounts.containers.workspaces.variables) — `name`, `type`, `parameter[]`
2. [Parameter 객체](https://developers.google.com/tag-platform/tag-manager/api/reference/rest/v2/Parameter) — `type`(`template` 등), `key`, `value`, `list`, `map`
3. 타입별 허용 `key` 목록은 Google의 **Variable Dictionary Reference**에 정리돼 있었으나, 현재 원본 URL은 404. Wayback 스냅샷(2022·2024년 모두 동일 내용)만 접근 가능:
   https://web.archive.org/web/2024/https://developers.google.com/tag-platform/tag-manager/api/v1/variable-dictionary-reference

## DOM Element 변수 (`type: "d"`) — **ID 모드만 공식 지원**

위 Dictionary가 보증하는 파라미터는 **딱 2개**다.

| key | type | 비고 |
|-----|------|------|
| `elementId` | `template` | HTML `id` 값(문자열). 필수 |
| `attributeName` | `template` | Optional. 빈 문자열이면 요소의 `textContent` |

GTM UI에는 “CSS Selector” 선택 모드가 있지만, **REST API 쪽 공식 Dictionary에는 CSS 키가 없다.** 비공식 추측 키(`selectionMethod`, `elementSelector`, `cssSelector` 등)를 보내면 서버가 조용히 무시하고, 남은 `elementId`가 비어 있다며 다음 400을 반환한다.

```
vendorTemplate.parameter.elementId: The value must not be empty.
```

### 이 프로젝트가 처리하는 방식

설계안이 CSS 기반이면 `gtm/dom_variable.py`의 `normalize_dom_element_parameters`가 **자동으로 `type: "jsm"` (Custom JavaScript) 변수로 변환**한다. 변수 이름은 유지된다.

| 설계 입력 | 변환 결과 | 비고 |
|-----------|-----------|------|
| `type: "d"` + `elementId` 값 존재 | `type: "d"` + `[elementId, attributeName]` | 공식 스펙 그대로 |
| `type: "d"` + CSS selector 존재(또는 `selectionMethod: CSS*`) | `type: "jsm"` + `[javascript]` | 아래 JS 본문 생성 |
| 둘 다 비어 있음 | `None` → 상위에서 드롭 | |

자동 생성되는 JSM 본문:

```js
function(){
  var el = document.querySelector(<선택자>);
  if (!el) return '';
  var a = <attributeName>;
  return a ? (el.getAttribute(a) || '') : ((el.textContent || '').trim());
}
```

### 인식하는 별칭 (설계안 키)

| 의미 | 허용 key (우선순위 순) |
|------|-------------------------|
| CSS 셀렉터 문자열 | `elementSelector`, `selector`, `cssSelector` |
| Element ID | `elementId`, `element_id` |
| 속성명 | `attributeName`, `attribute` |
| 선택 방식(선택적) | `selectionMethod` (`ID` / `CSS` 및 동의어) |

`selectionMethod`가 없으면 **셀렉터만 있으면 CSS, id만 있으면 ID**로 추론한다.

## 집계 CJS는 개별 변수를 참조해야 한다 (DRY 원칙)

`CJS - ecommerce_items` 같은 집계 변수가 내부에서 `document.querySelector("meta[...]")`를 직접 호출하면, 동일 selector가 `DOM - item_name`(또는 jsm 변환 결과)과 중복되어 유지보수 비용이 올라간다. **집계 CJS는 반드시 `{{DOM - item_name}}` 형태로 참조**해야 한다. GTM은 Custom JavaScript 변수 본문을 평가하기 전에 `{{변수명}}`을 해당 변수 값(문자열/숫자 리터럴)으로 치환한다.

이 규칙은 `agent/nodes/planning.py` 프롬프트에 명시돼 있으며, LLM이 집계 CJS를 `{{참조}}` 스타일로 내도록 유도한다. (자동 치환 안전망은 기존 LLM이 생성한 `var x = querySelector(...); ... x.content` 패턴을 문법적으로 깨뜨릴 수 있어 이 프로젝트에서는 의도적으로 도입하지 않음 — 프롬프트 쪽에서만 해결.)

## 코드 연동

- 정규화: `gtm/dom_variable.py` → `normalize_dom_element_parameters` (튜플 `(type, params)` 또는 `None` 반환)
- 호출: `agent/nodes/gtm_creation.py`의 `_build_variable` (type이 `"d"`일 때만)
- CanPlan 경로: `gtm/spec_builder.py`가 `VariableSpec.kind`를 기준으로 GTM 타입(`v/d/jsm/c`)으로 직렬화

## 관련 문서

- `gtm/CLAUDE.md` — GTM 클라이언트·모델 개요 및 위 모듈 안내
- `agent/nodes/CLAUDE.md` — Node 6(`gtm_creation`) 전체 흐름

---

## 2026-04-19 메모

- 기존 레거시 `plan`(`type: v/d/jsm/c`)은 호환 경로로 유지하되, 기본 경로는 CanPlan 정규화 결과를 사용한다.
- `STRICT_CANPLAN=1` 환경에서는 CanPlan이 없으면 레거시 빌더 경로를 차단한다.
