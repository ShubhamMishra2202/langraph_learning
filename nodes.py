import logging

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, ToolMessage
from dotenv import load_dotenv
from state import TravelState
from model import PlannerDecision
from tools import search_flights

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

    # Python remains the source of truth for required user information
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

    # ---------------------------------------------------------
    # 1. Required information is missing → ask the user
    # ---------------------------------------------------------
    if missing_fields:
        logger.info("Missing fields: %s", missing_fields)

        return {
            "next_node": "ask_user",
            "missing_fields": missing_fields
        }

    # ---------------------------------------------------------
    # 2. All required information is available
    #    Let the LLM decide the next workflow step
    # ---------------------------------------------------------

    flight_done = bool(state.get("flight"))
    hotel_done = bool(state.get("hotel"))
    itinerary_done = bool(state.get("itinerary"))

    prompt = f"""
You are the routing agent for a travel-planning workflow.

Your job is to decide the SINGLE best NEXT NODE to execute.

Do NOT generate a travel plan.
Do NOT explain your decision.
Return only the selected node.

USER REQUEST:
{state["user_query"]}

TRAVEL INFORMATION:
- Source: {state["source"]}
- Destination: {state["destination"]}
- Days: {state["days"]}
- Budget: {state["budget"]}
- Likes: {state["likes"]}

CURRENT WORKFLOW STATUS:
- Flight completed: {flight_done}
- Hotel completed: {hotel_done}
- Itinerary completed: {itinerary_done}

AVAILABLE NODES:
- flight
- hotel
- itinerary
- end

WORKFLOW RULES:

1. Flight should normally be completed before hotel.
2. Hotel should normally be completed before itinerary.
3. Itinerary should normally be generated after flight and hotel.
4. Never select a node that has already completed successfully.
5. If flight is not completed, prefer "flight".
6. If flight is completed but hotel is not completed, prefer "hotel".
7. If flight and hotel are completed but itinerary is not completed, choose "itinerary".
8. If flight, hotel, and itinerary are all completed, choose "end".
9. Never choose "end" if any required workflow step is incomplete.
10. Never repeatedly select the same completed node.
11. You may only return one of:
    flight
    hotel
    itinerary
    end

CURRENT STATE:
- flight = {state.get("flight")}
- hotel = {state.get("hotel")}
- itinerary = {state.get("itinerary")}

Return ONLY the node name.
"""

    structured_llm = llm.with_structured_output(PlannerDecision)

    response = structured_llm.invoke(prompt)

    next_node = response.next_node

    logger.info("LLM selected next node: %s", next_node)

    # ---------------------------------------------------------
    # 3. Safety validation
    #    Prevent the LLM from breaking the workflow
    # ---------------------------------------------------------

    if next_node == "flight" and flight_done:
        logger.warning(
            "LLM selected completed flight node. Overriding decision."
        )

        if not hotel_done:
            next_node = "hotel"
        elif not itinerary_done:
            next_node = "itinerary"
        else:
            next_node = "end"

    elif next_node == "hotel" and hotel_done:
        logger.warning(
            "LLM selected completed hotel node. Overriding decision."
        )

        if not itinerary_done:
            next_node = "itinerary"
        else:
            next_node = "end"

    elif next_node == "itinerary" and itinerary_done:
        logger.warning(
            "LLM selected completed itinerary node. Overriding decision."
        )

        next_node = "end"

    # ---------------------------------------------------------
    # 4. Prevent skipping required workflow steps
    # ---------------------------------------------------------

    if not flight_done and next_node in ["hotel", "itinerary", "end"]:
        logger.warning(
            "LLM attempted to skip flight. Overriding to flight."
        )
        next_node = "flight"

    elif flight_done and not hotel_done and next_node in ["itinerary", "end"]:
        logger.warning(
            "LLM attempted to skip hotel. Overriding to hotel."
        )
        next_node = "hotel"

    elif (
        flight_done
        and hotel_done
        and not itinerary_done
        and next_node == "end"
    ):
        logger.warning(
            "LLM attempted to end before itinerary. Overriding to itinerary."
        )
        next_node = "itinerary"

    logger.info("Final planner decision: %s", next_node)

    return {
        "next_node": next_node,
        "missing_fields": []
    }
def flight(state: TravelState):
    logger.info("Flight Node Executed")
    logger.info("State: %s", state)
    flight_llm = llm.bind_tools([search_flights])
    prompt = f"""
    You are a flight recommendation assistant.

    Find suitable flight options based on:

    Source: {state["source"]}
    Destination: {state["destination"]}
    Budget: {state["budget"]}

    Provide 2 realistic-looking flight options.
    Include airline, route and approximate price.
    """

    messages = [HumanMessage(content=prompt)]
    response = flight_llm.invoke(messages)
    messages.append(response)

    # Performs every tool call the llm model requested
    
    for tool_call in response.tool_calls:
        tool_result = search_flights.invoke(tool_call["args"])
        messages.append(ToolMessage(content=tool_result, tool_call_id=tool_call["id"]))

    # Sends back the tools responses so that the LLM model can generate the final answer 
    if response.tool_calls:
        response = flight_llm.invoke(messages)

    logger.info(f"Flight Mode response  {response}")

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