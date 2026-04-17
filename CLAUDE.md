# GTM AI Agent — CLAUDE.md

> 이 파일은 Claude Code가 프로젝트를 이해하기 위한 헌법입니다.
> 상세 설계는 `PROJECT_SPEC.md`를 참고하세요.

---

## 프로젝트 개요

자연어로 요청하면 AI가 대상 페이지를 직접 탐색해 dataLayer 이벤트를 캡처하고,
GTM Variable / Trigger / Tag를 자동 생성 후 Publish하는 LangGraph 멀티에이전트 시스템.
실행 완료 후 `logs/{run_id}/report.md`에 작업 내역 전체를 문서로 보고한다.

---

## 기술 스택

| 항목 | 버전/결정 |
|------|----------|
| Python | 3.11 |
| LangGraph | >=0.2 |
| langchain-anthropic | >=0.3 |
| Playwright | >=1.44 |
| google-api-python-client | >=2.0 |
| httpx | >=0.27 |
| beautifulsoup4 | >=4.12 |

---

## 아키텍처 원칙

### Node 구성 (순서 엄수)

```
Node 1    page_classifier      페이지 로드 + Listener 주입 + 페이지 타입 판단
Node 1.5  structure_analyzer   dataLayer 미완전 시 DOM/JSON-LD 구조 분석 (조건부)
Node 2    journey_planner      탐색 이벤트 목록 생성 + 큐 구성
Node 3    active_explorer      LLM Navigator + Playwright 루프 (핵심)
Node 4    manual_capture       purchase/refund 등 수동 캡처 게이트웨이 (조건부)
Node 5    planning             GTM 설계안 생성 + HITL (y/n)
Node 6    gtm_creation         Variable → Trigger → Tag 순서로 생성
Node 7    publish              Version 생성 + Publish
Node 8    reporter             실행 결과 마크다운 보고서 생성 (항상 실행)
```

### 이벤트 캡처 우선순위 (엄수)

1. **dataLayer 직접 캡처** — `window.__gtm_captured`에 누적된 이벤트 사용
2. **클릭 트리거 → dataLayer 확인** — 버튼 클릭 후 dataLayer 발화 여부 우선 확인
3. **클릭 트리거 → DOM 추출** — dataLayer 미발화 시 DOM selector로 직접 추출
4. **LLM Navigator → dataLayer 캡처** — 자동 탐색으로 dataLayer 이벤트 수집
5. **DOM 폴백** — Navigator 실패 시 DOM에서 직접 데이터 추출
6. **Manual Capture Gateway** — 모든 자동화 방법 실패 또는 purchase/refund 등

### 이벤트 분류

- **자동 캡처 가능**: page_view, view_item_list, view_item, add_to_cart, view_cart, begin_checkout
- **커스텀 이벤트 (auto_capturable)**: add_to_wishlist, select_item 등 사용자 요청에 명시된 비표준 이벤트
  - `add_to_wishlist`: 찜/하트/위시리스트 버튼 클릭 — purchase/refund가 아닌 모든 이벤트는 auto_capturable
- **부분 자동화**: add_shipping_info, add_payment_info (더미 데이터 폼 입력)
- **자동화 불가**: purchase, refund → Node 4 Manual Capture Gateway로 전환
- **분류 기준**: `MANUAL_REQUIRED_EVENTS = {"purchase", "refund"}` 외 모두 auto_capturable

### 보고서 원칙 (Node 8 Reporter)

- 실행 경로와 관계없이 항상 마지막에 reporter가 실행된다 (오류 발생 시도 포함)
- `event_capture_log`에 이벤트별 처리 방식·결과·특이사항을 구조화해서 저장한다
- 보고서는 `logs/{run_id}/report.md`에 저장된다
- 보고서 내용: 기본 정보 / dataLayer 분석 / 이벤트별 처리 내역 / 특이사항 / GTM 생성 결과 / Publish 결과

### Playwright 사용 원칙

- Event Listener는 반드시 `page.add_init_script()`로 주입한다 (페이지 이동 후에도 유지)
- `window.__gtm_captured`에 모든 dataLayer.push 이벤트를 누적한다
- LLM Navigator 루프에서 클릭 실패 시 최대 3회 재시도 후 Manual로 이관한다
- 액션(click/navigate/scroll/form_fill)은 `browser/actions.py` 래퍼를 통해 실행한다

### Navigator 이벤트별 탐색 전략 (`EVENT_CAPTURE_GUIDE`)

`browser/navigator.py`의 `EVENT_CAPTURE_GUIDE` 딕셔너리로 이벤트별 탐색 힌트를 관리한다.
Navigator가 현재 페이지에서 무엇을 해야 하는지 판단할 때 이 가이드를 프롬프트에 주입한다.

| 이벤트 | 전략 |
|--------|------|
| view_item | 홈/PLP이면 상품 클릭 → PDP 이동 먼저 |
| add_to_cart | PDP의 '장바구니/담기' 버튼 |
| add_to_wishlist | ♡/찜/하트/관심상품 버튼 — PLP 카드 위 또는 PDP에 존재 |
| view_item_list | 카테고리/목록 링크 클릭 |

새 이벤트 지원 시 `EVENT_CAPTURE_GUIDE`에 항목 추가만 하면 됨.

### Journey Planner 원칙

- `MANUAL_REQUIRED_EVENTS = {"purchase", "refund"}` 외 모든 이벤트는 `auto_capturable`
- `add_to_wishlist` 등 사용자 요청에 명시된 커스텀 이벤트도 자동으로 큐에 포함됨
- LLM에 현재 URL + 페이지 타입을 함께 전달해 탐색 순서를 정확히 결정
- LLM 파싱 실패 시 `_default_queue(page_type, user_request)`로 폴백하며 커스텀 이벤트도 반영

### GTM API 사용 원칙

- Workspace는 항상 신규 생성 후 작업한다
- 리소스 생성 순서: Variable → Trigger → Tag (의존 관계 있음)
- 이름 충돌 시 Create가 아닌 Update(덮어쓰기)를 호출한다
- credentials는 `credentials/token.json`에만 저장한다 (`.gitignore` 처리 필수)

---

## 폴더 구조

```
gtm_ai/
├── CLAUDE.md
├── PROJECT_SPEC.md             # 상세 설계 문서
├── main.py
├── agent/
│   ├── graph.py                # LangGraph StateGraph
│   ├── state.py                # GTMAgentState TypedDict
│   ├── orchestrator.py         # 라우팅 로직
│   └── nodes/
│       ├── page_classifier.py  # Node 1
│       ├── structure_analyzer.py  # Node 1.5
│       ├── journey_planner.py  # Node 2
│       ├── active_explorer.py  # Node 3 (이벤트 캡처 우선순위 로직 포함)
│       ├── manual_capture.py   # Node 4
│       ├── planning.py         # Node 5
│       ├── gtm_creation.py     # Node 6
│       ├── publish.py          # Node 7
│       └── reporter.py         # Node 8 — 보고서 생성 (항상 실행)
├── browser/
│   ├── listener.py             # Persistent Event Listener
│   ├── navigator.py            # LLM Navigator 루프
│   └── actions.py              # 액션 래퍼
├── gtm/
│   ├── auth.py
│   ├── client.py
│   └── models.py
├── docs/
│   └── fetcher.py              # Naver/Kakao 문서 실시간 fetch
├── config/
│   └── media_sources.yaml      # 매체별 문서 URL
├── logs/                       # 실행 로그 + 보고서 (run_id별 폴더)
│   └── {run_id}/
│       ├── run.log
│       ├── report.md           # 최종 작업 보고서
│       ├── events.json
│       ├── llm_decisions.jsonl
│       └── screenshots/
└── credentials/                # .gitignore 처리
```

---

## State 핵심 필드

| 필드 | 노드 | 설명 |
|------|------|------|
| `datalayer_status` | Node 1 | "full" / "partial" / "none" — 추출 방식 결정 기준 |
| `extraction_method` | Node 1.5 | "datalayer" / "dom" / "json_ld" 등 |
| `event_capture_log` | Node 3-4 | 이벤트별 처리 방식·결과·특이사항 (Reporter 입력) |
| `exploration_log` | Node 1-3 | 문자열 기반 실행 로그 (디버깅용) |
| `report_path` | Node 8 | 생성된 보고서 파일 절대 경로 |

---

## 네이밍 컨벤션

- 파일명: `snake_case.py`
- 클래스명: `PascalCase`
- LangGraph 노드 함수명: `node_` 접두사 없이 역할 그대로 (`page_classifier`, `active_explorer`)
- State 필드: `snake_case`, 노드별로 주석 구분

---

## 보안 원칙

- `.env`와 `credentials/`는 절대 커밋하지 않는다
- GTM API 호출 시 `account_id`, `container_id`는 환경변수에서만 읽는다
- Playwright로 폼 입력 시 더미 데이터만 사용한다 (실제 개인정보 입력 금지)

---

## 자주 쓰는 작업 흐름

```bash
# 패키지 설치
pip install -r requirements.txt
playwright install chromium

# 실행
python main.py

# OAuth 최초 인증 (브라우저 팝업)
python gtm/auth.py
```

---

## 참고 문서

- 상세 설계: `PROJECT_SPEC.md`
- GTM API: https://developers.google.com/tag-platform/tag-manager/api/v2
- Playwright Python: https://playwright.dev/python/
