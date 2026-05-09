# TaekwonFlo Demo Script

## Setup

1. Start the backend API.
2. Start the Vite frontend.
3. Confirm the dashboard shows rings (collapsed summaries by default — expand to see event cards), the staging queue, validation tiles, and the **`Live Reports`** pane (event coordinator buckets, schedule deltas, referee moves).

## Division Detail Flow

1. Open a division from a ring card **or** from a row in the Staging Queue (same panel either way).
2. The Division Detail panel opens.
3. Point out the division metadata: age group, gender, weight class, and competition class.
4. Walk the tabs — **Summary** (validation + headline current activity), **Queue** (repair notes, match numbers), **Bracket** (kyorugi columns with connector styling; placeholders read **`Winner of Match N`** until feeders complete), **Coaches** (movement sheet and roster coaches where present).
   - Competitors and teams appear in the right column rosters as before.
   - Match statuses and scores live in Queue and Bracket tabs.
   - Advanced competitors remain in the side panel.
5. Highlight the **current match** line on Summary when status is `in_progress` (ranked divisions may phrase the floor as a performance lane rather than a head-to-head line).
6. Review staging and waiting competitors in the side panel.
7. When opening from staging list rows or **`Live Reports` coordinator buckets**, observe the bracket tab jumps to `match-focus-*` anchors for quicker ring calls.

## Live Operations Pane

1. Locate **Event coordinator** columns (Warm up → Holding → Staging → Competing → Completed) and drill into urgency tags (`now` / `soon` / `later`).
2. Inspect **Schedule changes** after demos: rows list match numbers touched, athletes/coaches, ring deltas, referee crew moves, assigned referee IDs, and reasons where provided.
3. Inspect **Referee adjustments** rows after shortages or swaps to narrate borrowing scope (`temporary` vs `rest-of-day`).
4. Collapsed ring cards now summarize current/next divisions with match-number hints pulled from `/api/operations/live` plus remaining workload, reschedule hits, and delay minutes.

## Emergency Flow

1. Run a medical delay or ring pause.
2. Confirm the dashboard updates delayed/paused ring counts and changed events.
3. Click a rescheduled division to show that bracket detail remains available.
4. Explain that completed and active division events are frozen, while future work is locally repaired when feasible.
5. Scroll **`Live Reports` → Schedule changes** to narrate tangible deltas per match (numbers, roster strings, referee assignments).

## Referee Shortage Flow

1. Run a referee shortage.
2. Explain that events now carry `required_referee_count`.
3. Point out that lower-official-count work is preferred during the shortage window and higher-official-count events can be delayed.
4. If individual borrowing occurs, cite **`Live Reports` → Referee adjustments** to show who slid crews and for which ring window.

