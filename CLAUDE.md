# GTM AI Agent — 루트 CLAUDE.md

> 이 파일은 **개요와 CLAUDE.md 작성 가이드**만 담는다.
> 기능·메서드·구현 철학은 각 폴더의 CLAUDE.md를 읽을 것.

---

## 프로젝트 한 줄 요약

자연어 요청 → AI가 대상 페이지를 탐색해 dataLayer 이벤트를 캡처하고,
GTM Variable / Trigger / Tag를 자동 생성 후 Publish하는 LangGraph 멀티에이전트 시스템.

---

## 폴더 구조 & 각 CLAUDE.md 위치

```
gtm_ai/
├── CLAUDE.md                  ← 지금 이 파일: 개요 + 가이드만
├── agent/
│   ├── CLAUDE.md              ← StateGraph 토폴로지, 라우팅, State 설계
│   └── nodes/
│       └── CLAUDE.md          ← 각 Node의 역할·입력·출력·핵심 로직
├── browser/
│   └── CLAUDE.md              ← Playwright 원칙, listener 주입, navigator 루프
├── gtm/
│   └── CLAUDE.md              ← GTM API 클라이언트, 모델, 인증, 네이밍
├── utils/
│   └── CLAUDE.md              ← ui_emitter 사용법, token_tracker 사용법
├── docs/
│   └── CLAUDE.md              ← 문서 fetch 전략, 폴백 처리
├── config/
│   └── CLAUDE.md              ← media_sources.yaml 포맷, 매체 추가 방법
└── ui/
    └── CLAUDE.md              ← UI 아키텍처, 훅, 화면 구성, 데이터 흐름
```

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
