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

## 2026-08-17

### 4. Graph kept cycling Planner → Itinerary instead of terminating
**Issue:** Once all required fields were present, the planner prompt asked the LLM to freely choose between `flight` / `hotel` / `itinerary` / `end` on every pass, with no memory of which steps had already run. The LLM tended to keep re-selecting `itinerary` (or bouncing between it and the planner) instead of ever reaching `end`.

**Fix:** The planner now tracks `flight_done` / `hotel_done` / `itinerary_done` from the current state and passes that workflow status into the LLM prompt explicitly, with rules telling it not to re-select a completed step. A Python-side safety-validation pass then overrides the LLM's choice if it still picks an already-completed node, defaulting to the next incomplete step (or `end` once everything is done).

### 5. Planner's routing logic never selected `flight` or `hotel`
**Issue:** With the old prompt, the LLM almost always jumped straight to `itinerary` (or looped on it) because it had no explicit signal that `flight` and `hotel` needed to run first — nothing in the prompt enforced ordering.

**Fix:** The new planner prompt states the required order explicitly (flight → hotel → itinerary) and includes the current completion status for each. A second Python-side check (independent of the LLM call) forces the decision back to `flight` or `hotel` if the LLM tries to skip ahead to `itinerary`/`end` while an earlier step is still incomplete — so ordering is now enforced deterministically rather than left to the model.
