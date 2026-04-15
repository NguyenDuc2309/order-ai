from langgraph.graph import END, START, StateGraph

from app.graph.nodes import build_query_node, decide_node, extract_node, search_node
from app.graph.state import SearchState


def route_decision(state: SearchState) -> str:
    if state["response"].type == "exact_match":
        return "exact_match"
    return "clarification"


def format_exact_node(state: SearchState) -> dict:
    return {"response": state["response"]}


def format_clarification_node(state: SearchState) -> dict:
    return {"response": state["response"]}


def build_pipeline():
    graph = StateGraph(SearchState)
    graph.add_node("extract_node", extract_node)
    graph.add_node("build_query_node", build_query_node)
    graph.add_node("search_node", search_node)
    graph.add_node("decide_node", decide_node)
    graph.add_node("format_exact", format_exact_node)
    graph.add_node("format_clarification", format_clarification_node)

    graph.add_edge(START, "extract_node")
    graph.add_edge("extract_node", "build_query_node")
    graph.add_edge("build_query_node", "search_node")
    graph.add_edge("search_node", "decide_node")
    graph.add_conditional_edges(
        "decide_node",
        route_decision,
        {
            "exact_match": "format_exact",
            "clarification": "format_clarification",
        },
    )
    graph.add_edge("format_exact", END)
    graph.add_edge("format_clarification", END)
    return graph.compile()


pipeline = build_pipeline()
