# GTM AI Agent — 참고 자료 정리

> 작성일: 2026-04-16  
> 목적: 프로젝트 설계 전 기존 유사 구현 사례 조사

---

## Synter Media AI — Google Tag Manager Agent

**출처**: [github.com/Synter-Media-AI/google-tag-manager-agent](https://github.com/Synter-Media-AI/google-tag-manager-agent)

### 지원 기능

| 기능 | 세부 내용 |
|------|-----------|
| 태그 생성 | Google Ads, Meta Pixel, LinkedIn, TikTok 전환 추적 |
| 트리거 구성 | 페이지 방문, 폼 제출, 구매 이벤트 |
| 변수 관리 | dataLayer 변수, URL 변수 생성 |
| 컨테이너 감사 | 중복 태그 탐지, 오류 정리 |
| 게시 | 버전 관리, 미리보기 모드 지원 |

### 아키텍처

- **MCP(Model Context Protocol)** 기반
- 지원 환경: Amp, Cursor, VS Code (Copilot), Claude Desktop
- API: `SYNTER_API_KEY` (자체 Synter API — GTM API v2 래퍼로 추정)

### 우리 프로젝트와 비교

| 항목 | Synter | 우리 프로젝트 |
|------|--------|--------------|
| 아키텍처 | MCP 기반 | LangGraph 멀티에이전트 |
| API | 독점 Synter API | GTM API v2 직접 연동 |
| dataLayer 분석 | 미확인 | Playwright로 직접 분석 |
| HITL | 미확인 | Plan 단계 사용자 승인 |

### 기능 범위 체크리스트 (Synter 사례 기반)

- [x] 태그 생성 (GA4, Google Ads, Meta Pixel, 커스텀 HTML)
- [x] 트리거 생성 (페이지뷰, 클릭, 폼, 커스텀 이벤트)
- [x] 변수 생성 (dataLayer 변수, URL 변수)
- [x] 컨테이너 게시 (Version 생성 → Publish)
- [ ] 컨테이너 감사 (중복/오류 탐지) — 추후 고려
- [ ] 미리보기 모드 지원 — 추후 고려
