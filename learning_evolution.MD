# Learning Evolution

A running log of issues hit while building this LangGraph travel-planner project, and how they were resolved. Concept milestones reached are tracked in [MILESTONES.md](MILESTONES.md).

## 2026-08-13

### 1. `ask_user` kept re-asking for the same field
**Issue:** `ask_user` read `missing_fields[0]`, collected input for it, but never removed it from the list before returning. On the next loop through the graph, the planner saw the same non-empty `missing_fields` and routed back to `ask_user`, which asked for the exact same field again (e.g. it got stuck re-asking for `source`).

**Fix:** `ask_user` now returns `"missing_fields": missing_fields[1:]` alongside the collected field, so the list shrinks by one each pass and the graph progresses to the next missing field.

### 2. Missing-field detection was left to the LLM and was unreliable
**Issue:** The planner originally asked the LLM itself to notice missing fields from the prompt text and decide to route to `ask_user`. This was inconsistent — the LLM didn't always catch missing fields, and it wasn't type-aware (e.g. couldn't reliably tell `days=0` vs. `days` not set).

**Fix:** Missing-field detection was moved out of the LLM and into plain Python — the planner now checks `source/destination/days/budget/likes` directly against the state and routes to `ask_user` deterministically. The LLM is only invoked once every required field is present, and only to decide the next routing step (`flight` / `hotel` / `itinerary` / `end`) via structured output (`PlannerDecision` in `model.py`).

### 3. No visibility into state as it moved through the graph
**Issue:** It was hard to reason about what the state looked like at each node while debugging routing/field issues above.

**Fix:** Added a `print("State:", state)` at the top of every node (`planner`, `flight`, `hotel`, `itinerary`, `ask_user`) so the full state trajectory is visible in the console on each run.

## 2026-08-17

### 4. Graph kept cycling Planner → Itinerary instead of terminating
**Issue:** Once all required fields were present, the planner prompt asked the LLM to freely choose between `flight` / `hotel` / `itinerary` / `end` on every pass, with no memory of which steps had already run. The LLM tended to keep re-selecting `itinerary` (or bouncing between it and the planner) instead of ever reaching `end`.

**Fix:** The planner now tracks `flight_done` / `hotel_done` / `itinerary_done` from the current state and passes that workflow status into the LLM prompt explicitly, with rules telling it not to re-select a completed step. A Python-side safety-validation pass then overrides the LLM's choice if it still picks an already-completed node, defaulting to the next incomplete step (or `end` once everything is done).

### 5. Planner's routing logic never selected `flight` or `hotel`
**Issue:** With the old prompt, the LLM almost always jumped straight to `itinerary` (or looped on it) because it had no explicit signal that `flight` and `hotel` needed to run first — nothing in the prompt enforced ordering.

**Fix:** The new planner prompt states the required order explicitly (flight → hotel → itinerary) and includes the current completion status for each. A second Python-side check (independent of the LLM call) forces the decision back to `flight` or `hotel` if the LLM tries to skip ahead to `itinerary`/`end` while an earlier step is still incomplete — so ordering is now enforced deterministically rather than left to the model.

## 2026-08-21

### 6. `flight` node always returned an empty response
**Issue:** `flight()` called `llm.bind_tools([search_flights])` and read `response.content` directly. When a model is bound with tools and decides to use one, it returns `content=""` and puts the request in `response.tool_calls` instead — the tool is never actually executed by LangChain automatically. Since the code never checked `tool_calls`, ran `search_flights`, or fed the result back to the model, the LLM's real output was discarded and `flight` in state stayed empty.

**Fix:** Implemented the full tool-calling loop in `flight()`: send the prompt as a `HumanMessage`, check `response.tool_calls`, actually invoke `search_flights.invoke(tool_call["args"])` for each requested call, append each result as a `ToolMessage` (tagged with `tool_call_id`), then call the LLM again with the extended message history so it can produce the final answer using the tool output. Only then is `response.content` read.

## 2026-10-31

### 7. Flight tool loop only handled a single round of tool calls
**Issue:** The fix in #6 ran the requested tool calls once and invoked the LLM one more time. If that second response asked for *more* tools (e.g. a retry with different args), those calls were never executed and `response.content` was empty again. The loop was also hidden inside the `flight` node, so it didn't show up in the graph.

**Fix:** Moved the loop into the graph itself, the idiomatic LangGraph way. `TravelState` now has a `messages: Annotated[list[AnyMessage], add_messages]` channel, a prebuilt `ToolNode([search_flights])` is registered as `flight_tools`, and `tools_condition` routes `flight → flight_tools → flight` for as long as the last AI message has `tool_calls`, then `flight → planner`. The `flight` node seeds the conversation on its first pass and only writes `state["flight"]` once the LLM answers without tool calls. Runaway loops are bounded by LangGraph's `recursion_limit` (default 25).

**Milestone (8 in [MILESTONES.md](MILESTONES.md)):** This makes the flight step a proper **ReAct loop** (Reason → Act → Observe → repeat): `flight` reasons and decides on a tool call, `flight_tools` acts, the `ToolMessage` is the observation fed into the next `flight` pass, and `tools_condition` decides whether to loop or finish. The rest of the graph is still a planner-driven workflow; only `flight` is ReAct so far, and with a single stubbed tool it usually completes in one round.

## 2026-11-01

### 8. `flight` node was never moved onto the graph loop, and `search_flights` was a stub
**Issue:** #7 rewired the graph (`flight_tools` + `tools_condition`) but the `flight` node itself still ran the old in-node tool loop and never returned anything into `messages`. `tools_condition` reads the last message in `messages`, so with an empty list it raised `ValueError: No messages found in input state to tool_edge`. Separately, `search_flights` returned the same hard-coded Ahmedabad → Tokyo text whatever the arguments were.

**Fix:** `search_flights` in `tools.py` now calls the real Duffel API (`POST /air/offer_requests?return_offers=true`, token from `DUFFEL_ACCESS_TOKEN` in `.env`). It takes IATA codes, a departure date (default: 30 days out) and `days` (which adds a return slice), and returns the cheapest offers. Each request and HTTP status is logged. Duffel errors such as a bad IATA code come back as the tool result rather than an exception, so the LLM can observe them and retry. `flight` is now a single ReAct step: on its first pass it seeds the conversation with a `HumanMessage`, it invokes the tool-bound LLM on `state["messages"]`, appends the reply, and writes `state["flight"]` only when no more tools are requested.

## 2026-11-18

### 9. `ask_user` blocked on `input()` and nothing survived between invokes
**Issue:** The graph compiled without a checkpointer, so each `invoke` started from scratch. Missing fields were collected with a blocking `input()` inside the `ask_user` node, which only works in a terminal script and can't pause and resume across requests.

**Fix:** Compiled with `checkpointer=InMemorySaver()` and gave every run a `thread_id`. `ask_user` now calls `interrupt({"ask": field})`. [main.py](main.py) loops while the result contains `__interrupt__` and resumes with `Command(resume=answer)` on the same config. `run_id` is passed only on the first invoke because LangSmith needs a unique run id, so later resumes show up as separate runs. Tested with a stubbed planner: five interrupts, each answer converted correctly (`days`/`budget` to int, `likes` to a list), 13 checkpoints in the thread history. **Gotcha:** on resume the interrupted node runs again from its first line, so its log block appears twice.

**Milestones (10, 11 in [MILESTONES.md](MILESTONES.md)):** Persistence / Checkpointing and Human-in-the-loop.

### 10. Hotel and itinerary answered from the LLM's memory, with no tools
**Issue:** Only `flight` had a tool loop. `hotel` and `itinerary` were single `llm.invoke(prompt)` calls, so hotel names, prices and places to visit could be out of date or invented. Giving them tools via the shared `messages` channel would have mixed the conversations: the hotel LLM would see every flight tool call, and `tools_condition` could read another worker's last message.

**Fix:**
- **Separate channels.** Each ReAct worker has its own channel: `messages` (flight), `hotel_messages` and `itinerary_messages`. `ToolNode(..., messages_key=...)` and `partial(tools_condition, messages_key=...)` read and write only that channel.
- **One shared step.** `_react_step` in [nodes.py](nodes.py) is the shared Reason step. `add_react_worker` in [graph.py](graph.py) wires `worker → worker_tools → worker → planner` for each of the three workers.
- **New tools** in [tools.py](tools.py):
  - `search_hotels`: Wikivoyage Sleep listings, with real price ranges, plus OpenStreetMap hotels (names only).
  - `search_attractions`: Wikivoyage See/Do/Eat/Buy listings plus OpenStreetMap places by category.
  - `get_weather_forecast`: Open-Meteo forecast within 15 days; beyond that, the actual weather on the same dates last year.
  - `convert_currency` is reused by hotel.
- **Tool sets:** `HOTEL_TOOLS = [search_hotels, convert_currency]`, `ITINERARY_TOOLS = [search_attractions, get_weather_forecast]`.
- **Prompts** now pass the flight and hotel results along, so the itinerary uses the flight's dates and the hotel takes the flight cost out of the budget. They also tell the LLM to use only places the tools returned.

**Gotchas found while building:**
- Duffel Stays (hotel prices) returns 403 because it isn't enabled on this account.
- The public Overpass servers (OpenStreetMap queries) kept returning 502 or timing out. Each server now gets a 25 s timeout, and every tool merges two sources, so when OSM is down Wikivoyage still answers.
- OSM in India tags college hostels and even Indian Coffee House as `tourism=hotel`, so hostels are excluded.

**Verified** with a full run, Ahmedabad → Raipur, 3 days, ₹30,000:
- flight looked up both airports in parallel, then called `search_flights` and `convert_currency`.
- hotel called `search_hotels` and recommended the Wikivoyage hotels with their ₹1500–2500 prices.
- itinerary called `get_weather_forecast` and `search_attractions` in parallel, used the flight's 2026-12-18 start date and planned around the weather.

**Milestone (9 in [MILESTONES.md](MILESTONES.md)):** extended. Every worker now picks between its own tools.

## 2026-11-21

### 11. Getting the graph to run in LangGraph Studio
**Goal:** watch runs live in LangGraph Studio instead of only reading LangSmith traces afterwards. Added [langgraph.json](langgraph.json) and [studio.sh](studio.sh) (`langgraph dev`). Four things broke on the way:

- **The dev server needs Python ≥ 3.11.** `langgraph-cli[inmem]` quietly skips its server packages (`langgraph-api`, `langgraph-runtime-inmem`) on the 3.10 `venv/`. **Fix:** `studio.sh` runs the CLI through `uvx --python 3.11 --with-requirements requirements.txt`, which builds a separate cached env. `venv/` is unchanged and still runs `main.py`.
- **Custom checkpointer.** The dev server supplies its own persistence (threads, interrupts, time travel), so a graph compiled with `InMemorySaver` doesn't belong there. **Fix:** [graph.py](graph.py) compiles the same builder twice: `graph` with `InMemorySaver` for `main.py`, and `studio_graph` with no checkpointer for Studio.
- **`KeyError: 'source'` on the first planner step.** `main.py` used to pass every key (set to `None` or `[]`), but a Studio run only sends what's in the input form. LangGraph leaves a key out of state until a node writes it, so `state["source"]` and `state["messages"]` blew up. **Fix:** `.get()` for those reads in [nodes.py](nodes.py) (`planner`'s missing-field check, `_react_step`'s first pass, the flight log line). Added `TravelInput` (just `user_query`) as the graph's `input_schema`, so the form shows one field and `main.py` now passes only the query.
- **Studio showed no input/state form.** The server log said `Please use typing_extensions.TypedDict instead of typing.TypedDict on Python < 3.12`. Pydantic builds the JSON schema Studio uses to draw the forms, and it can't do that from `typing.TypedDict` before 3.12. **Fix:** [state.py](state.py) imports `TypedDict` from `typing_extensions`.

**Verified:**
- Through the dev server's API (the same calls Studio makes): one thread, five `ask_user` interrupts resumed with `Command(resume=...)`, then flight, hotel and itinerary all filled in, with 35 checkpoints in the thread history.
- The schemas endpoint returns `input: [user_query]` and all 14 state fields.
- `main.py` still runs end to end with the answers piped in.

**Milestone (17 in [MILESTONES.md](MILESTONES.md)):** observability half done; evaluation still to do.
