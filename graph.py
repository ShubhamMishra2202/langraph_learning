from langgraph.graph import StateGraph, START, END

from state import TravelState
from nodes import planner, flight, hotel, itinerary


graph_builder = StateGraph(TravelState)


graph_builder.add_node("planner", planner)
graph_builder.add_node("flight", flight)
graph_builder.add_node("hotel", hotel)
graph_builder.add_node("itinerary", itinerary)


# Start → Planner
graph_builder.add_edge(START, "planner")


# Planner decides where to go
def route(state: TravelState):
    return state["next_node"]


graph_builder.add_conditional_edges(
    "planner",
    route,
    {
        "flight": "flight",
        "hotel": "hotel",
        "itinerary": "itinerary",
        "end": END
    }
)


# After each worker, return to Planner
graph_builder.add_edge("flight", "planner")
graph_builder.add_edge("hotel", "planner")
graph_builder.add_edge("itinerary", "planner")


graph = graph_builder.compile()