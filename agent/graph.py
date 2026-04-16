"""LangGraph StateGraph 정의.

Node 1 → 2 → 3 → (4) → 5 → 6 → 7 순서로 실행됩니다.
manual_required 이벤트 유무에 따라 Node 4를 조건부로 실행합니다.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from agent.nodes.active_explorer import active_explorer
from agent.nodes.gtm_creation import gtm_creation
from agent.nodes.journey_planner import journey_planner
from agent.nodes.manual_capture import manual_capture
from agent.nodes.page_classifier import page_classifier
from agent.nodes.planning import planning
from agent.nodes.publish import publish
from agent.orchestrator import (
    route_after_creation,
    route_after_explorer,
    route_after_planning,
)
from agent.state import GTMAgentState


def build_graph() -> StateGraph:
    """GTM AI Agent LangGraph를 빌드하고 반환합니다."""
    graph = StateGraph(GTMAgentState)

    # 노드 등록
    graph.add_node("page_classifier", page_classifier)
    graph.add_node("journey_planner", journey_planner)
    graph.add_node("active_explorer", active_explorer)
    graph.add_node("manual_capture", manual_capture)
    graph.add_node("planning", planning)
    graph.add_node("gtm_creation", gtm_creation)
    graph.add_node("publish", publish)

    # 엣지 정의
    graph.add_edge(START, "page_classifier")
    graph.add_edge("page_classifier", "journey_planner")
    graph.add_edge("journey_planner", "active_explorer")

    # Active Explorer → Manual Capture (조건부) → Planning
    graph.add_conditional_edges(
        "active_explorer",
        route_after_explorer,
        {
            "manual_capture": "manual_capture",
            "planning": "planning",
        },
    )
    graph.add_edge("manual_capture", "planning")

    # Planning → GTM Creation (HITL 승인 시)
    graph.add_conditional_edges(
        "planning",
        route_after_planning,
        {
            "gtm_creation": "gtm_creation",
            "__end__": END,
        },
    )

    # GTM Creation → Publish (오류 없을 시)
    graph.add_conditional_edges(
        "gtm_creation",
        route_after_creation,
        {
            "publish": "publish",
            "__end__": END,
        },
    )

    graph.add_edge("publish", END)

    return graph


def compile_graph():
    """컴파일된 실행 가능한 그래프를 반환합니다."""
    return build_graph().compile()
