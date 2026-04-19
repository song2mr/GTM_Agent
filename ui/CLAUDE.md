# ui CLAUDE.md

React + Babel CDN 기반 단일 페이지 UI. 빌드 없이 `serve_ui.py`가 정적 파일로 서빙.

---

## 이벤트 선택(Explicit Scope)

`RunStartScreen`은 **설치할 이벤트**를 `EventPicker`(`ui.jsx`)로 구조화 입력받아
`POST /api/run` 본문에 `selected_events: string[]`(소문자 GA4 이벤트명)으로 실어 보낸다.

- `EventPicker` 구성: GA4 표준 이벤트 체크박스 + Manual 전용 체크박스 + 프리셋 버튼 + 커스텀 입력
- 프리셋(`EVENT_PRESETS` in `ui.jsx`): `GA4 이커머스 전체` · `구매 퍼널 핵심` · `조회만` · `관심상품 포함`
- `localStorage("gtm:config")`에 `selectedEvents`로 저장 → 다음 방문 시 자동 복원
- 서버(`agent/request_events.resolve_selected_events`)는 이 목록이 있으면 strict 모드로
  Journey Planner/Planning이 이 목록만 다루고, 비어 있으면 `user_request` 괄호 파서 → LLM으로 폴백한다.
  기존 자유 텍스트 UI(괄호 포함)는 CLI/레거시 호환으로만 남아 있다.

---

## 파일 구성

| 파일 | 역할 |
|------|------|
| `index.html` | 진입점, script 로드 순서 정의 |
| `src/api.jsx` | 데이터 훅 (`useRunLog`, `useHistory`, `useReport`, `useWorkspaces`) |
| `src/ui.jsx` | 공통 컴포넌트 (`Icon`, `Sidebar`, `Topbar`, `Timeline`, `Thoughts`, `Markdown`, `EventPicker`) |
| `src/screens.jsx` | 화면 컴포넌트 (7개 Screen) |
| `src/app.jsx` | 라우터, `App` 루트, `Tweaks` 패널 |
| `styles.css` | 전체 스타일 (CSS 변수 기반 다크 테마) |

**로드 순서**: `api.jsx` → `ui.jsx` → `screens.jsx` → `app.jsx`
순서를 바꾸면 전역 변수 참조 오류 발생.

**컴포넌트 정의 위치 주의**: 컴포넌트 함수를 다른 컴포넌트 렌더 함수 **내부**에서 선언하면
상태 변경 시마다 React가 새 타입으로 인식해 DOM을 unmount/remount한다 → input 포커스 소실.
재사용 컴포넌트는 반드시 모듈 최상위 레벨에 정의하고, 필요한 state는 prop으로 전달한다.

---

## 데이터 흐름

```
serve_ui.py
  ├─ POST /api/run   → 에이전트 스레드 시작
  ├─ POST /api/hitl  → hitl_response.json 파일 기록
  └─ GET  /*         → 정적 파일 (ui/, logs/)

브라우저 폴링 (1.5초)
  ├─ logs/{run_id}/state.json    → useRunLog.state
  ├─ logs/{run_id}/events.jsonl  → useRunLog.events / thoughts / plan / publishResult (`node_enter`로 thought에 nodeKey 태깅)
  ├─ logs/{run_id}/run.log       → 백엔드 상세(예: `[Snapshot]`, `[Navigator]` 단계, Playwright headless 여부)
  ├─ logs/{run_id}/report.md     → useReport
  └─ logs/index.json             → useHistory
```

모든 상태는 파일 기반 폴링으로 동기화된다. WebSocket 없음.

**Live 타임라인 UX**
- 노드 `status`: `queued` | `run` | `done` | `failed` | `skip` | `hitl_wait` 등. 분기 미진입 노드는 백엔드에서 `skip`으로 정리되는 경우가 많다.
- 기본 하이라이트: 실행 중은 `current_node`, 종료(`done`/`failed`) 후에는 **마지막 완료·실패·생략 노드**를 강조해 첫 노드로만 포커스가 가는 문제를 방지한다.
- 우측 Thought 패널: 선택한 타임라인 노드의 `key`와 `thought.nodeKey`가 일치하는 항목만 표시(구 로그는 태그 없으면 전체 표시).

---

## 훅 (`api.jsx`)

### useRunLog(runId)
```js
const { state, events, thoughts, plan, workspaceAsk, publishResult } = useRunLog(runId)
```
- `state`: `state.json` 전체 (nodes, status, token_usage, `created_*`, `workspace_id` 등)
- `events`: `datalayer_event` 타입만 필터
- `thoughts`: `thought` 타입만 필터. 증분 파싱 시 직전 `node_enter`의 `node_key`를 `nodeKey` 필드로 붙여 **노드별 필터**에 사용. `time`은 로그 `ts`(UTC)를 **`Asia/Seoul`** 기준 `HH:mm:ss`로 변환한 값
- `plan`: `hitl_request` 이벤트 중 `kind`가 없거나 `"plan"`인 것의 `plan` 필드 (Node 5 설계안 검토)
- `workspaceAsk`: `hitl_request` 이벤트 중 `kind="workspace_full"`의 페이로드 — `{workspaces, current_count, limit, default_reuse_id, message}`. `runner.py`가 그래프 시작 전에 한도(3)를 감지했을 때 또는 Node 6에서 감지했을 때 세팅(폼에 `workspace_id`가 이미 있으면 사전 HITL 생략). `hitl_decision` 수신 시 `null`로 초기화
- `publishResult`: `publish_result` 이벤트

### useWorkspaces()
```js
const { workspaces, activeId, activeWorkspace, add, update, remove, setActive } = useWorkspaces()
```
localStorage(`gtm:workspaces`, `gtm:activeWorkspace`) 기반.
`setActive(id)` 호출 시 `gtm:config`도 동기화 → `RunStartScreen` 폼 자동 반영.

### useHistory()
`logs/index.json` 10초마다 폴링.

### useReport(runId)
`logs/{run_id}/report.md` 5초마다 폴링.

---

## 화면 구성 (`screens.jsx`)

| Screen | route | 설명 |
|--------|-------|------|
| `RunStartScreen` | `start` | 새 Run 설정 폼 — **설치 이벤트는 `EventPicker`(체크박스·프리셋·커스텀 입력)로 구조화 입력**. `USER_REQUEST` 텍스트는 참고용 메모이며, 서버에는 `selected_events: string[]`로 전송된다. |
| `RunLiveScreen` | `live` | 노드 타임라인(`Timeline`) + 선택 노드별 Thought 필터 + dataLayer 테이블 |
| `HitlScreen` | `hitl` | GTM 설계안 검토·승인 |
| `HistoryScreen` | `history` | 실행 이력 목록 |
| `ResourcesScreen` | `resources` | 생성된 GTM 리소스 목록 |
| `ReportScreen` | `report` | 마크다운 보고서 렌더링 |
| `WorkspaceScreen` | `workspace` | GTM 컨테이너 구성 관리 |

---

## 라우팅 (`app.jsx`)

URL `?screen={route}&run={run_id}` 파라미터로 관리.
`navigate(runId, route)` 함수로 URL + React state 동시 업데이트.

```js
routeMap = {
  run: "live", history: "history", hitl: "hitl",
  resources: "resources", report: "report", workspace: "workspace"
}
```

---

## HITL 흐름

HITL 이벤트는 `kind` 필드로 구분한다. `POST /api/hitl` 요청 본문에도 동일한 `kind`를 실어야 한다.
`serve_ui.py`가 `kind="workspace_full"` 이면 `{decision, workspace_id}`, 그 외(`kind="plan"`)는 `{approved, feedback}` 스키마로 `hitl_response.json`에 기록한다.

### A. Plan 검토 (Node 5 `planning.py`)
1. `planning.py`가 `hitl_request`(`kind="plan"`, `plan`, `normalize_errors`) emit → `events.jsonl`에 기록
2. `useRunLog`가 `plan` state 업데이트
3. `HitlScreen`이 설계안 표시 + 승인/거부 버튼 노출
4. 승인 → POST `/api/hitl` `{kind:"plan", approved:true}` → `hitl_response.json` → 에이전트 재개 → `navigate("live")`
5. 거부 → `awaitingRedesign=true` → 에이전트가 재설계 후 새 `hitl_request` emit → 화면 자동 리셋

### B. 워크스페이스 상한 (`runner.py` 사전 + Node 6 `gtm_creation.py`)
1. `workspaces.list` 기준 상한(3)이고 Run 폼의 **workspace_id가 비어 있으면**, `runner.py`가 **그래프·브라우저·LLM 시작 전**에 `hitl_request`(`kind="workspace_full"`)를 emit하고 응답을 기다린다. 사용자가 재사용을 고르면 `initial_state["workspace_id"]`에 반영된다.
2. Node 6에서는 `workspace_id`가 이미 있으면 한도·HITL·신규 생성을 **건너뛰고** 바로 Variable/Trigger/Tag API를 호출한다(사전에 물었으면 Node 6에서 같은 질문을 반복하지 않음).
3. 사전 HITL을 건너뛴 경우(목록 조회 실패·워크스페이스 2개 이하·폼에 workspace_id 입력)에만, Node 6에서 이전과 같이 `hitl_request` 후 분기한다.
4. `useRunLog`가 `workspaceAsk` state 업데이트 → `app.jsx`가 자동으로 `route="hitl"` 로 전환하고 사이드바 Approvals 뱃지(●) 점등
5. `HitlScreen`이 Workspace 선택 카드를 **plan 검토보다 우선** 표시 — 라디오로 대상 작업공간을 고르고 `재사용` 또는 `실행 중단` 버튼 중 하나 클릭
6. `재사용` → POST `/api/hitl` `{kind:"workspace_full", decision:"reuse", workspace_id}` → (사전이면 그래프 진행 후 Node 6에서) 해당 Workspace에 Variable/Trigger/Tag를 생성
7. `실행 중단` 또는 5분 타임아웃 → `decision:"cancel"` → 사전이면 Run 즉시 `failed`, Node 6이면 해당 노드 `failed` 및 상세 `error`
8. 응답 즉시 `hitl_decision` 이벤트가 뒤따라 emit되어 UI 카드는 자동으로 닫힌다

---

## Tweaks 패널

개발/디자인 전용 오버레이. Topbar의 "Tweaks" 버튼으로 토글.

| 설정 | 옵션 | 설명 |
|------|------|------|
| DENSITY | tight / default / cozy | 전체 여백 조절 |
| VARIATION | A / C | A=기본, C=LangGraph 노드 그래프 |

localStorage 저장. 기본값은 `app.jsx`의 `TWEAK_DEFAULTS` 객체에서 관리.

---

## 스타일 시스템 (`styles.css`)

CSS 변수(`:root`) 기반 다크 테마. 주요 변수:

```css
--bg-base       /* 최하위 배경 */
--panel         /* 패널 배경 */
--line          /* 구분선 */
--ink-1 ~ --ink-4  /* 텍스트 계층 */
--accent        /* 강조색 */
--accent-ink    /* 강조 텍스트 */
--danger        /* 오류색 */
--warn          /* 경고색 */
```

새 컴포넌트 추가 시 인라인 스타일보다 CSS 변수를 사용한다.

---

## 2026-04-19 업데이트 (CanPlan/HITL)

- Planning HITL 페이로드는 `plan` 외에 `normalize_errors`를 함께 전달한다.
- Reporter는 `canplan_hash`와 정규화 결과 요약을 출력하므로, UI도 해당 필드를 읽어 확장할 수 있다.
- 전환기에는 기존 `plan` 렌더와 CanPlan 렌더를 병행할 수 있도록 상태 필드를 유지한다.
