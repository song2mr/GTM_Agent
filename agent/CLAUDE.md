# agent CLAUDE.md

`agent/` 패키지는 LangGraph StateGraph와 실행 진입점을 담는다.
각 Node의 상세 구현은 `agent/nodes/CLAUDE.md`를 읽을 것.

---

## 파일 구성

| 파일 | 역할 |
|------|------|
| `graph.py` | StateGraph 빌드·컴파일 |
| `state.py` | `GTMAgentState` TypedDict 정의 |
| `orchestrator.py` | 조건부 엣지 라우팅 함수 |
| `runner.py` | CLI/UI 공통 진입점 — `run_agent(config)` |
| `nodes/` | Node 1~8 구현체 |

---

## 그래프 토폴로지

```
START
  └─→ page_classifier (Node 1)
        ├─[datalayer_status != "full"]→ structure_analyzer (Node 1.5)
        │                                   └─→ journey_planner (Node 2)
        └─[datalayer_status == "full"]──────→ journey_planner (Node 2)
                                                  └─→ active_explorer (Node 3)
                                                        ├─(선택) cart_addition_explorer (3.25)
                                                        ├─(선택) begin_checkout_explorer (3.5)  ← 3.25 이후 또는 3 직행
                                                        ├─[manual_required 있음]→ manual_capture (Node 4)
                                                        │                             └─→ planning (Node 5)
                                                        └─[manual_required 없음]────→ planning (Node 5)
                                                                                            ├─[승인]→ gtm_creation (Node 6)
                                                                                            │            ├─[성공]→ publish (Node 7)
                                                                                            │            │            └─→ reporter (Node 8) → END
                                                                                            │            └─[오류]→ reporter (Node 8) → END
                                                                                            └─[거부/오류]→ reporter (Node 8) → END
```

## 라우팅 함수 (`orchestrator.py`)

| 함수 | 분기 기준 |
|------|----------|
| `route_after_classifier` | `datalayer_status == "full"` → `journey_planner`, 아니면 `structure_analyzer` |
| `route_after_active_explorer` | `cart_addition_events` → 3.25; 아니고 `begin_checkout_events` → 3.5; 아니면 `route_after_explorer` |
| `route_after_cart_addition` | `begin_checkout_events` → 3.5; 아니면 `route_after_explorer` |
| `route_after_explorer` | `state["manual_required"]` 비어있으면 `planning`, 있으면 `manual_capture` |
| `route_after_planning` | `state["error"]` → `reporter`; 아니면 `plan_approved` → `gtm_creation`, 그 외 → `reporter` |
| `route_after_creation` | `state["error"]` 없으면 `publish`, 있으면 `reporter` |

reporter(Node 8)는 항상 마지막에 실행되며 오류 경로에서도 반드시 통과한다.

---

## runner 종료 시 UI 스냅샷

`runner.run_agent` 마지막에 `update_state(status=..., current_node=8)`을 호출한다.  
`current_node`가 비어 Live 화면 기본 하이라이트가 1번 노드로만 가는 문제를 줄인다.

분기로 **실행되지 않은** 노드(`manual_capture`, `publish` 등)의 `queued`/`run` 잔류는 `reporter` 진입 시 `utils.ui_emitter.reconcile_timeline_at_reporter`와, Node 1·3의 선제 `skip` 갱신으로 보정한다.

---

## GTMAgentState 핵심 필드

| 필드 | 타입 | 기록 노드 | 설명 |
|------|------|----------|------|
| `target_url` | str | 초기화 | 분석 대상 URL |
| `page_type` | str | Node 1 | PLP/PDP/cart/checkout/home/unknown |
| `datalayer_status` | str | Node 1 | "full" / "partial" / "none" |
| `extraction_method` | str | Node 1.5 | "datalayer" / "dom" / "json_ld" |
| `exploration_queue` | list | Node 2 | 탐색할 이벤트 큐 |
| `auto_capturable` | list | Node 2 | 자동 캡처 가능 이벤트 목록 |
| `cart_addition_events` | list | Node 2 | 장바구니 담기 전용 탐색 대상(이름은 큐와 동일) |
| `begin_checkout_events` | list | Node 2 | 결제 시작 전용 탐색 대상 |
| `manual_required` | list | Node 2 | 수동 캡처 필요 이벤트 목록 |
| `captured_events` | list[dict] | Node 3~3.5 | 캡처된 dataLayer 이벤트 |
| `event_capture_log` | list[dict] | Node 3~4 | 이벤트별 처리 방식·결과 (Reporter 입력) |
| `plan` | dict | Node 5 | GTM 설계안 (variables/triggers/tags) |
| `plan_approved` | bool | Node 5 | HITL 승인 여부 |
| `hitl_mode` | str | 초기화 | "cli" / "file" |
| `created_variables` | list | Node 6 | 생성된 Variable 목록 |
| `created_triggers` | list | Node 6 | 생성된 Trigger 목록 |
| `created_tags` | list | Node 6 | 생성된 Tag 목록 |
| `publish_result` | dict | Node 7 | Publish 성공 여부·버전 |
| `report_path` | str \| None | Node 8 | 생성된 보고서 파일 경로 |
| `error` | str \| None | 전 노드 | 오류 발생 시 메시지 |

---

## runner.py — `run_agent(config)`

```python
config = {
    "target_url": str,       # 필수
    "user_request": str,     # 필수
    "tag_type": str,         # "GA4" | "naver" | "kakao", 기본 GA4
    "account_id": str,       # 필수
    "container_id": str,     # 필수
    "workspace_id": str,     # 선택, 비면 자동 생성
    "measurement_id": str,   # 선택
    "run_id": str,           # 선택, serve_ui가 주입
    "hitl_mode": str,        # "cli" | "file", 기본 "cli"
}
```

`serve_ui.py`는 `hitl_mode="file"`을 주입해 파일 기반 HITL을 활성화한다.
