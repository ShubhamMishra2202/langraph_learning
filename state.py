from typing import TypedDict

class TravelState(TypedDict):
    source : str
    destination: str
    days: int
    budget: int
    likes : list[str]
    flight: str
    hotel: str
    itinerary: str