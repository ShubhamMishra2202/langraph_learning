from langchain_core.tools import tool


@tool
def search_flights(
    source: str,
    destination: str,
    budget: int,
    days: int
) -> str:
    """Search available flights between two locations within a budget."""

    return f"""
    Flight search results:
    - Ahmedabad → Tokyo
      Airline: Qatar Airways
      Price: ₹85,000
      Duration: 17 hours

    - Ahmedabad → Osaka
      Airline: Emirates
      Price: ₹90,000
      Duration: 18 hours
    """
