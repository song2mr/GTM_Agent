"""라우팅 로직.

LangGraph 엣지에서 다음 노드를 결정합니다.
모든 종료 경로는 END 대신 reporter를 거칩니다.
"""

from __future__ import annotations

from agent.state import GTMAgentState


def route_after_classifier(state: GTMAgentState) -> str:
    """Page Classifier 이후 라우팅.

    dataLayer가 완전(full)하면 바로 journey_planner로,
    불완전(partial/none)하면 structure_analyzer로 이동합니다.
    """
    status = state.get("datalayer_status", "none")
    if status == "full":
        return "journey_planner"
    return "structure_analyzer"


def route_after_explorer(state: GTMAgentState) -> str:
    """Active Explorer 이후 라우팅.

    manual_required 이벤트가 있으면 manual_capture로,
    없으면 planning으로 이동합니다.
    """
    if state.get("manual_required"):
        return "manual_capture"
    return "planning"


def route_after_planning(state: GTMAgentState) -> str:
    """Planning 이후 라우팅.

    plan_approved=True이면 gtm_creation으로,
    미승인 또는 오류 시 reporter로 이동하여 보고서를 생성합니다.
    """
    if state.get("error"):
        return "reporter"
    if state.get("plan_approved"):
        return "gtm_creation"
    return "reporter"


def route_after_creation(state: GTMAgentState) -> str:
    """GTM Creation 이후 라우팅.

    오류 없으면 publish로, 오류 있으면 reporter로 이동합니다.
    오류가 있어도 reporter를 통해 어디까지 완료됐는지 기록합니다.
    """
    if state.get("error"):
        return "reporter"
    return "publish"
