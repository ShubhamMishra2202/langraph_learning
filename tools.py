import logging
import os
from datetime import date, timedelta
from typing import Optional

import requests
from dotenv import load_dotenv
from langchain_core.tools import tool

from tracing import log_block

load_dotenv()
logger = logging.getLogger(__name__)

DUFFEL_API_URL = "https://api.duffel.com"
DUFFEL_VERSION = "v2"
FRANKFURTER_API_URL = "https://api.frankfurter.dev/v1"


def _duffel_headers() -> dict:
    token = os.getenv("DUFFEL_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("DUFFEL_ACCESS_TOKEN is not set. Add it to your .env file.")

    return {
        "Authorization": f"Bearer {token}",
        "Duffel-Version": DUFFEL_VERSION,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _format_offer(offer: dict) -> str:
    lines = [f"- {offer['owner']['name']}: {offer['total_amount']} {offer['total_currency']}"]

    for flight_slice in offer["slices"]:
        stops = len(flight_slice["segments"]) - 1
        lines.append(
            f"    {flight_slice['origin']['iata_code']} → {flight_slice['destination']['iata_code']}"
            f" | duration {flight_slice.get('duration')} | stops {stops}"
        )
        for segment in flight_slice["segments"]:
            carrier = segment["marketing_carrier"]
            lines.append(
                f"      {carrier['iata_code']}{segment['marketing_carrier_flight_number']}"
                f" {segment['origin']['iata_code']} {segment['departing_at']}"
                f" → {segment['destination']['iata_code']} {segment['arriving_at']}"
            )

    return "\n".join(lines)


@tool
def search_flights(
    origin: str,
    destination: str,
    departure_date: Optional[str] = None,
    days: Optional[int] = None,
    adults: int = 1,
    cabin_class: str = "economy",
    max_results: int = 5,
) -> str:
    """Search real flight offers using the Duffel API.

    Args:
        origin: IATA airport or city code to fly from, e.g. "AMD" for Ahmedabad.
        destination: IATA airport or city code to fly to, e.g. "TYO" or "NRT" for Tokyo.
        departure_date: Outbound date as YYYY-MM-DD. Defaults to 30 days from today.
        days: Trip length in days. If given, a return flight is searched as well.
        adults: Number of adult passengers.
        cabin_class: One of "economy", "premium_economy", "business", "first".
        max_results: How many of the cheapest offers to return.
    """

    outbound = date.fromisoformat(departure_date) if departure_date else date.today() + timedelta(days=30)

    slices = [{"origin": origin, "destination": destination, "departure_date": outbound.isoformat()}]
    if days:
        inbound = outbound + timedelta(days=days)
        slices.append({"origin": destination, "destination": origin, "departure_date": inbound.isoformat()})

    payload = {
        "data": {
            "slices": slices,
            "passengers": [{"type": "adult"} for _ in range(adults)],
            "cabin_class": cabin_class,
        }
    }

    log_block(
        logger, "TOOL CALL",
        "search_flights → Duffel POST /air/offer_requests",
        *(f"   {leg['origin']} → {leg['destination']} on {leg['departure_date']}" for leg in slices),
    )

    response = requests.post(
        f"{DUFFEL_API_URL}/air/offer_requests",
        params={"return_offers": "true"},
        json=payload,
        headers=_duffel_headers(),
        timeout=60,
    )

    # Hand API errors back to the LLM as the tool result so it can retry with different args
    if not response.ok:
        errors = response.json().get("errors", [])
        messages = "; ".join(error.get("message", "") for error in errors) or response.text
        log_block(logger, "TOOL RESULT", f"search_flights → failed (HTTP {response.status_code})", f"   {messages}")
        return f"Flight search failed (HTTP {response.status_code}): {messages}"

    offers = response.json()["data"]["offers"]
    log_block(logger, "TOOL RESULT", f"search_flights → {len(offers)} offers (HTTP {response.status_code})")

    if not offers:
        return f"No flights found from {origin} to {destination} on {outbound.isoformat()}."

    cheapest = sorted(offers, key=lambda offer: float(offer["total_amount"]))[:max_results]

    return "Flight search results (cheapest first):\n" + "\n".join(
        _format_offer(offer) for offer in cheapest
    )


@tool
def lookup_airport_code(city: str, max_results: int = 5) -> str:
    """Find IATA airport and city codes for a place name using the Duffel API.

    Use this when the user gave a city or airport name rather than an IATA code,
    or when you are not sure which code is correct. Skip it if you already know the code.

    Args:
        city: City or airport name to look up, e.g. "Ahmedabad" or "Tokyo".
        max_results: How many matching places to return.
    """

    log_block(logger, "TOOL CALL", f"lookup_airport_code → Duffel GET /places/suggestions?query={city}")

    response = requests.get(
        f"{DUFFEL_API_URL}/places/suggestions",
        params={"query": city},
        headers=_duffel_headers(),
        timeout=30,
    )

    if not response.ok:
        log_block(logger, "TOOL RESULT", f"lookup_airport_code → failed (HTTP {response.status_code})")
        return f"Airport lookup failed (HTTP {response.status_code}): {response.text}"

    places = response.json()["data"][:max_results]
    log_block(logger, "TOOL RESULT", f"lookup_airport_code → {len(places)} places (HTTP {response.status_code})")

    if not places:
        return f"No airports found for '{city}'. Try a nearby larger city."

    lines = []
    for place in places:
        line = f"- {place['iata_code']} ({place['type']}): {place['name']}, {place['iata_country_code']}"
        # A city code covers several airports; list them so the LLM can pick one
        airports = [airport["iata_code"] for airport in place.get("airports") or []]
        if airports:
            line += f" | airports: {', '.join(airports)}"
        lines.append(line)

    return f"Places matching '{city}':\n" + "\n".join(lines)


@tool
def convert_currency(amount: float, from_currency: str, to_currency: str) -> str:
    """Convert an amount between currencies using the latest ECB exchange rates (Frankfurter API).

    Use this to compare prices in one currency against a budget in another,
    e.g. flight offers in USD against a budget in INR.

    Args:
        amount: The amount to convert.
        from_currency: ISO 4217 code of the amount's currency, e.g. "USD".
        to_currency: ISO 4217 code to convert into, e.g. "INR".
    """

    from_currency, to_currency = from_currency.upper(), to_currency.upper()
    if from_currency == to_currency:
        return f"{amount} {from_currency} = {amount} {to_currency}"

    log_block(logger, "TOOL CALL", f"convert_currency → Frankfurter {amount} {from_currency} → {to_currency}")

    response = requests.get(
        f"{FRANKFURTER_API_URL}/latest",
        params={"amount": amount, "from": from_currency, "to": to_currency},
        timeout=15,
    )

    if not response.ok:
        log_block(logger, "TOOL RESULT", f"convert_currency → failed (HTTP {response.status_code})")
        return f"Currency conversion failed (HTTP {response.status_code}): {response.text}"

    data = response.json()
    converted = data["rates"][to_currency]
    log_block(logger, "TOOL RESULT", f"convert_currency → {converted} {to_currency} (rate date {data['date']})")

    return f"{amount} {from_currency} = {converted} {to_currency} (rate date {data['date']})"


FLIGHT_TOOLS = [lookup_airport_code, search_flights, convert_currency]
