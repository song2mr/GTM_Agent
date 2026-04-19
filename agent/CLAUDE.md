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
| `request_events.py` | `selected_events` + `user_request` 괄호 파서 단일 진입점 (`resolve_selected_events`) |
| `commerce_events.py` | GA4 기본명 폴백(`fallback_cart_addition_events` 등) |
| `workspace_hitl.py` | 워크스페이스 상한(3) HITL 공용 로직 (runner 사전·Node 6 공용) |
| `nodes/` | Node 1~8 구현체 (`agent/nodes/CLAUDE.md`) |
| `canplan/` | CanPlan 스키마·정규화·EvidencePack·CJS 템플릿 (`agent/canplan/CLAUDE.md`) |
| `playbooks/` | 이벤트별 탐색 Playbook YAML + loader (`agent/playbooks/CLAUDE.md`) |

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
| `captured_events` | list[dict] | Node 3~3.5 | 캡처된 dataLayer 이벤트 (`_attach_evidence`로 `evidence.source`·`evidence.dl_health`·`evidence.url_patterns` 표준 메타 포함) |
| `event_capture_log` | list[dict] | Node 3~4 | 이벤트별 처리 방식·결과 (Reporter 입력) |
| `exploration_failures` | list[dict] | Node 3 | Playbook `surface_goal` 미도달 등 탐색 실패 사유 (예: `{event, reason: "surface_unreached", detail, url}`) |
| `site_url_patterns` | dict | Node 1.5 + Node 3 | `page_type`→URL regex. Node 3가 방문 URL을 canonical regex로 변환해 머지한다. |
| `plan` | dict | Node 5 | GTM 설계안 (variables/triggers/tags) — CanPlan이 있으면 `spec_builder`가 여기서 동등 스펙을 생성 |
| `draft_plan` | dict | Node 5 | LLM 초안(정규화 전) |
| `canplan` | dict | Node 5 | 정규화 통과 후 단일 정규형 (`version: "canplan/1"`) |
| `evidence_pack` | dict | Node 5 | Planning 입력 근거 번들 (`healthy_dl_fields` / `unhealthy_dl_fields` / 머지된 `url_patterns` / `fired_events` / `failures`) |
| `normalize_errors` | list[dict] | Node 5 | 정규화 경고/오류 (`severity`·`code`·`message`·`hint`) |
| `canplan_hash` | str | Node 5 | UI/보고서 동치 검증용 해시 (HITL 이벤트·Reporter에 노출) |
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

## 2026-04-19 업데이트 (CanPlan 파이프라인)

핵심 변경은 `docs/VARIABLE_PIPELINE_REDESIGN.md`에 설계 근거·정책 세부가 있다. 코드 내 요약:

- **Planning(Node 5)**
  - `evidence_pack = canplan.build_evidence_pack(state, target_events)`로 LLM 입력 근거를 단일 번들로 합성.
  - LLM 초안(`draft_plan`) → `normalize.normalize_draft_plan(draft, allowed_events=..., ga4_measurement_id=..., evidence_pack=...)` → `(canplan, normalize_errors)`.
  - 에러가 있으면 `summarize_issues(errors)`와 **직전 plan**을 프롬프트에 재주입해 LLM 재설계 루프를 돈다.
  - `STRICT_CANPLAN=1`이면 정규화 에러가 남을 때 LLM 1회 재시도 후 실패. 기본(0)은 경고 후 레거시 `plan` 경로 허용.
  - `hitl_request` 이벤트에 `plan`·`normalize_errors`·`canplan_hash`를 함께 실어 UI가 정규화 이슈를 표시할 수 있게 한다.
- **GTM Creation(Node 6)**
  - `canplan.version == "canplan/1"`이면 `gtm.spec_builder.build_specs_from_canplan(canplan)`으로 직렬화(`_fix_plan` 미경유).
  - 레거시 `plan` 경로로 들어온 경우 `_reject_in_set_in_legacy`가 `in_set` 조건을 예외로 거부하고, UI `thought`로 레거시 사용 경고를 남긴다.
- **Active Explorer(Node 3)**
  - Playbook `surface_goal` 미도달 시 `exploration_failures`에 `surface_unreached` 기록.
  - 방문 URL을 `_url_to_observed_pattern`로 canonical regex로 변환 → `site_url_patterns`에 머지.
  - `_attach_evidence`로 `captured_events[*].evidence`를 표준화(`source`/`dl_health`/`url_patterns`/`failures`).
- **Navigator 스냅샷 청크**
  - 본문 길이가 1500자 미만이면 1/4 페이지씩 스크롤해 최대 2회 재스냅샷 → 롱 페이지에서 LLM 컨텍스트 확보.

---

## 이벤트 스코프 단일 진입점 (`request_events.py`)

Journey Planner/Planning은 반드시 `resolve_selected_events(state)`만 호출한다.
1. `state["selected_events"]` 비어있지 않음 → 그 목록만 (strict, UI 체크박스 경로).
2. 없으면 `user_request`의 마지막 `( … )` 괄호 목록 파싱(CLI/레거시).
3. 둘 다 없으면 LLM 큐 제안으로 폴백(표준 퍼널 자동 확장은 프롬프트에서 금지).
어느 경로든 `purchase`/`refund`는 `exploration_queue`에서 제외되고 `manual_required`에만 추가된다.
