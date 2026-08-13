from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
from state import TravelState
from model import PlannerDecision

load_dotenv()
llm = ChatOpenAI(model="gpt-4o-mini")

def planner(state: TravelState):
    print("Planner Node Executed")
    print("State:", state)

    # Python is the source of truth for required fields
    required_fields = [
        "source",
        "destination",
        "days",
        "budget",
        "likes"
    ]

    missing_fields = [
        field for field in required_fields
        if not state[field]
    ]

    # If information is missing, don't ask the LLM
    if missing_fields:
        return {
            "next_node": "ask_user",
            "missing_fields": missing_fields
        }

    # Only use the LLM when we have all required information
    prompt = f"""
    You are a travel planner.

    User Query:
    {state["user_query"]}

    Available information:
    Source: {state["source"]}
    Destination: {state["destination"]}
    Days: {state["days"]}
    Budget: {state["budget"]}
    Likes: {state["likes"]}

    Decide what should happen next.

    Choose exactly one:
    - flight
    - hotel
    - itinerary
    - end

    Return the decision and nothing else.
    """

    structured_llm = llm.with_structured_output(PlannerDecision)
    response = structured_llm.invoke(prompt)

    return {
        "next_node": response.next_node,
        "missing_fields": []
    }
def flight(state:TravelState):
    print("Flight Node Executed")
    print("State:", state)

    source = state["source"]
    destination = state["destination"]
    budget = state["budget"]

    print(f"Source      : {source}")
    print(f"Destination : {destination}")
    print(f"Budget      : {budget}")

    flight_data = f"""
Option 1
---------
Air India
{source} → {destination}
₹48,000

Option 2
---------
ANA
{source} → {destination}
₹52,000
"""

    return {
        "flight": flight_data
    }

def hotel(state: TravelState):
    print("\n========== Hotel Node ==========")
    print("State:", state)

    destination = state["destination"]
    budget = state["budget"]
    days = state["days"]

    print(f"Destination : {destination}")
    print(f"Days        : {days}")
    print(f"Budget      : ₹{budget}")

    hotel_data = f"""
Option 1
---------
Tokyo Grand Hotel
5 Nights
₹35,000

Option 2
---------
Shinjuku Inn
5 Nights
₹28,000
"""

    return {
        "hotel": hotel_data
    }

def itinerary(state: TravelState):
    print("\n========== Itinerary Node ==========")
    print("State:", state)

    destination = state["destination"]
    days = state["days"]
    likes = state["likes"]

    print(f"Destination : {destination}")
    print(f"Days        : {days}")
    print(f"Interests   : {likes}")

    itinerary_data = f"""
Day 1 : Arrival in {destination}
Day 2 : City Tour
Day 3 : Local Food Exploration
Day 4 : Shopping & Cultural Visit
Day 5 : Return Journey
"""
    return {
        "itinerary": itinerary_data
    }


def ask_user(state: TravelState):
    print("\n========== Ask User Node ==========")
    print("State:", state)

    missing_fields = state["missing_fields"]
    field = missing_fields[0]

    user_input = input(f"Please provide {field}: ")

    if field == "days":
        user_input = int(user_input)

    elif field == "budget":
        user_input = int(user_input)

    elif field == "likes":
        user_input = [item.strip() for item in user_input.split(",")]

    return {
        field.lower(): user_input,
        "missing_fields": missing_fields[1:]
    }