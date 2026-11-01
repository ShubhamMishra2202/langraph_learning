# Milestones

The LangGraph concepts this travel-planner project is working through, in order. When a milestone is reached, its status flips to ✅ and a "How it was achieved" entry is added below. Detailed bug/fix history lives in [learning_evolution.MD](learning_evolution.MD).

| # | Concept | Status | Achieved | Commit |
|---|---|---|---|---|
| 1 | StateGraph | ✅ Done | 2026-08-07 | `d92e7cd` |
| 2 | Nodes | ✅ Done | 2026-08-07 | `d92e7cd` |
| 3 | Edges | ✅ Done | 2026-08-07 | `c5abacb` |
| 4 | Conditional routing | ✅ Done | 2026-08-08 | `75828d9` |
| 5 | LLM routing | ✅ Done | 2026-08-13 | `1f04610` |
| 6 | State-based guardrails | ✅ Done | 2026-08-17 | `1f04610`, `19654c2` |
| 7 | Tool calling | ✅ Done | 2026-08-21 | `eae6c43` |
| 8 | ReAct / Agent loop | ✅ Done | 2026-10-31 | `6cbcea2` |
| 9 | Multiple tools + tool selection | 🔴 | | |
| 10 | Persistence / Checkpointing | 🔴 | | |
| 11 | Human-in-the-loop | 🔴 | | |
| 12 | Retry / Error recovery | 🔴 | | |
| 13 | Multi-agent / Supervisor | 🔴 | | |
| 14 | Planning agents | 🔴 | | |
| 15 | Reflection / Critic agents | 🔴 | | |
| 16 | Dynamic workflows | 🔴 | | |
| 17 | Evaluation + observability | 🔴 | | |
| 18 | Production agent architecture | 🔴 | | |

## How each milestone was achieved

### 1. StateGraph
Defined the shared state as a `TypedDict` (`TravelState` in [state.py](state.py)): `user_query`, `source`, `destination`, `days`, `budget`, `likes`, `flight`, `hotel`, `itinerary`, plus control fields. Built the graph with `StateGraph(TravelState)` in [graph.py](graph.py) and compiled it with `graph_builder.compile()`. Every node reads this state and returns a partial dict that LangGraph merges back in.

### 2. Nodes
Wrote each step as a plain Python function `(state) -> dict` in [nodes.py](nodes.py): `planner`, `ask_user`, `flight`, `hotel`, `itinerary`. Each one was registered with `graph_builder.add_node(name, fn)`.

### 3. Edges
Connected the nodes with fixed `add_edge` calls: `START → planner` first, then a hard-coded sequence. Every worker (`flight`, `hotel`, `itinerary`, `ask_user`) still has a fixed edge back to `planner`, which makes the planner the hub.

### 4. Conditional routing
Replaced the static sequence with `add_conditional_edges("planner", route, {...})`. `route()` reads `state["next_node"]` and the mapping sends it to `flight`, `hotel`, `itinerary`, `ask_user` or `END`. The planner now chooses the path at runtime instead of the wiring fixing it.

### 5. LLM routing
Once every required field is filled in, `planner` asks the LLM which node to run next. It uses `llm.with_structured_output(PlannerDecision)` ([model.py](model.py)), so the answer is a typed `next_node` rather than free text. The prompt includes the trip details, which steps are already done, and the ordering rules.

### 6. State-based guardrails
Python stays in charge of the LLM's decisions (see learning_evolution #2, #4, #5):
- Missing-field detection is plain Python, not the LLM. If anything in `source/destination/days/budget/likes` is empty, the planner routes to `ask_user`. `ask_user` pops one field off `missing_fields` on each pass.
- `flight_done` / `hotel_done` / `itinerary_done` are worked out from the state. If the LLM picks a step that's already done, or tries to skip ahead (hotel before flight, end before itinerary), its choice is overridden. This fixed the infinite planner → itinerary cycling.

### 7. Tool calling
Wrote a `search_flights` tool with `@tool` in [tools.py](tools.py) and gave it to the LLM with `llm.bind_tools([search_flights])`. The key lesson was that a model bound to tools returns an empty `content` and puts the request in `tool_calls`. Nothing runs the tool automatically. The fix was to run each requested call, send the result back as a `ToolMessage` tagged with its `tool_call_id`, and call the LLM again (learning_evolution #6).

### 8. ReAct / Agent loop
Moved the tool loop out of the `flight` node and into the graph (learning_evolution #7):
- Added a `messages: Annotated[list[AnyMessage], add_messages]` channel to `TravelState`.
- Registered a prebuilt `ToolNode([search_flights])` as `flight_tools`.
- Routed with `tools_condition`: `flight → flight_tools → flight` for as long as the LLM asks for tools, then `flight → planner`.

That is Reason (`flight` calls the LLM) → Act (`flight_tools`) → Observe (the `ToolMessage` in `messages`) → repeat. It handles any number of tool rounds, every round is a visible graph step, and `recursion_limit` caps runaway loops. Tested with a stub LLM that made two tool rounds before answering.
