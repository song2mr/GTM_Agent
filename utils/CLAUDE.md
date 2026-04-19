# utils CLAUDE.md

에이전트 실행 중 발생하는 이벤트를 UI에 스트리밍하고 토큰 사용량을 추적하는 유틸리티.

---

## 파일 구성

| 파일 | 역할 |
|------|------|
| `ui_emitter.py` | `logs/{run_id}/` 아래 JSONL/JSON 파일에 이벤트 기록 |
| `token_tracker.py` | 노드별 LLM 토큰 사용량 누적 집계 |
| `logger.py` | `logs/{run_id}/` 초기화, `run.log` / 구조화 JSONL / `run_dir()` |
| `llm_json.py` | LLM 응답 JSON 파싱 공통 유틸 + `ChatOpenAI` lazy 팩토리 |

---

## logger.py

`logger.setup(run_id)` 이후 `logs/{run_id}/`에 아래가 쌓인다. **상세 DEBUG**는 `run.log` 파일 핸들러에만 전부 기록되고, 콘솔(StreamHandler)은 INFO라 `[get_captured_events]`·`[DL-Raw]` 등은 파일을 봐야 한다.

| 산출물 | 용도 |
|--------|------|
| `run.log` | 타임스탬프 전체 로그 |
| `llm_decisions.jsonl` | Navigator LLM 결정 요약 |
| `events.json` | 최종 캡처 이벤트 JSON |
| `datalayer_trace.jsonl` | `log_dl_state` — URL·`signal_names`·`noise_names`·cap/dl 길이·`raw_tail`(probe 시) |
| `datalayer_diagnose.jsonl` | `log_datalayer_diagnose` — `diagnose_datalayer()` 요약(JSON-LD는 타입 샘플만) |
| `datalayer_raw_tail.jsonl` | `log_dl_raw_peek` — `window.dataLayer` 꼬리 N개 원본(병리 분석) |
| `page_state.jsonl` | `log_page_state` / `probe_datalayer_verbose` 시 URL·readyState·body 길이 등 |
| `captured_mutations.jsonl` | 선택적 캡처 목록 변경 기록 |
| `llm_raw.jsonl` | 선택적 LLM 원문 전체 |

주요 API: `log_dl_state`, `log_datalayer_diagnose`, `log_dl_raw_peek`, `probe_datalayer_verbose` (listener의 `snapshot_datalayer_names` + `peek_datalayer_raw` + 선택적 `capture_page_state`), `log_page_state`, `log_captured_mutation`, `log_llm_raw`.

`browser.listener.get_captured_events(page, log_tag="…")` — 선택적 `log_tag`가 있으면 병합/필터 개수와 이벤트명 꼬리를 DEBUG로 남긴다.

---

## llm_json.py

LangChain LLM 응답에서 JSON을 추출하는 **모든 경로**가 이 모듈을 사용한다.
각 노드·Navigator에 직접 `split("```")[1]` 같은 파싱을 복붙하지 말 것 — 펜스가 하나만 있는 응답에서 IndexError로 파이프라인 전체가 죽는다.

```python
from utils.llm_json import make_chat_llm, parse_llm_json

# LLM 인스턴스: 모듈 최상단이 아니라 노드 함수 진입 시점에 생성
llm = make_chat_llm(model="gpt-5.4-mini", timeout=120.0)

try:
    response = await llm.ainvoke(messages)
except Exception as e:
    logger.error(f"LLM 호출 실패: {e}")
    return fallback_state

decision = parse_llm_json(response.content, fallback={})
```

### parse_llm_json(raw, *, fallback={})

다음 순서로 시도하고 모두 실패하면 `fallback`을 반환. **예외를 던지지 않는다.**

1. 마크다운 펜스(``` 또는 ```json ```) 사이의 각 블록을 순서대로 시도
2. 본문 전체를 `json.loads`
3. 최외곽 `{ ... }` 블록만 잘라 재시도

### make_chat_llm(model, *, timeout, **kwargs)

`ChatOpenAI(...)`를 **호출 시점에** 새로 만들어 반환한다. 모듈 최상단에서
`_llm = ChatOpenAI(...)`로 고정하면 OPENAI_API_KEY가 임포트 시점에 없을 때
크래시하거나 키 없는 클라이언트가 굳어버리므로, 이 팩토리를 통해 lazy 초기화한다.

**모델 문자열**은 가능하면 `config.llm_models_loader.llm_model("구역키")`로 `config/llm_models.yaml`에서 읽는다(노드·Navigator가 이미 그렇게 연결됨). `make_chat_llm`의 기본 `model` 인자는 YAML이 없을 때의 코드 폴백과 맞춘다.

---

## ui_emitter.py

### 초기화

```python
from utils.ui_emitter import emit, set_run_dir, update_state

set_run_dir(run_dir)   # runner.py에서 1회 호출, 이후 모든 모듈에서 emit 사용 가능
```

### emit(event_type, **payload)

`logs/{run_id}/events.jsonl`에 한 줄씩 append.
UI의 `useRunLog` 훅이 1.5초마다 폴링해 증분 읽기.

**표준 이벤트 타입**

| event_type | 용도 | 필수 payload |
|------------|------|-------------|
| `run_start` | 실행 시작 | `run_id`, `target_url`, `user_request` |
| `node_enter` | 노드 진입 | `node_id`, `node_key`, `title` |
| `node_exit` | 노드 종료 | `node_id`, `status`, `duration_ms` |
| `thought` | LLM 사고·툴 실행 | `who`, `label`, `text`, `kind` |
| `datalayer_event` | dataLayer 캡처 | `event`, `url`, `source`, `params` |
| `hitl_request` | HITL 대기 시작 | `kind`, 그리고 kind별 payload (아래 표 참고) |
| `hitl_decision` | HITL 결정 | `approved`, `feedback` |
| `gtm_created` | GTM 리소스 생성 | `kind`, `name`, `operation` |
| `publish_result` | Publish 결과 | `success`, `version_id`, `warning` |
| `run_end` | 실행 종료 | `report_path`, `duration_ms` |

`thought` 이벤트의 `kind`: `"plain"` | `"tool"` | `"highlight"`
`thought` 이벤트의 `who`: `"agent"` | `"tool"` | `"user"`

### `hitl_request` payload by kind

| kind | payload | 생성 위치 |
|------|---------|-----------|
| `"plan"` (또는 없음) | `plan`, `normalize_errors`, `canplan_hash` | `agent/nodes/planning.py` |
| `"workspace_full"` | `workspaces`, `current_count`, `limit`, `default_reuse_id`, `message` | `agent/runner.py`(사전) / `agent/nodes/gtm_creation.py`(노드 6) |

`hitl_decision` 이벤트는 `{approved: bool, feedback: str}` 공통. UI/서버 측은 `kind`로 카드 매칭을 처리한다(`ui/CLAUDE.md` 참고).

### CanPlan 산출물 (`logs/{run_id}/`)

- `plan.json` — HITL 화면에 표시되는 **레거시 plan 표현**. Planning이 HITL 진입 직전 `write_plan`으로 저장.
- `events.jsonl`의 `hitl_request(kind="plan")` payload에는 `canplan_hash`가 포함돼, UI와 Reporter가 동일 해시로 plan 동치를 대조한다.
- Reporter(Node 8)는 `state["canplan_hash"]`와 `summarize_issues(state["normalize_errors"])`를 보고서 "특이사항" 섹션에 포함한다.

### update_state(**fields)

`logs/{run_id}/state.json`을 partial merge.

```python
update_state(current_node=3, status="running")
update_state(nodes_status={"active_explorer": "run"})   # nodes 배열 내 특정 노드만 업데이트
update_state(
    workspace_id=ws_id,
    created_variables=[{"name": v.name, "id": v.id}],
)
```

`nodes_status` 키는 특별 처리 — `state["nodes"]` 배열에서 `key`가 일치하는 항목의 `status`를 업데이트한다.

### write_plan(plan: dict)

`logs/{run_id}/plan.json` 저장. HITL 화면에서 사용.

### write_history_index(logs_root)

`logs/` 하위 모든 run을 스캔해 `logs/index.json` 갱신. History 화면이 이 파일을 읽는다.

### reconcile_timeline_at_reporter(\*, has_error: bool)

`reporter` 노드가 시작되기 **직전**에 한 번 호출된다 (`agent/nodes/reporter.py`).

- LangGraph **분기로 실행되지 않은** 노드가 `state.json`에 `queued`로 남는 문제를 보정한다 → `skip`.
- 비정상적으로 `run`으로 남은 이전 노드(예: GTM 생성 예외 후 미정리)를 `failed`(오류 있음) 또는 `done`(없음)으로 정리한다.

UI 타임라인(`Timeline`)이 완료 Run에서도 **queued / 무한 running**으로 보이지 않게 한다.

---

## token_tracker.py

### 사용법

```python
from utils import token_tracker

response = await _llm.ainvoke(messages)
token_tracker.track("planning", response)   # 노드명, AIMessage
```

### summary() 반환 구조

```python
{
    "by_node": {
        "planning": { "input": 1200, "output": 800, "total": 2000, "calls": 2 },
    },
    "total_input": int,
    "total_output": int,
    "total": int,
    "total_calls": int,
}
```

reporter(Node 8)가 `summary()`를 호출해 보고서에 포함한다.

### 스레드 안전

`_lock`(threading.Lock)으로 보호됨. `serve_ui.py`의 멀티스레드 환경에서 안전.

`reset()`은 테스트 전용 — 프로덕션 코드에서 호출하지 않는다.
