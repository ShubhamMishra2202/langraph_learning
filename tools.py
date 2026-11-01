import logging
import os
from datetime import date, timedelta
from typing import Optional

import requests
from dotenv import load_dotenv
from langchain_core.tools import tool

load_dotenv()
logger = logging.getLogger(__name__)

DUFFEL_API_URL = "https://api.duffel.com"
DUFFEL_VERSION = "v2"


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

    logger.info("Duffel request: POST /air/offer_requests %s", payload)

    response = requests.post(
        f"{DUFFEL_API_URL}/air/offer_requests",
        params={"return_offers": "true"},
        json=payload,
        headers=_duffel_headers(),
        timeout=60,
    )

    logger.info("Duffel response: HTTP %s", response.status_code)

    # Hand API errors back to the LLM as the tool result so it can retry with different args
    if not response.ok:
        errors = response.json().get("errors", [])
        messages = "; ".join(error.get("message", "") for error in errors) or response.text
        return f"Flight search failed (HTTP {response.status_code}): {messages}"

    offers = response.json()["data"]["offers"]
    logger.info("Duffel returned %d offers", len(offers))

    if not offers:
        return f"No flights found from {origin} to {destination} on {outbound.isoformat()}."

    cheapest = sorted(offers, key=lambda offer: float(offer["total_amount"]))[:max_results]

    return "Flight search results (cheapest first):\n" + "\n".join(
        _format_offer(offer) for offer in cheapest
    )
