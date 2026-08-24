from langgraph.graph import END, StateGraph

from app.agent.nodes import (
    build_explanation_node,
    evaluate_step_node,
    execute_step_node,
    generate_charts_node,
    interpret_question_node,
    plan_analysis_node,
    profile_dataset_node,
    replan_analysis_node,
    route_after_evaluate,
    route_after_interpret,
    route_after_replan,
)
from app.agent.state import AgentState


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("profile_dataset", profile_dataset_node)
    graph.add_node("interpret_question", interpret_question_node)
    graph.add_node("plan_analysis", plan_analysis_node)
    graph.add_node("replan_analysis", replan_analysis_node)
    graph.add_node("execute_step", execute_step_node)
    graph.add_node("evaluate_step", evaluate_step_node)
    graph.add_node("generate_charts", generate_charts_node)
    graph.add_node("build_explanation", build_explanation_node)

    graph.set_entry_point("profile_dataset")
    graph.add_edge("profile_dataset", "interpret_question")

    # An unanswerable question skips straight to a clarification.
    graph.add_conditional_edges(
        "interpret_question",
        route_after_interpret,
        {"plan_analysis": "plan_analysis", "build_explanation": "build_explanation"},
    )

    graph.add_edge("plan_analysis", "execute_step")
    graph.add_edge("execute_step", "evaluate_step")

    # The evaluation is actually honoured: insufficient evidence loops back
    # through replanning, bounded by the step and replan budgets in `nodes`.
    graph.add_conditional_edges(
        "evaluate_step",
        route_after_evaluate,
        {
            "execute_step": "execute_step",
            "replan_analysis": "replan_analysis",
            "generate_charts": "generate_charts",
        },
    )
    graph.add_conditional_edges(
        "replan_analysis",
        route_after_replan,
        {"execute_step": "execute_step", "generate_charts": "generate_charts"},
    )

    graph.add_edge("generate_charts", "build_explanation")
    graph.add_edge("build_explanation", END)

    return graph.compile()


agent_graph = build_graph()
