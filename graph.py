from functools import partial

from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import InMemorySaver
from state import TravelState
from nodes import planner, flight, hotel, itinerary,ask_user
from tools import FLIGHT_TOOLS, HOTEL_TOOLS, ITINERARY_TOOLS


graph_builder = StateGraph(TravelState)


graph_builder.add_node("planner", planner)
graph_builder.add_node("ask_user", ask_user)


# Each worker is a ReAct loop: worker -> worker_tools -> worker until the LLM stops requesting tools,
# then back to the planner. Each loop has its own messages channel so the loops never mix.
def add_react_worker(name, node, tools, messages_key):
    graph_builder.add_node(name, node)
    graph_builder.add_node(f"{name}_tools", ToolNode(tools, messages_key=messages_key))
    graph_builder.add_conditional_edges(
        name,
        partial(tools_condition, messages_key=messages_key),
        {"tools": f"{name}_tools", END: "planner"},
    )
    graph_builder.add_edge(f"{name}_tools", name)


add_react_worker("flight", flight, FLIGHT_TOOLS, "messages")
add_react_worker("hotel", hotel, HOTEL_TOOLS, "hotel_messages")
add_react_worker("itinerary", itinerary, ITINERARY_TOOLS, "itinerary_messages")


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


# ask_user returns straight to the planner
graph_builder.add_edge("ask_user", "planner")


graph = graph_builder.compile(checkpointer=InMemorySaver())