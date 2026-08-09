from typing import TypedDict

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