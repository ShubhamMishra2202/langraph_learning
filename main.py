from graph import graph
initial_state = {
    "source":"Ahmedabad",
    "destination": "Japan",
    "days": 5,
    "budget": 150000,
    "likes":["anime","food"],
    "flight": "",
    "hotel": "",
    "itinerary": "",
    "next_node":"flight"
}
# result = graph.invoke(initial_state)
graph.invoke(initial_state)