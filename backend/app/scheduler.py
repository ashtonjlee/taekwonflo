from __future__ import annotations

from dataclasses import dataclass

from ortools.sat.python import cp_model

from .models import RingSchedule, ScheduledEvent, Tournament
from .schedule_ops import assign_referees_to_schedule


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

    order = sorted(range(num_events), key=lambda idx: (-durations[idx], idx))

    for ev_idx in order:
        evt = tournament.events[ev_idx]
        dur = durations[ev_idx]
        athlete_set = frozenset(evt.athlete_ids)
        coach_set = frozenset(evt.required_coach_ids)

        picks: list[tuple[int, int, int]] = []
        for ring_idx in range(num_rings):
            for crew_idx in range(num_crews):
                for t_candidate in range(0, horizon - dur + 1):
                    ok = True
                    end_candidate = t_candidate + dur

                    for pst, pend, pr, pc, other_idx in placed_blocks:
                        overlap_time = end_candidate > pst and pend > t_candidate
                        if not overlap_time:
                            continue

                        blocker = ring_idx == pr or crew_idx == pc
                        if not blocker:
                            other_evt = tournament.events[other_idx]
                            blocker = bool(athlete_set.intersection(other_evt.athlete_ids))
                            blocker = blocker or bool(coach_set.intersection(other_evt.required_coach_ids))

                        if blocker:
                            ok = False
                            break

                    if ok:
                        picks.append((t_candidate, ring_idx, crew_idx))

        if not picks:
            raise ScheduleError(f"Greedy hint builder exhausted horizon {horizon} on event idx {ev_idx}")

        picks.sort(key=lambda item: (item[0], item[2], item[1]))
        t_pick, ring_pick, crew_pick = picks[0]
        placements[ev_idx] = (t_pick, ring_pick, crew_pick)
        placed_blocks.append((t_pick, t_pick + dur, ring_pick, crew_pick, ev_idx))
        placed_blocks.sort(key=lambda item: item[0])

    return placements


def build_optimized_schedule(tournament: Tournament, solver_time_limit_seconds: float = 5.0) -> list[RingSchedule]:
    if not tournament.events:
        return [RingSchedule(ring_id=ring.id, ring_name=ring.name, events=[]) for ring in tournament.rings]
    if not tournament.rings:
        raise ScheduleError("No rings are available for scheduling.")
    if not tournament.referee_crews:
        raise ScheduleError("No referee crews are available for scheduling.")

    ls = tournament.lunch_start_minute
    lunch_end_soft = ls + tournament.lunch_duration_minutes
    grace_cutoff = ls + tournament.lunch_grace_minutes

    num_events = len(tournament.events)
    num_rings = len(tournament.rings)
    num_crews = len(tournament.referee_crews)

    durations = [event.estimated_duration_minutes + event.buffer_minutes for event in tournament.events]
    slack_pad = tournament.lunch_duration_minutes + max(durations + [120])
    horizon = max(1, sum(durations) + slack_pad)

    greedy = _greedy_feasible_placements(tournament, durations, horizon)

    model = cp_model.CpModel()
    evt_vars: dict[int, _EventVars] = {}

    for ei, event in enumerate(tournament.events):
        duration = durations[ei]
        start = model.NewIntVar(0, horizon + 640, f"start_e{ei}")
        end = model.NewIntVar(0, horizon + 640, f"end_e{ei}")
        model.Add(end == start + duration)
        interval = model.NewIntervalVar(start, duration, end, f"interval_e{ei}")

        ring_is = {}
        ring_iv = {}
        for ri in range(num_rings):
            flag = model.NewBoolVar(f"e{ei}_ring{ri}")
            ring_is[ri] = flag
            ring_iv[ri] = model.NewOptionalIntervalVar(start, duration, end, flag, f"ri_e{ei}_r{ri}")
        model.AddExactlyOne(ring_is.values())

        crew_is = {}
        crew_iv = {}
        for ci in range(num_crews):
            flag = model.NewBoolVar(f"e{ei}_crew{ci}")
            crew_is[ci] = flag
            crew_iv[ci] = model.NewOptionalIntervalVar(start, duration, end, flag, f"ci_e{ei}_c{ci}")
        model.AddExactlyOne(crew_is.values())

        evt_vars[ei] = _EventVars(
            start=start,
            end=end,
            duration=duration,
            interval=interval,
            ring_is_assigned=ring_is,
            crew_is_assigned=crew_is,
            ring_interval=ring_iv,
            crew_interval=crew_iv,
        )

    for ri in range(num_rings):
        model.AddNoOverlap([evt_vars[ei].ring_interval[ri] for ei in range(num_events)])
    for ci in range(num_crews):
        model.AddNoOverlap([evt_vars[ei].crew_interval[ci] for ei in range(num_events)])

    for i in range(num_events):
        ev_i = tournament.events[i]
        ai = set(ev_i.athlete_ids)
        ci_set = set(ev_i.required_coach_ids)
        for j in range(i + 1, num_events):
            ev_j = tournament.events[j]
            clash = ai.intersection(ev_j.athlete_ids) or ci_set.intersection(ev_j.required_coach_ids)
            if clash:
                model.AddNoOverlap([evt_vars[i].interval, evt_vars[j].interval])

    makespan = model.NewIntVar(0, horizon + 760, "makespan")
    model.AddMaxEquality(makespan, [evt_vars[ei].end for ei in range(num_events)])

    ring_first_floor: list[cp_model.IntVar] = []
    ring_used_flag: list[cp_model.BoolVar] = []
    ring_idle_terms: list[cp_model.IntVar] = []

    for ri in range(num_rings):
        pseudo_vals = []
        pseudo_end_vals = []
        for ei in range(num_events):
            ps = model.NewIntVar(0, horizon + 900, f"pseudo_r{ri}_e{ei}")
            pe = model.NewIntVar(0, horizon + 900, f"pseudo_end_r{ri}_e{ei}")
            flag_ring = evt_vars[ei].ring_is_assigned[ri]
            model.Add(ps == evt_vars[ei].start).OnlyEnforceIf(flag_ring)
            model.Add(ps == horizon + 380).OnlyEnforceIf(flag_ring.Not())
            model.Add(pe == evt_vars[ei].end).OnlyEnforceIf(flag_ring)
            model.Add(pe == 0).OnlyEnforceIf(flag_ring.Not())
            pseudo_vals.append(ps)
            pseudo_end_vals.append(pe)

        ring_min_start = model.NewIntVar(0, horizon + 900, f"ring_min_start_{ri}")
        model.AddMinEquality(ring_min_start, pseudo_vals)
        ring_max_end = model.NewIntVar(0, horizon + 900, f"ring_max_end_{ri}")
        model.AddMaxEquality(ring_max_end, pseudo_end_vals)

        used_here = model.NewBoolVar(f"ring_used_flag_{ri}")
        ring_used_flag.append(used_here)
        ring_sum_assign = sum(evt_vars[ei].ring_is_assigned[ri] for ei in range(num_events))
        model.Add(ring_sum_assign <= num_events * used_here)
        model.Add(ring_sum_assign >= used_here)

        ff = model.NewIntVar(0, horizon + 900, f"ring_first_floor_{ri}")
        model.Add(ff == ring_min_start).OnlyEnforceIf(used_here)
        model.Add(ff == 0).OnlyEnforceIf(used_here.Not())
        ring_first_floor.append(ff)

        ring_span = model.NewIntVar(0, horizon + 900, f"ring_span_{ri}")
        model.Add(ring_span == ring_max_end - ring_min_start).OnlyEnforceIf(used_here)
        model.Add(ring_span == 0).OnlyEnforceIf(used_here.Not())
        ring_workload = sum(evt_vars[e].duration * evt_vars[e].ring_is_assigned[ri] for e in range(num_events))
        ring_idle = model.NewIntVar(0, horizon + 900, f"ring_idle_{ri}")
        model.Add(ring_idle == ring_span - ring_workload).OnlyEnforceIf(used_here)
        model.Add(ring_idle == 0).OnlyEnforceIf(used_here.Not())
        ring_idle_terms.append(ring_idle)

    latest_parallel_start = model.NewIntVar(0, horizon + 900, "latest_ring_first_floor")
    model.AddMaxEquality(latest_parallel_start, ring_first_floor)

    workload_gaps = []
    for left in range(num_rings):
        for right in range(left + 1, num_rings):
            wl_l = sum(evt_vars[e].duration * evt_vars[e].ring_is_assigned[left] for e in range(num_events))
            wl_r = sum(evt_vars[e].duration * evt_vars[e].ring_is_assigned[right] for e in range(num_events))
            delta = model.NewIntVar(-horizon * max(num_events, 240), horizon * max(num_events, 240), f"wkdt_{left}_{right}")
            model.Add(delta == wl_l - wl_r)
            gap_abs = model.NewIntVar(0, horizon * max(num_events, 640), f"wkabs_{left}_{right}")
            model.AddAbsEquality(gap_abs, delta)
            workload_gaps.append(gap_abs)

    workload_imbalance = model.NewIntVar(0, horizon * max(240, len(workload_gaps) or 1), "workload_imbalance_terms")
    if workload_gaps:
        model.Add(workload_imbalance == sum(workload_gaps))
    else:
        model.Add(workload_imbalance == 0)

    ring_idle_total = model.NewIntVar(0, (horizon + 900) * max(1, num_rings), "ring_idle_total")
    model.Add(ring_idle_total == sum(ring_idle_terms))

    starts_sum_terms = []
    for ei in range(num_events):
        starts_sum_terms.append(evt_vars[ei].start)
    starts_sum_linear = cp_model.LinearExpr.Sum(starts_sum_terms)

    utilization_miss = model.NewIntVar(0, num_rings + 40, "utilization_miss")
    if num_events >= num_rings and num_crews >= num_rings:
        model.Add(utilization_miss == num_rings - cp_model.LinearExpr.Sum(ring_used_flag))
    else:
        model.Add(utilization_miss == 0)

    lunch_inside_penalties: list[cp_model.IntVar] = []
    lunch_cross_penalties: list[cp_model.IntVar] = []

    inside_weight = tournament.lunch_duration_minutes + 55
    cross_weight = tournament.lunch_duration_minutes + 145

    for ei in range(num_events):
        if lunch_end_soft > ls:
            b_pref_block = model.NewBoolVar(f"starts_preferred_block_{ei}")
            ge_ls = model.NewBoolVar(f"starts_ge_ls_{ei}")
            lt_ls_end = model.NewBoolVar(f"starts_lt_ls_end_{ei}")
            _literal_ge(model, evt_vars[ei].start, ls, ge_ls)
            _literal_lt(model, evt_vars[ei].start, lunch_end_soft, lt_ls_end)
            _and_bool(model, ge_ls, lt_ls_end, b_pref_block)

            penal_inside = model.NewIntVar(0, cross_weight + 120, f"pen_inside_{ei}")
            model.Add(penal_inside == inside_weight).OnlyEnforceIf(b_pref_block)
            model.Add(penal_inside == 0).OnlyEnforceIf(b_pref_block.Not())
            lunch_inside_penalties.append(penal_inside)

        crosses_grace_cut = model.NewBoolVar(f"crosses_deep_lunch_cut_{ei}")
        before_ls_start = model.NewBoolVar(f"starts_before_ls_{ei}")
        end_after_cut = model.NewBoolVar(f"ends_after_grace_cut_{ei}")
        _literal_lt(model, evt_vars[ei].start, ls, before_ls_start)
        _literal_gt(model, evt_vars[ei].end, grace_cutoff, end_after_cut)
        _and_bool(model, before_ls_start, end_after_cut, crosses_grace_cut)

        penal_cross = model.NewIntVar(0, cross_weight + 200, f"pen_cross_{ei}")
        model.Add(penal_cross == cross_weight).OnlyEnforceIf(crosses_grace_cut)
        model.Add(penal_cross == 0).OnlyEnforceIf(crosses_grace_cut.Not())
        lunch_cross_penalties.append(penal_cross)

    lunch_cost_terms: list = []
    lunch_cost_terms.extend(lunch_inside_penalties)
    lunch_cost_terms.extend(lunch_cross_penalties)

    lunch_cost = cp_model.LinearExpr.Sum(lunch_cost_terms) if lunch_cost_terms else 0
    poomsae_types = {"poomsae", "pair_poomsae", "team_poomsae"}
    kyorugi_event_indexes = [idx for idx, evt in enumerate(tournament.events) if evt.event_type == "kyorugi"]
    poomsae_event_indexes = [idx for idx, evt in enumerate(tournament.events) if evt.event_type in poomsae_types]
    for k_idx in kyorugi_event_indexes:
        for p_idx in poomsae_event_indexes:
            for ring_idx in range(num_rings):
                model.Add(evt_vars[k_idx].start >= evt_vars[p_idx].end).OnlyEnforceIf(
                    [
                        evt_vars[k_idx].ring_is_assigned[ring_idx],
                        evt_vars[p_idx].ring_is_assigned[ring_idx],
                    ]
                )

    model.Minimize(
        makespan * 75_000_000
        + utilization_miss * 9_350_000
        + lunch_cost * 62_500
        + latest_parallel_start * 1_975_000
        + ring_idle_total * 52_000
        + workload_imbalance * 880
        + starts_sum_linear * 2_010
    )

    for ei in range(num_events):
        hinted_start, hinted_ring, hinted_crew = greedy[ei]
        vars_for_event = evt_vars[ei]
        model.AddHint(vars_for_event.start, hinted_start)
        model.AddHint(vars_for_event.end, hinted_start + vars_for_event.duration)
        for ri in range(num_rings):
            model.AddHint(vars_for_event.ring_is_assigned[ri], 1 if ri == hinted_ring else 0)
        for ci in range(num_crews):
            model.AddHint(vars_for_event.crew_is_assigned[ci], 1 if ci == hinted_crew else 0)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = solver_time_limit_seconds
    solver.parameters.num_search_workers = 8

    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise ScheduleError(f"No feasible schedule found under current constraints (solver status: {solver.StatusName(status)}).")

    return _build_schedule_response(tournament, evt_vars, solver)


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
            required_coach_ids=event.required_coach_ids,
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
