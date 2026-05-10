from __future__ import annotations

import math
from dataclasses import dataclass

from ortools.sat.python import cp_model

from .models import Division, RingSchedule, ScheduledEvent, Tournament, TournamentEvent
from .schedule_ops import assign_referees_to_schedule


class ScheduleError(RuntimeError):
    """Raised when the scheduler cannot produce a feasible schedule."""


POOMSAE_TYPES = {"poomsae", "pair_poomsae", "team_poomsae"}


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


@dataclass(frozen=True)
class _SchedulableUnit:
    unit_id: str
    source_event: TournamentEvent
    division: Division
    unit_type: str
    round_name: str | None
    bracket_position: int | None
    duration: int
    athlete_ids: tuple[str, ...]
    team_ids: tuple[str, ...]
    coach_ids: tuple[str, ...]
    required_referee_count: int
    predecessor_ids: tuple[str, ...] = ()
    rest_after_predecessor_minutes: int = 0
    feeder_1_match_id: str | None = None
    feeder_2_match_id: str | None = None


def _literal_lt(model: cp_model.CpModel, left: cp_model.IntVar, right: int, out: cp_model.BoolVar) -> None:
    model.Add(left <= right - 1).OnlyEnforceIf(out)
    model.Add(left >= right).OnlyEnforceIf(out.Not())


def _literal_ge(model: cp_model.CpModel, left: cp_model.IntVar, right: int, out: cp_model.BoolVar) -> None:
    model.Add(left >= right).OnlyEnforceIf(out)
    model.Add(left <= right - 1).OnlyEnforceIf(out.Not())


def _literal_gt(model: cp_model.CpModel, left: cp_model.IntVar, right: int, out: cp_model.BoolVar) -> None:
    model.Add(left >= right + 1).OnlyEnforceIf(out)
    model.Add(left <= right).OnlyEnforceIf(out.Not())


def _and_bool(model: cp_model.CpModel, a: cp_model.BoolVar, b: cp_model.BoolVar, out: cp_model.BoolVar) -> None:
    model.Add(out <= a)
    model.Add(out <= b)
    model.Add(out >= a + b - 1)


def _greedy_feasible_placements(tournament: Tournament, durations: list[int], horizon: int) -> dict[int, tuple[int, int, int]]:
    placements: dict[int, tuple[int, int, int]] = {}
    placed_blocks: list[tuple[int, int, int, int, int]] = []

    num_events = len(durations)
    num_rings = len(tournament.rings)
    num_crews = len(tournament.referee_crews)
    ring_workloads = [0 for _ in range(num_rings)]
    crew_workloads = [0 for _ in range(num_crews)]
    ring_first_start: list[int | None] = [None for _ in range(num_rings)]
    athlete_sets = [frozenset(event.athlete_ids) for event in tournament.events]
    coach_sets = [
        frozenset(event.required_coach_ids) if event.event_type == "kyorugi" else frozenset()
        for event in tournament.events
    ]

    order = sorted(
        range(num_events),
        key=lambda idx: (
            0 if tournament.events[idx].event_type in POOMSAE_TYPES else 1,
            -durations[idx],
            idx,
        ),
    )

    for ev_idx in order:
        evt = tournament.events[ev_idx]
        dur = durations[ev_idx]
        athlete_set = athlete_sets[ev_idx]
        coach_set = coach_sets[ev_idx]

        picks: list[tuple[tuple[int, int, int, int, int, int], int, int, int]] = []
        for ring_idx in range(num_rings):
            for crew_idx in range(num_crews):
                t_candidate = 0
                while True:
                    if t_candidate + dur > horizon:
                        t_candidate = -1
                        break
                    end_candidate = t_candidate + dur
                    bumped_to = t_candidate

                    for pst, pend, pr, pc, other_idx in placed_blocks:
                        overlap_time = end_candidate > pst and pend > t_candidate
                        if not overlap_time:
                            continue
                        blocker = ring_idx == pr or crew_idx == pc
                        if not blocker:
                            blocker = bool(athlete_set.intersection(athlete_sets[other_idx]))
                            blocker = blocker or bool(coach_set.intersection(coach_sets[other_idx]))
                        if blocker:
                            bumped_to = max(bumped_to, pend)

                    if evt.event_type == "kyorugi":
                        for pst, pend, pr, _, other_idx in placed_blocks:
                            if pr != ring_idx:
                                continue
                            if tournament.events[other_idx].event_type in POOMSAE_TYPES:
                                bumped_to = max(bumped_to, pend)

                    if bumped_to == t_candidate:
                        break
                    t_candidate = bumped_to

                if t_candidate < 0:
                    continue
                unused_ring_first_wave = (
                    ring_workloads[ring_idx] == 0 and len(placements) < min(num_events, num_rings)
                )
                first_wave_start_penalty = (
                    0
                    if ring_first_start[ring_idx] is None and t_candidate == 0
                    else (t_candidate if ring_first_start[ring_idx] is None else 0)
                )
                score = (
                    0 if unused_ring_first_wave else 1,
                    first_wave_start_penalty,
                    t_candidate,
                    ring_workloads[ring_idx],
                    crew_workloads[crew_idx],
                    ring_idx,
                    crew_idx,
                )
                picks.append((score, t_candidate, ring_idx, crew_idx))

        if not picks:
            raise ScheduleError(f"Greedy hint builder exhausted horizon {horizon} on event idx {ev_idx}")

        picks.sort(key=lambda item: item[0])
        _, t_pick, ring_pick, crew_pick = picks[0]
        placements[ev_idx] = (t_pick, ring_pick, crew_pick)
        placed_blocks.append((t_pick, t_pick + dur, ring_pick, crew_pick, ev_idx))
        placed_blocks.sort(key=lambda item: item[0])
        ring_workloads[ring_pick] += dur
        crew_workloads[crew_pick] += dur
        if ring_first_start[ring_pick] is None:
            ring_first_start[ring_pick] = t_pick

    return placements


def build_balanced_greedy_schedule(tournament: Tournament) -> list[RingSchedule]:
    if not tournament.events:
        return [RingSchedule(ring_id=ring.id, ring_name=ring.name, events=[]) for ring in tournament.rings]
    if not tournament.rings:
        raise ScheduleError("No rings are available for scheduling.")
    if not tournament.referee_crews:
        raise ScheduleError("No referee crews are available for scheduling.")

    return build_compact_greedy_schedule(tournament)


def build_compact_greedy_schedule(tournament: Tournament) -> list[RingSchedule]:
    """Deterministic list scheduler that never emits resource overlaps.

    This is the emergency fallback path for imports and solver timeouts. It keeps
    ring timelines compact, starts a first wave at T+0 where hard resources allow,
    and treats coaches as a waitable resource rather than a reason to move whole
    divisions.
    """
    if not tournament.events:
        return [RingSchedule(ring_id=ring.id, ring_name=ring.name, events=[]) for ring in tournament.rings]
    if not tournament.rings:
        raise ScheduleError("No rings are available for scheduling.")
    if not tournament.referee_crews:
        raise ScheduleError("No referee crews are available for scheduling.")

    units = _build_schedulable_units(tournament)
    placements = _compact_unit_hint(units, len(tournament.rings), len(tournament.referee_crews))
    if len(placements) != len(units):
        missing = len(units) - len(placements)
        raise ScheduleError(f"Compact fallback could not place {missing} schedulable unit(s).")
    return _build_schedule_from_unit_placements(tournament, units, placements)


def _compact_list_placements(
    tournament: Tournament,
    durations: list[int],
) -> dict[int, tuple[int, int, int]]:
    num_events = len(tournament.events)
    num_rings = len(tournament.rings)
    num_crews = len(tournament.referee_crews)
    if num_events == 0:
        return {}

    unscheduled = set(range(num_events))
    placements: dict[int, tuple[int, int, int]] = {}
    ring_available = [0 for _ in range(num_rings)]
    crew_available = [0 for _ in range(num_crews)]
    athlete_available: dict[str, int] = {}
    coach_available: dict[str, int] = {}
    ring_poomsae_end = [0 for _ in range(num_rings)]

    event_order = sorted(
        range(num_events),
        key=lambda idx: (
            0 if tournament.events[idx].event_type in POOMSAE_TYPES else 1,
            tournament.events[idx].division_name,
            idx,
        ),
    )

    def event_ready_time(event_idx: int, ring_idx: int, crew_idx: int, base_time: int) -> int:
        event = tournament.events[event_idx]
        ready = max(base_time, ring_available[ring_idx], crew_available[crew_idx])
        if event.event_type == "kyorugi":
            ready = max(ready, ring_poomsae_end[ring_idx])
        for athlete_id in event.athlete_ids:
            ready = max(ready, athlete_available.get(athlete_id, 0))
        if event.event_type == "kyorugi":
            for coach_id in event.required_coach_ids:
                coach_ready = coach_available.get(coach_id, 0)
                if coach_ready > ready:
                    ready = coach_ready
        return ready

    def best_pick_for_ring(ring_idx: int, *, base_time: int | None = None) -> tuple[int, int, int] | None:
        base = ring_available[ring_idx] if base_time is None else base_time
        picks: list[tuple[tuple[int, int, int, int], int, int, int]] = []
        for event_idx in event_order:
            if event_idx not in unscheduled:
                continue
            for crew_idx in range(num_crews):
                start = event_ready_time(event_idx, ring_idx, crew_idx, base)
                wait = max(0, start - base)
                event = tournament.events[event_idx]
                score = (
                    start,
                    wait,
                    0 if event.event_type in POOMSAE_TYPES else 1,
                    event_idx,
                )
                picks.append((score, event_idx, crew_idx, start))
        if not picks:
            return None
        picks.sort(key=lambda row: row[0])
        _, event_idx, crew_idx, start = picks[0]
        return event_idx, crew_idx, start

    def place(event_idx: int, ring_idx: int, crew_idx: int, start: int) -> None:
        event = tournament.events[event_idx]
        end = start + durations[event_idx]
        placements[event_idx] = (start, ring_idx, crew_idx)
        unscheduled.remove(event_idx)
        ring_available[ring_idx] = end
        crew_available[crew_idx] = end
        if event.event_type in POOMSAE_TYPES:
            ring_poomsae_end[ring_idx] = max(ring_poomsae_end[ring_idx], end)
        for athlete_id in event.athlete_ids:
            athlete_available[athlete_id] = end
        if event.event_type == "kyorugi":
            for coach_id in event.required_coach_ids:
                coach_available[coach_id] = end

    # First wave: occupy every ring at T+0 when there are enough independent units.
    first_wave_count = min(num_rings, num_events)
    for ring_idx in range(first_wave_count):
        pick = best_pick_for_ring(ring_idx, base_time=0)
        if pick is None:
            break
        event_idx, crew_idx, start = pick
        if start != 0:
            # No remaining unit is independently feasible at T+0 for this ring.
            continue
        place(event_idx, ring_idx, crew_idx, start)

    while unscheduled:
        ring_idx = min(range(num_rings), key=lambda idx: (ring_available[idx], idx))
        pick = best_pick_for_ring(ring_idx)
        if pick is None:
            raise ScheduleError("Compact fallback could not find a schedulable event.")
        event_idx, crew_idx, start = pick
        place(event_idx, ring_idx, crew_idx, start)

    return placements


def build_optimized_schedule(tournament: Tournament, solver_time_limit_seconds: float = 5.0) -> list[RingSchedule]:
    if not tournament.events:
        return [RingSchedule(ring_id=ring.id, ring_name=ring.name, events=[]) for ring in tournament.rings]
    if not tournament.rings:
        raise ScheduleError("No rings are available for scheduling.")
    if not tournament.referee_crews:
        raise ScheduleError("No referee crews are available for scheduling.")

    units = _build_schedulable_units(tournament)
    if not units:
        return [RingSchedule(ring_id=ring.id, ring_name=ring.name, events=[]) for ring in tournament.rings]

    num_units = len(units)
    num_rings = len(tournament.rings)
    num_crews = len(tournament.referee_crews)
    horizon = max(1, sum(unit.duration for unit in units) + tournament.lunch_duration_minutes + 180)

    model = cp_model.CpModel()
    unit_vars: dict[int, _EventVars] = {}

    for idx, unit in enumerate(units):
        start = model.NewIntVar(0, horizon, f"start_u{idx}")
        end = model.NewIntVar(0, horizon, f"end_u{idx}")
        model.Add(end == start + unit.duration)
        interval = model.NewIntervalVar(start, unit.duration, end, f"interval_u{idx}")

        ring_is: dict[int, cp_model.BoolVar] = {}
        ring_iv: dict[int, cp_model.IntervalVar] = {}
        for ring_idx in range(num_rings):
            flag = model.NewBoolVar(f"u{idx}_ring{ring_idx}")
            ring_is[ring_idx] = flag
            ring_iv[ring_idx] = model.NewOptionalIntervalVar(start, unit.duration, end, flag, f"ri_u{idx}_r{ring_idx}")
        model.AddExactlyOne(ring_is.values())

        crew_is: dict[int, cp_model.BoolVar] = {}
        crew_iv: dict[int, cp_model.IntervalVar] = {}
        for crew_idx in range(num_crews):
            flag = model.NewBoolVar(f"u{idx}_crew{crew_idx}")
            crew_is[crew_idx] = flag
            crew_iv[crew_idx] = model.NewOptionalIntervalVar(start, unit.duration, end, flag, f"ci_u{idx}_c{crew_idx}")
        model.AddExactlyOne(crew_is.values())

        unit_vars[idx] = _EventVars(
            start=start,
            end=end,
            duration=unit.duration,
            interval=interval,
            ring_is_assigned=ring_is,
            crew_is_assigned=crew_is,
            ring_interval=ring_iv,
            crew_interval=crew_iv,
        )

    for ring_idx in range(num_rings):
        model.AddNoOverlap([unit_vars[idx].ring_interval[ring_idx] for idx in range(num_units)])
    for crew_idx in range(num_crews):
        model.AddNoOverlap([unit_vars[idx].crew_interval[crew_idx] for idx in range(num_units)])

    unit_idx_by_id = {unit.unit_id: idx for idx, unit in enumerate(units)}
    for idx, unit in enumerate(units):
        for predecessor_id in unit.predecessor_ids:
            pred_idx = unit_idx_by_id.get(predecessor_id)
            if pred_idx is not None:
                model.Add(unit_vars[idx].start >= unit_vars[pred_idx].end + unit.rest_after_predecessor_minutes)

    division_rounds: dict[str, dict[str, list[int]]] = {}
    for idx, unit in enumerate(units):
        if unit.unit_type == "kyorugi_match" and unit.round_name:
            division_rounds.setdefault(unit.division.id, {}).setdefault(unit.round_name, []).append(idx)
    for rounds_by_name in division_rounds.values():
        ordered_names = [name for name in ("round_of_16", "quarterfinal", "semifinal", "final") if name in rounds_by_name]
        for prior_name, next_name in zip(ordered_names, ordered_names[1:]):
            for prior_idx in rounds_by_name[prior_name]:
                for next_idx in rounds_by_name[next_name]:
                    model.Add(unit_vars[next_idx].start >= unit_vars[prior_idx].end + 5)
        for round_indexes in rounds_by_name.values():
            if 1 < len(round_indexes) <= num_rings:
                for ring_idx in range(num_rings):
                    model.Add(sum(unit_vars[idx].ring_is_assigned[ring_idx] for idx in round_indexes) <= 1)

    for left_idx in range(num_units):
        left = units[left_idx]
        left_athletes = set(left.athlete_ids)
        left_coaches = set(left.coach_ids)
        for right_idx in range(left_idx + 1, num_units):
            right = units[right_idx]
            if left_athletes.intersection(right.athlete_ids) or left_coaches.intersection(right.coach_ids):
                model.AddNoOverlap([unit_vars[left_idx].interval, unit_vars[right_idx].interval])

    hint = _compact_unit_hint(units, num_rings, num_crews)

    root_indexes = [idx for idx, unit in enumerate(units) if not unit.predecessor_ids]
    if (
        len(root_indexes) >= num_rings
        and num_crews >= num_rings
        and _hint_starts_all_rings_at_zero(hint, num_rings)
    ):
        root_starts_zero: dict[int, cp_model.BoolVar] = {}
        for idx in root_indexes:
            starts_zero = model.NewBoolVar(f"u{idx}_starts_zero")
            model.Add(unit_vars[idx].start == 0).OnlyEnforceIf(starts_zero)
            model.Add(unit_vars[idx].start >= 1).OnlyEnforceIf(starts_zero.Not())
            root_starts_zero[idx] = starts_zero
        for ring_idx in range(num_rings):
            starts_here_at_zero: list[cp_model.BoolVar] = []
            for idx in root_indexes:
                starts_zero = model.NewBoolVar(f"u{idx}_ring{ring_idx}_zero")
                model.Add(starts_zero <= root_starts_zero[idx])
                model.Add(starts_zero <= unit_vars[idx].ring_is_assigned[ring_idx])
                model.Add(starts_zero >= root_starts_zero[idx] + unit_vars[idx].ring_is_assigned[ring_idx] - 1)
                starts_here_at_zero.append(starts_zero)
            model.Add(cp_model.LinearExpr.Sum(starts_here_at_zero) >= 1)

    makespan = model.NewIntVar(0, horizon, "makespan")
    model.AddMaxEquality(makespan, [unit_vars[idx].end for idx in range(num_units)])

    ring_first_terms: list[cp_model.IntVar] = []
    ring_idle_terms: list[cp_model.IntVar] = []
    ring_workload_vars: list[cp_model.IntVar] = []
    ring_used_flags: list[cp_model.BoolVar] = []

    for ring_idx in range(num_rings):
        pseudo_starts: list[cp_model.IntVar] = []
        pseudo_ends: list[cp_model.IntVar] = []
        for idx in range(num_units):
            ps = model.NewIntVar(0, horizon + 1, f"pseudo_start_r{ring_idx}_u{idx}")
            pe = model.NewIntVar(0, horizon + 1, f"pseudo_end_r{ring_idx}_u{idx}")
            flag = unit_vars[idx].ring_is_assigned[ring_idx]
            model.Add(ps == unit_vars[idx].start).OnlyEnforceIf(flag)
            model.Add(ps == horizon + 1).OnlyEnforceIf(flag.Not())
            model.Add(pe == unit_vars[idx].end).OnlyEnforceIf(flag)
            model.Add(pe == 0).OnlyEnforceIf(flag.Not())
            pseudo_starts.append(ps)
            pseudo_ends.append(pe)

        ring_min_start = model.NewIntVar(0, horizon + 1, f"ring_min_start_{ring_idx}")
        ring_max_end = model.NewIntVar(0, horizon + 1, f"ring_max_end_{ring_idx}")
        model.AddMinEquality(ring_min_start, pseudo_starts)
        model.AddMaxEquality(ring_max_end, pseudo_ends)

        used = model.NewBoolVar(f"ring_used_{ring_idx}")
        ring_used_flags.append(used)
        assigned_count = sum(unit_vars[idx].ring_is_assigned[ring_idx] for idx in range(num_units))
        model.Add(assigned_count >= used)
        model.Add(assigned_count <= num_units * used)

        first = model.NewIntVar(0, horizon + 1, f"ring_first_{ring_idx}")
        model.Add(first == ring_min_start).OnlyEnforceIf(used)
        model.Add(first == 0).OnlyEnforceIf(used.Not())
        ring_first_terms.append(first)

        workload_expr = sum(units[idx].duration * unit_vars[idx].ring_is_assigned[ring_idx] for idx in range(num_units))
        workload = model.NewIntVar(0, horizon, f"ring_workload_{ring_idx}")
        model.Add(workload == workload_expr)
        ring_workload_vars.append(workload)

        span = model.NewIntVar(0, horizon + 1, f"ring_span_{ring_idx}")
        model.Add(span == ring_max_end - ring_min_start).OnlyEnforceIf(used)
        model.Add(span == 0).OnlyEnforceIf(used.Not())
        idle = model.NewIntVar(0, horizon + 1, f"ring_idle_{ring_idx}")
        model.Add(idle == span - workload).OnlyEnforceIf(used)
        model.Add(idle == 0).OnlyEnforceIf(used.Not())
        ring_idle_terms.append(idle)

    if num_units >= num_rings and num_crews >= num_rings:
        model.Add(cp_model.LinearExpr.Sum(ring_used_flags) == num_rings)

    ring_max_workload = model.NewIntVar(0, horizon, "ring_max_workload")
    ring_min_workload = model.NewIntVar(0, horizon, "ring_min_workload")
    model.AddMaxEquality(ring_max_workload, ring_workload_vars)
    model.AddMinEquality(ring_min_workload, ring_workload_vars)
    ring_workload_spread = model.NewIntVar(0, horizon, "ring_workload_spread")
    model.Add(ring_workload_spread == ring_max_workload - ring_min_workload)

    same_round_same_ring_penalties: list[cp_model.BoolVar] = []
    for left_idx in range(num_units):
        left = units[left_idx]
        if left.unit_type != "kyorugi_match" or not left.round_name:
            continue
        for right_idx in range(left_idx + 1, num_units):
            right = units[right_idx]
            if (
                right.unit_type != "kyorugi_match"
                or right.division.id != left.division.id
                or right.round_name != left.round_name
            ):
                continue
            for ring_idx in range(num_rings):
                both = model.NewBoolVar(f"same_round_ring_u{left_idx}_u{right_idx}_r{ring_idx}")
                model.Add(both <= unit_vars[left_idx].ring_is_assigned[ring_idx])
                model.Add(both <= unit_vars[right_idx].ring_is_assigned[ring_idx])
                model.Add(both >= unit_vars[left_idx].ring_is_assigned[ring_idx] + unit_vars[right_idx].ring_is_assigned[ring_idx] - 1)
                same_round_same_ring_penalties.append(both)

    latest_first = model.NewIntVar(0, horizon + 1, "latest_ring_first")
    model.AddMaxEquality(latest_first, ring_first_terms)
    ring_idle_total = model.NewIntVar(0, (horizon + 1) * max(1, num_rings), "ring_idle_total")
    model.Add(ring_idle_total == sum(ring_idle_terms))
    starts_sum = cp_model.LinearExpr.Sum([unit_vars[idx].start for idx in range(num_units)])

    model.Minimize(
        makespan * 10_000_000
        + latest_first * 3_000_000
        + ring_idle_total * 200_000
        + ring_workload_spread * 80_000
        + sum(same_round_same_ring_penalties) * 500_000
        + starts_sum * 500
    )

    for idx, (start_hint, ring_hint, crew_hint) in hint.items():
        model.AddHint(unit_vars[idx].start, start_hint)
        model.AddHint(unit_vars[idx].end, start_hint + units[idx].duration)
        for ring_idx, flag in unit_vars[idx].ring_is_assigned.items():
            model.AddHint(flag, 1 if ring_idx == ring_hint else 0)
        for crew_idx, flag in unit_vars[idx].crew_is_assigned.items():
            model.AddHint(flag, 1 if crew_idx == crew_hint else 0)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = solver_time_limit_seconds
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise ScheduleError(f"No feasible schedule found under current constraints (solver status: {solver.StatusName(status)}).")

    return _build_schedule_from_units(tournament, units, unit_vars, solver)


def _hint_starts_all_rings_at_zero(hint: dict[int, tuple[int, int, int]], num_rings: int) -> bool:
    rings_at_zero = {ring_idx for start, ring_idx, _ in hint.values() if start == 0}
    return len(rings_at_zero) >= num_rings


def _compact_unit_hint(
    units: list[_SchedulableUnit],
    num_rings: int,
    num_crews: int,
) -> dict[int, tuple[int, int, int]]:
    """Build a compact feasible hint for CP-SAT without relaxing hard resources."""
    if not units or num_rings <= 0 or num_crews <= 0:
        return {}

    unit_idx_by_id = {unit.unit_id: idx for idx, unit in enumerate(units)}
    round_rank_by_idx = {
        idx: _kyorugi_round_rank(unit.round_name)
        for idx, unit in enumerate(units)
        if unit.unit_type == "kyorugi_match" and unit.round_name
    }

    unscheduled = set(range(len(units)))
    placements: dict[int, tuple[int, int, int]] = {}
    end_by_idx: dict[int, int] = {}
    ring_available = [0 for _ in range(num_rings)]
    crew_available = [0 for _ in range(num_crews)]
    ring_workload = [0 for _ in range(num_rings)]
    athlete_available: dict[str, int] = {}
    coach_available: dict[str, int] = {}

    def prior_rounds_complete(idx: int) -> bool:
        unit = units[idx]
        rank = round_rank_by_idx.get(idx)
        if rank is None:
            return True
        for other_idx in unscheduled:
            if other_idx == idx:
                continue
            other = units[other_idx]
            if other.division.id != unit.division.id:
                continue
            other_rank = round_rank_by_idx.get(other_idx)
            if other_rank is not None and other_rank < rank:
                return False
        return True

    def predecessor_ready_time(unit: _SchedulableUnit) -> int | None:
        ready = 0
        for predecessor_id in unit.predecessor_ids:
            predecessor_idx = unit_idx_by_id.get(predecessor_id)
            if predecessor_idx is None:
                continue
            if predecessor_idx not in end_by_idx:
                return None
            ready = max(ready, end_by_idx[predecessor_idx] + unit.rest_after_predecessor_minutes)
        if unit.unit_type == "kyorugi_match":
            rank = _kyorugi_round_rank(unit.round_name)
            if rank is not None:
                for other_idx, other in enumerate(units):
                    if other.division.id != unit.division.id or other.unit_type != "kyorugi_match":
                        continue
                    other_rank = _kyorugi_round_rank(other.round_name)
                    if other_rank is None or other_rank >= rank:
                        continue
                    if other_idx not in end_by_idx:
                        return None
                    ready = max(ready, end_by_idx[other_idx] + 5)
        return ready

    def best_global_pick() -> tuple[int, int, int, int] | None:
        picks: list[tuple[tuple[int, int, int, int, int, int], int, int, int, int]] = []
        for idx in unscheduled:
            if not prior_rounds_complete(idx):
                continue
            unit = units[idx]
            pred_ready = predecessor_ready_time(unit)
            if pred_ready is None:
                continue
            for ring_idx in range(num_rings):
                base = ring_available[ring_idx]
                for crew_idx in range(num_crews):
                    start = max(base, crew_available[crew_idx], pred_ready)
                    for athlete_id in unit.athlete_ids:
                        start = max(start, athlete_available.get(athlete_id, 0))
                    for coach_id in unit.coach_ids:
                        start = max(start, coach_available.get(coach_id, 0))
                    score = (
                        start,
                        max(0, start - base),
                        ring_workload[ring_idx],
                        0 if unit.unit_type == "poomsae_block" else 1,
                        ring_idx,
                        idx,
                    )
                    picks.append((score, idx, ring_idx, crew_idx, start))
        if not picks:
            return None
        picks.sort(key=lambda row: row[0])
        _, idx, ring_idx, crew_idx, start = picks[0]
        return idx, ring_idx, crew_idx, start

    while unscheduled:
        pick = best_global_pick()
        if pick is None:
            break
        idx, ring_idx, crew_idx, start = pick
        unit = units[idx]
        end = start + unit.duration
        placements[idx] = (start, ring_idx, crew_idx)
        end_by_idx[idx] = end
        unscheduled.remove(idx)
        ring_available[ring_idx] = end
        crew_available[crew_idx] = end
        ring_workload[ring_idx] += unit.duration
        for athlete_id in unit.athlete_ids:
            athlete_available[athlete_id] = end
        for coach_id in unit.coach_ids:
            coach_available[coach_id] = end

    return placements


def _build_schedulable_units(tournament: Tournament) -> list[_SchedulableUnit]:
    division_by_id = {division.id: division for division in tournament.divisions}
    athlete_by_id = {athlete.id: athlete for athlete in tournament.athletes}
    units: list[_SchedulableUnit] = []

    for event in tournament.events:
        division = division_by_id.get(event.division_id)
        if not division:
            continue
        if event.event_type == "kyorugi":
            units.extend(_build_kyorugi_units(event, division, athlete_by_id))
        else:
            duration = max(5, event.estimated_duration_minutes + event.buffer_minutes)
            units.append(
                _SchedulableUnit(
                    unit_id=event.event_id,
                    source_event=event,
                    division=division,
                    unit_type="poomsae_block",
                    round_name=None,
                    bracket_position=None,
                    duration=duration,
                    athlete_ids=tuple(event.athlete_ids),
                    team_ids=tuple(event.team_ids),
                    coach_ids=(),
                    required_referee_count=event.required_referee_count,
                )
            )
    return units


def count_schedulable_units(tournament: Tournament) -> int:
    return len(_build_schedulable_units(tournament))


def _build_kyorugi_units(
    event: TournamentEvent,
    division: Division,
    athlete_by_id: dict[str, object],
) -> list[_SchedulableUnit]:
    athlete_ids = list(division.athlete_ids or event.athlete_ids)
    bracket_size = 1 << math.ceil(math.log2(max(2, len(athlete_ids))))
    rounds = _kyorugi_round_labels(bracket_size)
    leaves: list[str | None] = list(athlete_ids) + [None] * (bracket_size - len(athlete_ids))
    duration = _kyorugi_match_duration_minutes(division.belt_level)
    units: list[_SchedulableUnit] = []
    previous_tokens: list[tuple[str, str] | None] = [("athlete", athlete_id) if athlete_id else None for athlete_id in leaves]

    for round_index, round_name in enumerate(rounds):
        next_tokens: list[tuple[str, str] | None] = []
        for offset in range(0, len(previous_tokens), 2):
            left = previous_tokens[offset]
            right = previous_tokens[offset + 1] if offset + 1 < len(previous_tokens) else None
            if left is None and right is None:
                next_tokens.append(None)
                continue
            if left is None:
                next_tokens.append(right)
                continue
            if right is None:
                next_tokens.append(left)
                continue

            position = offset // 2 + 1
            match_id = f"{division.id}-ky-{round_name}-{position}"
            known_athletes = (
                tuple(token[1] for token in (left, right) if token and token[0] == "athlete")
                if round_index == 0
                else ()
            )
            known_teams = tuple(
                sorted(
                    {
                        getattr(athlete_by_id[athlete_id], "team_id")
                        for athlete_id in known_athletes
                        if athlete_id in athlete_by_id
                    }
                )
            )
            known_coaches = tuple(
                sorted(
                    {
                        coach_id
                        for athlete_id in known_athletes
                        if athlete_id in athlete_by_id
                        for coach_id in sorted(getattr(athlete_by_id[athlete_id], "coach_ids", []))[:1]
                    }
                )
            )
            predecessor_ids = tuple(token[1] for token in (left, right) if token and token[0] == "winner")
            units.append(
                _SchedulableUnit(
                    unit_id=match_id,
                    source_event=event,
                    division=division,
                    unit_type="kyorugi_match",
                    round_name=round_name,
                    bracket_position=position,
                    duration=duration,
                    athlete_ids=known_athletes,
                    team_ids=known_teams or tuple(event.team_ids),
                    coach_ids=known_coaches,
                    required_referee_count=event.required_referee_count,
                    predecessor_ids=predecessor_ids,
                    rest_after_predecessor_minutes=5 if predecessor_ids else 0,
                    feeder_1_match_id=left[1] if left and left[0] == "winner" else None,
                    feeder_2_match_id=right[1] if right and right[0] == "winner" else None,
                )
            )
            next_tokens.append(("winner", match_id))
        previous_tokens = next_tokens

    return units


def _kyorugi_round_labels(bracket_size: int) -> list[str]:
    if bracket_size <= 2:
        return ["final"]
    if bracket_size <= 4:
        return ["semifinal", "final"]
    if bracket_size <= 8:
        return ["quarterfinal", "semifinal", "final"]
    return ["round_of_16", "quarterfinal", "semifinal", "final"]


def _kyorugi_round_rank(round_name: str | None) -> int | None:
    if not round_name:
        return None
    order = {
        "round_of_16": 0,
        "quarterfinal": 1,
        "semifinal": 2,
        "final": 3,
    }
    return order.get(round_name)


def _kyorugi_match_duration_minutes(belt_level: str) -> int:
    if belt_level == "color_belt":
        return 5
    if belt_level in {"black_belt", "world_class"}:
        return 8
    return 7


def _build_schedule_from_units(
    tournament: Tournament,
    units: list[_SchedulableUnit],
    unit_vars: dict[int, _EventVars],
    solver: cp_model.CpSolver,
) -> list[RingSchedule]:
    ring_by_idx = {idx: ring for idx, ring in enumerate(tournament.rings)}
    crew_by_idx = {idx: crew for idx, crew in enumerate(tournament.referee_crews)}
    by_ring: dict[str, list[ScheduledEvent]] = {ring.id: [] for ring in tournament.rings}

    chronological_rows: list[ScheduledEvent] = []
    for idx, unit in enumerate(units):
        ring_idx = next(ri for ri in range(len(tournament.rings)) if solver.Value(unit_vars[idx].ring_is_assigned[ri]) == 1)
        crew_idx = next(ci for ci in range(len(tournament.referee_crews)) if solver.Value(unit_vars[idx].crew_is_assigned[ci]) == 1)
        ring = ring_by_idx[ring_idx]
        crew = crew_by_idx[crew_idx]
        source = unit.source_event
        start = solver.Value(unit_vars[idx].start)
        end = solver.Value(unit_vars[idx].end)
        is_kyorugi_match = unit.unit_type == "kyorugi_match"
        row = ScheduledEvent(
            event_id=unit.unit_id if is_kyorugi_match else source.event_id,
            source_event_id=source.event_id,
            division_id=source.division_id,
            division_name=(
                f"{source.division_name} - {unit.round_name} {unit.bracket_position}"
                if is_kyorugi_match and unit.round_name and unit.bracket_position
                else source.division_name
            ),
            event_type=source.event_type,
            age_group=source.age_group,
            belt_rank_group=source.belt_rank_group,
            weight_class=source.weight_class,
            match_id=unit.unit_id if is_kyorugi_match else None,
            round_name=unit.round_name,
            bracket_position=unit.bracket_position,
            feeder_1_match_id=unit.feeder_1_match_id,
            feeder_2_match_id=unit.feeder_2_match_id,
            ring_id=ring.id,
            ring_name=ring.name,
            referee_crew_id=crew.id,
            referee_crew_name=crew.name,
            start_minute=start,
            end_minute=end,
            estimated_duration_minutes=unit.duration,
            buffer_minutes=0 if is_kyorugi_match else source.buffer_minutes,
            athlete_ids=list(unit.athlete_ids),
            team_ids=list(unit.team_ids),
            required_coach_ids=list(unit.coach_ids),
            required_referee_count=unit.required_referee_count,
            status="scheduled",
        )
        chronological_rows.append(row)

    chronological_rows.sort(key=lambda item: (item.start_minute, item.end_minute, item.ring_id, item.event_id))
    for match_number, row in enumerate(chronological_rows, start=1):
        if row.event_type == "kyorugi":
            row.match_number = match_number
        by_ring[row.ring_id].append(row)

    schedules = [
        RingSchedule(
            ring_id=ring.id,
            ring_name=ring.name,
            events=sorted(by_ring[ring.id], key=lambda item: (item.start_minute, item.end_minute, item.event_id)),
        )
        for ring in tournament.rings
    ]
    if tournament.referees:
        schedules = assign_referees_to_schedule(tournament, schedules)
    return schedules


def _build_schedule_from_unit_placements(
    tournament: Tournament,
    units: list[_SchedulableUnit],
    placements: dict[int, tuple[int, int, int]],
) -> list[RingSchedule]:
    ring_by_idx = {idx: ring for idx, ring in enumerate(tournament.rings)}
    crew_by_idx = {idx: crew for idx, crew in enumerate(tournament.referee_crews)}
    by_ring: dict[str, list[ScheduledEvent]] = {ring.id: [] for ring in tournament.rings}

    chronological_rows: list[ScheduledEvent] = []
    for idx, unit in enumerate(units):
        if idx not in placements:
            raise ScheduleError(f"Missing compact placement for schedulable unit {unit.unit_id}.")
        start, ring_idx, crew_idx = placements[idx]
        ring = ring_by_idx[ring_idx]
        crew = crew_by_idx[crew_idx]
        source = unit.source_event
        is_kyorugi_match = unit.unit_type == "kyorugi_match"
        chronological_rows.append(
            ScheduledEvent(
                event_id=unit.unit_id if is_kyorugi_match else source.event_id,
                source_event_id=source.event_id,
                division_id=source.division_id,
                division_name=(
                    f"{source.division_name} - {unit.round_name} {unit.bracket_position}"
                    if is_kyorugi_match and unit.round_name and unit.bracket_position
                    else source.division_name
                ),
                event_type=source.event_type,
                age_group=source.age_group,
                belt_rank_group=source.belt_rank_group,
                weight_class=source.weight_class,
                match_id=unit.unit_id if is_kyorugi_match else None,
                round_name=unit.round_name,
                bracket_position=unit.bracket_position,
                feeder_1_match_id=unit.feeder_1_match_id,
                feeder_2_match_id=unit.feeder_2_match_id,
                ring_id=ring.id,
                ring_name=ring.name,
                referee_crew_id=crew.id,
                referee_crew_name=crew.name,
                start_minute=start,
                end_minute=start + unit.duration,
                estimated_duration_minutes=unit.duration,
                buffer_minutes=0 if is_kyorugi_match else source.buffer_minutes,
                athlete_ids=list(unit.athlete_ids),
                team_ids=list(unit.team_ids),
                required_coach_ids=list(unit.coach_ids),
                required_referee_count=unit.required_referee_count,
                status="scheduled",
            )
        )

    chronological_rows.sort(key=lambda item: (item.start_minute, item.end_minute, item.ring_id, item.event_id))
    for match_number, row in enumerate(chronological_rows, start=1):
        if row.event_type == "kyorugi":
            row.match_number = match_number
        by_ring[row.ring_id].append(row)

    schedules = [
        RingSchedule(
            ring_id=ring.id,
            ring_name=ring.name,
            events=sorted(by_ring[ring.id], key=lambda item: (item.start_minute, item.end_minute, item.event_id)),
        )
        for ring in tournament.rings
    ]
    if tournament.referees:
        schedules = assign_referees_to_schedule(tournament, schedules)
    return schedules


def _build_schedule_from_placements(
    tournament: Tournament,
    durations: list[int],
    placements: dict[int, tuple[int, int, int]],
) -> list[RingSchedule]:
    ring_by_idx = {idx: ring for idx, ring in enumerate(tournament.rings)}
    crew_by_idx = {idx: crew for idx, crew in enumerate(tournament.referee_crews)}
    events_by_ring: dict[str, list[ScheduledEvent]] = {ring.id: [] for ring in tournament.rings}

    for event_idx, event in enumerate(tournament.events):
        if event_idx not in placements:
            raise ScheduleError(f"Missing greedy placement for event index {event_idx}.")
        start, ring_idx, crew_idx = placements[event_idx]
        duration = durations[event_idx]
        ring = ring_by_idx[ring_idx]
        crew = crew_by_idx[crew_idx]
        events_by_ring[ring.id].append(
            ScheduledEvent(
                event_id=event.event_id,
                division_id=event.division_id,
                division_name=event.division_name,
                event_type=event.event_type,
                age_group=event.age_group,
                belt_rank_group=event.belt_rank_group,
                weight_class=event.weight_class,
                ring_id=ring.id,
                ring_name=ring.name,
                referee_crew_id=crew.id,
                referee_crew_name=crew.name,
                start_minute=start,
                end_minute=start + duration,
                estimated_duration_minutes=event.estimated_duration_minutes,
                buffer_minutes=event.buffer_minutes,
                athlete_ids=event.athlete_ids,
                team_ids=event.team_ids,
                required_coach_ids=event.required_coach_ids if event.event_type == "kyorugi" else [],
                required_referee_count=event.required_referee_count,
                status="scheduled",
            )
        )

    schedules = [
        RingSchedule(
            ring_id=ring.id,
            ring_name=ring.name,
            events=sorted(events_by_ring[ring.id], key=lambda row: row.start_minute),
        )
        for ring in tournament.rings
    ]
    if tournament.referees:
        schedules = assign_referees_to_schedule(tournament, schedules)
    return schedules


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
            ri for ri in range(len(tournament.rings)) if solver.Value(event_vars[event_idx].ring_is_assigned[ri]) == 1
        )
        chosen_crew_idx = next(
            ci for ci in range(len(tournament.referee_crews)) if solver.Value(event_vars[event_idx].crew_is_assigned[ci]) == 1
        )
        ring = ring_by_idx[chosen_ring_idx]
        crew = crew_by_idx[chosen_crew_idx]

        scheduled = ScheduledEvent(
            event_id=event.event_id,
            division_id=event.division_id,
            division_name=event.division_name,
            event_type=event.event_type,
            age_group=event.age_group,
            belt_rank_group=event.belt_rank_group,
            weight_class=event.weight_class,
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
            required_coach_ids=event.required_coach_ids if event.event_type == "kyorugi" else [],
            required_referee_count=event.required_referee_count,
            status="scheduled",
        )
        events_by_ring[ring.id].append(scheduled)

    schedules = [
        RingSchedule(
            ring_id=ring.id,
            ring_name=ring.name,
            events=sorted(events_by_ring[ring.id], key=lambda item: item.start_minute),
        )
        for ring in tournament.rings
    ]

    if tournament.referees:
        schedules = assign_referees_to_schedule(tournament, schedules)
    return schedules
