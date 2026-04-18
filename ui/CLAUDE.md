# ui CLAUDE.md

React + Babel CDN 기반 단일 페이지 UI. 빌드 없이 `serve_ui.py`가 정적 파일로 서빙.

---

## 파일 구성

| 파일 | 역할 |
|------|------|
| `index.html` | 진입점, script 로드 순서 정의 |
| `src/api.jsx` | 데이터 훅 (`useRunLog`, `useHistory`, `useReport`, `useWorkspaces`) |
| `src/ui.jsx` | 공통 컴포넌트 (`Icon`, `Sidebar`, `Topbar`, `Timeline`, `Thoughts`, `Markdown`) |
| `src/screens.jsx` | 화면 컴포넌트 (7개 Screen) |
| `src/app.jsx` | 라우터, `App` 루트, `Tweaks` 패널 |
| `styles.css` | 전체 스타일 (CSS 변수 기반 다크 테마) |

**로드 순서**: `api.jsx` → `ui.jsx` → `screens.jsx` → `app.jsx`
순서를 바꾸면 전역 변수 참조 오류 발생.

---

## 데이터 흐름

```
serve_ui.py
  ├─ POST /api/run   → 에이전트 스레드 시작
  ├─ POST /api/hitl  → hitl_response.json 파일 기록
  └─ GET  /*         → 정적 파일 (ui/, logs/)

브라우저 폴링 (1.5초)
  ├─ logs/{run_id}/state.json    → useRunLog.state
  ├─ logs/{run_id}/events.jsonl  → useRunLog.events / thoughts / plan / publishResult
  ├─ logs/{run_id}/report.md     → useReport
  └─ logs/index.json             → useHistory
```

모든 상태는 파일 기반 폴링으로 동기화된다. WebSocket 없음.

---

## 훅 (`api.jsx`)

### useRunLog(runId)
```js
const { state, events, thoughts, plan, publishResult } = useRunLog(runId)
```
- `state`: `state.json` 전체 (nodes, status, token_usage 등)
- `events`: `datalayer_event` 타입만 필터
- `thoughts`: `thought` 타입만 필터
- `plan`: 가장 최근 `hitl_request` 이벤트의 `plan`
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
| `RunStartScreen` | `start` | 새 Run 설정 폼 |
| `RunLiveScreen` | `live` | 노드 타임라인 + dataLayer 캡처 테이블 |
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

1. `planning.py`가 `hitl_request` 이벤트 emit → `events.jsonl`에 기록
2. `useRunLog`가 `plan` state 업데이트
3. `HitlScreen`이 설계안 표시 + 승인/거부 버튼 노출
4. 승인 → POST `/api/hitl` → `hitl_response.json` → 에이전트 재개 → `navigate("live")`
5. 거부 → `awaitingRedesign=true` → 에이전트가 재설계 후 새 `hitl_request` emit → 화면 자동 리셋

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
