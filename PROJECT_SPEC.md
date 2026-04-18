# GTM AI Agent — Project Specification

> 최초 작성: 2026-04-16  
> 최종 수정: 2026-04-18 (LLM 스택·UI 동기화 문서 반영)  
> 상태: 구현 진행 중 (MVP 동작 + 로컬 UI)

---

## 1. 프로젝트 개요

사용자가 원하는 GTM 이벤트를 자연어로 요청하면, AI 에이전트가:
1. 대상 페이지의 `dataLayer` 현황을 Playwright로 분석
2. 기존 dataLayer 구조를 기반으로 Trigger / Variable / Tag 설계
3. 사용자 확인(HITL) 후 GTM API로 생성 및 컨테이너 Publish

**대상 사용자**: 본인 GTM 계정 사용자 (단일 사용자, SaaS 아님)

---

## 2. 기술 스택 확정

| 항목 | 결정 |
|------|------|
| 오케스트레이션 | LangGraph (StateGraph + Orchestrator-Workers) |
| dataLayer 분석 | Playwright — JS 직접 실행으로 window.dataLayer 읽기 |
| GTM 제어 | GTM API v2, OAuth 2.0 (개인 계정) |
| LLM | OpenAI API (`langchain-openai`, 구현 기준) |
| 매체 문서 조회 | 실시간 웹 fetch (Naver/Kakao 픽셀 공식 문서 URL → LLM 컨텍스트 직접 투입) |
| 문서 URL 관리 | `config/media_sources.yaml` |
| HITL 인터페이스 | CLI 입력 또는 `serve_ui.py` + 파일(`hitl_response.json`) |
| Computer Use | 미사용 (Playwright로 대체) |
| Python | 3.11 |

### 핵심 패키지

```
langgraph>=0.2
langchain-openai>=0.2
playwright>=1.44
google-api-python-client>=2.0
google-auth-oauthlib>=1.0
httpx>=0.27
beautifulsoup4>=4.12
pyyaml>=6.0
python-dotenv>=1.0
```

---

## 3. 지원 태그 유형

| Phase | 태그 유형 | 문서 처리 방식 |
|-------|-----------|----------------|
| Phase 1 | GA4 이벤트 태그 | LLM 내장 지식 |
| Phase 2 | Naver Analytics 픽셀 | 실시간 문서 fetch |
| Phase 2 | Kakao Pixel | 실시간 문서 fetch |

---

## 4. dataLayer 분석 방식

### 이벤트 자동화 가능성 분류

| 분류 | 이벤트 예시 | 처리 방식 |
|------|------------|----------|
| 자동 캡처 가능 | page_view, view_item_list, view_item, add_to_cart, remove_from_cart, view_cart, begin_checkout | Active Explorer가 자동 탐색 |
| 부분 자동화 | add_shipping_info, add_payment_info | 더미 데이터로 폼 입력 시도 |
| 자동화 불가 | purchase, refund, 서버 트리거 이벤트 | Manual Capture Gateway로 전환 (`purchase`·`refund`는 `exploration_queue`에서 제거 후, 요청에 명시 시 `manual_required`에만 반영) |

### 전체 캡처 전략

```
페이지 로드
    ↓
Persistent Event Listener 주입 (페이지 이동 후에도 유지)
    ↓
Page Classifier: 페이지 타입 판단 (PLP/PDP/Cart/Checkout/기타)
    ↓
Journey Planner: 도달 가능한 이벤트 목록 생성 → 탐색 큐 구성(GA4 이커머스 권장 순 정렬, `purchase`·`refund`는 큐에서 제외)
    ↓
Active Explorer 루프 (LLM + Playwright)
    ↓
자동 캡처 불가 이벤트 → Manual Capture Gateway
    ↓
전체 이벤트 풀 완성 → Planning Agent로 전달
```

### Persistent Event Listener

페이지 이동 후에도 리스너가 유지되도록 `add_init_script`로 주입:

```python
await page.add_init_script("""
    window.__gtm_captured = window.__gtm_captured || [];
    const _push = window.dataLayer?.push?.bind(window.dataLayer);
    if (_push && !window.__gtm_listener_injected) {
        window.dataLayer.push = function(...args) {
            window.__gtm_captured.push({
                event: args[0],
                timestamp: Date.now(),
                url: window.location.href
            });
            return _push(...args);
        };
        window.__gtm_listener_injected = true;
    }
""")
# add_init_script → 페이지 이동마다 자동 재실행됨
```

### Active Explorer: LLM Navigator 루프

LLM이 현재 페이지 상태를 보고 다음 행동을 결정, Playwright가 실행:

```
[현재 페이지 HTML 스냅샷 + 목표 이벤트] → LLM 판단
    A) "이 selector를 클릭하세요"  → Playwright 클릭
    B) "이 URL로 이동하세요"       → Playwright navigate
    C) "이 페이지에서 캡처 불가"   → Manual Capture로 전환
    D) "이미 캡처됨"               → 다음 목표로
          ↓
    결과 확인
    - 새 dataLayer 이벤트 발화? → 수집
    - 예상 변화 없음 → 다음 스텝 (이벤트당 최대 `MAX_STEPS`, 현재 코드 기준 6)
    - 스텝 소진 시 Manual/DOM 폴백 경로로 이관
```

### Manual Capture Gateway

purchase, refund 등 자동화 불가 이벤트에 대해 사용자에게 3가지 옵션 제시:

```
에이전트:
  "[purchase] 이벤트는 자동 캡처가 불가능합니다. 방법을 선택하세요:

  A) 직접 캡처
     브라우저 콘솔에서 실제 주문완료 후 아래 명령어 실행:
     > copy(JSON.stringify(window.dataLayer))
     결과를 여기에 붙여넣어 주세요.

  B) GA4 표준 스키마로 진행 (권장)
     { event: 'purchase', ecommerce: { transaction_id, value, items: [...] } }
     이 구조를 기반으로 GTM을 설계합니다.

  C) 이 이벤트 스킵"
```

### 처리 가능한 엣지 케이스

| 상황 | 처리 전략 |
|------|----------|
| 로그인 필요 페이지 | 사용자에게 쿠키/세션 파일 제공 요청 |
| 팝업/모달 차단 | LLM이 닫기 버튼 감지 → 먼저 처리 |
| SPA 이벤트 타이밍 | networkidle 대신 커스텀 이벤트 polling |
| 무한 스크롤 | LLM이 scroll 액션 판단 |
| 상품 없는 목록 | LLM이 인식 → URL 직접 이동 시도 |
| 폼 입력 필요 | 테스트용 더미 데이터 자동 입력 |

---

## 5. 전체 아키텍처

```
[사용자: 자연어 요청 + 대상 URL]
             ↓
    [Orchestrator — LangGraph StateGraph]
             ↓
  Node 1: Page Classifier
    - Playwright로 페이지 로드
    - Persistent Event Listener 주입
    - 로드타임 이벤트 수집
    - LLM이 페이지 타입 판단 (PLP/PDP/Cart/Checkout/기타)
    - GTM API로 기존 컨테이너 설정 조회
             ↓
  Node 2: Journey Planner (LLM)
    - 페이지 타입 + 사용자 요청 기반으로 탐색 목표 이벤트 목록 생성
    - 이벤트별 자동화 가능 여부 분류
    - 탐색 시퀀스 큐 생성 (순서 중요): GA4 설치형 권장 순으로 `_normalize_and_sort_exploration_queue` 정렬
      예: [view_item_list → view_item → add_to_cart → view_cart → begin_checkout]
    - `purchase`·`refund`는 **자동 탐색 큐에서 제거**(LLM이 넣어도 필터; `exploration_log`에 사유)
    - Manual Capture 필요 이벤트: 사용자 요청에 purchase/refund가 있으면 `manual_required`에 추가(큐에는 미포함)
             ↓
  Node 3: Active Explorer (Playwright + LLM 루프) ← 핵심
    - 탐색 큐 순서대로 실행
    - 각 스텝: LLM이 "다음 클릭 대상" 결정 → Playwright 실행 → 이벤트 수집
    - 실패 시: 재시도 (최대 3회) → LLM 재판단 → 그래도 실패 시 Manual로 이관
    - 모든 캡처된 이벤트 축적
             ↓
  Node 4: Manual Capture Gateway
    - 자동 캡처 실패 / 불가 이벤트 목록 출력
    - 이벤트별 사용자 선택: A) 직접 캡처 / B) 표준 스키마 승인 / C) 스킵
    - 전체 이벤트 풀 완성
             ↓
  Node 5: Planning Agent (LLM)
    - 수집된 이벤트 구조 파싱
    - 태그 유형 판단
      GA4  → 내장 지식으로 설계
      Naver/Kakao → config에서 URL 로드 → 실시간 문서 fetch → LLM 컨텍스트 투입
    - Variable / Trigger / Tag 설계안 생성
    - ⚠️ HITL: 터미널에서 사용자 확인 (y/n + 피드백)
      y → Node 6으로 진행
      n → 피드백 입력받아 Planning Agent 재루프
             ↓ (y)
  Node 6: GTM Creation Agent
    - 새 Workspace 생성 (항상 신규, 디폴트)
    - Variable 생성 (순서 중요)
    - Trigger 생성
    - Tag 생성
    - 이름 충돌 시: 기존 리소스 Update (덮어쓰기)
             ↓
  Node 7: Publish Agent
    - Workspace Version 생성
    - 컨테이너 Publish
    - 결과 리포트
```

---

## 6. 실시간 문서 조회 설계 (Naver / Kakao 픽셀)

```
[매체 유형 확정 (naver | kakao)]
     ↓
[config/media_sources.yaml에서 URL 목록 로드]
     ↓
[httpx로 각 URL fetch → BeautifulSoup으로 본문 파싱]
     ↓
[파싱된 문서를 LLM 컨텍스트에 직접 투입]
     ↓
[Tag 설계 진행]
     ↓ (fetch 실패 시)
[경고 메시지 출력 후 내장 지식으로 폴백]
```

### 문서 URL 관리 (`config/media_sources.yaml`)

```yaml
kakao_pixel:
  name: "Kakao Pixel"
  urls:
    - "https://developers.kakao.com/docs/latest/ko/pixel/"

naver_analytics:
  name: "Naver Analytics"
  urls:
    - ""   # 직접 확인 후 기입
```

- URL 추가/변경은 yaml 파일만 수정
- fetch 실패(네트워크 오류, 404 등) → 경고 후 내장 지식 폴백

---

## 7. 충돌 처리 전략

| 상황 | 처리 방법 |
|------|-----------|
| 같은 이름의 Variable/Trigger/Tag 존재 | GTM API Update 호출 (덮어쓰기) |
| 없는 리소스 | GTM API Create 호출 |
| Workspace | 항상 신규 Workspace 생성 후 작업 (디폴트, 변경 불가) |

---

## 8. LangGraph State 설계

```python
class GTMAgentState(TypedDict):
    # 입력 (.env에서 로드)
    user_request: str
    target_url: str
    tag_type: str              # "GA4" | "naver" | "kakao"
    account_id: str
    container_id: str
    workspace_id: str          # 신규 생성 후 저장

    # Node 1: Page Classifier
    page_type: str             # "PLP" | "PDP" | "cart" | "checkout" | "unknown"
    existing_gtm_config: dict  # 현재 GTM 컨테이너 설정

    # Node 2: Journey Planner
    exploration_queue: list    # 탐색할 이벤트 목록 (순서 있음; purchase/refund 없음)
    auto_capturable: list      # 자동 캡처 가능 이벤트
    manual_required: list      # 수동 캡처 필요 이벤트 (purchase, refund 등)

    # Node 3: Active Explorer
    captured_events: list      # [{event, params, url, timestamp}, ...]
    exploration_log: list      # 각 시도 결과 로그 (디버깅용)
    current_url: str

    # Node 4: Manual Capture Gateway
    manual_capture_results: dict  # {event_name: dataLayer_schema}
    skipped_events: list          # 사용자가 스킵 선택한 이벤트

    # Node 5: Planning Agent
    doc_context: str           # fetch된 문서 본문 (Naver/Kakao용)
    doc_fetch_failed: bool     # fetch 실패 시 True → 내장 지식 폴백
    plan: dict                 # Variable/Trigger/Tag 설계안
    plan_approved: bool        # HITL 승인 여부
    hitl_feedback: str         # n 선택 시 사용자 피드백

    # Node 6-7: 실행 결과
    created_variables: list
    created_triggers: list
    created_tags: list
    publish_result: dict
    error: str | None
```

---

## 9. 환경 변수 (.env)

```env
OPENAI_API_KEY=
GTM_ACCOUNT_ID=
GTM_CONTAINER_ID=
GTM_WORKSPACE_ID=        # 신규 workspace 생성 후 자동 기입 (선택)
```

### OAuth 토큰 저장
- 경로: `credentials/token.json`
- `.gitignore`에 `credentials/` 추가

---

## 10. 폴더 구조

```
gtm_ai/
├── PROJECT_SPEC.md
├── .env                        # GTM API 인증 정보
├── .gitignore                  # credentials/, .env 포함
├── requirements.txt
├── main.py                     # 진입점
│
├── agent/
│   ├── graph.py                # LangGraph StateGraph 정의
│   ├── state.py                # GTMAgentState TypedDict
│   ├── orchestrator.py         # 라우팅 로직
│   └── nodes/
│       ├── page_classifier.py  # Node 1: 페이지 로드 + 타입 판단 + 로드타임 이벤트 수집
│       ├── journey_planner.py  # Node 2: 탐색 목표 이벤트 목록 + 큐 생성
│       ├── active_explorer.py  # Node 3: LLM Navigator + Playwright 루프 + 재시도
│       ├── manual_capture.py   # Node 4: purchase/refund 등 수동 캡처 게이트웨이
│       ├── planning.py         # Node 5: LLM 플랜 생성 + HITL
│       ├── gtm_creation.py     # Node 6: Workspace 생성 + GTM API Create/Update
│       └── publish.py          # Node 7: Publish
│
├── playwright/
│   ├── listener.py             # Persistent Event Listener 주입 유틸
│   ├── navigator.py            # LLM Navigator 루프 + 재시도 로직
│   └── actions.py              # click / navigate / scroll / form_fill 액션 래퍼
│
├── gtm/
│   ├── auth.py                 # OAuth 2.0 인증 (token.json 관리)
│   ├── client.py               # GTM API 클라이언트 래퍼
│   └── models.py               # Tag/Trigger/Variable 데이터 모델
│
├── docs/
│   └── fetcher.py              # URL fetch + BeautifulSoup 파싱
│
├── config/
│   └── media_sources.yaml      # 매체별 문서 URL 목록
│
├── tests/
│   ├── unit/                   # 단위 테스트
│   └── integration/            # E2E 테스트
│
└── credentials/                # OAuth 토큰 (.gitignore 처리)
    └── token.json
```

---

## 11. 구현 순서

### Phase 1: 기반 인프라
1. [ ] `.env`, `.gitignore`, `requirements.txt` 작성
2. [ ] GTM API OAuth 인증 (`gtm/auth.py`) — Google Cloud Console 설정 선행 필요
3. [ ] GTM API 클라이언트 래퍼 (`gtm/client.py`)
4. [ ] LangGraph StateGraph 골격 (`agent/graph.py`, `agent/state.py`)

### Phase 2: Playwright 탐색 엔진
5. [ ] Persistent Event Listener (`playwright/listener.py`)
6. [ ] Page Classifier — 페이지 타입 판단 (`agent/nodes/page_classifier.py`)
7. [ ] Journey Planner — 탐색 큐 생성 (`agent/nodes/journey_planner.py`)
8. [ ] LLM Navigator + 재시도 로직 (`playwright/navigator.py`, `playwright/actions.py`)
9. [ ] Active Explorer 노드 (`agent/nodes/active_explorer.py`)
10. [ ] Manual Capture Gateway (`agent/nodes/manual_capture.py`)

### Phase 3: GTM 설계 및 생성
11. [ ] Planning Agent — GA4 플랜 생성 + HITL (`agent/nodes/planning.py`)
12. [ ] GTM Creation Agent — Workspace 생성 포함 (`agent/nodes/gtm_creation.py`)
13. [ ] Publish Agent (`agent/nodes/publish.py`)
14. [ ] 진입점 (`main.py`)

### Phase 4: 확장
15. [x] End-to-End GA4 이커머스 테스트 — leekorea.co.kr 기준 (2026-04-18)
16. [ ] 문서 fetch 모듈 (`docs/fetcher.py`) + `config/media_sources.yaml` URL 기입
17. [ ] Naver/Kakao 태그 지원 추가

---

## 12. 알려진 버그 / 수정 이력

### 2026-04-18 — leekorea.co.kr 테스트 런 기반

| # | 버그 | 수정 방법 | 파일 |
|---|------|-----------|------|
| 1 | extraction_method=dom이어도 DL 이벤트가 실제로 캡처됐으면 DL 기반 GTM 설계를 사용해야 함 | `_classify_events()`로 DL vs DOM 이벤트 분류 후 `effective_method` 결정 | `planning.py` |
| 2 | GA4 Measurement ID를 설계안에 반영하지 않음 | user_request에서 `G-XXXXXXXX` 패턴 자동 추출 → Constant Variable 생성 + 모든 Tag에 주입 | `planning.py` |
| 3 | customEventFilter arg0에 `{{DLV - event}}` 사용 → GTM API 400 오류 | 반드시 `{{_event}}`로 강제 수정 (`_fix_custom_event_filter()`) | `gtm_creation.py` |
| 4 | LLM이 일부 CE Trigger(view_item, add_to_cart) 누락 생성 | `_fix_plan()`에서 DL 이벤트 순회 → 누락된 CE Trigger 자동 생성 | `gtm_creation.py` |
| 5 | DL 이벤트 Tag가 Click Trigger에 잘못 연결됨 (예: GA4-view_item → Click Trigger) | DL 이벤트 태그는 반드시 `CE - {event}` 트리거로 강제 교정 | `gtm_creation.py` |
| 6 | Publish 403 (insufficientPermissions) | OAuth 스코프 문제 아님 — GTM 계정 Publish 권한 부족. GTM UI에서 수동 Publish 필요 | 해결 불가 (GTM 계정 설정 문제) |

### Publish 403 해결 방법
1. GTM UI → 관리 → 사용자 관리 → 해당 계정에 Publish 권한 부여
2. 또는 GTM UI에서 직접 게시: `https://tagmanager.google.com/`
