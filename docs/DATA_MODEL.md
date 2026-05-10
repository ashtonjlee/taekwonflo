# TaekwonFlo Data Model

## Tournament Metadata

Synthetic tournaments contain rings, teams, coaches, athletes, divisions, referee crews, individual referees, and scheduled events. Crews roster 3–5 referees via `referee_ids`, while each referee tracks `home_crew_id`. Division events persist `referee_crew_id` alongside `assigned_referee_ids` populated after deterministic roster passes. The default demo simulation targets about 61 divisions across 5 rings with roughly 360 athletes, 24 teams, and 10 referee crews calibrated to finish near an 8–10 hour day.

Athletes include:

- `age_group`: `peewee`, `cadet`, `junior`, `senior`
- `gender`: `male`, `female`
- `belt_level`: `color_belt`, `black_belt`, `world_class`
- team and coach assignments

Divisions include:

- event type: `kyorugi`, `poomsae`, `pair_poomsae`, `team_poomsae`
- age group, gender, belt level, and simplified weight class
- bracket size or competitor count
- round structure metadata
- required referee or judge count
- bracket type
- estimated division duration

The simplified kyorugi weight classes are WT/USAT-inspired demo buckets, not an official rulebook. Peewee divisions use local tournament-style `Light`, `Middle`, and `Heavy` buckets. Actual official rules, weight categories, and division formats should be checked against current USATKD and WT event manuals for the specific event.

Senior male: `-54`, `-58`, `-63`, `-68`, `-74`, `-80`, `-87`, `+87`

Senior female: `-46`, `-49`, `-53`, `-57`, `-62`, `-67`, `-73`, `+73`

Junior male: `-45`, `-48`, `-51`, `-55`, `-59`, `-63`, `-68`, `-73`, `-78`, `+78`

Junior female: `-42`, `-44`, `-46`, `-49`, `-52`, `-55`, `-59`, `-63`, `-68`, `+68`

Cadet male: `-33`, `-37`, `-41`, `-45`, `-49`, `-53`, `-57`, `-61`, `-65`, `+65`

Cadet female: `-29`, `-33`, `-37`, `-41`, `-44`, `-47`, `-51`, `-55`, `-59`, `+59`

## Match-Level Detail

`GET /api/divisions/{division_id}/detail` returns a `DivisionDetail` payload:

- `division`: division metadata
- `competitors`: athletes with seed, team, age, gender, and belt data
- `bracket`: bracket type, rounds, and matches
- `current_match`: match currently competing, if any
- `waiting_competitors`
- `staging_competitors`
- `completed_matches`
- `advanced_competitors`

Each `Match` includes:

- `match_id`
- **`match_number`**: immutable tournament bracket label surfaced across UI summaries
- `division_id`
- `round_name`
- `bracket_position`
- resolved `competitor_1` / `competitor_2` when both sides are known
- kyorugi placeholders **`source_1_label` / `source_2_label`** (for example **`Winner of Match 12`**) whenever a feeder duel is unfinished
- optional **`feeder_1_match_number` / `feeder_2_match_number`** tying placeholders back to feeders
- optional `winner_id` and optional `loser_id` when the knockout side is tracked (**losers never advance** via `next_match_id`)
- optional score when completed
- status: `waiting`, `staging`, `in_progress`, `completed`
- scheduled event id, ring, start/end minute window (`ring_name` echoes the rostered ring label)
- `required_referee_count` plus **`assigned_referee_ids`** for the officials covering that duel
- kyorugi: `bye`, `next_match_id` bracket wiring when applicable
- ranked and pair/team lanes: `participant_athlete_ids` lists athletes on that performance slot (when not represented as two sides)
- `repair_note`, `swapped_from_match_id` when local repair modifies queue order

For future kyorugi rounds, unresolved feeders remain placeholders rather than fabricated athletes. The MVP reserves the future
round window but should not treat unknown winners as exact hard athlete/coach obligations until feeder matches complete. Once a
winner is known, the live availability index can resolve the actual athlete and assigned coach and local repair can respond to
new conflicts. This is a documented conservative bridge while the scheduler moves from division-block events toward fully
match-native conditional optimization.

Division detail optionally returns **`focused_match_id`** when the client passes `focus_match_id` through `GET /api/divisions/{id}/detail?...`; the MVP UI jumps to that match card inside the bracket view.

`MatchCompetitor` may include `coach_ids` and `coach_names` for roster and reporting views.

Each `MatchCompetitor` now also carries:

- **`assigned_coach_id`** / **`assigned_coach_name`** — the active coach for that specific match-side or performance entry.  
  Team-level coach pools remain available via `coach_ids`, but operational constraints and coach call sheets should use assigned match coaches.

Division detail augmentations beyond `bracket.matches`:

- `kyorugi_rounds`: layers of matches grouped by knockout round label (UI column layout).
- `ranked_rounds`: poomsae-style panels with ranked entries (`display_name`, `athlete_members`, scores, advancement flags).
- `coach_report`: rows describing where coaches should stage or watch (`CoachToReport` status such as report/in holding/waiting/currently coaching/done).
- `detail_validation`: structural audit `{ valid, errors, warnings }` for demo bracket integrity checks.

## Live coordination + change auditing

Emergency repairs/reschedules can emit supplemental rows for the UI:

- **`CoordinationBoard` / `CoordinatorMatchRow`**: per-match operational phase buckets (`warm_up_now`, `report_holding`, `report_staging`, `currently_competing`, `completed`) with urgency tiers (`now`, `soon`, `later`), ring/start metadata, rostered athletes/teams/coaches, and **`match_number`** for call scripts.
- **`ScheduleChangeDetail`**: per changed scheduled event captures ring/time deltas, referee crew deltas, **`assigned_referee_ids` before/after**, coach/athlete involvement, textual match breakdown entries, plus **`affected_match_numbers`** for quick scanning.
- **`RefereeAdjustment`**: granular moves when borrowing changes who covers a ring window (temporary versus rest-of-day scope).
- **`POST /api/operations/live`** returns `coordination_board` plus **`ring_hints`**: collapsed ring summaries (current/next division labels, **`current_match_number` / `next_match_number`**, remaining events on the ring, **`material_reschedule_count`**, and **`total_delay_minutes`** derived from `changed_events`). For stable numbering after repairs/reschedules, clients can include optional `original_schedule`; coordinator and ring hints keep the published-day `match_number` map.

Frontend ring surfaces consume coordinator match rows as the primary ring timeline when available:

- collapsed cards show current/next match number + division and remaining match count
- expanded cards show next match rows (MVP: next 20) with a scrollable “show all” list for the ring’s remaining day
- match rows include match number, division, round, athlete/entry display, assigned coaches, estimated start, and status

Greedy referee rostering minimizes borrowing: crews are filled from their home members first and only spill to other qualified referees when shortages remain, which keeps `RefereeAdjustment` deltas small in the steady state.

## Demo Scores

Kyorugi scores are deterministic point totals. Completed mock kyorugi winners are chosen from a seeded hash of match id and
competitor ids, so they are repeatable for the same tournament seed but do not always advance the first listed athlete. Poomsae
scores are deterministic decimal scores. These are realistic enough for the live demo but are not judging logic or prediction.

## Multi-ring Scheduling Direction

Large divisions should eventually decompose into match/flight records that can be assigned independently across rings:

- 8-athlete kyorugi quarterfinals may run in parallel on multiple rings when athletes, coaches, and referees are available.
- semifinals may run on fewer rings, and finals should wait for both feeders plus the default 5-minute advancing-athlete rest.
- large poomsae preliminaries may split into flights across rings, with later rounds consolidated when useful.

Current API payloads still include division-level `ScheduledEvent` blocks in several paths. Those blocks are a compatibility
surface for the demo UI, not a rule that a real division must stay on one ring.

## CSV Import

`POST /api/import/csv` accepts a multipart CSV upload and returns the same schedule shape as `/api/mock/snapshot`, plus a
`preview` object containing athlete/team/division counts, detected columns, and warnings. Flexible columns include:

- `athlete_name`
- `team_name`
- `coach_name`
- `gender`
- `age_group`
- `belt_rank`
- `weight_class`
- `event_type`
- `division_name`

When rings or referee crews are not present in the CSV, the backend uses demo defaults. Missing optional fields produce warnings
and deterministic defaults instead of crashing.

## Live Time Simulation

The frontend can advance `current_minute` locally in 15-minute or 1-hour steps, play a timelapse, reset to start, and inject
manual or random delays. The same schedule payload is reused; `/api/operations/live` recalculates current/next rings, staging,
holding, and completed buckets for the selected minute. When a delay is injected, the existing repair/reschedule endpoints return
an updated schedule and the frontend appends a visible event-log entry.

## Timing Assumptions

Durations are hackathon estimates, not official timing rules. Real tournament timing varies by event manual, age group, belt level, division size, staging, equipment checks, video review, protests, and ring operations.

Kyorugi estimates:

- color belt divisions approximate two 60-second rounds with a 30-second rest, plus setup and transition time.
- black belt and world class divisions approximate three 90-second rounds with 30-second rests, plus setup and transition time.
- bracket duration scales by expected match count.

Poomsae estimates:

- individual preliminary rounds use about 2.5 minutes per competitor.
- pair and team poomsae use about 3.0 minutes per entry.
- black belt and world class finals are longer because finalists may perform two poomsae/forms.
- finals use about 4-5 minutes per finalist or entry, plus transition and buffer time.
