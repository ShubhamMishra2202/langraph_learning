import logging
import os
import re
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


GEOCODING_API_URL = "https://geocoding-api.open-meteo.com/v1/search"
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
WIKIVOYAGE_API_URL = "https://en.wikivoyage.org/w/api.php"
# Public Overpass servers are often overloaded (502/504/timeouts), so try each with a short timeout
OVERPASS_API_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
OVERPASS_TIMEOUT_SECONDS = 25
OSM_HEADERS = {"User-Agent": "langgraph-travel-planner/0.1"}
FORECAST_HORIZON_DAYS = 15


def _geocode(city: str) -> Optional[dict]:
    """Resolve a city name to {name, country, latitude, longitude} with Open-Meteo geocoding."""
    response = requests.get(GEOCODING_API_URL, params={"name": city, "count": 1}, timeout=20)
    response.raise_for_status()
    results = response.json().get("results")
    return results[0] if results else None


def _overpass(query: str) -> list[dict]:
    last_error = None
    for url in OVERPASS_API_URLS:
        try:
            response = requests.post(url, data={"data": query}, headers=OSM_HEADERS, timeout=OVERPASS_TIMEOUT_SECONDS)
            response.raise_for_status()
            return response.json()["elements"]
        except requests.RequestException as error:
            logger.warning("Overpass %s failed: %s; trying next mirror", url, error)
            last_error = error
    raise last_error


def _osm_places(city: str, tag_filters: list[str], radius_km: int) -> list[dict]:
    """Named OpenStreetMap places matching any of the Overpass tag filters around a city."""
    place = _geocode(city)
    if not place:
        return []
    around = f"(around:{radius_km * 1000},{place['latitude']},{place['longitude']})"
    filters = "\n".join(f'  nwr{tag_filter}["name"]{around};' for tag_filter in tag_filters)
    elements = _overpass(f"[out:json][timeout:{OVERPASS_TIMEOUT_SECONDS}];\n(\n{filters}\n);\nout center tags;")
    # Same place is often mapped twice (node + building); keep one per name
    return list({el["tags"]["name"].lower(): el for el in elements}.values())


def _clean_wikitext(text: str) -> str:
    text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", text)  # [[link|label]] -> label
    text = re.sub(r"\[https?://\S+ ([^\]]*)\]", r"\1", text)        # [url label] -> label
    text = re.sub(r"'{2,}", "", text)                                # bold / italics
    return " ".join(text.split())


def _wikivoyage_listings(city: str, kinds: set[str]) -> list[dict]:
    """Structured {{see|...}}, {{sleep|...}} etc. listings from a city's English Wikivoyage page."""
    response = requests.get(
        WIKIVOYAGE_API_URL,
        params={"action": "parse", "page": city, "prop": "wikitext", "format": "json", "formatversion": 2, "redirects": 1},
        headers=OSM_HEADERS,
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()
    if "error" in data:  # no Wikivoyage page for this city
        return []

    listings = []
    for kind, body in re.findall(r"\{\{\s*(see|do|eat|drink|buy|sleep)\s*\|(.*?)\n?\}\}", data["parse"]["wikitext"], re.I | re.S):
        if kind.lower() not in kinds:
            continue
        fields = {}
        for part in re.split(r"\n?\s*\|\s*", body):
            key, _, value = part.partition("=")
            fields[key.strip().lower()] = _clean_wikitext(value)
        if fields.get("name"):
            listings.append({"kind": kind.lower(), **fields})
    return listings


def _format_listing(listing: dict) -> str:
    line = f"  - {listing['name']}"
    for field in ("price", "hours"):
        if listing.get(field):
            line += f" | {field}: {listing[field]}"
    if listing.get("address") or listing.get("directions"):
        line += f" | {listing.get('address') or listing.get('directions')}"
    if listing.get("content"):
        line += f" | {listing['content'][:200]}"
    return line


@tool
def search_hotels(city: str, radius_km: int = 8, max_results: int = 10) -> str:
    """Find real hotels in a city from Wikivoyage (with price ranges) and OpenStreetMap (names only).

    Wikivoyage listings include price ranges and descriptions but cover fewer hotels.
    OpenStreetMap covers more hotels but has no prices; for those, estimate a nightly range
    yourself and say it is an estimate.

    Args:
        city: City to search in, e.g. "Raipur".
        radius_km: OpenStreetMap search radius around the city centre in kilometres.
        max_results: How many OpenStreetMap hotels to return.
    """

    log_block(logger, "TOOL CALL", f"search_hotels → Wikivoyage + OpenStreetMap hotels in {city}")
    sections, errors = [], []

    try:
        listings = _wikivoyage_listings(city, {"sleep"})
        sections.append(
            "Wikivoyage hotel listings (with prices):\n"
            + ("\n".join(_format_listing(listing) for listing in listings) or "  - none listed")
        )
    except requests.RequestException as error:
        errors.append(f"Wikivoyage failed: {error}")

    try:
        hotels = _osm_places(city, ['["tourism"~"^(hotel|guest_house|motel)$"]'], radius_km)
        # Places with stars or a website tend to be the better-documented, established hotels
        hotels.sort(key=lambda el: (bool(el["tags"].get("stars")), bool(el["tags"].get("website"))), reverse=True)
        lines = []
        for hotel in hotels[:max_results]:
            tags = hotel["tags"]
            line = f"  - {tags['name']} ({tags['tourism'].replace('_', ' ')})"
            if tags.get("stars"):
                line += f" | {tags['stars']} stars"
            if tags.get("website"):
                line += f" | {tags['website']}"
            lines.append(line)
        sections.append("OpenStreetMap hotels (no prices):\n" + ("\n".join(lines) or "  - none found"))
    except requests.RequestException as error:
        errors.append(f"OpenStreetMap failed: {error}")

    log_block(logger, "TOOL RESULT", f"search_hotels → {len(sections)} source(s) answered", *(f"   {e}" for e in errors))

    if not sections:
        return "Hotel search failed on every source: " + "; ".join(errors)
    return f"Hotels in {city}:\n" + "\n".join(sections) + ("\nNote: " + "; ".join(errors) if errors else "")


# Each category maps to Wikivoyage listing kinds and an OpenStreetMap filter (plus a check to tell results apart)
ATTRACTION_CATEGORIES = {
    "museum": ('["tourism"="museum"]', lambda t: t.get("tourism") == "museum"),
    "religious": ('["amenity"="place_of_worship"]', lambda t: t.get("amenity") == "place_of_worship"),
    "historic": ('["historic"~"^(monument|memorial|fort|castle|ruins|archaeological_site|palace)$"]', lambda t: "historic" in t),
    "park": ('["leisure"~"^(park|garden|nature_reserve)$"]', lambda t: t.get("leisure") in ("park", "garden", "nature_reserve")),
    "lake": ('["natural"="water"]["water"~"^(lake|reservoir)$"]', lambda t: t.get("natural") == "water"),
    "viewpoint": ('["tourism"="viewpoint"]', lambda t: t.get("tourism") == "viewpoint"),
    "zoo_or_theme_park": ('["tourism"~"^(zoo|theme_park|aquarium)$"]', lambda t: t.get("tourism") in ("zoo", "theme_park", "aquarium")),
    "attraction": ('["tourism"="attraction"]', lambda t: t.get("tourism") == "attraction"),
    "market": ('["amenity"="marketplace"]', lambda t: t.get("amenity") == "marketplace"),
    "restaurant": ('["amenity"="restaurant"]', lambda t: t.get("amenity") == "restaurant"),
}


@tool
def search_attractions(city: str, categories: list[str], radius_km: int = 10, per_category: int = 6) -> str:
    """Find real places to visit in a city from Wikivoyage and OpenStreetMap.

    Wikivoyage gives the city's curated See / Do / Eat / Buy highlights with descriptions.
    OpenStreetMap adds more places in the categories you pick; ones with a Wikipedia entry
    are listed first and marked [notable]. Pick categories that match the traveller's interests.

    Args:
        city: City to search in, e.g. "Raipur".
        categories: Any of: museum, religious, historic, park, lake, viewpoint,
            zoo_or_theme_park, attraction, market, restaurant.
        radius_km: OpenStreetMap search radius around the city centre in kilometres.
        per_category: Maximum OpenStreetMap places to return per category.
    """

    unknown = [c for c in categories if c not in ATTRACTION_CATEGORIES]
    categories = [c for c in categories if c in ATTRACTION_CATEGORIES]
    if not categories:
        return f"No valid categories. Choose from: {', '.join(ATTRACTION_CATEGORIES)}."

    log_block(logger, "TOOL CALL", f"search_attractions → Wikivoyage + OpenStreetMap {categories} in {city}")
    sections, errors = [], []

    try:
        listings = _wikivoyage_listings(city, {"see", "do", "eat", "buy"})
        lines = [f"{_format_listing(listing)} [{listing['kind']}]" for listing in listings]
        sections.append("Wikivoyage highlights:\n" + ("\n".join(lines) or "  - none listed"))
    except requests.RequestException as error:
        errors.append(f"Wikivoyage failed: {error}")

    try:
        elements = _osm_places(city, [ATTRACTION_CATEGORIES[c][0] for c in categories], radius_km)
        for category in categories:
            found = [el for el in elements if ATTRACTION_CATEGORIES[category][1](el["tags"])]
            found.sort(key=lambda el: "wikidata" in el["tags"] or "wikipedia" in el["tags"], reverse=True)
            lines = []
            for el in found[:per_category]:
                tags = el["tags"]
                notable = " [notable]" if "wikidata" in tags or "wikipedia" in tags else ""
                detail = tags.get("religion") or tags.get("historic") or ""
                lines.append(f"  - {tags['name']}{notable}" + (f" ({detail})" if detail else ""))
            sections.append(f"OpenStreetMap {category} ({len(found)} found):\n" + ("\n".join(lines) or "  - none found"))
    except requests.RequestException as error:
        errors.append(f"OpenStreetMap failed: {error}")

    log_block(logger, "TOOL RESULT", f"search_attractions → {len(sections)} section(s)", *(f"   {e}" for e in errors))

    if not sections:
        return "Attraction search failed on every source: " + "; ".join(errors)
    notes = errors + ([f"Ignored unknown categories: {', '.join(unknown)}"] if unknown else [])
    return f"Places in {city}:\n" + "\n".join(sections) + ("\nNote: " + "; ".join(notes) if notes else "")


WEATHER_CODES = {
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 80: "rain showers", 81: "rain showers",
    82: "violent rain showers", 95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with hail",
}


@tool
def get_weather_forecast(city: str, start_date: str, days: int) -> str:
    """Get the daily weather for a city over the trip dates (Open-Meteo).

    Dates within the next 15 days get a real forecast. Dates further out get the actual
    weather on the same dates last year, as a guide to what is typical.

    Args:
        city: City name, e.g. "Raipur".
        start_date: First day of the trip as YYYY-MM-DD.
        days: Number of days to cover.
    """

    start = date.fromisoformat(start_date)
    is_forecast = start <= date.today() + timedelta(days=FORECAST_HORIZON_DAYS)
    if not is_forecast:
        start = start - timedelta(days=365)
    end = start + timedelta(days=max(days, 1) - 1)

    source = "forecast" if is_forecast else "same dates last year"
    log_block(logger, "TOOL CALL", f"get_weather_forecast → Open-Meteo {source} for {city} {start} → {end}")

    try:
        place = _geocode(city)
        if not place:
            return f"Could not find a city called '{city}'. Try a different spelling."

        response = requests.get(
            OPEN_METEO_FORECAST_URL if is_forecast else OPEN_METEO_ARCHIVE_URL,
            params={
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum",
                "timezone": "auto",
            },
            timeout=20,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        log_block(logger, "TOOL RESULT", f"get_weather_forecast → failed: {error}")
        return f"Weather lookup failed: {error}"

    daily = response.json()["daily"]
    lines = [
        f"- {day}: {WEATHER_CODES.get(code, f'code {code}')}, {low}–{high} °C, rain {rain} mm"
        for day, code, high, low, rain in zip(
            daily["time"], daily["weather_code"], daily["temperature_2m_max"],
            daily["temperature_2m_min"], daily["precipitation_sum"],
        )
    ]
    log_block(logger, "TOOL RESULT", f"get_weather_forecast → {len(lines)} days ({source})")

    heading = "Forecast" if is_forecast else f"Trip is beyond the {FORECAST_HORIZON_DAYS}-day forecast; actual weather on the same dates last year"
    return f"{heading} for {place['name']}:\n" + "\n".join(lines)


FLIGHT_TOOLS = [lookup_airport_code, search_flights, convert_currency]
HOTEL_TOOLS = [search_hotels, convert_currency]
ITINERARY_TOOLS = [search_attractions, get_weather_forecast]
