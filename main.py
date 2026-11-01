from graph import graph
initial_state = {
    "user_query":"I want to visit Raipur.Currently I live in Ahmedabad. 3 days of stay and my budget is 30 thousand",
    "source":None,
    "destination": None,
    "days": None,
    "budget": None,
    "likes":[],
    "flight": "",
    "hotel": "",
    "itinerary": "",
    "next_node":None,
    "messages": []
}
# result = graph.invoke(initial_state)
graph.invoke(initial_state)