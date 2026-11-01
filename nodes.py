import logging
from datetime import date

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from dotenv import load_dotenv
from state import TravelState
from model import PlannerDecision
from tools import FLIGHT_TOOLS
from tracing import setup_logging, log_block, log_llm_response

load_dotenv()
llm = ChatOpenAI(model="gpt-4o-mini")

setup_logging()
logger = logging.getLogger(__name__)

def planner(state: TravelState):
    log_block(
        logger, "NODE",
        "Node: planner",
        f"Done: flight={bool(state.get('flight'))} hotel={bool(state.get('hotel'))} itinerary={bool(state.get('itinerary'))}",
    )

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
        log_block(logger, "DECISION", f"Missing fields: {missing_fields}", "→ NEXT: ask_user")

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
    llm_choice = next_node

    log_block(logger, "LLM", f"→ PLANNER CHOICE: {llm_choice}")

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

    overridden = f" (guardrail overrode LLM choice '{llm_choice}')" if next_node != llm_choice else ""
    log_block(logger, "DECISION", f"→ NEXT: {next_node}{overridden}")

    return {
        "next_node": next_node,
        "missing_fields": []
    }
def flight(state: TravelState):
    log_block(
        logger, "NODE",
        "Node: flight",
        f"Trip: {state['source']} → {state['destination']}, {state['days']} days, budget {state['budget']}",
        f"Messages so far: {len(state['messages'])}",
    )
    flight_llm = llm.bind_tools(FLIGHT_TOOLS)

    # First pass seeds the conversation; later passes continue it with the ToolMessages from flight_tools
    new_messages = []
    if not state["messages"]:
        prompt = f"""
    You are a flight recommendation assistant with these tools:
    - lookup_airport_code: find IATA codes for a city name
    - search_flights: search real flight offers (needs IATA codes)
    - convert_currency: convert prices into another currency

    Find real flight offers for this trip:

    Source: {state["source"]}
    Destination: {state["destination"]}
    Days: {state["days"]}
    Budget: {state["budget"]} INR
    Today's date: {date.today().isoformat()}

    Decide for yourself which tools you need and in what order.
    search_flights needs IATA codes; look them up if you are not sure of them.
    The user has not chosen travel dates, so do not pass departure_date; the tool picks a default.
    If a tool fails, fix the arguments and try again.

    Before recommending, make sure prices are compared against the budget in the same currency.
    Recommend the 2 best options for the budget.
    Include airline, route, dates and price in both the offer currency and INR.
    """
        new_messages.append(HumanMessage(content=prompt))

    response = flight_llm.invoke(state["messages"] + new_messages)
    new_messages.append(response)

    log_llm_response(logger, response)

    update = {"messages": new_messages}

    # No tool calls means the LLM has its final answer; tools_condition routes back to planner
    if not response.tool_calls:
        update["flight"] = response.content

    return update

def hotel(state: TravelState):
    log_block(
        logger, "NODE",
        "Node: hotel",
        f"Trip: {state['destination']}, {state['days']} days, budget {state['budget']}, likes {state['likes']}",
    )

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
    log_llm_response(logger, response)

    return {
        "hotel": response.content
    }
def itinerary(state: TravelState):
    log_block(
        logger, "NODE",
        "Node: itinerary",
        f"Trip: {state['days']} days in {state['destination']}, interests {state['likes']}",
    )

    prompt = f"""
    You are a travel itinerary assistant.

    Create a {state["days"]}-day itinerary.

    Destination: {state["destination"]}
    Interests: {state["likes"]}

    Create a simple day-by-day itinerary.
    """

    response = llm.invoke(prompt)
    log_llm_response(logger, response)

    return {
        "itinerary": response.content
    }


def ask_user(state: TravelState):
    missing_fields = state["missing_fields"]
    field = missing_fields[0]

    log_block(
        logger, "NODE",
        "Node: ask_user",
        f"Asking for: {field}",
        f"Still missing after this: {missing_fields[1:]}",
    )

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