from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode, tools_condition

from state import TravelState
from nodes import planner, flight, hotel, itinerary,ask_user
from tools import search_flights


graph_builder = StateGraph(TravelState)


graph_builder.add_node("planner", planner)
graph_builder.add_node("flight", flight)
graph_builder.add_node("flight_tools", ToolNode([search_flights]))
graph_builder.add_node("hotel", hotel)
graph_builder.add_node("itinerary", itinerary)
graph_builder.add_node("ask_user", ask_user)


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
        "ask_user":"ask_user",
        "end": END
    }
)


# Flight tool loop: flight -> flight_tools -> flight until the LLM stops requesting tools --> ReACT
graph_builder.add_conditional_edges(
    "flight",
    tools_condition,
    {
        "tools": "flight_tools",
        END: "planner"
    }
)
graph_builder.add_edge("flight_tools", "flight")


# After each worker, return to Planner
graph_builder.add_edge("hotel", "planner")
graph_builder.add_edge("itinerary", "planner")
graph_builder.add_edge("ask_user", "planner")


graph = graph_builder.compile()