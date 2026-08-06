from langgraph.graph import StateGraph, START, END

from state import TravelState
from nodes import planner

graph_builder = StateGraph(TravelState)

graph_builder.add_node("planner", planner)

graph_builder.add_edge(START, "planner")
graph_builder.add_edge("planner", END)

graph = graph_builder.compile()