from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
from state import TravelState
load_dotenv()
llm = ChatOpenAI(model="gpt-4o-mini")
def planner(state: TravelState):
    print("Planner Node Executed")

    prompt = f"""
    You are a travel planner.

    User Query:
    {state["user_query"]}

    Current information:
    Source: {state["source"]}
    Destination: {state["destination"]}
    Days: {state["days"]}
    Budget: {state["budget"]}
    Likes: {state["likes"]}

    Decide what should happen next.

    If required information is missing, return:
    ask_user

    Otherwise choose exactly one:
    flight
    hotel
    itinerary
    end

    Return ONLY one of these words.
    """

    response = llm.invoke(prompt)

    decision = response.content.strip().lower()

    print("LLM Decision:", decision)

    return {
        "next_node": decision
    }
def flight(state:TravelState):
    print("Flight Node Executed")

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
    print(state)
    return {
        "itinerary": itinerary_data
    }



def ask_user(state: TravelState):
    print("\n========== Ask User Node ==========")

    missing_fields = state["missing_fields"]

    print(f"I need the following information: {missing_fields}")

    user_input = input(f"Please provide {missing_fields[0]}: ")

    return {
        missing_fields[0]: user_input
    }