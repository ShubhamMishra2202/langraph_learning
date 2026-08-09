from graph import graph
initial_state = {
    "user_query":"I want to visit japan",
    "source":None,
    "destination": None,
    "days": None,
    "budget": None,
    "likes":[],
    "flight": "",
    "hotel": "",
    "itinerary": "",
    "next_node":None
}
# result = graph.invoke(initial_state)
graph.invoke(initial_state)