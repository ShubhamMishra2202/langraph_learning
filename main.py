from graph import graph
initial_state = {
    "destination": "Japan",
    "days": 5,
    "budget": 150000,
    "flight": "",
    "hotel": "",
    "itinerary": ""
}
result = graph.invoke(initial_state)
graph.invoke(initial_state)