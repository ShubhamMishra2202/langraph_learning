import logging
from langgraph.types import interrupt
from datetime import date

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from dotenv import load_dotenv
from state import TravelState
from model import PlannerDecision
from tools import FLIGHT_TOOLS, HOTEL_TOOLS, ITINERARY_TOOLS
from tracing import setup_logging, log_block, log_llm_response

load_dotenv()
llm = ChatOpenAI(model="gpt-4o-mini")

setup_logging()
logger = logging.getLogger(__name__)


def _react_step(state: TravelState, messages_key: str, tools: list, prompt: str, result_key: str) -> dict:
    """One Reason step of a worker's ReAct loop (worker -> worker_tools -> worker).

    Each worker keeps its own conversation in state[messages_key], so it never sees another
    worker's tool calls and tools_condition(messages_key=...) reads the right last message.
    """
    # First pass seeds the conversation; later passes continue it with the ToolMessages from the ToolNode.
    # A channel nothing has written to yet is absent from state (e.g. a run started from Studio), hence .get().
    history = state.get(messages_key) or []
    new_messages = [] if history else [HumanMessage(content=prompt)]

    response = llm.bind_tools(tools).invoke(history + new_messages)
    new_messages.append(response)
    log_llm_response(logger, response)

    update = {messages_key: new_messages}

    # No tool calls means the LLM has its final answer; tools_condition routes back to planner
    if not response.tool_calls:
        update[result_key] = response.content

    return update

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

    # .get(): the graph's input is only user_query, so these keys don't exist until ask_user fills them
    missing_fields = [
        field for field in required_fields
        if not state.get(field)
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
        f"Messages so far: {len(state.get('messages') or [])}",
    )
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
    return _react_step(state, "messages", FLIGHT_TOOLS, prompt, "flight")

def hotel(state: TravelState):
    log_block(
        logger, "NODE",
        "Node: hotel",
        f"Trip: {state['destination']}, {state['days']} days, budget {state['budget']}, likes {state['likes']}",
    )

    prompt = f"""
    You are a hotel recommendation assistant with these tools:
    - search_hotels: real hotels and guest houses in a city from OpenStreetMap (no prices)
    - convert_currency: convert prices into another currency

    Recommend hotels for this trip:

    Destination: {state["destination"]}
    Nights: {state["days"]}
    Total trip budget: {state["budget"]} INR
    Likes: {state["likes"]}

    Flight plan already chosen (its cost comes out of the same budget):
    {state.get("flight") or "not available"}

    Decide for yourself which tools you need.
    Only recommend hotels that search_hotels actually returned; never invent hotel names.
    The tool has no prices, so give an estimated nightly range in INR and label it as an estimate.
    The budget and Indian hotel prices are already in INR; only call convert_currency for prices
    in another currency, rather than guessing the rate.
    If a tool fails, fix the arguments and try again.

    Recommend 2 hotels that fit what is left of the budget after the flight.
    Include name, type, star rating if known, estimated price per night and total, and why it suits the traveller.
    """
    return _react_step(state, "hotel_messages", HOTEL_TOOLS, prompt, "hotel")
def itinerary(state: TravelState):
    log_block(
        logger, "NODE",
        "Node: itinerary",
        f"Trip: {state['days']} days in {state['destination']}, interests {state['likes']}",
    )

    prompt = f"""
    You are a travel itinerary assistant with these tools:
    - search_attractions: real places in a city from OpenStreetMap, by category
      (museum, religious, historic, park, lake, viewpoint, zoo_or_theme_park, attraction, market, restaurant)
    - get_weather_forecast: daily weather for the trip dates

    Create a {state["days"]}-day itinerary.

    Destination: {state["destination"]}
    Interests: {state["likes"]}
    Today's date: {date.today().isoformat()}

    Flight plan (use its dates for the trip; if it has none, assume the trip starts 30 days from today):
    {state.get("flight") or "not available"}

    Hotel plan:
    {state.get("hotel") or "not available"}

    Decide for yourself which tools you need.
    Pick attraction categories that match the traveller's interests.
    Only include places that search_attractions actually returned; never invent place names.
    Use the weather to plan: indoor places on rainy or very hot days, outdoor ones on good days.
    If a tool fails, fix the arguments and try again.

    Give a simple day-by-day plan with the date, the weather and morning / afternoon / evening activities.
    """
    return _react_step(state, "itinerary_messages", ITINERARY_TOOLS, prompt, "itinerary")


def ask_user(state: TravelState):
    missing_fields = state["missing_fields"]
    field = missing_fields[0]

    log_block(
        logger, "NODE",
        "Node: ask_user",
        f"Asking for: {field}",
        f"Still missing after this: {missing_fields[1:]}",
    )

    user_input = interrupt({"ask": field})

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