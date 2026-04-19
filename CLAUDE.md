# GTM AI Agent — 루트 CLAUDE.md

> 이 파일은 **개요와 CLAUDE.md 작성 가이드**만 담는다.
> 기능·메서드·구현 철학은 각 폴더의 CLAUDE.md를 읽을 것.

---

## 프로젝트 한 줄 요약

사용자가 UI 체크박스로 **설치할 GA4 이벤트**를 고르면 → AI가 대상 페이지를 탐색해 dataLayer 이벤트를 캡처하고,
GTM Variable / Trigger / Tag를 자동 생성 후 Publish하는 LangGraph 멀티에이전트 시스템.

> 이벤트 스코프는 UI(`EventPicker`) → `selected_events` → `agent/request_events.resolve_selected_events()`가 단일 근거로 결정한다.
> `user_request` 문자열은 자유 텍스트 **메모**이며 설치 대상을 직접 결정하지 않는다(CLI/레거시는 `( … )` 괄호 파서로 폴백).

---

## 폴더 구조 & 각 CLAUDE.md 위치

```
gtm_ai/
├── CLAUDE.md                       ← 지금 이 파일: 개요 + 가이드만
├── agent/
│   ├── CLAUDE.md                   ← StateGraph 토폴로지, 라우팅, State 설계
│   ├── canplan/
│   │   └── CLAUDE.md               ← CanPlan 스키마·정규화·EvidencePack·CJS 템플릿
│   ├── playbooks/
│   │   └── CLAUDE.md               ← 이벤트별 Playbook(YAML) 계약·loader
│   └── nodes/
│       └── CLAUDE.md               ← 각 Node의 역할·입력·출력·핵심 로직
├── browser/
│   └── CLAUDE.md                   ← Playwright 원칙, listener 주입, navigator 루프
├── gtm/
│   └── CLAUDE.md                   ← GTM API 클라이언트, 모델, 인증, 네이밍, spec_builder
├── utils/
│   └── CLAUDE.md                   ← ui_emitter 사용법, token_tracker 사용법
├── docs/
│   ├── CLAUDE.md                   ← 문서 fetch 전략, 폴백 처리
│   ├── VARIABLE_PIPELINE_REDESIGN.md  ← CanPlan 파이프라인 재설계 기준 문서(정규화 규칙, §16 진행 상태)
│   └── gtm-variable-api.md
├── config/
│   ├── CLAUDE.md                   ← media_sources, exploration_limits, llm_models 등 설정
│   ├── exploration_limits.yaml     ← 전용 탐색 노드 LLM 스텝 상한
│   ├── exploration_limits_loader.py
│   ├── llm_models.yaml             ← 구역(zone)별 OpenAI 채팅 모델 ID
│   └── llm_models_loader.py
├── tests/
│   └── CLAUDE.md                   ← 테스트 실행 방식(pytest 없이 직접 실행), 골든 케이스
└── ui/
    └── CLAUDE.md                   ← UI 아키텍처, 훅, 화면 구성, 데이터 흐름
```

### 신규/변경 요약 (2026-04)

- `agent/canplan/` — CanPlan(`canplan/1`) 스키마·Draft→Canonical 정규화·EvidencePack 합성·CJS 템플릿 레지스트리.
- `agent/playbooks/` — GA4 이커머스 이벤트별 `surface_goal`·`entry_hints`·`observation`·`trigger_fallbacks` YAML과 loader.
- `gtm/spec_builder.py` — CanPlan → GTM API 스펙 직렬화(레거시 `_fix_plan`/`_build_*` 경로와 분리).
- `docs/VARIABLE_PIPELINE_REDESIGN.md` — 파이프라인 재설계 설계 문서(§16 구현 진행 상태 포함).
- `tests/` — `spec_builder`·CanPlan 정규화 골든 테스트(외부 pytest 의존 없이 `_run()`으로 직접 실행).

---

## 기술 스택

| 항목 | 버전/결정 |
|------|----------|
| Python | 3.11 |
| LangGraph | >=0.2 |
| langchain-openai | >=0.2 |
| Playwright | >=1.44 |
| google-api-python-client | >=2.0 |
| httpx | >=0.27 |
| beautifulsoup4 | >=4.12 |
| UI | React (Babel CDN), vanilla CSS |

---

## 실행

```bash
pip install -r requirements.txt
playwright install chromium

python gtm/auth.py        # OAuth 최초 인증 (한 번만)
python serve_ui.py        # UI 서버 → http://localhost:8766/ui/ (`serve_ui.py`의 PORT)
python main.py            # CLI 직접 실행
```

Windows에서 `python`이 PATH에 없으면 동일하게 **`py -3`** 로 실행하면 된다 (`py -3 serve_ui.py`, `py -3 main.py`, `py -3 gtm/auth.py`).

**진단**: PDP에서 dataLayer `view_item` 재현만 볼 때 `py -3 scripts/check_pdp_view_item.py` (옵션 `--headed`). 상세 로그 산출물은 `utils/CLAUDE.md`의 `logger.py` 절 참고.

Playwright 창: `serve_ui` / 노드 공통으로 `GTM_AI_HEADLESS`가 `1|true|yes`일 때만 headless. `serve_ui`는 값이 없으면 **`GTM_AI_HEADLESS=0`(headed)** 을 기본 설정한다. 상세는 `agent/nodes/CLAUDE.md`, `.env.example` 참고.

---

## CLAUDE.md 작성 규칙

| 레벨 | 위치 | 담을 내용 |
|------|------|----------|
| 루트 | `gtm_ai/CLAUDE.md` | 개요, 스택, 폴더맵, 이 가이드 |
| 중간 | `agent/CLAUDE.md` 등 | 해당 패키지의 설계 원칙, 주요 인터페이스 |
| 최하위 | `agent/nodes/CLAUDE.md` 등 | 메서드 시그니처, 동작 흐름, 엣지케이스, 철학 |

**규칙**
- 루트 CLAUDE.md에 구현 세부사항을 적지 않는다.
- 코드가 바뀌면 해당 폴더의 CLAUDE.md도 같이 업데이트한다.
- 복사·붙여넣기 금지 — 상위 파일이 하위 내용을 중복 기술하지 않는다.
- 각 CLAUDE.md 첫 줄에 `# {패키지명} CLAUDE.md` 형식으로 제목을 쓴다.

---

## 공통 안정성 규칙 (전 노드 공통)

로컬 MVP라도 **LLM 호출·JSON 파싱·브라우저 종료**는 파이프라인을 죽이지 않게 방어한다.

- **ChatOpenAI 인스턴스는 `utils/llm_json.make_chat_llm`으로 lazy 생성**한다. 모듈 최상단 `_llm = ChatOpenAI(...)` 패턴 금지 — 임포트 시점 API 키 의존으로 크래시한다.
- **LLM 응답 JSON 파싱은 `utils/llm_json.parse_llm_json`만 사용**한다. `split("```")[1]` 같은 직접 파싱은 펜스가 하나일 때 IndexError를 낸다.
- **모든 `ainvoke`는 `try/except`로 감싼다**. 네트워크·rate limit·타임아웃은 "기본 큐 폴백" 또는 `{"action": "impossible"}` 결정으로 변환한다.
- **`captured_events` 중복 판정은 `browser.listener.event_fingerprint`로 튜플화한 뒤 `set`으로 비교**한다. dict 동등성(`in`) 비교는 메타 필드가 추가되면 깨진다.
- **`browser.close()` 예외는 `logger.debug`로 남긴다**. `except Exception: pass`로 완전히 삼키지 않는다.
- **Navigator 스텝 상한은 `config/exploration_limits.yaml`에서 로드**한다(`navigator` / `cart_addition` / `begin_checkout`).
- **노드·Navigator별 LLM 모델 ID는 `config/llm_models.yaml`**에서 로드한다(`config.llm_models_loader.llm_model`). Navigator 생성자에 `model=`을 넘기면 YAML보다 우선한다.
- **사용자 대면이 아닌 로그는 `utils.logger`만 사용**한다(`print()` 금지). CLI HITL 프롬프트처럼 사용자가 직접 읽어야 하는 출력만 `print` 허용.
- **LLM 자유 JS 금지**: Custom JavaScript 변수는 `agent/canplan/cjs_templates.py`의 등록된 `template_id`만 허용한다. 자유 작성 CJS는 `normalize.py`가 `POLICY_VIOLATION`으로 반려한다.
- **in_set 연산자 금지**: CanPlan 필터 조건에서 `in_set`은 쓰지 않는다(정규화에서 거부, 레거시 경로에서도 `gtm_creation._reject_in_set_in_legacy`가 차단). 실제 의도가 multi-match면 regex/여러 조건으로 분해한다.
- **CanPlan 경로 토글**: `STRICT_CANPLAN=1`이면 정규화 실패 시 LLM 1회 재시도 후 실패 처리하고 레거시 경로로 폴백하지 않는다. 기본(0)은 경고 + 레거시 허용.
