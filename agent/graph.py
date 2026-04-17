"""LangGraph StateGraph 정의.

Node 1 → 1.5(조건부) → 2 → 3 → (4) → 5 → 6 → 7 → 8 순서로 실행됩니다.
- dataLayer가 불완전하면 Node 1.5 Structure Analyzer를 실행합니다.
- manual_required 이벤트 유무에 따라 Node 4를 조건부로 실행합니다.
- Node 8 Reporter는 항상 마지막에 실행됩니다 (오류 경로 포함).
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
from agent.nodes.reporter import reporter
from agent.nodes.structure_analyzer import structure_analyzer
from agent.orchestrator import (
    route_after_classifier,
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
    graph.add_node("structure_analyzer", structure_analyzer)
    graph.add_node("journey_planner", journey_planner)
    graph.add_node("active_explorer", active_explorer)
    graph.add_node("manual_capture", manual_capture)
    graph.add_node("planning", planning)
    graph.add_node("gtm_creation", gtm_creation)
    graph.add_node("publish", publish)
    graph.add_node("reporter", reporter)   # Node 8: 항상 마지막 실행

    # 시작
    graph.add_edge(START, "page_classifier")

    # Node 1 → Node 1.5(조건부) → Node 2
    graph.add_conditional_edges(
        "page_classifier",
        route_after_classifier,
        {
            "structure_analyzer": "structure_analyzer",
            "journey_planner": "journey_planner",
        },
    )
    graph.add_edge("structure_analyzer", "journey_planner")
    graph.add_edge("journey_planner", "active_explorer")

    # Node 3 → Node 4(조건부) → Node 5
    graph.add_conditional_edges(
        "active_explorer",
        route_after_explorer,
        {
            "manual_capture": "manual_capture",
            "planning": "planning",
        },
    )
    graph.add_edge("manual_capture", "planning")

    # Node 5 → Node 6 (HITL 승인 시), 미승인/오류 시 → reporter
    graph.add_conditional_edges(
        "planning",
        route_after_planning,
        {
            "gtm_creation": "gtm_creation",
            "reporter": "reporter",   # 미승인 또는 오류 → 보고서만 생성
        },
    )

    # Node 6 → Node 7 (오류 없을 시), 오류 시 → reporter
    graph.add_conditional_edges(
        "gtm_creation",
        route_after_creation,
        {
            "publish": "publish",
            "reporter": "reporter",   # 생성 오류 → 보고서만 생성
        },
    )

    # Node 7 → Node 8 (항상)
    graph.add_edge("publish", "reporter")

    # Node 8 → END
    graph.add_edge("reporter", END)

    return graph


def compile_graph():
    """컴파일된 실행 가능한 그래프를 반환합니다."""
    return build_graph().compile()
