import logging

from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
from state import TravelState
from model import PlannerDecision

load_dotenv()
llm = ChatOpenAI(model="gpt-4o-mini")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

def planner(state: TravelState):
    logger.info("Planner Node Executed")
    logger.info("State: %s", state)

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
def flight(state: TravelState):
    logger.info("Flight Node Executed")
    logger.info("State: %s", state)

    prompt = f"""
    You are a flight recommendation assistant.

    Find suitable flight options based on:

    Source: {state["source"]}
    Destination: {state["destination"]}
    Budget: {state["budget"]}

    Provide 2 realistic-looking flight options.
    Include airline, route and approximate price.
    """

    response = llm.invoke(prompt)

    return {
        "flight": response.content
    }

def hotel(state: TravelState):
    logger.info("Hotel Node Executed")
    logger.info("State: %s", state)

    prompt = f"""
    You are a hotel recommendation assistant.

    Recommend suitable hotels based on:

    Destination: {state["destination"]}
    Days: {state["days"]}
    Budget: {state["budget"]}
    Likes: {state["likes"]}

    Provide 2 suitable hotel options.
    Include hotel name, approximate price and a short description.
    """

    response = llm.invoke(prompt)

    return {
        "hotel": response.content
    }
def itinerary(state: TravelState):
    logger.info("Itinerary Node Executed")
    logger.info("State: %s", state)

    prompt = f"""
    You are a travel itinerary assistant.

    Create a {state["days"]}-day itinerary.

    Destination: {state["destination"]}
    Interests: {state["likes"]}

    Create a simple day-by-day itinerary.
    """

    response = llm.invoke(prompt)

    return {
        "itinerary": response.content
    }


def ask_user(state: TravelState):
    logger.info("========== Ask User Node ==========")
    logger.info("State: %s", state)

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