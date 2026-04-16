"""라우팅 로직.

LangGraph 엣지에서 다음 노드를 결정합니다.
"""

from __future__ import annotations

from agent.state import GTMAgentState


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
    오류가 있으면 END로 종료합니다.
    """
    if state.get("error"):
        return "__end__"
    if state.get("plan_approved"):
        return "gtm_creation"
    return "__end__"


def route_after_creation(state: GTMAgentState) -> str:
    """GTM Creation 이후 라우팅.

    오류 없으면 publish로, 오류 있으면 END.
    """
    if state.get("error"):
        return "__end__"
    return "publish"
