from __future__ import annotations

import re

from .models import RingSchedule, SnapshotValidationResponse, Tournament

COUNT_PATTERN = re.compile(r"\((\d+)\s+competitors\)")


def validate_snapshot(tournament: Tournament, schedule: list[RingSchedule]) -> SnapshotValidationResponse:
    errors: list[str] = []
    warnings: list[str] = []

    athlete_ids = {athlete.id for athlete in tournament.athletes}
    coach_ids = {coach.id for coach in tournament.coaches}
    team_ids = {team.id for team in tournament.teams}

    division_by_id = {division.id: division for division in tournament.divisions}
    for division in tournament.divisions:
        count_match = COUNT_PATTERN.search(division.name)
        if count_match:
            expected = int(count_match.group(1))
            actual = len(division.athlete_ids)
            if expected != actual:
                errors.append(
                    f"Division '{division.id}' name count ({expected}) does not match athlete_ids size ({actual})."
                )

    for event in tournament.events:
        for athlete_id in event.athlete_ids:
            if athlete_id not in athlete_ids:
                errors.append(f"Event '{event.event_id}' references missing athlete_id '{athlete_id}'.")
        for coach_id in event.required_coach_ids:
            if coach_id not in coach_ids:
                errors.append(f"Event '{event.event_id}' references missing required_coach_id '{coach_id}'.")
        for team_id in event.team_ids:
            if team_id not in team_ids:
                errors.append(f"Event '{event.event_id}' references missing team_id '{team_id}'.")

        division = division_by_id.get(event.division_id)
        if division and division.name != event.division_name:
            warnings.append(
                f"Event '{event.event_id}' division_name differs from division '{event.division_id}' name."
            )

    _validate_schedule_overlaps(schedule, errors)

    return SnapshotValidationResponse(valid=len(errors) == 0, errors=errors, warnings=warnings)


def _validate_schedule_overlaps(schedule: list[RingSchedule], errors: list[str]) -> None:
    all_events = [event for ring in schedule for event in ring.events]

    # Same ring overlap
    for ring in schedule:
        ordered = sorted(ring.events, key=lambda event: event.start_minute)
        for idx in range(len(ordered) - 1):
            left = ordered[idx]
            right = ordered[idx + 1]
            if left.end_minute > right.start_minute:
                errors.append(
                    f"Ring overlap on {ring.ring_id}: {left.event_id} [{left.start_minute},{left.end_minute}) "
                    f"overlaps {right.event_id} [{right.start_minute},{right.end_minute})."
                )

    # Same referee crew overlap
    events_by_crew: dict[str, list] = {}
    for event in all_events:
        events_by_crew.setdefault(event.referee_crew_id, []).append(event)
    for crew_id, crew_events in events_by_crew.items():
        ordered = sorted(crew_events, key=lambda event: event.start_minute)
        for idx in range(len(ordered) - 1):
            left = ordered[idx]
            right = ordered[idx + 1]
            if left.end_minute > right.start_minute:
                errors.append(
                    f"Referee overlap on {crew_id}: {left.event_id} [{left.start_minute},{left.end_minute}) "
                    f"overlaps {right.event_id} [{right.start_minute},{right.end_minute})."
                )

    # Shared athlete/coach overlaps
    for left_idx in range(len(all_events)):
        left = all_events[left_idx]
        left_athletes = set(left.athlete_ids)
        left_coaches = set(left.required_coach_ids)
        for right_idx in range(left_idx + 1, len(all_events)):
            right = all_events[right_idx]
            overlaps_in_time = not (left.end_minute <= right.start_minute or right.end_minute <= left.start_minute)
            if not overlaps_in_time:
                continue

            shared_athletes = left_athletes.intersection(right.athlete_ids)
            if shared_athletes:
                errors.append(
                    f"Athlete overlap between {left.event_id} and {right.event_id}: {sorted(shared_athletes)}."
                )

            shared_coaches = left_coaches.intersection(right.required_coach_ids)
            if shared_coaches:
                errors.append(
                    f"Coach overlap between {left.event_id} and {right.event_id}: {sorted(shared_coaches)}."
                )
