from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ortools.sat.python import cp_model

from .models import ChangedEvent, RingSchedule, ScheduledEvent, Tournament, TournamentEvent
from .schedule_ops import assign_referees_to_schedule
from .validation import sort_schedule, validate_schedule_hard_constraints

EmergencyType = Literal["medical_delay", "ring_pause", "referee_shortage", "coach_conflict"]


class RescheduleError(RuntimeError):
    """Raised when emergency rescheduling cannot produce a feasible result."""


def _source_event_id(event: ScheduledEvent) -> str:
    return event.source_event_id or event.event_id


@dataclass(frozen=True)
class EmergencyConfig:
    emergency_type: EmergencyType
    current_minute: int
    ring_id: str | None = None
    referee_crew_id: str | None = None
    coach_id: str | None = None
    delay_minutes: int = 20
    pause_start_minute: int = 60
    pause_duration_minutes: int = 20
    unavailable_start_minute: int = 60
    unavailable_duration_minutes: int = 20


@dataclass(frozen=True)
class _FutureEventVars:
    start: cp_model.IntVar
    end: cp_model.IntVar
    duration: int
    interval: cp_model.IntervalVar
    ring_is_assigned: dict[int, cp_model.BoolVar]
    crew_is_assigned: dict[int, cp_model.BoolVar]
    ring_interval: dict[int, cp_model.IntervalVar]
    crew_interval: dict[int, cp_model.IntervalVar]


def reoptimize_future_events(
    tournament: Tournament,
    original_schedule: list[RingSchedule],
    config: EmergencyConfig,
    solver_time_limit_seconds: float = 5.0,
) -> tuple[list[RingSchedule], list[ChangedEvent]]:
    if config.current_minute < 0:
        raise RescheduleError("current_minute must be >= 0.")

    all_original_events = [event for ring in original_schedule for event in ring.events]
    original_by_event_id = {event.event_id: event for event in all_original_events}
    if len(original_by_event_id) != len(all_original_events):
        raise RescheduleError("Original schedule contains duplicate event_id values.")

    frozen_events = [event for event in all_original_events if event.end_minute <= config.current_minute]
    frozen_events += [
        event
        for event in all_original_events
        if event.start_minute <= config.current_minute < event.end_minute and event not in frozen_events
    ]
    future_events = [event for event in all_original_events if event.start_minute > config.current_minute]
    _validate_frozen_events_against_emergency(frozen_events=frozen_events, config=config)

    if not future_events:
        return _clone_schedule(original_schedule), []

    tournament_event_by_id = {event.event_id: event for event in tournament.events}
    for scheduled in future_events:
        if _source_event_id(scheduled) not in tournament_event_by_id:
            raise RescheduleError(f"Missing tournament event payload for '{scheduled.event_id}'.")

    local_result = _try_local_repair(
        tournament=tournament,
        original_schedule=original_schedule,
        all_original_events=all_original_events,
        original_by_event_id=original_by_event_id,
        config=config,
    )
    if local_result is not None:
        return local_result

    model = cp_model.CpModel()
    ring_index = {ring.id: idx for idx, ring in enumerate(tournament.rings)}
    crew_index = {crew.id: idx for idx, crew in enumerate(tournament.referee_crews)}
    ring_by_idx = {idx: ring for idx, ring in enumerate(tournament.rings)}
    crew_by_idx = {idx: crew for idx, crew in enumerate(tournament.referee_crews)}

    max_original_end = max(event.end_minute for event in all_original_events)
    extra_horizon = sum(event.end_minute - event.start_minute for event in future_events) + 180
    horizon = max(max_original_end + extra_horizon, config.current_minute + 1)
    num_rings = len(tournament.rings)
    num_crews = len(tournament.referee_crews)

    future_vars: dict[str, _FutureEventVars] = {}
    for scheduled in future_events:
        event_payload = tournament_event_by_id[_source_event_id(scheduled)]
        duration = scheduled.end_minute - scheduled.start_minute
        start = model.NewIntVar(config.current_minute + 1, horizon, f"start_{scheduled.event_id}")
        end = model.NewIntVar(config.current_minute + 1, horizon, f"end_{scheduled.event_id}")
        model.Add(end == start + duration)
        interval = model.NewIntervalVar(start, duration, end, f"interval_{scheduled.event_id}")

        ring_is_assigned: dict[int, cp_model.BoolVar] = {}
        ring_interval: dict[int, cp_model.IntervalVar] = {}
        for idx in range(num_rings):
            b = model.NewBoolVar(f"{scheduled.event_id}_ring_{idx}")
            ring_is_assigned[idx] = b
            ring_interval[idx] = model.NewOptionalIntervalVar(start, duration, end, b, f"ri_{scheduled.event_id}_{idx}")
        model.AddExactlyOne(ring_is_assigned.values())

        crew_is_assigned: dict[int, cp_model.BoolVar] = {}
        crew_interval: dict[int, cp_model.IntervalVar] = {}
        for idx in range(num_crews):
            b = model.NewBoolVar(f"{scheduled.event_id}_crew_{idx}")
            crew_is_assigned[idx] = b
            crew_interval[idx] = model.NewOptionalIntervalVar(start, duration, end, b, f"ci_{scheduled.event_id}_{idx}")
        model.AddExactlyOne(crew_is_assigned.values())

        future_vars[scheduled.event_id] = _FutureEventVars(
            start=start,
            end=end,
            duration=duration,
            interval=interval,
            ring_is_assigned=ring_is_assigned,
            crew_is_assigned=crew_is_assigned,
            ring_interval=ring_interval,
            crew_interval=crew_interval,
        )

    # No overlaps among future events for shared resources.
    for ring_idx in range(num_rings):
        model.AddNoOverlap([future_vars[event.event_id].ring_interval[ring_idx] for event in future_events])
    for crew_idx in range(num_crews):
        model.AddNoOverlap([future_vars[event.event_id].crew_interval[crew_idx] for event in future_events])

    for left_idx in range(len(future_events)):
        left = future_events[left_idx]
        left_athletes = set(left.athlete_ids)
        left_coaches = set(left.required_coach_ids) if left.event_type == "kyorugi" else set()
        for right_idx in range(left_idx + 1, len(future_events)):
            right = future_events[right_idx]
            right_coaches = set(right.required_coach_ids) if right.event_type == "kyorugi" else set()
            if left_athletes.intersection(right.athlete_ids) or left_coaches.intersection(right_coaches):
                model.AddNoOverlap([future_vars[left.event_id].interval, future_vars[right.event_id].interval])

    # Frozen events act as fixed blockers.
    for frozen in frozen_events:
        for future in future_events:
            vars_for_future = future_vars[future.event_id]

            # Same ring
            frozen_ring_idx = ring_index[frozen.ring_id]
            model.Add(vars_for_future.start >= frozen.end_minute).OnlyEnforceIf(vars_for_future.ring_is_assigned[frozen_ring_idx])

            # Same referee crew
            frozen_crew_idx = crew_index[frozen.referee_crew_id]
            model.Add(vars_for_future.start >= frozen.end_minute).OnlyEnforceIf(vars_for_future.crew_is_assigned[frozen_crew_idx])

            # Shared athlete/coach with frozen event
            shares_athlete = bool(set(frozen.athlete_ids).intersection(future.athlete_ids))
            shares_coach = (
                frozen.event_type == "kyorugi"
                and future.event_type == "kyorugi"
                and bool(set(frozen.required_coach_ids).intersection(future.required_coach_ids))
            )
            if shares_athlete or shares_coach:
                model.Add(vars_for_future.start >= frozen.end_minute)

    _apply_match_precedence_constraints(
        model=model,
        frozen_events=frozen_events,
        future_events=future_events,
        future_vars=future_vars,
    )

    _apply_emergency_constraints(
        model=model,
        config=config,
        future_events=future_events,
        future_vars=future_vars,
        tournament_event_by_id=tournament_event_by_id,
        ring_index=ring_index,
        crew_index=crew_index,
    )

    poomsae_types = {"poomsae", "pair_poomsae", "team_poomsae"}
    future_kyorugi_events = [
        event for event in future_events if tournament_event_by_id[_source_event_id(event)].event_type == "kyorugi"
    ]
    future_poomsae_events = [
        event for event in future_events if tournament_event_by_id[_source_event_id(event)].event_type in poomsae_types
    ]
    for k_event in future_kyorugi_events:
        k_vars = future_vars[k_event.event_id]
        for p_event in future_poomsae_events:
            p_vars = future_vars[p_event.event_id]
            for ring_idx in range(num_rings):
                model.Add(k_vars.start >= p_vars.end).OnlyEnforceIf(
                    [k_vars.ring_is_assigned[ring_idx], p_vars.ring_is_assigned[ring_idx]]
                )

    # Objective with change penalties.
    makespan = model.NewIntVar(0, horizon, "reschedule_makespan")
    model.AddMaxEquality(makespan, [future_vars[event.event_id].end for event in future_events] + [model.NewConstant(0)])
    makespan_extension = model.NewIntVar(0, horizon, "reschedule_makespan_extension")
    model.Add(makespan_extension >= makespan - max_original_end)
    model.Add(makespan_extension >= 0)

    ring_change_terms: list[cp_model.BoolVar] = []
    crew_change_terms: list[cp_model.BoolVar] = []
    start_changed_terms: list[cp_model.BoolVar] = []
    start_shift_terms: list[cp_model.IntVar] = []
    shortage_overlap_terms: list[cp_model.IntVar] = []

    for event in future_events:
        vars_for_event = future_vars[event.event_id]
        original_ring_idx = ring_index[event.ring_id]
        original_crew_idx = crew_index[event.referee_crew_id]

        same_ring = vars_for_event.ring_is_assigned[original_ring_idx]
        ring_changed = model.NewBoolVar(f"{event.event_id}_ring_changed")
        model.Add(ring_changed + same_ring == 1)
        ring_change_terms.append(ring_changed)

        same_crew = vars_for_event.crew_is_assigned[original_crew_idx]
        crew_changed = model.NewBoolVar(f"{event.event_id}_crew_changed")
        model.Add(crew_changed + same_crew == 1)
        crew_change_terms.append(crew_changed)

        shift = model.NewIntVar(0, horizon, f"{event.event_id}_start_shift")
        model.AddAbsEquality(shift, vars_for_event.start - event.start_minute)
        start_shift_terms.append(shift)
        start_changed = model.NewBoolVar(f"{event.event_id}_start_changed")
        model.Add(shift == 0).OnlyEnforceIf(start_changed.Not())
        model.Add(shift >= 1).OnlyEnforceIf(start_changed)
        start_changed_terms.append(start_changed)

        if config.emergency_type == "referee_shortage":
            payload = tournament_event_by_id[_source_event_id(event)]
            overlap = _add_window_overlap_indicator(
                model=model,
                start=vars_for_event.start,
                end=vars_for_event.end,
                window_start=config.unavailable_start_minute,
                window_end=config.unavailable_start_minute + max(1, config.unavailable_duration_minutes),
                name=f"{event.event_id}_shortage_window_overlap",
            )
            weighted_overlap = model.NewIntVar(0, horizon, f"{event.event_id}_shortage_ref_weight")
            model.Add(weighted_overlap == overlap * payload.required_referee_count)
            shortage_overlap_terms.append(weighted_overlap)

        # Small hint to preserve original schedule.
        model.AddHint(vars_for_event.start, event.start_minute)
        model.AddHint(vars_for_event.end, event.end_minute)
        for idx in range(num_rings):
            model.AddHint(vars_for_event.ring_is_assigned[idx], 1 if idx == original_ring_idx else 0)
        for idx in range(num_crews):
            model.AddHint(vars_for_event.crew_is_assigned[idx], 1 if idx == original_crew_idx else 0)

    changed_event_weight = 400_000_000
    ring_change_weight = 150_000_000
    crew_change_weight = 120_000_000 if config.emergency_type == "referee_shortage" else 90_000_000
    start_shift_weight = 700_000 if config.emergency_type in {"medical_delay", "ring_pause"} else 500_000

    model.Minimize(
        sum(start_changed_terms) * changed_event_weight
        + sum(crew_change_terms) * crew_change_weight
        + sum(ring_change_terms) * ring_change_weight
        + sum(start_shift_terms) * start_shift_weight
        + sum(shortage_overlap_terms) * 20_000
        + makespan_extension * 2_000_000
        + makespan
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = solver_time_limit_seconds
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RescheduleError("No feasible emergency reschedule found for this disruption.")

    # Build final schedule = frozen unchanged + new future assignments.
    rescheduled_events: list[ScheduledEvent] = []
    for frozen in frozen_events:
        rescheduled_events.append(frozen)

    for original in future_events:
        payload = tournament_event_by_id[_source_event_id(original)]
        vars_for_event = future_vars[original.event_id]
        chosen_ring_idx = next(idx for idx in range(num_rings) if solver.Value(vars_for_event.ring_is_assigned[idx]) == 1)
        chosen_crew_idx = next(idx for idx in range(num_crews) if solver.Value(vars_for_event.crew_is_assigned[idx]) == 1)
        ring = ring_by_idx[chosen_ring_idx]
        crew = crew_by_idx[chosen_crew_idx]

        rescheduled_events.append(
            ScheduledEvent(
                event_id=original.event_id,
                source_event_id=original.source_event_id or payload.event_id,
                division_id=payload.division_id,
                division_name=original.division_name,
                event_type=payload.event_type,
                age_group=payload.age_group,
                belt_rank_group=payload.belt_rank_group,
                weight_class=payload.weight_class,
                match_id=original.match_id,
                match_number=original.match_number,
                round_name=original.round_name,
                bracket_position=original.bracket_position,
                feeder_1_match_id=original.feeder_1_match_id,
                feeder_2_match_id=original.feeder_2_match_id,
                ring_id=ring.id,
                ring_name=ring.name,
                referee_crew_id=crew.id,
                referee_crew_name=crew.name,
                start_minute=solver.Value(vars_for_event.start),
                end_minute=solver.Value(vars_for_event.end),
                estimated_duration_minutes=original.estimated_duration_minutes,
                buffer_minutes=original.buffer_minutes,
                athlete_ids=original.athlete_ids,
                team_ids=original.team_ids,
                required_coach_ids=original.required_coach_ids,
                required_referee_count=original.required_referee_count,
                status="scheduled",
            )
        )

    rescheduled_schedule = _group_events_by_ring(tournament, rescheduled_events)
    if tournament.referees:
        rescheduled_schedule = assign_referees_to_schedule(tournament, rescheduled_schedule)
    changed_events = _collect_changes(original_by_event_id, rescheduled_events)
    return rescheduled_schedule, changed_events


def _try_local_repair(
    *,
    tournament: Tournament,
    original_schedule: list[RingSchedule],
    all_original_events: list[ScheduledEvent],
    original_by_event_id: dict[str, ScheduledEvent],
    config: EmergencyConfig,
) -> tuple[list[RingSchedule], list[ChangedEvent]] | None:
    if config.emergency_type in {"medical_delay", "ring_pause"}:
        ring_id = config.ring_id
        if not ring_id:
            raise RescheduleError(f"{config.emergency_type} requires a valid ring_id.")
        delay = max(1, config.delay_minutes if config.emergency_type == "medical_delay" else config.pause_duration_minutes)
        from_minute = config.current_minute if config.emergency_type == "medical_delay" else config.pause_start_minute
        return local_shift_ring_queue(
            tournament=tournament,
            original_schedule=original_schedule,
            original_by_event_id=original_by_event_id,
            ring_id=ring_id,
            from_minute=from_minute,
            delay_minutes=delay,
            reason=config.emergency_type,
        )

    if config.emergency_type == "referee_shortage":
        borrowed = local_referee_borrow(
            tournament=tournament,
            original_schedule=original_schedule,
            original_by_event_id=original_by_event_id,
            config=config,
        )
        if borrowed is not None:
            return borrowed
        impacted = _first_event_overlapping_referee_shortage(all_original_events, config)
        if impacted is None:
            return _clone_schedule(original_schedule), []
        return local_shift_ring_queue(
            tournament=tournament,
            original_schedule=original_schedule,
            original_by_event_id=original_by_event_id,
            ring_id=impacted.ring_id,
            from_minute=impacted.start_minute,
            delay_minutes=max(1, config.unavailable_duration_minutes),
            reason="referee_shortage_local_delay",
        )

    if config.emergency_type == "coach_conflict":
        swapped = local_swap_same_division_round(
            tournament=tournament,
            original_schedule=original_schedule,
            original_by_event_id=original_by_event_id,
            config=config,
        )
        if swapped is not None:
            return swapped
        impacted = _first_event_overlapping_coach_delay(all_original_events, config)
        if impacted is None:
            return _clone_schedule(original_schedule), []
        delay_until = config.unavailable_start_minute + max(1, config.unavailable_duration_minutes)
        delay = max(1, delay_until - impacted.start_minute)
        return local_shift_ring_queue(
            tournament=tournament,
            original_schedule=original_schedule,
            original_by_event_id=original_by_event_id,
            ring_id=impacted.ring_id,
            from_minute=impacted.start_minute,
            delay_minutes=delay,
            reason="coach_conflict_local_wait",
        )

    return None


def local_shift_ring_queue(
    *,
    tournament: Tournament,
    original_schedule: list[RingSchedule],
    original_by_event_id: dict[str, ScheduledEvent],
    ring_id: str,
    from_minute: int,
    delay_minutes: int,
    reason: str,
) -> tuple[list[RingSchedule], list[ChangedEvent]]:
    events = _clone_events_by_id(original_schedule)
    changed_ids: set[str] = set()
    _shift_queue_on_ring(
        events=events,
        original_by_event_id=original_by_event_id,
        ring_id=ring_id,
        from_minute=from_minute,
        delta=max(1, delay_minutes),
        changed_ids=changed_ids,
    )
    _stabilize_local_schedule(
        tournament=tournament,
        events=events,
        original_by_event_id=original_by_event_id,
        changed_ids=changed_ids,
    )
    return _finalize_local_result(
        tournament=tournament,
        events=events,
        original_schedule=original_schedule,
        original_by_event_id=original_by_event_id,
        changed_ids=changed_ids,
        reason=reason,
    )


def local_referee_borrow(
    *,
    tournament: Tournament,
    original_schedule: list[RingSchedule],
    original_by_event_id: dict[str, ScheduledEvent],
    config: EmergencyConfig,
) -> tuple[list[RingSchedule], list[ChangedEvent]] | None:
    if not config.referee_crew_id:
        raise RescheduleError("referee_shortage requires a valid referee_crew_id.")
    impacted = _first_event_overlapping_referee_shortage(
        [event for ring in original_schedule for event in ring.events],
        config,
    )
    if impacted is None:
        return _clone_schedule(original_schedule), []
    if len(tournament.referee_crews) <= 1 and not tournament.referees:
        return None
    # Individual referee borrowing is handled later by schedule hydration. Preserve
    # the published Gantt when there is another crew or referee pool available.
    return _clone_schedule(original_schedule), []


def local_swap_same_division_round(
    *,
    tournament: Tournament,
    original_schedule: list[RingSchedule],
    original_by_event_id: dict[str, ScheduledEvent],
    config: EmergencyConfig,
) -> tuple[list[RingSchedule], list[ChangedEvent]] | None:
    if not config.coach_id:
        raise RescheduleError("coach_conflict requires coach_id.")
    events = _clone_events_by_id(original_schedule)
    impacted = _first_event_overlapping_coach_delay(list(events.values()), config)
    if impacted is None:
        return _clone_schedule(original_schedule), []
    impacted_current = events[impacted.event_id]
    same_round = sorted(
        [
            event
            for event in events.values()
            if event.event_id != impacted.event_id
            and event.division_id == impacted.division_id
            and event.round_name == impacted.round_name
            and event.start_minute >= impacted.start_minute
            and (not event.required_coach_ids or config.coach_id not in event.required_coach_ids)
        ],
        key=lambda event: (event.start_minute, event.end_minute, event.event_id),
    )
    if not same_round:
        return None
    candidate = same_round[0]
    ignored = {impacted.event_id, candidate.event_id}
    if not _event_can_occupy_slot(
        events=events,
        event=candidate,
        start=impacted_current.start_minute,
        end=impacted_current.start_minute + _duration(candidate),
        ignored_event_ids=ignored,
    ):
        return None
    delayed_start = max(candidate.start_minute, config.unavailable_start_minute + max(1, config.unavailable_duration_minutes))
    if not _event_can_occupy_slot(
        events=events,
        event=impacted_current,
        start=delayed_start,
        end=delayed_start + _duration(impacted_current),
        ignored_event_ids=ignored,
    ):
        return None

    changed_ids = {impacted.event_id, candidate.event_id}
    _move_event(events[candidate.event_id], impacted_current.start_minute, candidate.ring_id, candidate.ring_name)
    _move_event(events[impacted.event_id], delayed_start, impacted_current.ring_id, impacted_current.ring_name)
    _stabilize_local_schedule(
        tournament=tournament,
        events=events,
        original_by_event_id=original_by_event_id,
        changed_ids=changed_ids,
    )
    return _finalize_local_result(
        tournament=tournament,
        events=events,
        original_schedule=original_schedule,
        original_by_event_id=original_by_event_id,
        changed_ids=changed_ids,
        reason="coach_conflict_same_division_round_swap",
    )


def _clone_events_by_id(schedule: list[RingSchedule]) -> dict[str, ScheduledEvent]:
    return {
        event.event_id: ScheduledEvent(**event.model_dump())
        for ring in schedule
        for event in ring.events
    }


def _duration(event: ScheduledEvent) -> int:
    return max(1, event.end_minute - event.start_minute)


def _move_event(event: ScheduledEvent, new_start: int, ring_id: str | None = None, ring_name: str | None = None) -> None:
    duration = _duration(event)
    event.start_minute = new_start
    event.end_minute = new_start + duration
    if ring_id is not None:
        event.ring_id = ring_id
    if ring_name is not None:
        event.ring_name = ring_name


def _shift_queue_on_ring(
    *,
    events: dict[str, ScheduledEvent],
    original_by_event_id: dict[str, ScheduledEvent],
    ring_id: str,
    from_minute: int,
    delta: int,
    changed_ids: set[str],
) -> None:
    for event in sorted(events.values(), key=lambda row: (row.start_minute, row.end_minute, row.event_id)):
        original = original_by_event_id[event.event_id]
        if event.ring_id != ring_id:
            continue
        if event.start_minute < from_minute:
            continue
        _move_event(event, event.start_minute + delta)
        changed_ids.add(event.event_id)


def _stabilize_local_schedule(
    *,
    tournament: Tournament,
    events: dict[str, ScheduledEvent],
    original_by_event_id: dict[str, ScheduledEvent],
    changed_ids: set[str],
    max_passes: int = 500,
) -> None:
    for _ in range(max_passes):
        changed = False
        for ring_id in sorted({event.ring_id for event in events.values()}):
            ordered = sorted(
                [event for event in events.values() if event.ring_id == ring_id],
                key=lambda row: (row.start_minute, row.end_minute, row.event_id),
            )
            for left, right in zip(ordered, ordered[1:]):
                if left.end_minute > right.start_minute:
                    _shift_queue_on_ring(
                        events=events,
                        original_by_event_id=original_by_event_id,
                        ring_id=right.ring_id,
                        from_minute=right.start_minute,
                        delta=left.end_minute - right.start_minute,
                        changed_ids=changed_ids,
                    )
                    changed = True
                    break
            if changed:
                break
        if changed:
            continue

        precedence_shift = _first_precedence_shift(events)
        if precedence_shift:
            event, required_start = precedence_shift
            _shift_queue_on_ring(
                events=events,
                original_by_event_id=original_by_event_id,
                ring_id=event.ring_id,
                from_minute=event.start_minute,
                delta=required_start - event.start_minute,
                changed_ids=changed_ids,
            )
            continue

        resource_shift = _first_resource_shift(events, changed_ids)
        if resource_shift:
            event, required_start = resource_shift
            if _try_reassign_referee_crew(
                tournament=tournament,
                events=events,
                event=event,
                changed_ids=changed_ids,
            ):
                continue
            _shift_queue_on_ring(
                events=events,
                original_by_event_id=original_by_event_id,
                ring_id=event.ring_id,
                from_minute=event.start_minute,
                delta=required_start - event.start_minute,
                changed_ids=changed_ids,
            )
            continue
        return


def _first_precedence_shift(events: dict[str, ScheduledEvent]) -> tuple[ScheduledEvent, int] | None:
    by_match_id = {event.match_id: event for event in events.values() if event.match_id}
    for event in sorted(events.values(), key=lambda row: (row.start_minute, row.event_id)):
        required_start = event.start_minute
        for feeder_id in (event.feeder_1_match_id, event.feeder_2_match_id):
            feeder = by_match_id.get(feeder_id or "")
            if feeder:
                required_start = max(required_start, feeder.end_minute + 5)
        rank = _match_round_rank(event.round_name)
        if rank is not None:
            for prior in events.values():
                if prior.division_id != event.division_id or prior.event_id == event.event_id:
                    continue
                prior_rank = _match_round_rank(prior.round_name)
                if prior_rank is not None and prior_rank < rank:
                    required_start = max(required_start, prior.end_minute + 5)
        if required_start > event.start_minute:
            return event, required_start
    return None


def _first_resource_shift(
    events: dict[str, ScheduledEvent],
    changed_ids: set[str],
) -> tuple[ScheduledEvent, int] | None:
    ordered = sorted(events.values(), key=lambda row: (row.start_minute, row.end_minute, row.event_id))
    for idx, left in enumerate(ordered):
        for right in ordered[idx + 1 :]:
            if right.start_minute >= left.end_minute:
                break
            if not _events_share_hard_resource(left, right):
                continue
            if left.ring_id == right.ring_id:
                return right, left.end_minute
            if right.event_id in changed_ids:
                return right, left.end_minute
            if left.event_id in changed_ids:
                return left, right.end_minute
            return right, left.end_minute
    return None


def _events_share_hard_resource(left: ScheduledEvent, right: ScheduledEvent) -> bool:
    if left.ring_id == right.ring_id:
        return True
    if left.referee_crew_id == right.referee_crew_id:
        return True
    if set(left.athlete_ids).intersection(right.athlete_ids):
        return True
    if (
        left.event_type == "kyorugi"
        and right.event_type == "kyorugi"
        and set(left.required_coach_ids).intersection(right.required_coach_ids)
    ):
        return True
    if set(left.assigned_referee_ids).intersection(right.assigned_referee_ids):
        return True
    return False


def _try_reassign_referee_crew(
    *,
    tournament: Tournament,
    events: dict[str, ScheduledEvent],
    event: ScheduledEvent,
    changed_ids: set[str],
) -> bool:
    current = event.referee_crew_id
    crew_by_id = {crew.id: crew for crew in tournament.referee_crews}
    for crew in tournament.referee_crews:
        if crew.id == current:
            continue
        conflict = False
        for other in events.values():
            if other.event_id == event.event_id:
                continue
            if other.referee_crew_id != crew.id:
                continue
            if event.end_minute <= other.start_minute or other.end_minute <= event.start_minute:
                continue
            conflict = True
            break
        if conflict:
            continue
        event.referee_crew_id = crew.id
        event.referee_crew_name = crew.name
        event.assigned_referee_ids = []
        changed_ids.add(event.event_id)
        return True
    event.referee_crew_id = current
    event.referee_crew_name = crew_by_id[current].name if current in crew_by_id else event.referee_crew_name
    return False


def _event_can_occupy_slot(
    *,
    events: dict[str, ScheduledEvent],
    event: ScheduledEvent,
    start: int,
    end: int,
    ignored_event_ids: set[str],
) -> bool:
    trial = ScheduledEvent(**event.model_dump())
    _move_event(trial, start)
    for other in events.values():
        if other.event_id == event.event_id or other.event_id in ignored_event_ids:
            continue
        if end <= other.start_minute or other.end_minute <= start:
            continue
        if _events_share_hard_resource(trial, other):
            return False
    return True


def _finalize_local_result(
    *,
    tournament: Tournament,
    events: dict[str, ScheduledEvent],
    original_schedule: list[RingSchedule],
    original_by_event_id: dict[str, ScheduledEvent],
    changed_ids: set[str],
    reason: str,
) -> tuple[list[RingSchedule], list[ChangedEvent]] | None:
    repaired = _group_events_by_ring(tournament, list(events.values()))
    repaired = sort_schedule(repaired)
    validation = validate_schedule_hard_constraints(tournament, repaired)
    if not validation.valid:
        return None
    changed_events = _collect_changes(original_by_event_id, [event for ring in repaired for event in ring.events])
    changed_count = len(changed_events)
    future_count = sum(
        1 for event in original_by_event_id.values() if event.start_minute >= min((row.original_start_minute for row in changed_events), default=10**9)
    )
    if future_count and changed_count / future_count > 0.10 and reason in {"medical_delay", "ring_pause", "coach_conflict_local_wait", "referee_shortage_local_delay"}:
        # The local propagation became too broad; let the high-stability CP-SAT
        # fallback decide whether a smaller valid repair exists.
        return None
    return repaired, changed_events


def _first_event_overlapping_referee_shortage(
    events: list[ScheduledEvent],
    config: EmergencyConfig,
) -> ScheduledEvent | None:
    start = config.unavailable_start_minute
    end = start + max(1, config.unavailable_duration_minutes)
    candidates = [
        event
        for event in events
        if event.referee_crew_id == config.referee_crew_id
        and not (event.end_minute <= start or event.start_minute >= end)
    ]
    return min(candidates, key=lambda row: (row.start_minute, row.end_minute, row.event_id), default=None)


def _first_event_overlapping_coach_delay(
    events: list[ScheduledEvent],
    config: EmergencyConfig,
) -> ScheduledEvent | None:
    start = config.unavailable_start_minute
    end = start + max(1, config.unavailable_duration_minutes)
    candidates = [
        event
        for event in events
        if event.event_type == "kyorugi"
        and config.coach_id in event.required_coach_ids
        and not (event.end_minute <= start or event.start_minute >= end)
    ]
    return min(candidates, key=lambda row: (row.start_minute, row.end_minute, row.event_id), default=None)


def _apply_emergency_constraints(
    model: cp_model.CpModel,
    config: EmergencyConfig,
    future_events: list[ScheduledEvent],
    future_vars: dict[str, _FutureEventVars],
    tournament_event_by_id: dict[str, TournamentEvent],
    ring_index: dict[str, int],
    crew_index: dict[str, int],
) -> None:
    if config.emergency_type == "medical_delay":
        if not config.ring_id or config.ring_id not in ring_index:
            raise RescheduleError("medical_delay requires a valid ring_id.")
        ring_idx = ring_index[config.ring_id]
        threshold = config.current_minute + max(1, config.delay_minutes)
        for event in future_events:
            vars_for_event = future_vars[event.event_id]
            if event.ring_id == config.ring_id:
                model.Add(vars_for_event.start >= event.start_minute + max(1, config.delay_minutes))
            model.Add(vars_for_event.start >= threshold).OnlyEnforceIf(vars_for_event.ring_is_assigned[ring_idx])
        return

    if config.emergency_type == "ring_pause":
        if not config.ring_id or config.ring_id not in ring_index:
            raise RescheduleError("ring_pause requires a valid ring_id.")
        ring_idx = ring_index[config.ring_id]
        window_start = config.pause_start_minute
        window_end = config.pause_start_minute + max(1, config.pause_duration_minutes)
        for event in future_events:
            vars_for_event = future_vars[event.event_id]
            before_pause = model.NewBoolVar(f"{event.event_id}_before_pause")
            model.Add(vars_for_event.end <= window_start).OnlyEnforceIf(
                [vars_for_event.ring_is_assigned[ring_idx], before_pause]
            )
            model.Add(vars_for_event.start >= window_end).OnlyEnforceIf(
                [vars_for_event.ring_is_assigned[ring_idx], before_pause.Not()]
            )
        return

    if config.emergency_type == "referee_shortage":
        if not config.referee_crew_id or config.referee_crew_id not in crew_index:
            raise RescheduleError("referee_shortage requires a valid referee_crew_id.")
        crew_idx = crew_index[config.referee_crew_id]
        window_start = config.unavailable_start_minute
        window_end = config.unavailable_start_minute + max(1, config.unavailable_duration_minutes)
        for event in future_events:
            vars_for_event = future_vars[event.event_id]
            before_unavailable = model.NewBoolVar(f"{event.event_id}_before_crew_unavail")
            model.Add(vars_for_event.end <= window_start).OnlyEnforceIf(
                [vars_for_event.crew_is_assigned[crew_idx], before_unavailable]
            )
            model.Add(vars_for_event.start >= window_end).OnlyEnforceIf(
                [vars_for_event.crew_is_assigned[crew_idx], before_unavailable.Not()]
            )
        return

    if config.emergency_type == "coach_conflict":
        if not config.coach_id:
            raise RescheduleError("coach_conflict requires coach_id.")
        window_start = config.unavailable_start_minute
        window_end = config.unavailable_start_minute + max(1, config.unavailable_duration_minutes)
        for event in future_events:
            payload = tournament_event_by_id[_source_event_id(event)]
            if config.coach_id not in payload.required_coach_ids:
                continue
            vars_for_event = future_vars[event.event_id]
            before_unavailable = model.NewBoolVar(f"{event.event_id}_before_coach_unavail")
            model.Add(vars_for_event.end <= window_start).OnlyEnforceIf(before_unavailable)
            model.Add(vars_for_event.start >= window_end).OnlyEnforceIf(before_unavailable.Not())
        return

    raise RescheduleError(f"Unsupported emergency_type '{config.emergency_type}'.")


def _match_round_rank(round_name: str | None) -> int | None:
    normalized = (round_name or "").lower().replace(" ", "_")
    order = ["round_of_16", "quarterfinal", "semifinal", "final"]
    for idx, label in enumerate(order):
        if label in normalized:
            return idx
    return None


def _apply_match_precedence_constraints(
    *,
    model: cp_model.CpModel,
    frozen_events: list[ScheduledEvent],
    future_events: list[ScheduledEvent],
    future_vars: dict[str, _FutureEventVars],
) -> None:
    all_events = [*frozen_events, *future_events]
    event_by_match_id = {event.match_id: event for event in all_events if event.match_id}
    future_ids = {event.event_id for event in future_events}

    for event in future_events:
        vars_for_event = future_vars[event.event_id]
        for feeder_id in (event.feeder_1_match_id, event.feeder_2_match_id):
            feeder = event_by_match_id.get(feeder_id or "")
            if not feeder:
                continue
            if feeder.event_id in future_ids:
                model.Add(vars_for_event.start >= future_vars[feeder.event_id].end + 5)
            else:
                model.Add(vars_for_event.start >= feeder.end_minute + 5)

    for later in future_events:
        later_rank = _match_round_rank(later.round_name)
        if later_rank is None:
            continue
        later_vars = future_vars[later.event_id]
        for earlier in all_events:
            if earlier.division_id != later.division_id or earlier.event_id == later.event_id:
                continue
            earlier_rank = _match_round_rank(earlier.round_name)
            if earlier_rank is None or earlier_rank >= later_rank:
                continue
            if earlier.event_id in future_ids:
                model.Add(later_vars.start >= future_vars[earlier.event_id].end + 5)
            else:
                model.Add(later_vars.start >= earlier.end_minute + 5)


def _add_window_overlap_indicator(
    *,
    model: cp_model.CpModel,
    start: cp_model.IntVar,
    end: cp_model.IntVar,
    window_start: int,
    window_end: int,
    name: str,
) -> cp_model.IntVar:
    ends_before = model.NewBoolVar(f"{name}_ends_before")
    starts_after = model.NewBoolVar(f"{name}_starts_after")
    overlaps = model.NewBoolVar(name)

    model.Add(end <= window_start).OnlyEnforceIf(ends_before)
    model.Add(end > window_start).OnlyEnforceIf(ends_before.Not())
    model.Add(start >= window_end).OnlyEnforceIf(starts_after)
    model.Add(start < window_end).OnlyEnforceIf(starts_after.Not())
    model.AddBoolOr([ends_before, starts_after, overlaps])
    model.AddImplication(ends_before, overlaps.Not())
    model.AddImplication(starts_after, overlaps.Not())
    return overlaps


def _group_events_by_ring(tournament: Tournament, events: list[ScheduledEvent]) -> list[RingSchedule]:
    by_ring: dict[str, list[ScheduledEvent]] = {ring.id: [] for ring in tournament.rings}
    for event in events:
        by_ring[event.ring_id].append(event)
    return [
        RingSchedule(ring_id=ring.id, ring_name=ring.name, events=sorted(by_ring[ring.id], key=lambda item: item.start_minute))
        for ring in tournament.rings
    ]


def _collect_changes(original_by_event_id: dict[str, ScheduledEvent], updated_events: list[ScheduledEvent]) -> list[ChangedEvent]:
    changed: list[ChangedEvent] = []
    for updated in updated_events:
        original = original_by_event_id.get(updated.event_id)
        if not original:
            continue
        changes: list[str] = []
        if original.ring_id != updated.ring_id:
            changes.append("ring_changed")
        if original.referee_crew_id != updated.referee_crew_id:
            changes.append("referee_crew_changed")
        if original.start_minute != updated.start_minute:
            changes.append("start_time_changed")
        if not changes:
            continue
        changed.append(
            ChangedEvent(
                event_id=updated.event_id,
                changes=changes,
                original_ring_id=original.ring_id,
                new_ring_id=updated.ring_id,
                original_referee_crew_id=original.referee_crew_id,
                new_referee_crew_id=updated.referee_crew_id,
                original_start_minute=original.start_minute,
                new_start_minute=updated.start_minute,
            )
        )
    return sorted(changed, key=lambda item: item.event_id)


def _clone_schedule(schedule: list[RingSchedule]) -> list[RingSchedule]:
    return [
        RingSchedule(
            ring_id=ring.ring_id,
            ring_name=ring.ring_name,
            events=[ScheduledEvent(**event.model_dump()) for event in ring.events],
        )
        for ring in schedule
    ]


def _validate_frozen_events_against_emergency(frozen_events: list[ScheduledEvent], config: EmergencyConfig) -> None:
    """Fail fast when frozen events already violate the emergency window."""
    if config.emergency_type == "medical_delay":
        if not config.ring_id:
            raise RescheduleError("medical_delay requires a valid ring_id.")
        threshold = config.current_minute + max(1, config.delay_minutes)
        for event in frozen_events:
            if event.ring_id == config.ring_id and event.start_minute > config.current_minute and event.start_minute < threshold:
                raise RescheduleError("Frozen event conflicts with medical_delay window on selected ring.")
        return

    if config.emergency_type == "ring_pause":
        if not config.ring_id:
            raise RescheduleError("ring_pause requires a valid ring_id.")
        start = config.pause_start_minute
        end = config.pause_start_minute + max(1, config.pause_duration_minutes)
        for event in frozen_events:
            if event.ring_id != config.ring_id:
                continue
            overlaps = not (event.end_minute <= start or event.start_minute >= end)
            if overlaps:
                raise RescheduleError("Frozen event conflicts with requested ring_pause window.")
        return

    if config.emergency_type == "referee_shortage":
        if not config.referee_crew_id:
            raise RescheduleError("referee_shortage requires a valid referee_crew_id.")
        start = config.unavailable_start_minute
        end = config.unavailable_start_minute + max(1, config.unavailable_duration_minutes)
        for event in frozen_events:
            if event.referee_crew_id != config.referee_crew_id:
                continue
            overlaps = not (event.end_minute <= start or event.start_minute >= end)
            if overlaps:
                raise RescheduleError("Frozen event conflicts with referee_shortage window.")
        return

    if config.emergency_type == "coach_conflict":
        if not config.coach_id:
            raise RescheduleError("coach_conflict requires coach_id.")
        start = config.unavailable_start_minute
        end = config.unavailable_start_minute + max(1, config.unavailable_duration_minutes)
        for event in frozen_events:
            if config.coach_id not in event.required_coach_ids:
                continue
            overlaps = not (event.end_minute <= start or event.start_minute >= end)
            if overlaps:
                raise RescheduleError("Frozen event conflicts with coach_conflict window.")
        return

    raise RescheduleError(f"Unsupported emergency_type '{config.emergency_type}'.")
