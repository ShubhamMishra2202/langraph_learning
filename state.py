from typing import Annotated

# typing_extensions, not typing: on Python < 3.12 pydantic can't build a JSON schema from typing.TypedDict,
# and Studio needs that schema to draw the input/state forms
from typing_extensions import TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

class TravelInput(TypedDict):
    """What a caller passes in (and the only field Studio's input form shows). The planner asks for the rest."""
    user_query: str


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
    # One conversation per ReAct worker, so each tool loop only sees its own messages
    # and tools_condition reads the right last message
    messages: Annotated[list[AnyMessage], add_messages]            # flight <-> flight_tools
    hotel_messages: Annotated[list[AnyMessage], add_messages]      # hotel <-> hotel_tools
    itinerary_messages: Annotated[list[AnyMessage], add_messages]  # itinerary <-> itinerary_tools
