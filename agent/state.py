"""GTM AI Agent — LangGraph State 정의."""

from typing import TypedDict


class GTMAgentState(TypedDict):
    # ── 입력 (UI 폼 또는 CLI에서 전달) ────────────────────────────────────────
    user_request: str
    target_url: str
    tag_type: str               # "GA4" | "naver" | "kakao"
    account_id: str
    container_id: str
    workspace_id: str           # 신규 생성 후 저장
    measurement_id: str         # ★ UI 폼에서 전달된 G-XXXXXXXX (선택)

    # ── 설치할 이벤트 **명시 목록** (UI 체크박스 등) ────────────────────────
    # 비어 있으면 "자유 텍스트 모드": 괄호 파서/LLM 큐를 사용 (하위 호환).
    # 값이 있으면 strict: Journey Planner는 이 목록만 탐색·설계에 사용.
    selected_events: list       # list[str], GA4 이벤트명 소문자 권장

    # ── Node 1: Page Classifier ─────────────────────────────────────────────
    page_type: str              # "PLP" | "PDP" | "cart" | "checkout" | "unknown"
    existing_gtm_config: dict   # 현재 GTM 컨테이너 설정 (tags/triggers/variables)
    datalayer_status: str       # "full" | "partial" | "none"
    datalayer_events_found: list  # dataLayer에서 발견된 이벤트명 목록

    # ── Node 1.5: Structure Analyzer ─────────────────────────────────────────
    extraction_method: str      # "datalayer" | "dom" | "custom_js" | "json_ld"
    dom_selectors: dict         # {field: css_selector} — LLM이 HTML에서 추출
    selector_validation: dict   # {field: extracted_value} — Playwright로 검증된 값
    json_ld_data: dict          # JSON-LD 구조화 데이터 (있을 경우)
    click_triggers: dict        # {event_name: css_selector} — 클릭 트리거 대상
    site_url_patterns: dict     # page_type별 URL 패턴 추론 결과
    site_spa: bool              # SPA 추정 플래그

    # ── Node 2: Journey Planner ─────────────────────────────────────────────
    exploration_queue: list     # 탐색할 이벤트 목록 (순서 있음)
    auto_capturable: list       # 자동 캡처 가능 이벤트
    # 장바구니 담기 계열 → Node 3.25 전용 (이벤트명은 Journey Planner가 지정)
    cart_addition_events: list
    # 결제 시작 계열 → Node 3.5 전용
    begin_checkout_events: list
    manual_required: list       # 수동 캡처 필요 이벤트 (purchase, refund 등)

    # ── Node 3: Active Explorer ─────────────────────────────────────────────
    captured_events: list       # [{event, params, url, timestamp}, ...]
    exploration_log: list       # 각 시도 결과 로그 (디버깅용)
    current_url: str
    # PDP URL 마지막 스냅샷 — 장바구니 전용 노드가 current_url이 카트일 때 재개용
    last_pdp_url: str
    # Playbook surface_goal 미도달 등 드롭 판정 근거
    exploration_failures: list

    # ── Node 4: Manual Capture Gateway ──────────────────────────────────────
    manual_capture_results: dict    # {event_name: dataLayer_schema}
    skipped_events: list            # 사용자가 스킵 선택한 이벤트

    # ── Node 5: Planning Agent ──────────────────────────────────────────────
    doc_context: str            # fetch된 문서 본문 (Naver/Kakao용)
    doc_fetch_failed: bool      # fetch 실패 시 True → 내장 지식 폴백
    plan: dict                  # Variable/Trigger/Tag 설계안
    draft_plan: dict            # LLM 초안 (신뢰 전)
    canplan: dict               # 정규화 통과 후 단일 정규형
    evidence_pack: dict         # LLM 판단 근거 번들
    normalize_errors: list      # 정규화 경고/오류 목록
    canplan_hash: str           # UI 표시와 API 전송 동치 검증용 해시
    exploration_plan: list      # [{event, playbook}] 확장 큐 (신규 파이프라인)
    plan_approved: bool         # HITL 승인 여부
    hitl_feedback: str          # n 선택 시 사용자 피드백

    # ── Node 6-7: 실행 결과 ─────────────────────────────────────────────────
    created_variables: list
    created_triggers: list
    created_tags: list
    publish_result: dict
    publish_warning: str | None  # Publish 권한 부족 등 경고 (치명적 오류 아님)
    error: str | None

    # ── Node 3-4: 이벤트별 처리 내역 (Reporter용 구조화 로그) ────────────────
    # 각 항목: {event, method, result, selector, notes}
    # method 우선순위: datalayer > click_trigger_datalayer > click_trigger_dom
    #                > navigator_datalayer > dom_fallback > datalayer_dom_supplement
    #                > manual_standard > manual_paste > skipped
    event_capture_log: list

    # ── 토큰 사용량 (token_tracker에서 자동 수집) ────────────────────────────
    token_usage: dict  # token_tracker.summary() 결과

    # ── Node 8: Reporter ─────────────────────────────────────────────────────
    report_path: str | None  # 생성된 보고서 파일 경로

    # ── 실행 모드 ─────────────────────────────────────────────────────────────
    hitl_mode: str  # "cli" | "file" — HITL 승인 방식 (file: UI 폼, cli: 터미널)
