# GTM AI Agent — CLAUDE.md

> 이 파일은 Claude Code가 프로젝트를 이해하기 위한 헌법입니다.
> 상세 설계는 `PROJECT_SPEC.md`를 참고하세요.

---

## 프로젝트 개요

자연어로 요청하면 AI가 대상 페이지를 직접 탐색해 dataLayer 이벤트를 캡처하고,
GTM Variable / Trigger / Tag를 자동 생성 후 Publish하는 LangGraph 멀티에이전트 시스템.

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
Node 1  page_classifier    페이지 로드 + Listener 주입 + 페이지 타입 판단
Node 2  journey_planner    탐색 이벤트 목록 생성 + 큐 구성
Node 3  active_explorer    LLM Navigator + Playwright 루프 (핵심)
Node 4  manual_capture     purchase/refund 등 수동 캡처 게이트웨이
Node 5  planning           GTM 설계안 생성 + HITL (y/n)
Node 6  gtm_creation       Variable → Trigger → Tag 순서로 생성
Node 7  publish            Version 생성 + Publish
```

### 이벤트 처리 원칙

- **자동 캡처 가능**: page_view, view_item_list, view_item, add_to_cart, view_cart, begin_checkout
- **부분 자동화**: add_shipping_info, add_payment_info (더미 데이터 폼 입력)
- **자동화 불가**: purchase, refund → Node 4 Manual Capture Gateway로 전환

### Playwright 사용 원칙

- Event Listener는 반드시 `page.add_init_script()`로 주입한다 (페이지 이동 후에도 유지)
- `window.__gtm_captured`에 모든 dataLayer.push 이벤트를 누적한다
- LLM Navigator 루프에서 클릭 실패 시 최대 3회 재시도 후 Manual로 이관한다
- 액션(click/navigate/scroll/form_fill)은 `playwright/actions.py` 래퍼를 통해 실행한다

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
├── PROJECT_SPEC.md         # 상세 설계 문서
├── main.py
├── agent/
│   ├── graph.py
│   ├── state.py            # GTMAgentState TypedDict
│   ├── orchestrator.py
│   └── nodes/              # Node 1~7 각 파일
├── playwright/
│   ├── listener.py         # Persistent Event Listener
│   ├── navigator.py        # LLM Navigator 루프
│   └── actions.py          # 액션 래퍼
├── gtm/
│   ├── auth.py
│   ├── client.py
│   └── models.py
├── docs/
│   └── fetcher.py          # Naver/Kakao 문서 실시간 fetch
├── config/
│   └── media_sources.yaml  # 매체별 문서 URL
└── credentials/            # .gitignore 처리
```

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
