"""main.py 초기화 구간에 추가할 예시 (patch).

기존 main.py의 `logger.setup()` 호출 직후에 아래 블록을 넣으면 된다.
파일 전체를 교체하지 말고, 이 부분만 복사해서 적용.
"""

# ──────────────────────────────────────────────────────────────────────────
# main.py 의 async def main() 내부, `run_dir = logger.setup()` 뒤에 추가:
# ──────────────────────────────────────────────────────────────────────────

from utils.ui_emitter import set_run_dir, emit, update_state, write_history_index
from pathlib import Path

run_dir = logger.setup()          # (기존 라인)
set_run_dir(run_dir)               # ★ 추가

# 초기 state.json 생성 (History 화면에서 바로 보이도록)
update_state(
    run_id=run_dir.name,
    status="running",
    started_at=run_dir.name,       # 시간 포맷으로 쓰고 싶으면 datetime으로 교체
    target_url=target_url,
    user_request=user_request,
    tag_type=tag_type,
    current_node=1,
    nodes=[
        {"id": 1,   "title": "Page Classifier",    "status": "queued"},
        {"id": 1.5, "title": "Structure Analyzer", "status": "queued"},
        {"id": 2,   "title": "Journey Planner",    "status": "queued"},
        {"id": 3,   "title": "Active Explorer",    "status": "queued"},
        {"id": 4,   "title": "Manual Capture",     "status": "queued"},
        {"id": 5,   "title": "Planning · HITL",    "status": "queued"},
        {"id": 6,   "title": "GTM Creation",       "status": "queued"},
        {"id": 7,   "title": "Publish",            "status": "queued"},
        {"id": 8,   "title": "Reporter",           "status": "queued"},
    ],
)

emit(
    "run_start",
    run_id=run_dir.name,
    target_url=target_url,
    user_request=user_request,
    tag_type=tag_type,
    account_id=os.environ["GTM_ACCOUNT_ID"],
    container_id=os.environ["GTM_CONTAINER_ID"],
)

# (기존 graph.ainvoke 호출)
final_state = await graph.ainvoke(initial_state)

# ──────────────────────────────────────────────────────────────────────────
# main 끝부분, 보고서 경로 출력 전에 추가:
# ──────────────────────────────────────────────────────────────────────────

# 최종 상태 갱신
update_state(
    status="done" if not final_state.get("error") else "failed",
    events_count=len(final_state.get("captured_events", [])),
)
emit("run_end",
     report_path=str(final_state.get("report_path") or ""),
     token_usage=final_state.get("token_usage", {}))

# History 화면용 index.json 갱신
write_history_index(Path("logs"))
