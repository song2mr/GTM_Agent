# GTM AI UI — 로컬 프로젝트 적용 가이드

> 이 문서는 Claude Desktop 'gtm ai' 디자인 프로젝트에서 만든 UI를
> 사용자님의 로컬 `gtm_ai/` Python 프로젝트에 붙이기 위한 가이드입니다.
> 이 문서를 Claude Code에 그대로 전달해도 됩니다.

---

## 목표

- LangGraph 에이전트가 실행될 때 `logs/{run_id}/` 아래에 **구조화된 이벤트 파일**을 남긴다.
- 별도 API 서버 없이, 정적 HTML UI가 그 파일들을 `fetch()`로 읽어 렌더링한다.
- 테스트 단계에선 이거 하나로 충분하다 (나중에 WebSocket/FastAPI로 교체 쉬움).

---

## ⚠️ 변경된 점 (개발 단에서 반영 필요)

### GTM 자격 정보를 `.env` 대신 **UI 입력**으로 이동

**기존:**
- `.env`의 `GTM_ACCOUNT_ID`, `GTM_CONTAINER_ID`, `GTM_WORKSPACE_ID`를 `main.py`가 읽음
- `os.environ["GTM_ACCOUNT_ID"]` 필수 체크

**변경:**
- **`main.py`는 더 이상 이 값들을 `.env`에서 읽지 않는다** — UI 폼에서 입력받아 전달
- `.env`에는 `OPENAI_API_KEY`만 남김 (OAuth는 `credentials/token.json`이 관리)
- 실행 방식이 CLI `input()` → UI → 백엔드 호출로 바뀌므로, `main.py`를 다음과 같이 분리:

```
main.py         → CLI 호환 엔트리 (기존 input() 방식 유지, 옵션)
agent/runner.py → run_agent(config: dict) 함수 — UI/CLI 공통 진입점
```

`agent/runner.py` 예시:
```python
async def run_agent(config: dict) -> dict:
    """
    config: {
        "target_url": str,
        "user_request": str,
        "tag_type": "GA4"|"naver"|"kakao",
        "account_id": str,           # ← UI 폼에서 전달 (필수)
        "container_id": str,         # ← UI 폼에서 전달 (필수)
        "workspace_id": str,         # ← UI 폼에서 전달 (선택, 비면 자동 생성)
        "measurement_id": str,       # ← UI 폼에서 전달 (선택)
    }
    """
    # 환경변수 의존 제거 — config에서만 읽기
    initial_state: GTMAgentState = {
        "user_request": config["user_request"],
        "target_url": config["target_url"],
        "tag_type": config["tag_type"],
        "account_id": config["account_id"],
        "container_id": config["container_id"],
        "workspace_id": config.get("workspace_id", ""),
        # … 나머지 초기화 동일
    }
    # Measurement ID는 user_request 파싱 대신 config에서 직접 주입
    if config.get("measurement_id"):
        initial_state["measurement_id"] = config["measurement_id"]
    # … graph.ainvoke(initial_state)
```

**`agent/state.py`에 필드 추가:**
```python
class GTMAgentState(TypedDict):
    # … 기존 …
    measurement_id: str   # ★ 신규 — UI 폼에서 전달된 G-XXXXXXXX
```

**`agent/nodes/planning.py` 수정:**
- 기존에 `user_request`에서 정규식으로 `G-XXXXXXXX` 뽑던 로직을
  `state["measurement_id"]`로 교체 (있으면 우선, 없으면 기존 방식 폴백).

**`.env.example` 업데이트:**
```env
# 이전: GTM_ACCOUNT_ID, GTM_CONTAINER_ID, GTM_WORKSPACE_ID 필요
# 이후: OPENAI_API_KEY만 필요. GTM 정보는 UI에서 입력
OPENAI_API_KEY=
```

**UI → 백엔드 전달 방식 (현재 파일 기반 구조에서):**
- UI는 사용자가 "에이전트 실행"을 누르면 `logs/pending/run_request.json`에 config를 쓴다
- 별도 워커 스크립트 `run_watcher.py`가 이 파일을 감지해 `run_agent(config)` 호출
- 또는 임시로: 사용자가 UI에서 config를 채우고 **"복사하여 실행"** 버튼으로 CLI 명령을 생성
  → `python -m agent.runner --url=… --account=… --container=…`

**localStorage 저장:**
- UI는 account/container 등을 `localStorage['gtm:config']`에 보관 (체크박스 토글 시)
- 민감 정보는 로컬에서만, 서버로는 OAuth 토큰이 이미 `credentials/token.json`에 있으므로 추가 저장 불필요

---

## 폴더 구조 (적용 후)

```
gtm_ai/
├── main.py                     # 기존
├── agent/…                     # 기존
├── browser/…                   # 기존
├── utils/
│   ├── logger.py               # 기존 — 유지
│   └── ui_emitter.py           # ★ 신규: JSONL 이벤트 emit
├── logs/
│   └── {run_id}/
│       ├── run.log             # 기존
│       ├── events.jsonl        # ★ 신규: UI가 구독할 이벤트 스트림
│       ├── state.json          # ★ 신규: 현재 Node, 상태 요약 (덮어쓰기)
│       ├── plan.json           # ★ 신규: HITL 시 기록되는 설계안
│       ├── report.md           # 기존
│       └── screenshots/        # 기존
├── ui/                         # ★ 신규: UI 전체
│   ├── index.html
│   ├── styles.css
│   └── src/
│       ├── data.jsx            # (목업은 제거, 대신 api.jsx 사용)
│       ├── api.jsx             # ★ 신규: logs 폴더 구독
│       ├── ui.jsx
│       ├── screens.jsx
│       └── app.jsx
└── serve_ui.py                 # ★ 신규: 로컬 정적 서버 (선택)
```

---

## 1. UI 파일 복사

Claude Desktop 'gtm ai' 프로젝트의 다음 파일들을 로컬 `gtm_ai/ui/`로 복사:

- `index.html` → `gtm_ai/ui/index.html`
- `styles.css` → `gtm_ai/ui/styles.css`
- `src/ui.jsx` → `gtm_ai/ui/src/ui.jsx`
- `src/screens.jsx` → `gtm_ai/ui/src/screens.jsx`
- `src/app.jsx` → `gtm_ai/ui/src/app.jsx`
- `src/data.jsx` → (참고용으로만 남기고, 실제로는 `api.jsx`가 대체)

---

## 2. 이벤트 스키마 (가장 중요)

`logs/{run_id}/events.jsonl` — 한 줄에 JSON 하나씩 append.
UI는 이 파일을 polling (1~2초)으로 읽고 마지막 오프셋 이후만 처리.

### 공통 필드
```json
{ "ts": "2026-04-18T09:22:14.812Z", "type": "...", ... }
```

### 이벤트 타입

| type | 발생 시점 | 페이로드 |
|---|---|---|
| `run_start` | main.py 시작 | `{ run_id, target_url, user_request, tag_type, account_id, container_id }` |
| `node_enter` | 각 Node 진입 | `{ node_id, node_key, title }` |
| `node_exit`  | 각 Node 종료 | `{ node_id, status: "done"|"failed"|"skipped", duration_ms, tokens_in, tokens_out }` |
| `thought`    | LLM 판단 | `{ who: "agent"|"tool"|"user", label, text, kind?: "plain"|"tool"|"highlight" }` |
| `datalayer_event` | Playwright가 DL 이벤트 캡처 | `{ event, url, source: "datalayer"|"dom"|"json_ld", params }` |
| `hitl_request` | Node 5 Plan 생성 | `{ plan: { variables, triggers, tags } }` → `plan.json`도 같이 씀 |
| `hitl_decision` | 사용자 y/n | `{ approved: bool, feedback?: string }` |
| `gtm_created` | Node 6 | `{ kind: "variable"|"trigger"|"tag", name, operation: "create"|"update" }` |
| `publish_result` | Node 7 | `{ success: bool, warning?: string, version_id?: string }` |
| `run_end` | 마지막 | `{ report_path, duration_ms, token_usage }` |

### 예시 events.jsonl (발췌)
```jsonl
{"ts":"2026-04-18T09:22:14.000Z","type":"run_start","run_id":"20260418_092214","target_url":"https://shop.leekorea.co.kr","user_request":"GA4 …","tag_type":"GA4"}
{"ts":"2026-04-18T09:22:14.050Z","type":"node_enter","node_id":1,"node_key":"page_classifier","title":"Page Classifier"}
{"ts":"2026-04-18T09:22:15.120Z","type":"thought","who":"tool","label":"playwright.navigate","text":"GET https://shop.leekorea.co.kr → 200","kind":"tool"}
{"ts":"2026-04-18T09:22:23.400Z","type":"thought","who":"agent","label":"PageClassifier","text":"datalayer_status = 'full'. 추출 방식: datalayer."}
{"ts":"2026-04-18T09:22:23.800Z","type":"node_exit","node_id":1,"status":"done","duration_ms":8200,"tokens_in":8400,"tokens_out":4000}
{"ts":"2026-04-18T09:22:31.104Z","type":"datalayer_event","event":"view_item_list","url":"/category/best","source":"datalayer","params":{"item_list_id":"best","items":24}}
```

### state.json (덮어쓰기)

UI가 처음 페이지 로드했을 때 현재 상태를 빠르게 가져가기 위한 스냅샷.
각 Node 진입/종료 시마다 전체를 덮어쓴다.

```json
{
  "run_id": "20260418_092214",
  "status": "running",
  "current_node": 3,
  "nodes": [
    {"id":1, "title":"Page Classifier", "status":"done", "duration":"8.2s", "tokens":"12.4k"},
    {"id":1.5,"title":"Structure Analyzer","status":"done","duration":"4.1s","tokens":"3.2k"},
    {"id":2, "title":"Journey Planner","status":"done","duration":"2.9s","tokens":"2.8k"},
    {"id":3, "title":"Active Explorer","status":"run","duration":"1m 42s","tokens":"48.1k"},
    {"id":4, "title":"Manual Capture","status":"queued"},
    {"id":5, "title":"Planning · HITL","status":"queued"},
    {"id":6, "title":"GTM Creation","status":"queued"},
    {"id":7, "title":"Publish","status":"queued"},
    {"id":8, "title":"Reporter","status":"queued"}
  ],
  "token_usage": {"in": 48200, "out": 12100, "usd": 0.18}
}
```

---

## 3. Python 측 구현

### `utils/ui_emitter.py` (신규 파일)

```python
"""UI가 구독할 수 있도록 logs/{run_id}/ 아래 JSONL/JSON 파일로 이벤트를 emit.

사용 예:
    from utils.ui_emitter import emit, set_run_dir, update_state

    set_run_dir(run_dir)  # logger.setup()이 반환한 경로
    emit("run_start", run_id=run_id, target_url=url, ...)
    emit("node_enter", node_id=1, node_key="page_classifier", title="Page Classifier")
    emit("thought", who="agent", label="PageClassifier", text="…")
    emit("datalayer_event", event="view_item", url="/product/3481", source="datalayer", params={...})
    update_state(current_node=3, nodes=[...])
"""

from __future__ import annotations
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_lock = threading.Lock()
_run_dir: Path | None = None


def set_run_dir(path: str | Path) -> None:
    global _run_dir
    _run_dir = Path(path)
    _run_dir.mkdir(parents=True, exist_ok=True)
    # 빈 파일 초기화
    events = _run_dir / "events.jsonl"
    if not events.exists():
        events.touch()


def emit(event_type: str, **payload: Any) -> None:
    if _run_dir is None:
        return
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "type": event_type,
        **payload,
    }
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with _lock:
        with (_run_dir / "events.jsonl").open("a", encoding="utf-8") as f:
            f.write(line)


def update_state(**fields: Any) -> None:
    if _run_dir is None:
        return
    path = _run_dir / "state.json"
    with _lock:
        current: dict = {}
        if path.exists():
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                current = {}
        current.update(fields)
        path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")


def write_plan(plan: dict) -> None:
    if _run_dir is None:
        return
    (_run_dir / "plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )
```

### `main.py` 수정 (초기화 구간)

```python
from utils.ui_emitter import set_run_dir, emit, update_state

run_dir = logger.setup()   # 기존
set_run_dir(run_dir)       # ★ 추가

emit("run_start",
     run_id=run_dir.name,
     target_url=target_url,
     user_request=user_request,
     tag_type=tag_type,
     account_id=os.environ["GTM_ACCOUNT_ID"],
     container_id=os.environ["GTM_CONTAINER_ID"])
```

### LangGraph 노드에 `emit` 훅 추가

가장 간단한 방법: `agent/orchestrator.py` 또는 각 `agent/nodes/*.py`에
node 진입/종료 지점에 넣기. 예시:

```python
# agent/nodes/active_explorer.py
from utils.ui_emitter import emit, update_state
import time

async def active_explorer(state: GTMAgentState) -> GTMAgentState:
    emit("node_enter", node_id=3, node_key="active_explorer", title="Active Explorer")
    started = time.time()
    # … 기존 로직 …
    # LLM 판단 직후:
    emit("thought", who="agent", label="Navigator",
         text=llm_reasoning_text, kind="plain")
    # dataLayer 이벤트 캡처 직후:
    emit("datalayer_event", event=ev["event"], url=ev["url"],
         source="datalayer", params=ev.get("params", {}))

    duration_ms = int((time.time() - started) * 1000)
    emit("node_exit", node_id=3, status="done", duration_ms=duration_ms,
         tokens_in=tt_in, tokens_out=tt_out)
    return state
```

### Playwright 액션 래퍼 (`browser/actions.py`) 에 훅

```python
from utils.ui_emitter import emit

async def click(page, selector: str):
    emit("thought", who="tool", label="playwright.click",
         text=selector, kind="tool")
    # … 기존 로직 …
```

### HITL 훅 (`agent/nodes/planning.py`)

```python
from utils.ui_emitter import emit, write_plan

# plan 생성 직후
write_plan(plan)
emit("hitl_request", plan=plan)

# 사용자 y/n 입력 이후
emit("hitl_decision", approved=True, feedback="")
```

---

## 4. UI 측 구현 (`ui/src/api.jsx` 신규)

데이터 소스를 교체하기 위해 `api.jsx`를 추가하고, 기존 `screens.jsx`에서
`window.CAPTURED_EVENTS` / `window.THOUGHTS` / `window.PLAN` / `window.NODES` /
`window.HISTORY` / `window.REPORT_MD` 를 읽던 부분을 이 api의 상태로 교체.

```jsx
/* global React */
// ui/src/api.jsx — logs/{run_id}/ 폴더를 구독하는 훅

const POLL_MS = 1500;

window.useRunLog = function useRunLog(runId) {
  const [state, setState] = React.useState({ nodes: [], status: "loading" });
  const [events, setEvents] = React.useState([]);       // datalayer_event
  const [thoughts, setThoughts] = React.useState([]);
  const [plan, setPlan] = React.useState(null);
  const offsetRef = React.useRef(0);

  const base = `logs/${runId}`;

  React.useEffect(() => {
    let alive = true;

    async function tick() {
      // 1) state.json — 스냅샷
      try {
        const s = await fetch(`${base}/state.json`, { cache: "no-store" });
        if (s.ok) setState(await s.json());
      } catch {}

      // 2) events.jsonl — 증분 읽기
      try {
        const r = await fetch(`${base}/events.jsonl`, { cache: "no-store" });
        if (r.ok) {
          const txt = await r.text();
          const newPart = txt.slice(offsetRef.current);
          offsetRef.current = txt.length;
          const lines = newPart.split("\n").filter(Boolean);
          for (const line of lines) {
            let ev; try { ev = JSON.parse(line); } catch { continue; }
            if (ev.type === "datalayer_event") {
              setEvents(cur => [...cur, {
                t: ev.ts.slice(11, 23), event: ev.event, url: ev.url,
                source: ev.source, params: ev.params, status: "ok",
              }]);
            } else if (ev.type === "thought") {
              setThoughts(cur => [...cur, {
                who: ev.who, label: ev.label, time: ev.ts.slice(11, 19),
                kind: ev.kind || "plain", text: ev.text,
              }]);
            } else if (ev.type === "hitl_request") {
              setPlan(ev.plan);
            }
          }
        }
      } catch {}
      if (alive) setTimeout(tick, POLL_MS);
    }
    tick();
    return () => { alive = false; };
  }, [runId]);

  return { state, events, thoughts, plan };
};

window.useHistory = function useHistory() {
  const [items, setItems] = React.useState([]);
  React.useEffect(() => {
    fetch("logs/index.json", { cache: "no-store" })
      .then(r => r.ok ? r.json() : [])
      .then(setItems)
      .catch(() => setItems([]));
  }, []);
  return items;
};

window.useReport = function useReport(runId) {
  const [md, setMd] = React.useState("");
  React.useEffect(() => {
    fetch(`logs/${runId}/report.md`, { cache: "no-store" })
      .then(r => r.ok ? r.text() : "")
      .then(setMd);
  }, [runId]);
  return md;
};
```

`index.html`의 script 태그에 추가:
```html
<script type="text/babel" src="src/api.jsx"></script>
```

`screens.jsx`에서 교체 예시 (RunLiveScreen):
```jsx
function RunLiveScreen({ runId, variation }) {
  const { state, events, thoughts } = window.useRunLog(runId);
  const nodes = state.nodes.length ? state.nodes : window.NODES; // fallback
  // … thoughts, events 를 그대로 Thoughts / dataLayer table 에 전달
}
```

**History 인덱스(`logs/index.json`) 만들기**:
Python 쪽에서 run 종료 시 `logs/` 폴더 전체를 스캔해 배열로 쓰는 작은 스크립트 추가
(또는 UI가 폴더 목록 대신 `run_id` 하나만 URL 쿼리(`?run=20260418_092214`)로 받도록 해도 OK).

---

## 5. 로컬 서버 (선택)

`file://`에선 `fetch()`가 막히므로 정적 서버가 필요. `serve_ui.py`:

```python
"""간단한 로컬 정적 서버.

실행:
    python serve_ui.py
    → http://localhost:8765/ui/

logs/는 동일 디렉토리에서 같이 서빙되므로 UI가 fetch('logs/…') 가능.
"""
import http.server, socketserver, os

PORT = 8765
os.chdir(os.path.dirname(os.path.abspath(__file__)))

class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # 개발용: 캐시 끄기
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

with socketserver.TCPServer(("", PORT), Handler) as httpd:
    print(f"Serving gtm_ai at http://localhost:{PORT}/ui/")
    httpd.serve_forever()
```

열기: `http://localhost:8765/ui/?run=20260418_092214`

---

## 6. 검증 체크리스트

- [ ] `python main.py` 실행 시 `logs/{run_id}/events.jsonl`, `state.json`이 생성됨
- [ ] 각 Node가 `node_enter`/`node_exit`을 emit
- [ ] Playwright click/navigate가 `thought` (kind=tool)으로 기록됨
- [ ] LLM 판단이 `thought` (who=agent)으로 기록됨
- [ ] dataLayer 캡처가 `datalayer_event`로 기록됨
- [ ] Planning 직후 `plan.json` + `hitl_request` 이벤트 존재
- [ ] `serve_ui.py` 실행 후 `http://localhost:8765/ui/?run=…` 열면 타임라인/말풍선/이벤트가 실시간 업데이트됨

---

## 7. 나중에 진짜 API로 바꿀 때

`api.jsx`의 `fetch('logs/…')` 부분만 WebSocket 구독으로 교체하면 끝.
나머지 UI 구조는 동일하게 사용 가능.
