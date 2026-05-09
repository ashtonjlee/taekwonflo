from __future__ import annotations

from dataclasses import dataclass

from ortools.sat.python import cp_model

from .models import RingSchedule, ScheduledEvent, Tournament


class ScheduleError(RuntimeError):
    """Raised when the scheduler cannot produce a feasible schedule."""


@dataclass(frozen=True)
class _EventVars:
    start: cp_model.IntVar
    end: cp_model.IntVar
    duration: int
    interval: cp_model.IntervalVar
    ring_is_assigned: dict[int, cp_model.BoolVar]
    crew_is_assigned: dict[int, cp_model.BoolVar]
    ring_interval: dict[int, cp_model.IntervalVar]
    crew_interval: dict[int, cp_model.IntervalVar]


def build_optimized_schedule(tournament: Tournament, solver_time_limit_seconds: float = 5.0) -> list[RingSchedule]:
    """
    Build a schedule using CP-SAT with minute-level integer time.

    Hard constraints:
    - every event assigned exactly one ring and one referee crew
    - no overlap on the same ring
    - no overlap for the same referee crew
    - no overlap for shared athletes
    - no overlap for shared required coaches
    - duration = estimated_duration_minutes + buffer_minutes

    Objective (weighted):
    - minimize makespan first
    - then reduce total ring idle time
    - then reduce imbalance across ring workloads
    """
    if not tournament.events:
        return [RingSchedule(ring_id=ring.id, ring_name=ring.name, events=[]) for ring in tournament.rings]
    if not tournament.rings:
        raise ScheduleError("No rings are available for scheduling.")
    if not tournament.referee_crews:
        raise ScheduleError("No referee crews are available for scheduling.")

    model = cp_model.CpModel()
    num_events = len(tournament.events)
    num_rings = len(tournament.rings)
    num_crews = len(tournament.referee_crews)

    durations = [event.estimated_duration_minutes + event.buffer_minutes for event in tournament.events]
    horizon = max(1, sum(durations))

    event_vars: dict[int, _EventVars] = {}

    # Variables and assignment choices per event.
    for event_idx, event in enumerate(tournament.events):
        duration = event.estimated_duration_minutes + event.buffer_minutes
        start = model.NewIntVar(0, horizon, f"start_e{event_idx}")
        end = model.NewIntVar(0, horizon, f"end_e{event_idx}")
        model.Add(end == start + duration)

        interval = model.NewIntervalVar(start, duration, end, f"interval_e{event_idx}")

        ring_is_assigned: dict[int, cp_model.BoolVar] = {}
        ring_interval: dict[int, cp_model.IntervalVar] = {}
        for ring_idx in range(num_rings):
            assigned = model.NewBoolVar(f"event_{event_idx}_uses_ring_{ring_idx}")
            ring_is_assigned[ring_idx] = assigned
            ring_interval[ring_idx] = model.NewOptionalIntervalVar(
                start, duration, end, assigned, f"ring_interval_e{event_idx}_r{ring_idx}"
            )
        model.AddExactlyOne(ring_is_assigned.values())

        crew_is_assigned: dict[int, cp_model.BoolVar] = {}
        crew_interval: dict[int, cp_model.IntervalVar] = {}
        for crew_idx in range(num_crews):
            assigned = model.NewBoolVar(f"event_{event_idx}_uses_crew_{crew_idx}")
            crew_is_assigned[crew_idx] = assigned
            crew_interval[crew_idx] = model.NewOptionalIntervalVar(
                start, duration, end, assigned, f"crew_interval_e{event_idx}_c{crew_idx}"
            )
        model.AddExactlyOne(crew_is_assigned.values())

        event_vars[event_idx] = _EventVars(
            start=start,
            end=end,
            duration=duration,
            interval=interval,
            ring_is_assigned=ring_is_assigned,
            crew_is_assigned=crew_is_assigned,
            ring_interval=ring_interval,
            crew_interval=crew_interval,
        )

    # Ring capacity: no overlapping events on same ring.
    for ring_idx in range(num_rings):
        model.AddNoOverlap([event_vars[event_idx].ring_interval[ring_idx] for event_idx in range(num_events)])

    # Referee crew capacity: no overlapping events on same crew.
    for crew_idx in range(num_crews):
        model.AddNoOverlap([event_vars[event_idx].crew_interval[crew_idx] for event_idx in range(num_events)])

    # Athlete and coach conflict constraints.
    for i in range(num_events):
        event_i = tournament.events[i]
        athletes_i = set(event_i.athlete_ids)
        coaches_i = set(event_i.required_coach_ids)
        for j in range(i + 1, num_events):
            event_j = tournament.events[j]
            share_athlete = bool(athletes_i.intersection(event_j.athlete_ids))
            share_coach = bool(coaches_i.intersection(event_j.required_coach_ids))
            if share_athlete or share_coach:
                model.AddNoOverlap([event_vars[i].interval, event_vars[j].interval])

    # Makespan.
    makespan = model.NewIntVar(0, horizon, "makespan")
    model.AddMaxEquality(makespan, [event_vars[event_idx].end for event_idx in range(num_events)])

    # Ring workload helpers.
    ring_workloads: list[cp_model.IntVar] = []
    total_duration_sum = sum(durations)
    ideal_per_ring = max(1, total_duration_sum // num_rings)

    for ring_idx in range(num_rings):
        workload = model.NewIntVar(0, horizon, f"workload_ring_{ring_idx}")
        model.Add(
            workload
            == sum(
                event_vars[event_idx].duration * event_vars[event_idx].ring_is_assigned[ring_idx]
                for event_idx in range(num_events)
            )
        )
        ring_workloads.append(workload)

    # Workload balance term (pairwise absolute differences).
    workload_pair_gaps: list[cp_model.IntVar] = []
    for left in range(num_rings):
        for right in range(left + 1, num_rings):
            gap = model.NewIntVar(0, horizon, f"workload_gap_{left}_{right}")
            model.AddAbsEquality(gap, ring_workloads[left] - ring_workloads[right])
            workload_pair_gaps.append(gap)
    workload_imbalance = model.NewIntVar(0, horizon * max(1, len(workload_pair_gaps)), "workload_imbalance")
    if workload_pair_gaps:
        model.Add(workload_imbalance == sum(workload_pair_gaps))
    else:
        model.Add(workload_imbalance == 0)

    # Idle-time proxy: minimizing total start minutes tends to reduce gaps/idle.
    total_starts = model.NewIntVar(0, horizon * num_events, "total_starts")
    model.Add(total_starts == sum(event_vars[event_idx].start for event_idx in range(num_events)))

    # Weighted objective: makespan dominates; then idle proxy; then workload balancing.
    model.Minimize(makespan * 1_000_000 + total_starts * 100 + workload_imbalance)

    # Provide a deterministic feasible hint: schedule everything sequentially on ring 0 / crew 0.
    hint_start = 0
    for event_idx in range(num_events):
        vars_for_event = event_vars[event_idx]
        model.AddHint(vars_for_event.start, hint_start)
        model.AddHint(vars_for_event.end, hint_start + vars_for_event.duration)
        for ring_idx in range(num_rings):
            model.AddHint(vars_for_event.ring_is_assigned[ring_idx], 1 if ring_idx == 0 else 0)
        for crew_idx in range(num_crews):
            model.AddHint(vars_for_event.crew_is_assigned[crew_idx], 1 if crew_idx == 0 else 0)
        hint_start += vars_for_event.duration

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = solver_time_limit_seconds
    solver.parameters.num_search_workers = 8

    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise ScheduleError(
            f"No feasible schedule found under current constraints (solver status: {solver.StatusName(status)})."
        )

    return _build_schedule_response(tournament, event_vars, solver)


def _build_schedule_response(
    tournament: Tournament,
    event_vars: dict[int, _EventVars],
    solver: cp_model.CpSolver,
) -> list[RingSchedule]:
    ring_by_idx = {idx: ring for idx, ring in enumerate(tournament.rings)}
    crew_by_idx = {idx: crew for idx, crew in enumerate(tournament.referee_crews)}
    events_by_ring: dict[str, list[ScheduledEvent]] = {ring.id: [] for ring in tournament.rings}

    for event_idx, event in enumerate(tournament.events):
        chosen_ring_idx = next(
            idx for idx in range(len(tournament.rings)) if solver.Value(event_vars[event_idx].ring_is_assigned[idx]) == 1
        )
        chosen_crew_idx = next(
            idx
            for idx in range(len(tournament.referee_crews))
            if solver.Value(event_vars[event_idx].crew_is_assigned[idx]) == 1
        )
        ring = ring_by_idx[chosen_ring_idx]
        crew = crew_by_idx[chosen_crew_idx]

        scheduled = ScheduledEvent(
            event_id=event.event_id,
            division_id=event.division_id,
            division_name=event.division_name,
            event_type=event.event_type,
            ring_id=ring.id,
            ring_name=ring.name,
            referee_crew_id=crew.id,
            referee_crew_name=crew.name,
            start_minute=solver.Value(event_vars[event_idx].start),
            end_minute=solver.Value(event_vars[event_idx].end),
            estimated_duration_minutes=event.estimated_duration_minutes,
            buffer_minutes=event.buffer_minutes,
            athlete_ids=event.athlete_ids,
            team_ids=event.team_ids,
            required_coach_ids=event.required_coach_ids,
            status="scheduled",
        )
        events_by_ring[ring.id].append(scheduled)

    schedules: list[RingSchedule] = []
    for ring in tournament.rings:
        ring_events = sorted(events_by_ring[ring.id], key=lambda item: item.start_minute)
        schedules.append(RingSchedule(ring_id=ring.id, ring_name=ring.name, events=ring_events))
    return schedules
