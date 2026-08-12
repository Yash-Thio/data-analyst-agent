from langgraph.graph import END, StateGraph

from app.agent.nodes import (
    build_explanation_node,
    evaluate_step_node,
    execute_step_node,
    generate_charts_node,
    interpret_question_node,
    plan_analysis_node,
    profile_dataset_node,
    route_after_evaluate,
)
from app.agent.state import AgentState


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("profile_dataset", profile_dataset_node)
    graph.add_node("interpret_question", interpret_question_node)
    graph.add_node("plan_analysis", plan_analysis_node)
    graph.add_node("execute_step", execute_step_node)
    graph.add_node("evaluate_step", evaluate_step_node)
    graph.add_node("generate_charts", generate_charts_node)
    graph.add_node("build_explanation", build_explanation_node)

    graph.set_entry_point("profile_dataset")
    graph.add_edge("profile_dataset", "interpret_question")
    graph.add_edge("interpret_question", "plan_analysis")
    graph.add_edge("plan_analysis", "execute_step")
    graph.add_edge("execute_step", "evaluate_step")
    graph.add_conditional_edges("evaluate_step", route_after_evaluate)
    graph.add_edge("generate_charts", "build_explanation")
    graph.add_edge("build_explanation", END)

    return graph.compile()


agent_graph = build_graph()
