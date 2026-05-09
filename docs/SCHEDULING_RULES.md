# TaekwonFlo Scheduling Rules

## Current Scope

TaekwonFlo schedules division-level tournament events and now exposes deterministic match/bracket detail inside each scheduled division. The optimizer still assigns one scheduled event per division; match-level timing is derived from that scheduled event for live operations views. The default demo simulates a large 5-ring, roughly 61-division WT/USAT-inspired tournament day.

## Hard Constraints

- One ring may run only one scheduled event at a time.
- One referee crew may work only one scheduled event at a time.
- Athletes may not be scheduled into overlapping division events.
- Required coaches may not be scheduled into overlapping division events.
- Scheduled events include staging/transition buffer time.

## Emergency Rescheduling

Completed and currently active events are frozen. Future events can move, but the rescheduler penalizes unnecessary changes.

## Match-Level Local Repair

Before division-level or global rescheduling, `/api/repair/demo` tries match-level repair:

- same-division match swap
- same-ring match swap
- ring-local shift
- global reschedule fallback

The repair layer uses `AvailabilityIndex` to check athletes, coaches, referee crews, rings, and future medical-team resources. It also rejects bracket-invalid swaps, such as running a final before its semifinals are completed.

Medical delay and ring pause behavior:

- The affected ring is treated as unavailable for the emergency window.
- Future events on that ring are shifted after the delay window.
- Ring changes are heavily penalized so local repair is preferred.
- Events move to other rings only when the makespan benefit is large enough to justify the change and constraints remain valid.

Referee shortage behavior:

- Events carry `required_referee_count`.
- Kyorugi uses a referee crew count of 3 for the demo.
- Poomsae preliminary-style rounds use 3 officials.
- Poomsae semifinal/final and larger team poomsae groups use 5 officials.
- During a shortage window, the rescheduler prefers lower-official-count work and delays higher-official-count events when needed.

Greedy referee rostering runs after deterministic ring assignments: each scheduled event prefers its crew’s referees (`referee_ids`) before minimally borrowing certified individuals from other crews to satisfy `required_referee_count`. Availability tracking records each borrowed referee interval separately from coarse crew overlaps so temporary loans remain auditable, and summaries surface deltas through `RefereeAdjustment` rows whenever borrowing occurs.

Kyorugi bracket exports never print athlete names ahead of known feeder outcomes; placeholders read `Winner of Match N`, keyed by feeder `match_number`, and knockout losers cannot advance downstream.

## Weight Classes And Timing

The synthetic generator uses simplified WT/USAT-inspired categories for demo realism. These categories are not an official rulebook. Actual official rules, recognized divisions, weigh-in procedures, and match timing should be checked against current USATKD and WT event manuals for each event.

Kyorugi timing estimates:

- color belt matches approximate two 60-second rounds, a 30-second rest, setup, and transition.
- black belt and world class matches approximate three 90-second rounds, 30-second rests, setup, and transition.
- division duration scales by bracket size and expected match count.

Poomsae timing estimates:

- individual preliminary rounds use about 2.5 minutes per competitor.
- pair/team rounds use about 3.0 minutes per entry.
- black belt/world class finals are longer because finalists may perform two poomsae/forms.
- final rounds use about 4-5 minutes per finalist or entry plus operational buffer.

These estimates intentionally include buffer because real ring throughput depends on staging, judge readiness, athlete check-in, equipment, protests, and local event procedures.

## Match Detail Status

Match statuses are derived from the division event time and the requested `current_minute`:

- `completed`: match window ended before or at current minute.
- `in_progress`: current minute falls within the match window.
- `staging`: match starts within the next 10 minutes.
- `waiting`: match starts later.
