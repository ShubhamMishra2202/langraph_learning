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
| 9 | Multiple tools + tool selection | ✅ Done | 2026-11-01 | `77524b6` |
| 10 | Persistence / Checkpointing | ✅ Done | 2026-11-18 | `ea8c842` (+ next commit) |
| 11 | Human-in-the-loop | ✅ Done | 2026-11-18 | `ea8c842` (+ next commit) |
| 12 | Retry / Error recovery | 🔴 | | |
| 13 | Multi-agent / Supervisor | 🔴 | | |
| 14 | Planning agents | 🔴 | | |
| 15 | Reflection / Critic agents | 🔴 | | |
| 16 | Dynamic workflows | 🔴 | | |
| 17 | Evaluation + observability | 🟡 Observability done, evaluation to do | 2026-11-21 (partial) | `dcd0e63`, `d92c922` |
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

### 9. Multiple tools + tool selection
Added `lookup_airport_code` (Duffel place suggestions) and `convert_currency` (Frankfurter ECB rates) alongside `search_flights`, bundled as `FLIGHT_TOOLS` in [tools.py](tools.py). The `flight` node binds all three with `llm.bind_tools(FLIGHT_TOOLS)` and one `ToolNode(FLIGHT_TOOLS)` runs whichever tool the model requests. The prompt describes the tools and the goal but doesn't script the steps, so the LLM picks the order itself. In a real run it looked up both airport codes in parallel, searched flights, then converted prices to INR twice before answering.

**Extended (2026-11-18):** `hotel` and `itinerary` became ReAct workers too. `hotel` has `search_hotels` and `convert_currency`; `itinerary` has `search_attractions` and `get_weather_forecast`. Each worker has its own messages channel (`messages`, `hotel_messages`, `itinerary_messages`) through `ToolNode(messages_key=...)` and `tools_condition(messages_key=...)`, and all three are wired with one `add_react_worker` helper in [graph.py](graph.py). See learning_evolution #10.

### 10. Persistence / Checkpointing
[graph.py](graph.py) compiles with `checkpointer=InMemorySaver()`, so LangGraph saves a snapshot of the full state after every step. [main.py](main.py) passes `configurable.thread_id` (the trace id), which is the key every later invoke uses to continue the same saved state. `graph.get_state(config)` and `graph.get_state_history(config)` now show the current snapshot and every past step. `InMemorySaver` only lasts for the life of the process; `SqliteSaver` or `PostgresSaver` would make it survive restarts.

### 11. Human-in-the-loop
`ask_user` in [nodes.py](nodes.py) calls `interrupt({"ask": field})` instead of the blocking `input()`. The graph pauses, saves a checkpoint and returns `__interrupt__` to the caller. [main.py](main.py) loops: it reads the question from `result["__interrupt__"][0].value`, gets the answer from the user and resumes with `graph.invoke(Command(resume=answer), config)`. Because the pause/resume goes through the checkpointer, the same graph can now sit behind an API or UI rather than a terminal. When it resumes, the interrupted node runs again from its first line and `interrupt()` returns the answer this time, so `ask_user` logs twice per field. Anything before `interrupt()` in a node must be safe to run twice.

### 17. Evaluation + observability (in progress)
**Observability, done:**
- **LangSmith tracing** (`dcd0e63`): every run is a trace on smith.langchain.com, and the trace id in [app.log](app.log) is also the LangSmith run id.
- **LangGraph Studio** (2026-11-21): [langgraph.json](langgraph.json) points the local dev server at `studio_graph` in [graph.py](graph.py). Start it with [studio.sh](studio.sh), which opens Studio at `https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024`. Studio draws the graph, lights up each node as it runs, shows the state after every step, pauses at `ask_user`'s `interrupt()` so you can type the resume value in the UI, and can rewind to any checkpoint and fork from there.
  - The dev server brings its own persistence, so `studio_graph` is compiled without a checkpointer. `graph` keeps `InMemorySaver` for [main.py](main.py).
  - The graph's input schema is now `TravelInput` (just `user_query`) in [state.py](state.py), so Studio's input form is a single box and the planner asks for everything else.

**Evaluation, still to do:** LangSmith datasets and evaluators that score the planner's routing and the workers' answers.
