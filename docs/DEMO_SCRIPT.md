# TaekwonFlo Demo Script

## Setup

1. Start the backend API.
2. Start the Vite frontend.
3. Confirm the dashboard shows rings, events, staging queue, and validation status.

## Division Detail Flow

1. Click a division event card in any ring.
2. The Division Detail panel opens.
3. Point out the division metadata: age group, gender, weight class, and competition class.
4. Review the bracket list:
   - competitors and teams
   - match statuses
   - scores for completed matches
   - advanced competitors
5. Highlight the current match if one overlaps the current tournament minute.
6. Review staging and waiting competitors in the side panel.

## Emergency Flow

1. Run a medical delay or ring pause.
2. Confirm the dashboard updates delayed/paused ring counts and changed events.
3. Click a rescheduled division to show that bracket detail remains available.
4. Explain that completed and active division events are frozen, while future work is locally repaired when feasible.

## Referee Shortage Flow

1. Run a referee shortage.
2. Explain that events now carry `required_referee_count`.
3. Point out that lower-official-count work is preferred during the shortage window and higher-official-count events can be delayed.

