"""Node 8: Reporter.

전체 실행 결과를 마크다운 보고서로 생성합니다.
logs/{run_id}/report.md 에 저장됩니다.

보고서 구성:
1. 실행 기본 정보
2. dataLayer 분석 결과 및 추출 방식 결정 경위
3. 이벤트별 처리 내역 — 어떤 방법으로 캡처했는지, 왜 그 방법을 택했는지
4. 특이사항 (DOM fallback, manual 이관 등)
5. GTM 생성 결과 (Variable / Trigger / Tag 목록)
6. Publish 결과
7. 오류 내역 (있을 경우)
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import time

from agent.state import GTMAgentState
from utils import logger, token_tracker
from utils.ui_emitter import emit, reconcile_timeline_at_reporter, update_state

# 처리 방식 레이블 (보고서 표시용)
_METHOD_LABELS: dict[str, str] = {
    "datalayer":                  "dataLayer 직접 캡처",
    "click_trigger_datalayer":    "클릭 → dataLayer 캡처",
    "click_trigger_dom":          "클릭 → DOM 추출 (dataLayer 미발화)",
    "navigator_datalayer":        "LLM Navigator → dataLayer 캡처",
    "datalayer_dom_supplement":   "dataLayer 캡처 + DOM 보충",
    "dom_fallback":               "DOM 직접 추출 (Navigator 실패)",
    "manual_paste":               "수동 캡처 (사용자 직접 입력)",
    "manual_standard":            "수동 캡처 (GA4 표준 스키마 적용)",
    "manual":                     "Manual Gateway 이관 대기",
    "skipped":                    "스킵 (사용자 선택)",
}

_RESULT_EMOJI: dict[str, str] = {
    "success": "✅",
    "failed":  "❌",
    "pending": "⏳",
    "skipped": "⏭",
}

# dataLayer 우선순위가 적용된 방법들 (특이사항 없음)
_DATALAYER_METHODS = {"datalayer", "navigator_datalayer", "click_trigger_datalayer"}


async def reporter(state: GTMAgentState) -> GTMAgentState:
    """Node 8: 마크다운 보고서 생성 및 저장."""
    reconcile_timeline_at_reporter(has_error=bool(state.get("error")))
    emit("node_enter", node_id=8, node_key="reporter", title="Reporter")
    update_state(current_node=8, nodes_status={"reporter": "run"})
    _started = time.time()

    usage = token_tracker.summary()

    run_dir = logger.run_dir()
    if run_dir is None:
        run_dir = Path("logs") / datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir.mkdir(parents=True, exist_ok=True)

    report_path = run_dir / "report.md"
    content = _build_report(state, usage)

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info(f"[Reporter] 보고서 저장 완료 → {report_path.resolve()}")
    print(f"\n[Reporter] 보고서가 생성되었습니다: {report_path.resolve()}")

    total = usage.get("total", 0)
    total_calls = usage.get("total_calls", 0)
    print(f"[Reporter] 총 LLM 토큰 사용량: {total:,} tokens ({total_calls}회 호출)")

    _dur = int((time.time() - _started) * 1000)
    emit("node_exit", node_id=8, status="done", duration_ms=_dur)
    # 전체 status는 runner가 error 유무에 따라 마지막에 기록 (여기서 done으로 덮어쓰면 잠깐 어긋남)
    update_state(
        nodes_status={"reporter": "done"},
        events_count=len(state.get("captured_events", [])),
        duration=f"{_dur // 1000}s",
    )

    return {
        **state,
        "token_usage": usage,
        "report_path": str(report_path.resolve()),
    }


# ──────────────────────────────────────────────────────────────────────────────
# 보고서 빌더
# ──────────────────────────────────────────────────────────────────────────────

def _build_report(state: GTMAgentState, usage: dict | None = None) -> str:
    sections: list[str] = [
        _section_header(state),
        _section_datalayer_analysis(state),
        _section_event_table(state),
        _section_notable_cases(state),
        _section_gtm_resources(state),
        _section_publish(state),
    ]

    error = state.get("error")
    if error:
        sections.append(_section_error(error))

    sections.append(_section_raw_log(state))
    sections.append(_section_token_usage(usage or {}))

    return "\n\n".join(s for s in sections if s)


def _section_header(state: GTMAgentState) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"""# GTM AI Agent 실행 보고서

| 항목 | 값 |
|------|-----|
| 실행 일시 | {now} |
| 대상 URL | {state.get("target_url", "-")} |
| 사용자 요청 | {state.get("user_request", "-")} |
| 태그 유형 | {state.get("tag_type", "GA4")} |
| 페이지 타입 | {state.get("page_type", "-")} |"""


def _section_datalayer_analysis(state: GTMAgentState) -> str:
    dl_status = state.get("datalayer_status", "none")
    dl_events = state.get("datalayer_events_found", [])
    extraction_method = state.get("extraction_method", "datalayer")
    json_ld = state.get("json_ld_data", {})

    status_map = {
        "full":    "완전 (full) — 모든 이벤트가 dataLayer로 발화됨",
        "partial": "부분 (partial) — 일부 이벤트만 dataLayer에 존재",
        "none":    "없음 (none) — dataLayer 미구현 사이트",
    }
    status_label = status_map.get(dl_status, dl_status)

    method_map = {
        "datalayer":     "dataLayer 직접 사용 (Structure Analyzer 스킵)",
        "json_ld":       "JSON-LD 구조화 데이터 활용",
        "json_ld+dom":   "JSON-LD + DOM selector 혼용",
        "dom":           "DOM selector 직접 추출",
        "custom_js":     "Custom JavaScript 추출",
    }
    method_label = method_map.get(extraction_method, extraction_method)

    found_str = ", ".join(dl_events) if dl_events else "없음"
    json_ld_str = f"발견 ({len(json_ld)}개 항목)" if json_ld else "없음"

    decision_reason = _explain_extraction_decision(dl_status, extraction_method)

    return f"""## 1. dataLayer 분석 결과

| 항목 | 값 |
|------|-----|
| dataLayer 상태 | {status_label} |
| 발견된 이벤트 | {found_str} |
| JSON-LD 데이터 | {json_ld_str} |
| **최종 추출 방식** | **{method_label}** |

**추출 방식 결정 경위:** {decision_reason}"""


def _explain_extraction_decision(dl_status: str, extraction_method: str) -> str:
    if dl_status == "full":
        return (
            "dataLayer가 완전하게 구현되어 있으므로 Structure Analyzer를 건너뛰고 "
            "dataLayer 이벤트를 직접 활용했습니다."
        )
    if extraction_method == "json_ld":
        return (
            "dataLayer가 불완전하지만 JSON-LD 구조화 데이터가 충분히 발견되어 "
            "이를 우선 활용했습니다."
        )
    if extraction_method in ("dom", "json_ld+dom"):
        return (
            f"dataLayer 상태가 '{dl_status}'이므로 Structure Analyzer를 실행하여 "
            "HTML에서 CSS selector를 추출하고 Playwright로 검증했습니다. "
            "GTM 설계 시 DOM Element / Custom JS Variable과 Click Trigger를 사용합니다."
        )
    if extraction_method == "datalayer" and dl_status == "none":
        return (
            "초기 페이지 로드 시 dataLayer 이커머스 이벤트는 없었으나, "
            "Active Explorer 탐색 중 실제 dataLayer 이벤트(view_item_list, view_item, add_to_cart 등)가 "
            "발화됨이 확인됐습니다. dataLayer 기반으로 GTM을 설계했습니다. "
            "dataLayer를 발화시키지 않는 이벤트(add_to_wishlist 등)는 Click Trigger 방식을 사용합니다."
        )
    return f"추출 방식: {extraction_method}"


def _section_event_table(state: GTMAgentState) -> str:
    logs: list[dict] = state.get("event_capture_log", [])
    if not logs:
        return ""

    rows: list[str] = []
    for entry in logs:
        event = entry.get("event", "-")
        method = entry.get("method", "-")
        result = entry.get("result", "-")
        notes = entry.get("notes", "")

        method_label = _METHOD_LABELS.get(method, method)
        result_icon = _RESULT_EMOJI.get(result, result)
        rows.append(f"| {event} | {method_label} | {result_icon} {result} | {notes} |")

    table = "\n".join(rows)
    return f"""## 2. 이벤트별 처리 내역

| 이벤트 | 처리 방식 | 결과 | 비고 |
|--------|----------|------|------|
{table}"""


def _section_notable_cases(state: GTMAgentState) -> str:
    logs: list[dict] = state.get("event_capture_log", [])
    notable: list[str] = []

    for i, entry in enumerate(logs, 1):
        method = entry.get("method", "")
        result = entry.get("result", "")
        event = entry.get("event", "")
        notes = entry.get("notes", "")
        selector = entry.get("selector", "")

        # dataLayer 정상 캡처가 아닌 모든 케이스 → 특이사항
        if method in _DATALAYER_METHODS and result == "success":
            continue

        if method == "click_trigger_dom":
            sel_info = f" (selector: `{selector}`)" if selector else ""
            notable.append(
                f"- **{event}**: dataLayer 미발화{sel_info} — "
                f"버튼 클릭 후 DOM에서 직접 데이터 추출했습니다. {notes}"
            )
        elif method == "datalayer_dom_supplement":
            notable.append(
                f"- **{event}**: dataLayer 이벤트는 발화됐으나 ecommerce 파라미터 누락 — "
                f"DOM 데이터로 보충했습니다."
            )
        elif method == "dom_fallback":
            notable.append(
                f"- **{event}**: LLM Navigator가 자동 탐색에 실패 — "
                f"DOM selector로 데이터를 직접 추출했습니다."
            )
        elif method == "manual_standard":
            notable.append(
                f"- **{event}**: 자동화 불가 이벤트 (purchase/refund 등) — "
                f"GA4 표준 스키마로 GTM 설계를 진행했습니다. "
                f"실제 이벤트 데이터와 파라미터명이 다를 수 있으니 배포 후 검증이 필요합니다."
            )
        elif method == "manual_paste":
            notable.append(
                f"- **{event}**: 자동화 불가 이벤트 — "
                f"사용자가 브라우저 콘솔에서 직접 수집한 dataLayer JSON을 사용했습니다."
            )
        elif method == "skipped":
            notable.append(f"- **{event}**: 사용자 선택으로 스킵되었습니다.")
        elif result == "failed":
            notable.append(f"- **{event}**: 모든 캡처 방법 실패. {notes}")

    doc_fetch_failed = state.get("doc_fetch_failed", False)
    tag_type = state.get("tag_type", "GA4")
    if doc_fetch_failed:
        notable.append(
            f"- **문서 fetch 실패**: {tag_type} 공식 문서를 가져오지 못했습니다. "
            f"LLM 내장 지식으로 폴백하여 설계를 진행했습니다."
        )

    if not notable:
        return "## 3. 특이사항\n\n특이사항 없음 — 모든 이벤트가 dataLayer를 통해 정상 캡처되었습니다."

    return "## 3. 특이사항\n\n" + "\n".join(notable)


def _section_gtm_resources(state: GTMAgentState) -> str:
    variables = state.get("created_variables", [])
    triggers = state.get("created_triggers", [])
    tags = state.get("created_tags", [])
    workspace_id = state.get("workspace_id", "-")

    if not (variables or triggers or tags):
        return "## 4. GTM 생성 결과\n\nGTM 리소스가 생성되지 않았습니다."

    def _list_resources(items: list[dict]) -> str:
        if not items:
            return "  - (없음)"
        return "\n".join(f"  - `{item.get('name', item)}`" for item in items)

    return f"""## 4. GTM 생성 결과

- **Workspace ID**: `{workspace_id}`
- Variable {len(variables)}개 / Trigger {len(triggers)}개 / Tag {len(tags)}개

### Variables ({len(variables)}개)
{_list_resources(variables)}

### Triggers ({len(triggers)}개)
{_list_resources(triggers)}

### Tags ({len(tags)}개)
{_list_resources(tags)}"""


def _section_publish(state: GTMAgentState) -> str:
    publish_warning = state.get("publish_warning")
    publish_result = state.get("publish_result", {})

    if publish_warning:
        workspace_id = state.get("workspace_id", "-")
        return f"""## 5. Publish 결과

⚠️ **{publish_warning}**

GTM 리소스(Variable/Trigger/Tag) 생성은 완료되었습니다.
GTM UI에서 Workspace `{workspace_id}`를 직접 Publish하세요.

**해결 방법**:
1. **[권장] GTM UI 직접 Publish**: https://tagmanager.google.com/ → 컨테이너 선택 → 제출
2. **GTM 계정 권한 확인**: GTM → 관리 → 사용자 관리 → 해당 계정에 Publish 권한 부여
3. **OAuth 재인증**: `credentials/token.json` 삭제 후 `python gtm/auth.py` 재실행"""

    if not publish_result:
        return "## 5. Publish 결과\n\nPublish가 실행되지 않았습니다."

    version = publish_result.get("containerVersion", publish_result)
    version_id = version.get("containerVersionId", "-")
    container_id = version.get("containerId", state.get("container_id", "-"))
    status = "성공" if not state.get("error") else "실패"

    return f"""## 5. Publish 결과

| 항목 | 값 |
|------|-----|
| 상태 | {status} |
| Container ID | {container_id} |
| Published Version ID | {version_id} |"""


def _section_error(error: str) -> str:
    return f"""## ⚠️ 오류 내역

```
{error}
```"""


_NODE_LABELS: dict[str, str] = {
    "page_classifier": "Node 1 — Page Classifier",
    "structure_analyzer": "Node 1.5 — Structure Analyzer",
    "journey_planner": "Node 2 — Journey Planner",
    "navigator": "Node 3 — Active Explorer (Navigator)",
    "planning": "Node 5 — Planning",
}


def _section_token_usage(usage: dict) -> str:
    total = usage.get("total", 0)
    if not total:
        return ""

    total_input = usage.get("total_input", 0)
    total_output = usage.get("total_output", 0)
    total_calls = usage.get("total_calls", 0)
    by_node: dict = usage.get("by_node", {})

    rows: list[str] = []
    for node, data in by_node.items():
        label = _NODE_LABELS.get(node, node)
        rows.append(
            f"| {label} | {data['calls']} | "
            f"{data['input']:,} | {data['output']:,} | {data['total']:,} |"
        )

    table = "\n".join(rows)
    return f"""## 7. LLM 토큰 사용량

| 노드 | 호출 횟수 | Input tokens | Output tokens | 합계 |
|------|----------|-------------|--------------|------|
{table}
| **합계** | **{total_calls}** | **{total_input:,}** | **{total_output:,}** | **{total:,}** |"""


def _section_raw_log(state: GTMAgentState) -> str:
    log: list[str] = state.get("exploration_log", [])
    if not log:
        return ""
    log_lines = "\n".join(f"- {entry}" for entry in log)
    return f"""## 8. 실행 로그 (상세)

<details>
<summary>펼치기</summary>

{log_lines}

</details>"""
