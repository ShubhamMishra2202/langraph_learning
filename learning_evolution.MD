# Learning Evolution

A running log of issues hit while building this LangGraph travel-planner project, and how they were resolved.

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
