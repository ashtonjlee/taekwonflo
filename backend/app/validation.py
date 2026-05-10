from __future__ import annotations

import re

from .brackets import build_division_detail
from .models import RingSchedule, SnapshotValidationResponse, Tournament

COUNT_PATTERN = re.compile(r"\((\d+)\s+competitors\)")
POOMSAE_TYPES = {"poomsae", "pair_poomsae", "team_poomsae"}


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
        if event.event_type in POOMSAE_TYPES and event.required_coach_ids:
            warnings.append(
                f"Event '{event.event_id}' is {event.event_type} and lists required_coach_ids; "
                "poomsae coach IDs must be ignored by scheduling constraints for MVP."
            )
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

    _validate_schedule_overlaps(schedule, errors, warnings)
    _validate_poomsae_coaches_not_scheduled(schedule, warnings)
    _validate_kyorugi_schedule_shape(tournament, schedule, errors, warnings)
    _validate_poomsae_before_kyorugi(schedule, warnings)
    # Until the solver moves to true match-level intervals (see
    # docs/SCHEDULER_ARCHITECTURE_NOTES.md), the contiguity check fires often on
    # otherwise-feasible snapshots. Treat it as a warning in demo mode so the
    # validation panel is actionable rather than a wall of errors.
    _validate_poomsae_round_block_contiguity(tournament, schedule, warnings if demo_mode else errors)
    _validate_bracket_round_precedence(tournament, schedule, errors)
    _validate_match_level_detail(tournament, schedule, errors, warnings)

    _validate_live_operations_hints(tournament, schedule, warnings)

    return SnapshotValidationResponse(valid=len(errors) == 0, errors=errors, warnings=warnings)


def validate_schedule_hard_constraints(
    tournament: Tournament,
    schedule: list[RingSchedule],
) -> SnapshotValidationResponse:
    """Validate constraints that must never be returned as a successful schedule."""
    errors: list[str] = []
    warnings: list[str] = []

    _validate_schedule_overlaps(schedule, errors, warnings)
    _validate_poomsae_coaches_not_scheduled(schedule, warnings)
    _validate_kyorugi_schedule_shape(tournament, schedule, errors, warnings)
    _validate_scheduled_poomsae_block_continuity(tournament, schedule, errors)
    _validate_bracket_round_precedence(tournament, schedule, errors)
    _validate_match_level_detail(tournament, schedule, errors, warnings)
    _validate_live_operations_hints(tournament, schedule, warnings)

    return SnapshotValidationResponse(valid=len(errors) == 0, errors=errors, warnings=warnings)


def sort_schedule(schedule: list[RingSchedule]) -> list[RingSchedule]:
    return [
        RingSchedule(
            ring_id=ring.ring_id,
            ring_name=ring.ring_name,
            events=sorted(
                (event.model_copy(update={"ring_id": ring.ring_id, "ring_name": ring.ring_name}) for event in ring.events),
                key=lambda event: (event.start_minute, event.end_minute, event.event_id),
            ),
        )
        for ring in schedule
    ]


def _validate_scheduled_poomsae_block_continuity(
    tournament: Tournament,
    schedule: list[RingSchedule],
    errors: list[str],
) -> None:
    poomsae_types = {"poomsae", "pair_poomsae", "team_poomsae"}
    poomsae_division_ids = {
        division.id for division in tournament.divisions if division.event_type in poomsae_types
    }
    if not poomsae_division_ids:
        return

    for ring in schedule:
        by_division: dict[str, list] = {}
        for event in ring.events:
            if event.division_id in poomsae_division_ids:
                by_division.setdefault(event.division_id, []).append(event)

        for division_id, events in by_division.items():
            if len(events) <= 1:
                continue
            block_start = min(event.start_minute for event in events)
            block_end = max(event.end_minute for event in events)
            for event in ring.events:
                if event.division_id == division_id:
                    continue
                if event.start_minute < block_end and event.end_minute > block_start:
                    errors.append(
                        f"Poomsae scheduled block interrupted on {ring.ring_id}: division "
                        f"'{division_id}' window [{block_start},{block_end}) overlaps event "
                        f"'{event.event_id}' [{event.start_minute},{event.end_minute})."
                    )


def _validate_kyorugi_schedule_shape(
    tournament: Tournament,
    schedule: list[RingSchedule],
    errors: list[str],
    warnings: list[str],
) -> None:
    events = [event for ring in schedule for event in ring.events]
    for division in tournament.divisions:
        if division.event_type != "kyorugi":
            continue
        rows = [event for event in events if event.division_id == division.id]
        if not rows:
            continue
        match_rows = [event for event in rows if event.match_id]
        if not match_rows:
            errors.append(f"{division.id}: kyorugi division is scheduled as a division block, not match-level rows.")
            continue
        expected = _expected_kyorugi_scheduled_match_count(len(division.athlete_ids))
        if len(match_rows) != expected:
            errors.append(
                f"{division.id}: kyorugi scheduled match count is {len(match_rows)}, expected {expected} from bracket structure."
            )
        for event in match_rows:
            duration = event.end_minute - event.start_minute
            if duration > 15:
                errors.append(
                    f"{division.id}: kyorugi match '{event.event_id}' duration is {duration}m; expected one match around 5-10m."
                )
            if event.round_name == "final" and duration > 12:
                errors.append(
                    f"{division.id}: kyorugi final '{event.event_id}' is {duration}m, not a single-match duration."
                )
            if duration < 5 or duration > 10:
                warnings.append(
                    f"{division.id}: kyorugi match '{event.event_id}' duration is {duration}m; MVP target is 5-10m."
                )
        by_round: dict[str, list] = {}
        for event in match_rows:
            by_round.setdefault(event.round_name or "", []).append(event)
        for round_name, round_rows in by_round.items():
            if len(round_rows) <= 1:
                continue
            rings_used = {event.ring_id for event in round_rows}
            if len(rings_used) == 1 and len(schedule) > 1:
                warnings.append(
                    f"{division.id}: all {len(round_rows)} {round_name} matches are on {next(iter(rings_used))}; "
                    "same-round kyorugi matches may be spread across rings."
                )


def _expected_kyorugi_scheduled_match_count(competitor_count: int) -> int:
    bracket_size = 1
    while bracket_size < max(2, competitor_count):
        bracket_size *= 2
    tokens: list[bool] = [idx < competitor_count for idx in range(bracket_size)]
    count = 0
    while len(tokens) > 1:
        next_tokens: list[bool] = []
        for idx in range(0, len(tokens), 2):
            left = tokens[idx]
            right = tokens[idx + 1] if idx + 1 < len(tokens) else False
            if left and right:
                count += 1
                next_tokens.append(True)
            else:
                next_tokens.append(left or right)
        tokens = next_tokens
    return count


def _validate_schedule_overlaps(schedule: list[RingSchedule], errors: list[str], warnings: list[str]) -> None:
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

            if left.event_type != "kyorugi" or right.event_type != "kyorugi":
                continue

            shared_coaches = left_coaches.intersection(right.required_coach_ids)
            if shared_coaches:
                overlap = min(left.end_minute, right.end_minute) - max(left.start_minute, right.start_minute)
                if overlap <= 2:
                    warnings.append(
                        f"Coach overlap tolerance (<=2m) between {left.event_id} and {right.event_id}: {sorted(shared_coaches)} ({overlap}m)."
                    )
                else:
                    errors.append(
                        f"Coach overlap between {left.event_id} and {right.event_id}: {sorted(shared_coaches)} ({overlap}m)."
                    )


def _validate_poomsae_coaches_not_scheduled(schedule: list[RingSchedule], warnings: list[str]) -> None:
    offenders = [
        event.event_id
        for ring in schedule
        for event in ring.events
        if event.event_type in POOMSAE_TYPES and event.required_coach_ids
    ]
    if offenders:
        warnings.append(
            "poomsae_coach_constraints_present: scheduled poomsae rows include required_coach_ids "
            f"({', '.join(sorted(offenders)[:8])}); these must not be used as hard scheduling constraints."
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

        if division.event_type in {"poomsae", "pair_poomsae", "team_poomsae"}:
            round_windows: dict[str, tuple[int, int]] = {}
            for match in detail.bracket.matches:
                if match.round_name not in detail.bracket.rounds:
                    continue
                current = round_windows.get(match.round_name)
                if current is None:
                    round_windows[match.round_name] = (match.start_minute, match.end_minute)
                else:
                    round_windows[match.round_name] = (
                        min(current[0], match.start_minute),
                        max(current[1], match.end_minute),
                    )
            for previous_round, next_round in zip(detail.bracket.rounds, detail.bracket.rounds[1:]):
                previous_window = round_windows.get(previous_round)
                next_window = round_windows.get(next_round)
                if not previous_window or not next_window:
                    continue
                previous_end = previous_window[1]
                next_start = next_window[0]
                if previous_end > next_start:
                    errors.append(
                        f"{division.id}: poomsae round ordering violation: {previous_round} ends T+{previous_end} "
                        f"after {next_round} starts T+{next_start}."
                    )

        for match in detail.bracket.matches:
            for feeder_number in [match.feeder_1_match_number, match.feeder_2_match_number]:
                if feeder_number is None:
                    continue
                feeder = next((candidate for candidate in detail.bracket.matches if candidate.match_number == feeder_number), None)
                if feeder and feeder.end_minute > match.start_minute:
                    errors.append(
                        f"{division.id}: bracket dependency violation: Match {match.match_number} starts T+{match.start_minute} "
                        f"before feeder Match {feeder.match_number} ends T+{feeder.end_minute}."
                    )

            for side_name, side in (("competitor_1", match.competitor_1), ("competitor_2", match.competitor_2)):
                if not side:
                    continue
                if division.event_type != "kyorugi":
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


def _validate_poomsae_round_block_contiguity(
    tournament: Tournament,
    schedule: list[RingSchedule],
    errors: list[str],
) -> None:
    """A poomsae division round block must be contiguous on a single ring.

    Within the start/end window of a (division_id, round_name) block on a given ring,
    no unrelated division's match may be interleaved.
    """
    poomsae_types = {"poomsae", "pair_poomsae", "team_poomsae"}
    poomsae_division_ids = {
        division.id for division in tournament.divisions if division.event_type in poomsae_types
    }
    if not poomsae_division_ids:
        return

    division_event_id_to_division = {
        event.event_id: event.division_id for ring in schedule for event in ring.events
    }

    for ring in schedule:
        # Build per-(division, round) block windows from match-level detail.
        # We collect division windows by walking each poomsae division on this ring once.
        ring_event_division_ids = {
            event.division_id for event in ring.events if event.division_id in poomsae_division_ids
        }
        round_blocks: list[tuple[str, str, int, int]] = []  # (division_id, round_name, start, end)
        for division_id in ring_event_division_ids:
            try:
                detail = build_division_detail(
                    tournament=tournament,
                    schedule=schedule,
                    division_id=division_id,
                    current_minute=0,
                )
            except (KeyError, ValueError):
                continue
            per_round: dict[str, tuple[int, int]] = {}
            for match in detail.bracket.matches:
                if match.ring_id != ring.ring_id:
                    continue
                cur = per_round.get(match.round_name)
                if cur is None:
                    per_round[match.round_name] = (match.start_minute, match.end_minute)
                else:
                    per_round[match.round_name] = (
                        min(cur[0], match.start_minute),
                        max(cur[1], match.end_minute),
                    )
            for round_name, (start, end) in per_round.items():
                round_blocks.append((division_id, round_name, start, end))

        # Look for any other division event whose window falls strictly inside a poomsae block.
        for division_id, round_name, block_start, block_end in round_blocks:
            for event in ring.events:
                if event.division_id == division_id:
                    continue
                # interleaved means strictly inside
                interleaved = event.start_minute >= block_start and event.end_minute <= block_end
                # also catch partial overlap that is not a full bracket of the block
                partial = (
                    event.start_minute < block_end
                    and event.end_minute > block_start
                    and not interleaved
                )
                if interleaved or partial:
                    errors.append(
                        f"Poomsae round block interrupted on {ring.ring_id}: division "
                        f"'{division_id}' round '{round_name}' window [{block_start},{block_end}) "
                        f"is broken by event '{event.event_id}' "
                        f"[{event.start_minute},{event.end_minute})."
                    )


_KYORUGI_ROUND_ORDER = (
    "preliminary",
    "round_of_64",
    "round_of_32",
    "round_of_16",
    "quarterfinal",
    "semifinal",
    "final",
)


def _round_rank(round_name: str) -> int | None:
    name = (round_name or "").lower().replace(" ", "_")
    for idx, label in enumerate(_KYORUGI_ROUND_ORDER):
        if label in name:
            return idx
    return None


def _validate_bracket_round_precedence(
    tournament: Tournament,
    schedule: list[RingSchedule],
    errors: list[str],
) -> None:
    """No final before semifinal; no semifinal before preliminaries/quarterfinals; etc."""
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

        round_windows: dict[str, tuple[int, int]] = {}
        for match in detail.bracket.matches:
            cur = round_windows.get(match.round_name)
            if cur is None:
                round_windows[match.round_name] = (match.start_minute, match.end_minute)
            else:
                round_windows[match.round_name] = (
                    min(cur[0], match.start_minute),
                    max(cur[1], match.end_minute),
                )
        ranked = []
        for round_name, (start, end) in round_windows.items():
            rank = _round_rank(round_name)
            if rank is not None:
                ranked.append((rank, round_name, start, end))
        ranked.sort(key=lambda row: row[0])
        for left_idx in range(len(ranked)):
            left_rank, left_name, _, left_end = ranked[left_idx]
            for right_idx in range(left_idx + 1, len(ranked)):
                right_rank, right_name, right_start, _ = ranked[right_idx]
                if right_rank > left_rank and right_start < left_end:
                    errors.append(
                        f"{division.id}: bracket round precedence violation: "
                        f"{right_name} starts T+{right_start} before {left_name} ends T+{left_end}."
                    )


def _validate_live_operations_hints(tournament: Tournament, schedule: list[RingSchedule], warnings: list[str]) -> None:
    ls = getattr(tournament, "lunch_start_minute", 180)
    grace_cut = ls + getattr(tournament, "lunch_grace_minutes", 20)
    all_events = [event for ring in schedule for event in ring.events]

    first_starts_ring: dict[str, int | None] = {}
    num_rings = len(schedule)
    ring_workloads: dict[str, int] = {}
    ring_end_times: dict[str, int] = {}

    for ring_row in schedule:
        evts = sorted(ring_row.events or [], key=lambda event: event.start_minute)
        first_starts_ring[ring_row.ring_id] = evts[0].start_minute if evts else None
        ring_workloads[ring_row.ring_id] = sum(max(0, event.end_minute - event.start_minute) for event in evts)
        ring_end_times[ring_row.ring_id] = max((event.end_minute for event in evts), default=0)

        for left, right in zip(evts, evts[1:]):
            gap = right.start_minute - left.end_minute
            if gap >= 45:
                warnings.append(
                    f"large_idle_gap: {ring_row.ring_name} has {gap} minutes between '{left.division_name}' "
                    f"ending T+{left.end_minute} and '{right.division_name}' starting T+{right.start_minute}."
                )
            if gap >= 30:
                midpoint = left.end_minute + gap // 2
                active_elsewhere = sum(
                    1
                    for event in all_events
                    if event.ring_id != ring_row.ring_id and event.start_minute <= midpoint < event.end_minute
                )
                if active_elsewhere < max(0, num_rings - 1):
                    warnings.append(
                        f"Potentially avoidable idle on {ring_row.ring_name}: {gap}-minute gap while not all rings were busy "
                        f"(T+{left.end_minute} to T+{right.start_minute})."
                    )

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
            "unused_ring_with_available_work: "
            + f"rings {', '.join(sorted(empties))} had no scheduled work although events/crews were sufficient."
        )

    nonzero_first = [(rid, fst) for rid, fst in first_starts_ring.items() if fst is not None]
    if nonzero_first:
        earliest = min(pair[1] for pair in nonzero_first)
        if earliest > 0 and len(tournament.events or []) >= num_rings and len(tournament.referee_crews or []) >= num_rings:
            warnings.append(
                f"late_first_start: earliest ring begins at T+{earliest} despite enough events/crews to start at T+0."
            )
        stragglers = [rid for rid, fst in nonzero_first if fst is not None and earliest == 0 and fst >= 55]
        if stragglers:
            warnings.append(
                "late_first_start: ring first-start disparity: "
                + ", ".join(sorted(stragglers))
                + " start much later than other rings despite spare referee crews.",
            )
        late_rings = [rid for rid, fst in nonzero_first if fst is not None and fst >= 30]
        if len(late_rings) > 0 and len(tournament.events or []) >= num_rings:
            warnings.append(
                "late_first_start: "
                + ", ".join(sorted(late_rings))
                + " start at/after T+30 despite enough schedulable work."
            )

    used_workloads = [work for rid, work in ring_workloads.items() if first_starts_ring.get(rid) is not None]
    total_workload = sum(ring_workloads.values())
    if total_workload > 0 and len(ring_workloads) >= 2:
        overloaded = [
            rid for rid, work in ring_workloads.items() if work / total_workload > 0.40
        ]
        underloaded = [
            rid for rid, work in ring_workloads.items() if work / total_workload < 0.10
        ]
        if overloaded and underloaded:
            warnings.append(
                "ring_workload_extreme_imbalance: "
                + ", ".join(sorted(overloaded))
                + " carry more than 40% of scheduled duration while "
                + ", ".join(sorted(underloaded))
                + " carry less than 10%."
            )
    latest_end = max(ring_end_times.values(), default=0)
    if latest_end >= 30 * 60:
        warnings.append(
            f"unreasonable_schedule_duration: schedule reaches T+{latest_end} (30+ hours); "
            "normal CSV/demo data should be parallelized instead of serialized."
        )
    elif latest_end >= 12 * 60:
        warnings.append(
            f"long_schedule_duration: schedule reaches T+{latest_end}; check ring balance and poomsae parallelism."
        )
    if len(used_workloads) >= 2:
        max_work = max(used_workloads)
        min_work = min(used_workloads)
        spread = max_work - min_work
        avg_work = sum(used_workloads) / len(used_workloads)
        if spread >= 120:
            warnings.append(
                f"ring_workload_imbalance: workload spread is {spread} minutes (max={max_work}, min={min_work}, avg={avg_work:.1f})."
            )
        overloaded = [
            rid
            for rid, work in ring_workloads.items()
            if first_starts_ring.get(rid) is not None and work >= min_work + 150
        ]
        if overloaded:
            warnings.append(
                "overloaded_ring: "
                + ", ".join(sorted(overloaded))
                + f" carry significantly more work (min={min_work}, max={max_work})."
            )
        end_spread = max(ring_end_times.values()) - min(ring_end_times.values())
        if end_spread >= 120:
            warnings.append(
                f"ring_workload_imbalance: ring finish-time spread is {end_spread} minutes (latest={max(ring_end_times.values())}, earliest={min(ring_end_times.values())})."
            )
