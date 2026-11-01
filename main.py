import uuid

from graph import graph
from tracing import trace_id_var

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
# Same id in app.log and as the LangSmith run id, so the two can be matched up
trace_id = uuid.uuid4()
trace_id_var.set(str(trace_id))

graph.invoke(
    initial_state,
    config={"run_id": trace_id, "run_name": "travel_planner", "tags": ["travel-planner"]},
)