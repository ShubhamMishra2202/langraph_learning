from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

class TravelState(TypedDict):
    user_query:str
    source : str
    destination: str
    days: int
    budget: int
    likes : list[str]
    flight: str
    hotel: str
    itinerary: str
    next_node:str
    missing_fields:list[str]
    # Conversation used by the flight node's tool-calling loop (flight <-> flight_tools)
    messages: Annotated[list[AnyMessage], add_messages]
