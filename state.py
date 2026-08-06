from typing import TypedDict

class TravelState(TypedDict):
    destination: str
    days: int
    budget: int
    flight: str
    hotel: str
    itinerary: str