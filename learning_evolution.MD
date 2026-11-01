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
