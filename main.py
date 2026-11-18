import uuid
from langgraph.types import Command
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
# Same id in app.log and as the LangSmith run id, so the two can be matched up
trace_id = uuid.uuid4()
trace_id_var.set(str(trace_id))

# thread_id is the checkpointer key: every invoke with it continues the same saved state
config = {
    "run_name": "travel_planner",
    "tags": ["travel-planner"],
    "configurable": {"thread_id": str(trace_id)},
}

# run_id must be unique per LangSmith run, so only the first invoke gets it
result = graph.invoke(initial_state, config={**config, "run_id": trace_id})

# ask_user calls interrupt(): the graph pauses, saves a checkpoint and returns __interrupt__
while "__interrupt__" in result:
    question = result["__interrupt__"][0].value
    answer = input(f"Please provide {question['ask']}: ")
    result = graph.invoke(Command(resume=answer), config=config)