"""GTM AI Agent — LangGraph State 정의."""

from typing import TypedDict


class GTMAgentState(TypedDict):
    # ── 입력 (.env에서 로드) ────────────────────────────────────────────────
    user_request: str
    target_url: str
    tag_type: str               # "GA4" | "naver" | "kakao"
    account_id: str
    container_id: str
    workspace_id: str           # 신규 생성 후 저장

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

    # ── Node 2: Journey Planner ─────────────────────────────────────────────
    exploration_queue: list     # 탐색할 이벤트 목록 (순서 있음)
    auto_capturable: list       # 자동 캡처 가능 이벤트
    manual_required: list       # 수동 캡처 필요 이벤트 (purchase, refund 등)

    # ── Node 3: Active Explorer ─────────────────────────────────────────────
    captured_events: list       # [{event, params, url, timestamp}, ...]
    exploration_log: list       # 각 시도 결과 로그 (디버깅용)
    current_url: str

    # ── Node 4: Manual Capture Gateway ──────────────────────────────────────
    manual_capture_results: dict    # {event_name: dataLayer_schema}
    skipped_events: list            # 사용자가 스킵 선택한 이벤트

    # ── Node 5: Planning Agent ──────────────────────────────────────────────
    doc_context: str            # fetch된 문서 본문 (Naver/Kakao용)
    doc_fetch_failed: bool      # fetch 실패 시 True → 내장 지식 폴백
    plan: dict                  # Variable/Trigger/Tag 설계안
    plan_approved: bool         # HITL 승인 여부
    hitl_feedback: str          # n 선택 시 사용자 피드백

    # ── Node 6-7: 실행 결과 ─────────────────────────────────────────────────
    created_variables: list
    created_triggers: list
    created_tags: list
    publish_result: dict
    error: str | None

    # ── Node 3-4: 이벤트별 처리 내역 (Reporter용 구조화 로그) ────────────────
    # 각 항목: {event, method, result, selector, notes}
    # method 우선순위: datalayer > click_trigger_datalayer > click_trigger_dom
    #                > navigator_datalayer > dom_fallback > datalayer_dom_supplement
    #                > manual_standard > manual_paste > skipped
    event_capture_log: list

    # ── Node 8: Reporter ─────────────────────────────────────────────────────
    report_path: str | None  # 생성된 보고서 파일 경로
