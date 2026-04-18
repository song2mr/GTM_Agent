# agent/nodes CLAUDE.md

Node 1~8 각각의 역할, 입출력, 핵심 로직, 주의사항.

---

## Node 1 — `page_classifier.py`

**역할**: 페이지 로드 + Persistent Event Listener 주입 + 페이지 타입 판단 + 로드타임 이벤트 수집

**입력**: `target_url`
**출력**: `page_type`, `datalayer_status`, `datalayer_events_found`, `current_url`

**핵심 흐름**
1. `async_playwright` 실행 → `headless=False`로 Chromium 실행
2. `inject_listener(page)` — `add_init_script()`로 persistent listener 주입
3. 페이지 이동 후 `window.__gtm_captured` 읽기
4. LLM에 HTML 스냅샷 전달 → PLP/PDP/cart/checkout/home/unknown 반환
5. `datalayer_status` 결정: 이벤트 3개 이상 → "full", 1~2개 → "partial", 0개 → "none"

**주의**: `headless=False`는 CLI(`main.py`) 직접 실행 시에만 창이 보인다.
`serve_ui.py`(백그라운드 스레드)에서는 창이 뜨지 않는다 — 의도된 동작.

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
- 최대 3회 재시도 후 실패 시 manual로 전환
- `EVENT_CAPTURE_GUIDE` 딕셔너리로 이벤트별 탐색 힌트 관리
- 클릭 실패·타임아웃은 `ActionResult.success=False`로 처리, 예외 미발생

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

**보고서 섹션**
1. 기본 정보 (URL, 태그 유형, 실행 시간)
2. dataLayer 분석 (`datalayer_status`, `extraction_method`)
3. 이벤트별 처리 내역 (`event_capture_log` 기반 표)
4. 특이사항
5. GTM 생성 결과 (Variable/Trigger/Tag 수)
6. Publish 결과

reporter는 절대 생략되지 않는다 — `graph.py`의 오류 경로 엣지 모두 reporter로 귀결.
