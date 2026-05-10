# TaekwonFlo Scheduling Constraints (Target Model)

This document describes the **complete scheduling constraint model** TaekwonFlo is moving toward. It is **normative for product intent** and may **diverge from the current MVP implementation** (which still schedules many operations at **division-block** granularity). See also `docs/DATA_MODEL.md` for concrete API shapes today and `docs/SCHEDULING_RULES.md` for current solver behavior.

---

## 1. Core scheduling unit

The **true atomic scheduling unit** is a **match** or **flight** (a schedulable unit of competition), not necessarily an entire division.

- A **division** may be decomposed into many matches or flights.
- A division may be **split across multiple rings** when rules, entries, and resources allow.
- Each scheduled item should carry at least:
  - **`match_number`** — stable identifier for the day (see §2)
  - **`match_id`** — internal unique key
  - **`division_id`**
  - **`round_name`** (e.g., preliminary flight A, quarterfinal, semifinal, final)
  - **`ring_id`**
  - **`start_minute`** / **`end_minute`** (tournament-minute timeline)
  - **athletes / entries** (roster for that unit)
  - **coaches** required or associated for reporting
  - **referees / judges** (crew + individual assignments where used)
  - **`status`** (e.g., waiting, staging, in_progress, completed)

**Note:** The live MVP often still exposes **division-level** `ScheduledEvent` rows while **match-level** detail is built for bracket views; the target is to converge so the **solver and published schedule** reason about **match/flight intervals** as first-class citizens.

---

## 2. Global match numbering

**Match numbers must be unique across the entire tournament day** (one global sequence for the event, not per ring and not per division).

- Numbers are assigned **once** when the **original published schedule** is created, in **chronological order** of the published plan (or per a documented tie-break if two units share the same nominal start).
- **`match_number` does not change** after emergency repair, match swap, local shift, or global reschedule.  
  - Example: if **Match 42** was published on Ring 2 at 10:20 and later moves to Ring 4 at 10:45, it **remains Match 42**.
- This stability is required so athletes, coaches, and staging staff only track **one number** for the day.
- Internally, **`match_id`** may remain the stable primary key; **`match_number`** is the human-facing stable label tied to that match for the day.

---

## 3. Division splitting across rings

Entire divisions **do not** have to remain on a single ring.

**Poomsae-style example**

- A large preliminary round (e.g., 60 entries) may run as **three flights** on **three rings** (~20 entries each), in parallel subject to judging and staging capacity.
- **Semifinals / finals** may **consolidate** onto fewer rings as the field narrows and advancement is known.

**Kyorugi example**

- An 8-athlete bracket has **four** quarterfinal matches. Those four may run **simultaneously on four rings** if athletes, coaches, and referees are all available and bracket rules allow.
- **Two** semifinals may then run on **two** rings in parallel.
- The **final** must wait until **both semifinals are complete**, winners are known, and any **rest / cooldown** rules for advancing athletes are satisfied (see §5).

---

## 4. Bracket dependency constraints

- A match **cannot start** until **all required feeder matches** are **completed** (or handled as byes).
- A **final** cannot start until **both semifinal winners** are known.
- UI and API for **future** bracket slots must show placeholders such as **`Winner of Match X`**, not fabricated athlete names.
- **Losers do not advance** in single-elimination kyorugi.
- **Byes** are modeled as **automatic advancement** into the next slot without requiring a contested bout.

---

## 5. Athlete constraints

- An athlete **cannot** be scheduled in **overlapping** matches or flights (including across divisions, e.g., poomsae and kyorugi the same day).
- For **kyorugi advancement**, enforce a **minimum rest / cooldown** between bouts for the same athlete.
  - **Default minimum:** **5 minutes** between fights for the same athlete (product default; configurable per event rules).
  - Especially critical between **semifinal and final**.
- Multi-event athletes (e.g., poomsae + kyorugi) must respect **non-overlap** across all scheduled units.

---

## 6. Coach constraints

- A coach **cannot** be required in **two places at once** (no overlapping coach obligations across rings).
- Each match-side (kyorugi) or performance entry (poomsae/pair/team) should carry **one active assigned coach** for that unit (`assigned_coach_id`).
- Team-level coach pools remain available (`coach_ids`), but scheduling/availability should use the **assigned match coach**, not all team coaches at once.
- **Single-coach teams:** avoid scheduling that team’s athletes in **multiple rings at the same time** when those athletes need that coach.
- **Coach delay** response hierarchy (prefer **smallest** change):
  1. **Match-level repair** within the division (next eligible match that respects bracket and resources).
  2. **Same-ring** swap to another eligible match.
  3. **Local ring** time shift.
  4. **Global reschedule** only as a **last resort** when local options are exhausted or invalid.

**Coach state tracking (target):** the system should support operational views with location/status such as:

- ring (actively coaching / watching)
- holding
- staging
- warmup
- available
- done

(Coordinator UI and APIs should align these with call phases; see §12.)

---

## 7. Referee constraints

- **Referee crews** are the default assignment unit per ring when possible.
- **Individuals** may be **reassigned or borrowed** across crews when necessary, but this should be **minimized** and **stabilized** when the schedule is published.
- Prefer **one crew associated with a ring** for operational clarity; crews commonly have **3–5** members.
- Each match/flight requires a **count** of referees/judges (e.g., 3 for many prelims, 5 for some later panels).
- **Borrowing** individuals is allowed only when required to satisfy **required official count**; treat excess borrowing as a **soft penalty** in optimization.
- **Referees need lunch/break coverage** analogous to rings: avoid impossible back-to-back demands and prefer breaks that align with the lunch policy (§8–9).

---

## 8. Ring constraints

- A ring runs **at most one match/flight at a time** (no overlap on the same ring timeline).
- When **events, crews, and entries** allow, **all rings should be active near tournament start** (parallelize first-wave work; minimize idle rings at T+0).
- **Ring idle time** between scheduled units should be **minimized** (soft objective), subject to buffers and safety.
- **Lunch:** rings need not stop exactly at `lunch_start_minute`; they should **finish the current unit** when reasonable, then observe a **break window** before resuming (see §9). **New** work should **not** start deep into the lunch corridor unless unavoidable (soft penalty).

---

## 9. Lunch / break constraints

- **Default lunch duration:** **60 minutes** (`lunch_duration_minutes`).
- **Default lunch anchor:** around **noon or 1:00 PM** wall-clock depending on tournament start (e.g., `lunch_start_minute` ≈ 180 or 240 from a 9:00 AM start).
- A ring may **complete the match/flight in progress** before entering break.
- **Referees** should receive **coordinated breaks** (not only ring-level gaps); borrowing and lunch staggering may be needed.
- Avoid **starting** new units that **significantly cross** into lunch; when they do, treat as **exception** with clear coordinator visibility.

---

## 10. Emergency repair hierarchy

Prefer the **smallest** change that restores feasibility:

1. **Same-division match swap** (reorder eligible matches).
2. **Same-ring match swap**.
3. **Local ring shift** (time slide on one ring).
4. **Division-level repair** (move or re-block a larger chunk of work).
5. **Global reschedule** (re-optimize many future intervals).

**Medical pause**

- Pause the **affected ring** (or relevant window).
- Resume after the delay; **avoid** moving an entire division unless necessary.

**Referee shortage**

- Prefer scheduling **lower official-count** units during the shortage window.
- **Borrow** individual referees **only if necessary**.

**Coach delay**

- Prefer **swap-in** of another eligible **match** before moving **whole divisions**.

---

## 11. Published schedule stability

After publication, **minimize churn**. Soft penalties (or lexicographic objectives) should discourage:

- **ring** changes for a given match_number
- **start time** shifts
- **referee** assignment changes
- new **coach** conflicts
- **division-wide** moves when a **match-level** fix exists

All material changes should surface in **coordinator-facing summaries** (ring/time/official deltas, reasons when available).

---

## 12. Coordinator visibility requirements

**Event coordinator** surface should bucket work by operational phase:

- Warm up now  
- Report to holding  
- Report to staging  
- Currently competing  
- Finished  

**Every match** in these views should show:

- **stable `match_number`**
- athletes / entries
- coaches (to report or involved)
- ring
- **estimated start** (and updates after repair)
- status

**Staging / holding** call timing should be driven by **estimated start** and lead-time rules (e.g., soon / now / later), not only by static division blocks.

---

## 13. Frontend behavior (target)

- **Rings** default **collapsed**.
- **Collapsed** ring card shows:
  - current **match number + division**
  - next **match number + division**
  - current status
  - remaining match/flight count
  - delays / rescheduled counts (and total delay where applicable)
- **Expand** ring to see the next match-level units (for MVP, next 20) plus a way to open all remaining ring matches in a scrollable panel.
- **Click** division/match row → **detail panel** (bracket, queue, coaches).
- **Bracket** view: standard **tournament bracket** layout (columns, connectors), with **Winner of Match N** for undecided feeders.

## 15. Division naming + duplicate policy

- Division names must include event-defining metadata:
  - **Kyorugi:** age group, gender, belt rank, weight class, event type  
    (e.g. `Junior Male Black Belt -59kg Kyorugi`)
  - **Poomsae:** age group, gender/coed, belt rank, event type  
    (e.g. `Cadet Female Color Belt Individual Poomsae`)
- Avoid duplicate division names unless intentionally flighted.
- If duplicate buckets are needed, append explicit flight suffixes (`Flight A`, `Flight B`, ...).
- For large poomsae fields, prefer one division with flighted round structure over repeated identical standalone divisions.

---

## 14. Implementation notes (future coding)

When moving from division-block CP-SAT to **match/flight** scheduling:

- Use **OR-Tools CP-SAT** with **interval variables per match/flight** (not only per division event).
- **`AddNoOverlap`** on:
  - each **ring**
  - each **athlete** (personal interval graph)
  - each **coach** obligation
  - each **referee** (and/or crew, depending on modeling)
- **Precedence constraints** for bracket edges (feeder completes before downstream start).
- **Minimum gap** constraints between intervals for the **same athlete** in kyorugi (default **5 minutes** unless configured).
- **Soft penalties** for:
  - schedule churn vs published plan
  - referee borrowing
  - idle ring time / late first starts
  - lunch-unfriendly starts
- Keep **`AvailabilityIndex`** (or equivalent) for **fast feasibility checks** and **local repair**.
- **Preserve `match_number`** across all repair/reschedule paths; never renumber published matches for the day.

---

## Cross-references

- **`docs/DATA_MODEL.md`** — current `Match`, `ScheduledEvent`, coordinator, and change-audit shapes.  
- **`docs/SCHEDULING_RULES.md`** — current MVP scheduler/rescheduler behavior and demo assumptions.  
- **`.github/copilot-instructions.md`** — high-level priorities and module map.
