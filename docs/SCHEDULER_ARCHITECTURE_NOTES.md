# Scheduler Architecture Notes

Diagnosis of the **current** scheduler / rescheduler / local-repair stack against the
target match-flight model defined in `docs/SCHEDULING_CONSTRAINTS.md`.

---

## 1. Atomic unit today

The CP-SAT model in `build_optimized_schedule` builds **one `IntervalVar` per `TournamentEvent` (i.e. per division)** — **not per match**.

Reference: `backend/app/scheduler.py:126-159`

```python
for ei, event in enumerate(tournament.events):
    duration = durations[ei]
    start = model.NewIntVar(0, horizon + 640, f"start_e{ei}")
    end = model.NewIntVar(0, horizon + 640, f"end_e{ei}")
    model.Add(end == start + duration)
    interval = model.NewIntervalVar(start, duration, end, f"interval_e{ei}")
```

Match-level timing is **derived after the fact** by slicing the division's window inside
`brackets.build_division_detail` (`backend/app/brackets.py:26-159`, see `_match_window`).
Matches inherit the division event's `start_minute` / `end_minute`; their times are not
first-class CP-SAT variables.

This is the root cause of every other issue in this document.

---

## 2. Constraints that are still division-wide

All of these are applied to the **division event interval**, not to individual matches:

| Constraint | Scope today | Reference |
| --- | --- | --- |
| Ring no-overlap | division-event | `scheduler.py:160-161` |
| Referee crew no-overlap | division-event | `scheduler.py:162-163` |
| Athlete no-overlap | division-event pair (`AddNoOverlap` on shared athletes) | `scheduler.py:165-173` |
| Coach no-overlap | division-event pair | `scheduler.py:165-173` |
| Poomsae-before-kyorugi per ring | division-event | `scheduler.py:292-303` |
| Availability index | events seed match-level intervals, but staging windows are derived from `event.start_minute` | `availability.py:107-208` |

If division A and division B share a single athlete, the **whole division blocks** are
no-overlap-coupled even if only one match in each actually uses that athlete.

The `AvailabilityIndex` synthesizes warmup/holding/staging intervals **30/15/5 minutes
before `event.start_minute`** (`availability.py:206-208`). Every match in that division
inherits the event-level staging window, so a late-round match cannot legally occupy an
earlier slot in its own division — the staging ghost blocks it.

---

## 3. Why one blocked match can move an entire division

Two pathways:

### 3a. Swap path (`_swap_matches_in_detail`)
`local_repair.py` — when `try_same_division_*_swap` succeeds, the repaired bracket detail
swaps two `Match` objects' `start_minute` / `end_minute` but the underlying
`ScheduledEvent` is **not** mutated. That's actually fine — the swap is local, and
`changed_match_count` stays small.

### 3b. Same-ring or global path
`_swap_events_in_same_ring` (`local_repair.py:1119-1140`) and `reoptimize_future_events`
(`rescheduler.py:44-307`) operate on **`ScheduledEvent` (division-event) intervals**.
Shifting one division event by `delay_minutes` shifts every match inside it by the same
amount, because all match times are derived from the event's window. There is no way to
move only one match — there is no "match interval" in the model.

The global rescheduler's change penalty is high (25M per `start_changed`,
`rescheduler.py:244-256`) but additive against makespan, so unrelated future divisions
can still slide.

---

## 4. Why local swaps are ineffective

`_candidate_is_ready_for_swap` (`local_repair.py`) gates candidates on:

1. **`_bracket_dependencies_ready`** — requires **every** match in **every** prior round
   to be `status == "completed"` (`local_repair.py:1039-1049`). For semifinals or finals
   in a freshly-built schedule, this is essentially never true.
2. **`_match_uses_blocked_resource`** — disqualifies candidates that share the blocked
   coach / athlete / referee crew / ring.
3. **`_available_for_current_slot`** — checks the candidate's resources against the
   `AvailabilityIndex` at the **affected match's** time slot. Because the index is built
   from the original division-event placements (which encode staging-window ghosts), most
   "ready" candidates report phantom conflicts.

Net effect: the most desirable swap target — a sibling match at the same round in the
same division — is usually filtered out, and the repair degrades to `small_local_wait`,
ring queue rotation, or global reschedule.

---

## 5. Idle ring gaps

Objective weights in `scheduler.py:303-313`:

| Term | Weight |
| --- | --- |
| Makespan | 75,000,000 |
| Latest parallel start | 1,975,000 (load balance) |
| Utilization miss | 9,350,000 (use all rings) |
| Lunch crossing | 62,500 |
| **Ring idle total** | **52,000 (weak)** |
| Workload imbalance | 880 |
| Starts sum | 2,010 |

Ring idle is one of the **weakest** terms in the objective. There is **no penalty for
gaps within a division event** — the solver sees each event as a monolith. There is no
inter-match spacing term to keep work tight.

---

## 6. Why a small delay can blow up makespan

`reoptimize_future_events`:

- Treats every event whose `start_minute > current_minute` as a free variable
  (`rescheduler.py:64`).
- Re-solves with a heavily-weighted "do not change start" penalty, but **the makespan
  itself is added directly to the objective** (`rescheduler.py:255`). When the solver
  has to slide event A by 20 minutes, it can also slide unrelated event B by a tiny
  amount if that buys back makespan.
- Frozen events are hard blockers (`rescheduler.py:143-161`). When a delay pushes a
  frozen event's end forward, it crowds future events on the same ring/crew, which
  creates a chain of forced shifts.
- Because everything is at division granularity, one bumped division can collide with the
  *full block* of the next division on its ring — even if only one match would actually
  conflict.

---

## 7. Validation behavior

`validation.py` runs:

- `_validate_schedule_overlaps` — event-level ring/crew/athlete/coach no-overlap.
- `_validate_poomsae_before_kyorugi` — same-ring sequencing.
- `_validate_poomsae_round_block_contiguity` (added in this branch) — flags any
  unrelated event whose window falls inside a poomsae division's `(division_id,
  round_name)` window on the same ring.
- `_validate_bracket_round_precedence` (added in this branch) — flags later rounds
  starting before earlier rounds end.
- `_validate_match_level_detail` — per-division detail audit.
- `_validate_live_operations_hints` — soft checks (lunch, idle, first-start disparity).

Because the underlying scheduler still slices match windows from a single division event,
the new poomsae-contiguity validator will fire a lot in the default snapshot today: the
solver happily packs rings with multiple division blocks, and the match-level slicing
inside one block can effectively interleave matches from other blocks if event windows
overlap on the same ring (which the no-overlap should prevent at event level — but the
slicing-into-matches step does not re-check). This validator is therefore a useful
*early warning*: it surfaces real architectural friction even before we move to true
match intervals.

---

## 8. CSV import infeasibility

`/api/import/csv` in `main.py`:

- Calls strict `build_optimized_schedule` first.
- On `ScheduleError` (CP-SAT returns `INFEASIBLE` / `UNKNOWN`), falls back to
  `_relaxed_greedy_schedule`, which enforces ring/athlete/coach no-overlap and warns on
  referee shortages.
- Returns diagnostics including `solver_status`, `fallback_used`, warnings.

Today the relaxed path is **only** used as a fallback, not the default. For real-world
CSVs whose populations don't match the synthetic generator's assumptions, the strict
solver often returns `UNKNOWN` and the fallback fires. That's fine — but the **strict
solver should probably not be the default for imported CSVs at all**, because users
care about getting *a* feasible schedule, not the absolute optimum.

---

## 9. Original-vs-live flow

The repair / reschedule endpoints already preserve `original_schedule` and emit a
separate `repaired_schedule`. `try_small_local_wait` and friends always copy events via
`model_dump()` before mutating (`local_repair.py:535-603`), so the baseline is never
clobbered in-place.

**However**, the frontend's live-demo path is messier:

- `App.jsx#handleRunDemo('coach_delayed')` overwrites both `originalSchedule` and
  `currentSchedule` from the repair response.
- `handleEmergencySimulation` and `injectLiveDelay` similarly swap state from the
  reschedule response.

There is no clean "publish baseline / inspect baseline / simulate disruption / show
diff" sequence — the baseline is whatever the last response says it is.

---

## 10. Match number stability

`brackets.build_division_detail` accepts `match_number_by_match_id`. When provided
(via `match_numbers.build_published_match_number_map`), match numbers are **stable**.
When omitted, matches receive sequential fallback numbers
(`brackets.py:1212-1219`).

`local_repair.try_repair_next_match` calls `build_division_detail` **without** the
published map (`local_repair.py:53, 90`), so the repaired `division_detail` returned to
the frontend can carry regenerated numbers. The coordinator board path (which does pass
the map) keeps stable numbers, so call-sheet UIs are still correct, but the repair
response's bracket view can drift.

This is a low-risk bug today (the UI mostly uses the coordinator numbers) but should be
fixed when we move to match-level intervals.

---

## Summary of root causes

1. **Atomic unit mismatch.** The solver schedules division events; matches are derived
   from those windows. There is no first-class match interval.
2. **Staging-window ghosts.** Availability is anchored on `event.start_minute`, so any
   match in the division is "in staging" for the whole event's prelude — late-round
   matches cannot legally occupy earlier slots in their own division.
3. **Bracket dependency lock.** Local-repair candidate readiness requires *all* prior
   rounds completed, which is almost never true at publication time.
4. **Division-coupled rescheduling.** Shifting a division event shifts every match in
   it; small delays cascade because adjacent division blocks must give way to whole-block
   moves.
5. **Weak idle penalties.** The objective is dominated by makespan and load balance; the
   solver has no incentive to pack matches tightly inside a ring or division.
6. **Match-number regeneration risk.** Repair endpoints rebuild division detail without
   the published match-number map.
7. **Baseline / live conflation in the frontend.** There is no explicit "publish vs
   simulate" boundary; the live demo overwrites the baseline state on every event.

Fixing (1) is the long-term cure. (2)–(7) are the symptoms we can stabilize incrementally
without a full rewrite of the CP-SAT solver. The remainder of this branch's work targets
the symptoms via:

- match-level local repair (already in `try_same_division_*_swap`),
- relaxed staging-window check during local repair,
- objective-side gap penalties,
- explicit "publish original / simulate disruption" separation in the API,
- propagating the published match-number map into repair detail rebuilds.
