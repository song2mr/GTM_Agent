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
| `user_request` | str | 초기화 | 자유 텍스트 **메모**(설치 대상을 직접 결정하지 않음) |
| `selected_events` | list[str] | 초기화(UI/CLI) | **설치할 이벤트 명시 목록**. 비어 있지 않으면 Journey Planner/Planning이 이 목록만 탐색·설계 대상으로 사용(strict). 비어 있으면 `user_request`의 `( … )` 괄호 파서 → 실패 시 LLM 큐로 폴백. |
| `page_type` | str | Node 1 | PLP/PDP/cart/checkout/home/unknown |
| `datalayer_status` | str | Node 1 | "full" / "partial" / "none" |
| `extraction_method` | str | Node 1.5 | "datalayer" / "dom" / "json_ld" |
| `exploration_queue` | list | Node 2 | 탐색할 이벤트 큐(`purchase`·`refund`는 정규화 시 제외) |
| `auto_capturable` | list | Node 2 | 자동 캡처 가능 이벤트 목록 |
| `cart_addition_events` | list | Node 2 | 장바구니 담기 전용 탐색 대상(이름은 큐와 동일) |
| `begin_checkout_events` | list | Node 2 | 결제 시작 전용 탐색 대상 |
| `manual_required` | list | Node 2 | 수동 캡처 필요 이벤트 목록 |
| `captured_events` | list[dict] | Node 3~3.5 | 캡처된 dataLayer 이벤트 |
| `event_capture_log` | list[dict] | Node 3~4 | 이벤트별 처리 방식·결과 (Reporter 입력) |
| `plan` | dict | Node 5 | GTM 설계안 (variables/triggers/tags) |
| `draft_plan` | dict | Node 5 | LLM 초안(정규화 전) |
| `canplan` | dict | Node 5 | 정규화 통과 후 단일 정규형 |
| `evidence_pack` | dict | Node 5 | Planning 입력 근거 번들 |
| `normalize_errors` | list[dict] | Node 5 | 정규화 경고/오류 |
| `canplan_hash` | str | Node 5 | CanPlan 정합성 확인 해시 |
| `exploration_plan` | list[dict] | Node 2 | 이벤트별 Playbook 확장 큐 |
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
    "target_url": str,            # 필수
    "user_request": str,          # 필수, 자유 텍스트 메모
    "tag_type": str,              # "GA4" | "naver" | "kakao", 기본 GA4
    "account_id": str,            # 필수
    "container_id": str,          # 필수
    "workspace_id": str,          # 선택, 비면 자동 생성
    "measurement_id": str,        # 선택
    "selected_events": list[str], # 선택. 설치할 이벤트 명시 목록(UI 체크박스).
                                   # 있으면 Journey Planner/Planning이 strict 모드로
                                   # 이 목록만 처리. 비면 괄호 파서 → LLM 큐 폴백.
    "run_id": str,                # 선택, serve_ui가 주입
    "hitl_mode": str,             # "cli" | "file", 기본 "cli"
}
```

`serve_ui.py`는 `hitl_mode="file"`을 주입해 파일 기반 HITL을 활성화한다.

GTM `workspaces.list` 결과가 상한(3)이고 `workspace_id`가 비어 있으면, **그래프 `ainvoke` 전**에 `agent/workspace_hitl.py`로 `workspace_full` HITL을 한 번 수행해 비용·시간 낭비를 막는다(`agent/nodes/CLAUDE.md`).

노드별 OpenAI 채팅 모델은 **`config/llm_models.yaml`**에서 구역(zone) 키로 조정한다(`config/CLAUDE.md`, `agent/nodes/CLAUDE.md` 참고).

---

## 2026-04-19 업데이트 (CanPlan 경로)

- Planning은 기존 `plan`만 생성하지 않고 `draft_plan -> canplan` 정규화 단계를 포함한다.
- `STRICT_CANPLAN=1`이면 정규화 에러가 있을 때 LLM 1회 재시도 후 실패 처리한다.
- GTM Creation은 `canplan.version == "canplan/1"`인 경우 `gtm/spec_builder.py` 경로를 우선 사용한다.
