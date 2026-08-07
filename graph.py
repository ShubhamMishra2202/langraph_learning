from langgraph.graph import StateGraph, START, END

from state import TravelState
from nodes import planner,flight,hotel,iterinary

graph_builder = StateGraph(TravelState)

graph_builder.add_node("planner", planner)
graph_builder.add_node("flight", flight)
graph_builder.add_node("hotel", hotel)
graph_builder.add_node("iterinary", iterinary)
graph_builder.add_edge(START, "planner")
graph_builder.add_edge("planner","flight")
graph_builder.add_edge("flight", END)

graph = graph_builder.compile()