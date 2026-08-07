from langgraph.graph import StateGraph, START, END

from state import TravelState
from nodes import planner,flight,hotel,itinerary

graph_builder = StateGraph(TravelState)

graph_builder.add_node("planner", planner)
graph_builder.add_node("flight", flight)
graph_builder.add_node("hotel", hotel)
graph_builder.add_node("itinerary", itinerary)
graph_builder.add_edge(START, "planner")
graph_builder.add_edge("planner","flight")
graph_builder.add_edge("flight","hotel")
graph_builder.add_edge("hotel", "itinerary")
graph_builder.add_edge("itinerary",END)

graph = graph_builder.compile()