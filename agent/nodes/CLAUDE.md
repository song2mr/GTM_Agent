# agent/nodes CLAUDE.md

Node 1~8 각각의 역할, 입출력, 핵심 로직, 주의사항.

---

## Node 1 — `page_classifier.py`

**역할**: 페이지 로드 + Persistent Event Listener 주입 + 페이지 타입 판단 + 로드타임 이벤트 수집

**입력**: `target_url`
**출력**: `page_type`, `datalayer_status`, `datalayer_events_found`, `current_url`

**핵심 흐름**
1. `async_playwright` 실행 → `GTM_AI_HEADLESS`가 `1|true|yes`가 아니면 **headed**(브라우저 창 표시)
2. `inject_listener(page)` — `add_init_script()`로 persistent listener 주입
3. 페이지 이동 후 `window.__gtm_captured` 읽기
4. LLM에 HTML 스냅샷 전달 → PLP/PDP/cart/checkout/home/unknown 반환
5. `datalayer_status` 결정: 이벤트 3개 이상 → "full", 1~2개 → "partial", 0개 → "none"

**UI 동기화**: `datalayer_status == "full"`이면 그래프가 Structure Analyzer를 건너뛰므로, 노드 1.5가 `queued`로 남지 않게 `nodes_status={"structure_analyzer": "skip"}`를 기록한다.

**브라우저 표시**: `serve_ui.py`는 에이전트 스레드 시작 시 `GTM_AI_HEADLESS` 미설정이면 **`0`을 기본값으로 넣어 headed**를 쓴다(`.env`에 `1`이면 headless). Windows·스레드 환경에 따라 창이 뒤에 깔리거나 간헐적으로 안 보일 수 있다.

**로그**: 노드 진입 시 `run.log`에 `[PageClassifier] Playwright headless=…` 한 줄이 남는다.

---

## Node 1.5 — `structure_analyzer.py`

**역할**: dataLayer 미완전 시 DOM/JSON-LD 구조 분석 (조건부 실행)

**실행 조건**: `datalayer_status != "full"`
**입력**: `target_url`, `page_type`
**출력**: `extraction_method`, `dom_selectors`, `selector_validation`, `json_ld_data`, `click_triggers`

**핵심 흐름**
1. JSON-LD 스크립트 태그 파싱 → 상품 스키마 추출
2. CSS selector로 가격·상품명·이미지 등 핵심 필드 후보 추출
3. 후보 selector를 페이지에서 실제 실행해 `selector_validation`에 저장
4. click_triggers: 찜/장바구니 버튼 selector 사전 탐색

**로그**: Playwright 기동 시 `run.log`에 `[StructureAnalyzer] Playwright headless=…` 한 줄.

---

## Node 2 — `journey_planner.py`

**역할**: 탐색 이벤트 큐 생성 + auto_capturable / manual_required 분류

**입력**: `user_request`, `page_type`, `datalayer_status`
**출력**: `exploration_queue`, `auto_capturable`, `manual_required`

**분류 기준**
```python
MANUAL_REQUIRED_EVENTS = {"purchase", "refund"}
# 그 외 모든 이벤트 → auto_capturable
```

**LLM 폴백**: 파싱 실패 시 `_default_queue(page_type, user_request)` 호출.
`add_to_wishlist` 등 user_request에 명시된 커스텀 이벤트도 큐에 자동 포함된다.

---

## Node 3 — `active_explorer.py`

**역할**: LLM Navigator + Playwright 루프로 이벤트 캡처 (시스템 핵심)

**입력**: `exploration_queue`, `auto_capturable`, `current_url`, `page_type`
**출력**: `captured_events`, `event_capture_log`, `manual_required`(갱신), `current_url`

**이벤트 캡처 우선순위 (반드시 이 순서)**
1. dataLayer 직접 캡처 (`window.__gtm_captured`)
2. 클릭 트리거 → dataLayer 확인 (DL/DOM 모드 무관하게 항상 시도)
3. 클릭 트리거 → DOM 추출 (dataLayer 미발화 시)
4. LLM Navigator 자동 탐색 → dataLayer 캡처
5. DOM 폴백
6. 실패 → `manual_required`로 이관

**핵심 변경**: `use_dom` 조건 제거 — click_triggers에 있는 이벤트는 항상 클릭 후 DL 발화를 먼저 확인.
DL 발화 → source 없음(CE Trigger), 미발화 → source="dom_extraction"(Click Trigger)로 자동 구분.

**Navigator 루프**
- `MAX_STEPS=6` 멀티스텝 탐색. 재시도가 아닌 스텝 진행 개념
- 이벤트별 **implicit**(view_item_list·view_cart) / **interaction**(add_to_cart 등) / **hybrid** — `navigator.py`에서 시스템·사용자 메시지로 분리해 LLM이 전략을 섞지 않게 함
- `LLMNavigator._action_history`에 세션 전체 액션 누적 — 이벤트 간 리셋 없음; 히스토리 텍스트에는 `scroll`의 **direction**, `navigate`의 **url**, `click`의 **단일 셀렉터**(쉼표 나열 시 첫 항만 실행)가 반영됨
- interaction·PDP URL이면 스냅샷 전 짧은 스크롤 + `get_page_snapshot(..., prefer_bottom=True)` 로 본문 가시성 보강
- LLM이 히스토리를 보고 "현재 어느 단계인지" 스스로 판단해 다음 액션 결정
- `EVENT_CAPTURE_GUIDE`는 "어떤 조건이 충족되어야 발화되는가" 목표 중심으로 서술
- 클릭 실패·타임아웃은 `ActionResult.success=False`로 처리, 예외 미발생

**브라우저**: `GTM_AI_HEADLESS=1|true|yes`이면 headless. 그 외(미설정 포함)는 headed — `serve_ui.py`는 `.env`에 값이 없을 때 **`0`을 기본 주입**한다. 숨김만 쓰려면 `.env`에 `GTM_AI_HEADLESS=1`.

**로그(멈춤 추적)**: `run.log`에 `[ActiveExplorer] Playwright headless=…`, Navigator 루프의 `[Navigator] run_for_event …` / `decide_next_action …` / `LLM ainvoke …` / `액션 실행 끝 …` 및 `browser/actions.get_page_snapshot`의 `[Snapshot] page.content() …`·`완료`·`타임아웃`이 순서대로 찍힌다(스냅샷은 `page.content()` 30초 상한).

**UI 동기화**: `manual_required`가 비어 있으면 Manual Capture 노드는 그래프에서 호출되지 않으므로, 탐색 종료 시 `nodes_status={"manual_capture": "skip"}`를 기록한다.

**event_capture_log 항목 구조**
```python
{
    "event": str,
    "method": str,      # "datalayer" | "click_datalayer" | "dom_extraction" | "manual" | "skipped"
    "success": bool,
    "data": dict,       # 캡처된 파라미터
    "note": str,        # 특이사항
}
```

---

## Node 4 — `manual_capture.py`

**역할**: purchase/refund 등 자동화 불가 이벤트의 수동 캡처 게이트웨이

**실행 조건**: `manual_required` 비어있지 않음
**입력**: `manual_required`
**출력**: `manual_capture_results`

**동작**: 각 이벤트에 대해 사용자에게 직접 데이터를 요청하거나 스킵(C) 선택.
CLI 모드에서는 `input()`, file 모드에서는 hitl_response.json 방식과 동일.

---

## Node 5 — `planning.py`

**역할**: GTM 설계안 생성(LLM) + HITL 승인

**입력**: `captured_events`, `manual_capture_results`, `extraction_method`, `tag_type`, `measurement_id`
**출력**: `plan`, `plan_approved`, `hitl_feedback`, `doc_context`

**설계안 JSON 구조**
```json
{
  "variables": [{ "name": "DLV - event", "type": "v", "parameters": [...] }],
  "triggers":  [{ "name": "CE - view_item", "type": "customEvent", "customEventFilter": [...] }],
  "tags":      [{ "name": "GA4 - view_item", "type": "gaawe", "event_parameters": [...], "firing_trigger_names": [...] }]
}
```

**단일 시스템 프롬프트 (`_PLANNING_SYSTEM`)**
LLM이 각 이벤트의 `source` 필드를 보고 이벤트별로 판단:
- `source` 없음 / `"datalayer"` / `"datalayer+dom"` → CE Trigger + DLV Variable
- `source = "dom_extraction"` → Click Trigger + DOM/CJS Variable
- 비표준 이벤트명(addToCart 등)도 실제 이름 그대로 CE Trigger 생성

`_classify_events` / `effective_method` 전역 분기 제거 — 이벤트별 개별 판단.

**HITL 대기**
- `hitl_mode="cli"` → `input()` 폴링
- `hitl_mode="file"` → `logs/{run_id}/hitl_response.json` 5분 폴링, 타임아웃 시 자동 승인

거부 시 `hitl_feedback`을 받아 `while True` 루프에서 재설계.

---

## Node 6 — `gtm_creation.py`

**역할**: Variable → Trigger → Tag 순서로 GTM 리소스 생성

**입력**: `plan`, `account_id`, `container_id`
**출력**: `workspace_id`, `created_variables`, `created_triggers`, `created_tags`

**실행 순서 엄수**: Variable → Trigger → Tag (의존 관계)
**이름 충돌**: `create_or_update_*` 메서드로 덮어쓰기
**Rate Limit(429)**: 최대 3회 재시도(30/60/90초), 실패 시 기존 `gtm-ai-*` workspace 재사용
**Workspace**: 실행마다 `gtm-ai-{timestamp}` 이름으로 신규 생성

`plan` 자동 보정 (`_fix_plan`): 누락 트리거 생성 + 잘못된 `firing_trigger_names` 수정.

**UI 동기화 (`state.json`)**
- 성공·실패 모두 `_sync_created_resources_ui(...)`로 `workspace_id`, `created_variables` / `created_triggers` / `created_tags`를 `state.json`에 반영한다.  
  (이전에는 성공 시에만 반영되어, 실패 Run에서 Report와 Resources 탭 내용이 어긋날 수 있었다.)
- 설계안 없음·Workspace 생성 불가·예외 경로에서도 `gtm_creation` 노드 exit / `nodes_status`를 일관되게 남긴다.

---

## Node 7 — `publish.py`

**역할**: GTM Workspace를 Version으로 생성 후 Publish

**입력**: `workspace_id`, `account_id`, `container_id`
**출력**: `publish_result`

```python
publish_result = {
    "success": bool,
    "version_id": str,   # 성공 시
    "warning": str,      # 실패/경고 시 (insufficientPermissions 등)
}
```

Publish 권한 없으면 오류 대신 `publish_warning`에 메시지 기록 후 계속 진행.

---

## Node 8 — `reporter.py`

**역할**: 실행 결과 마크다운 보고서 생성 (항상 마지막 실행, 오류 경로 포함)

**입력**: state 전체
**출력**: `report_path` (`logs/{run_id}/report.md`)

**UI 동기화**
- 진입 직전 `reconcile_timeline_at_reporter(has_error=...)` 호출로 타임라인 `queued`/`run` 잔류를 정리한다.
- `update_state`에서는 전역 `status`를 덮어쓰지 않는다(최종 `done`/`failed`는 `runner.py`가 기록).

**보고서 섹션**
1. 기본 정보 (URL, 태그 유형, 실행 시간)
2. dataLayer 분석 (`datalayer_status`, `extraction_method`)
3. 이벤트별 처리 내역 (`event_capture_log` 기반 표)
4. 특이사항
5. GTM 생성 결과 (Variable/Trigger/Tag 수)
6. Publish 결과

reporter는 절대 생략되지 않는다 — `graph.py`의 오류 경로 엣지 모두 reporter로 귀결.
