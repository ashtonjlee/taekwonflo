from __future__ import annotations

import re

from .brackets import build_division_detail
from .models import RingSchedule, SnapshotValidationResponse, Tournament

COUNT_PATTERN = re.compile(r"\((\d+)\s+competitors\)")


def validate_snapshot(
    tournament: Tournament,
    schedule: list[RingSchedule],
    *,
    demo_mode: bool = False,
) -> SnapshotValidationResponse:
    errors: list[str] = []
    warnings: list[str] = []

    athlete_ids = {athlete.id for athlete in tournament.athletes}
    coach_ids = {coach.id for coach in tournament.coaches}
    team_ids = {team.id for team in tournament.teams}

    division_by_id = {division.id: division for division in tournament.divisions}
    team_by_id = {team.id: team for team in tournament.teams}
    for division in tournament.divisions:
        count_match = COUNT_PATTERN.search(division.name)
        if count_match:
            expected = int(count_match.group(1))
            actual = len(division.athlete_ids)
            if expected != actual:
                errors.append(
                    f"Division '{division.id}' name count ({expected}) does not match athlete_ids size ({actual})."
                )

    name_to_divisions: dict[str, list[str]] = {}
    for division in tournament.divisions:
        name_to_divisions.setdefault(division.name, []).append(division.id)
    for division_name, division_ids in name_to_divisions.items():
        if len(division_ids) <= 1:
            continue
        if "Flight " not in division_name:
            errors.append(
                f"Duplicate division name '{division_name}' appears in {division_ids} without flight labeling."
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
            team = team_by_id.get(team_id)
            if not team or len(team.coach_ids) <= 1:
                continue
            if set(team.coach_ids).issubset(set(event.required_coach_ids)):
                warnings.append(
                    f"Event '{event.event_id}' appears to require all coaches from multi-coach team '{team_id}'."
                )

        division = division_by_id.get(event.division_id)
        if division and division.name != event.division_name:
            warnings.append(
                f"Event '{event.event_id}' division_name differs from division '{event.division_id}' name."
            )

    _validate_schedule_overlaps(schedule, errors)
    _validate_poomsae_before_kyorugi(schedule, errors if demo_mode else warnings)
    _validate_match_level_detail(tournament, schedule, errors, warnings)

    _validate_live_operations_hints(tournament, schedule, warnings)

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


def _validate_match_level_detail(
    tournament: Tournament,
    schedule: list[RingSchedule],
    errors: list[str],
    warnings: list[str],
) -> None:
    for division in tournament.divisions:
        try:
            detail = build_division_detail(
                tournament=tournament,
                schedule=schedule,
                division_id=division.id,
                current_minute=0,
            )
        except (KeyError, ValueError):
            continue

        for item in detail.detail_validation.errors:
            errors.append(f"{division.id}: {item}")
        for item in detail.detail_validation.warnings:
            warnings.append(f"{division.id}: {item}")

        for match in detail.bracket.matches:
            for side_name, side in (("competitor_1", match.competitor_1), ("competitor_2", match.competitor_2)):
                if not side:
                    continue
                if side.coach_ids and not side.assigned_coach_id:
                    errors.append(
                        f"{division.id} {match.match_id} {side_name} missing assigned coach for this match."
                    )
                if side.assigned_coach_id and side.coach_ids and side.assigned_coach_id not in side.coach_ids:
                    errors.append(
                        f"{division.id} {match.match_id} {side_name} assigned coach not in available coach_ids."
                    )


def _validate_poomsae_before_kyorugi(schedule: list[RingSchedule], violations: list[str]) -> None:
    poomsae_types = {"poomsae", "pair_poomsae", "team_poomsae"}
    for ring in schedule:
        ordered = sorted(ring.events, key=lambda event: event.start_minute)
        poomsae_events = [event for event in ordered if event.event_type in poomsae_types]
        if not poomsae_events:
            continue
        ring_poomsae_end = max(event.end_minute for event in poomsae_events)
        violating_kyorugi = [event for event in ordered if event.event_type == "kyorugi" and event.start_minute < ring_poomsae_end]
        if not violating_kyorugi:
            continue
        offenders = ", ".join(
            f"{event.event_id}@T+{event.start_minute}" for event in sorted(violating_kyorugi, key=lambda event: event.start_minute)
        )
        violations.append(
            f"Ring {ring.ring_id} starts kyorugi before poomsae is complete (poomsae finishes T+{ring_poomsae_end}): {offenders}."
        )


def _validate_live_operations_hints(tournament: Tournament, schedule: list[RingSchedule], warnings: list[str]) -> None:
    ls = getattr(tournament, "lunch_start_minute", 180)
    grace_cut = ls + getattr(tournament, "lunch_grace_minutes", 20)

    first_starts_ring: dict[str, int | None] = {}
    num_rings = len(schedule)

    for ring_row in schedule:
        evts = sorted(ring_row.events or [], key=lambda event: event.start_minute)
        first_starts_ring[ring_row.ring_id] = evts[0].start_minute if evts else None

        for evt in evts:
            crossover = evt.start_minute < ls and evt.end_minute > grace_cut
            if crossover:
                warnings.append(
                    f"Soft lunch bleed: '{evt.division_name}' on {ring_row.ring_name} spans lunch grace corridor "
                    f"(T+{evt.start_minute}-T+{evt.end_minute})."
                )

            need = getattr(evt, "required_referee_count", 3) or 3
            assigned = getattr(evt, "assigned_referee_ids", None)

            actual_len = len(assigned or [])
            if actual_len > 0 and actual_len < need:
                warnings.append(
                    f"Underscheduled officials: '{evt.division_name}' needs {need} assigned referees but only lists "
                    f"{actual_len} after rostering passes."
                )

    num_evt = sum(len(ring.events or []) for ring in schedule)

    empties = [ring.ring_id for ring in schedule if not ring.events]
    utilize_all = len(tournament.referee_crews) >= num_rings and len(tournament.events or []) >= num_rings

    if utilize_all and num_evt >= num_rings and empties:
        warnings.append(
            f"Unused ring(s) although crews/divisions suffice to spread workload: {', '.join(sorted(empties))}."
        )

    nonzero_first = [(rid, fst) for rid, fst in first_starts_ring.items() if fst is not None]
    if nonzero_first:
        earliest = min(pair[1] for pair in nonzero_first)
        stragglers = [rid for rid, fst in nonzero_first if fst is not None and earliest == 0 and fst >= 55]
        if stragglers:
            warnings.append(
                "Ring first-start disparity: "
                + ", ".join(sorted(stragglers))
                + " start much later than other rings despite spare referee crews.",
            )
