"""Bridge TaekwonFlo tournaments to the experimental CP-SAT scheduler in ashton_file."""

from __future__ import annotations

from collections import defaultdict

from .ashton_file import Match, SchedulerConfig, schedule
from .models import RingSchedule, ScheduledEvent, Tournament


def _belt_label(belt_rank_group: str) -> str:
    if belt_rank_group in ("black_belt", "world_class"):
        return "Black"
    return "Red"


def _friend_age_group(age: str) -> str:
    return {
        "peewee": "Youth",
        "cadet": "Cadet",
        "junior": "Junior",
        "senior": "Senior",
    }.get(age, "Junior")


def _tournament_event_as_match(
    *,
    event_kind: str,
    belt: str,
    evt,
) -> Match:
    dur = max(1, evt.estimated_duration_minutes + evt.buffer_minutes)
    return Match(
        id=evt.event_id,
        division_id=evt.division_id,
        event=event_kind,
        belt=belt,
        round_num=1,
        total_rounds=1,
        predecessors=[],
        duration_min=dur,
        label=evt.division_name,
    )


def _assign_crews_greedy(tournament: Tournament, schedule: list[RingSchedule]) -> list[RingSchedule]:
    """Pick a referee crew per event so the same crew is not double-booked in time (best-effort)."""
    crews = tournament.referee_crews
    crew_by_id = {c.id: c for c in crews}
    events_flat = sorted(
        (e for r in schedule for e in r.events),
        key=lambda e: (e.start_minute, e.ring_id, e.event_id),
    )
    crew_busy_until: dict[str, int] = {c.id: 0 for c in crews}
    chosen: dict[str, tuple[str, str]] = {}
    for evt in events_flat:
        eligible = [c for c in crews if crew_busy_until[c.id] <= evt.start_minute]
        if eligible:
            pick = min(eligible, key=lambda c: (crew_busy_until[c.id], c.id))
        else:
            pick = min(crews, key=lambda c: (crew_busy_until[c.id], c.id))
        chosen[evt.event_id] = (pick.id, crew_by_id[pick.id].name)
        crew_busy_until[pick.id] = max(crew_busy_until[pick.id], evt.end_minute)

    rebuilt: list[RingSchedule] = []
    for ring in schedule:
        evs = []
        for e in ring.events:
            cid, cname = chosen[e.event_id]
            evs.append(e.model_copy(update={"referee_crew_id": cid, "referee_crew_name": cname}))
        rebuilt.append(
            RingSchedule(
                ring_id=ring.ring_id,
                ring_name=ring.ring_name,
                events=sorted(evs, key=lambda item: item.start_minute),
            )
        )
    return rebuilt


def build_teammate_schedule(
    tournament: Tournament,
    solver_time_limit_seconds: float = 5.0,
) -> list[RingSchedule]:
    from .scheduler import ScheduleError

    if not tournament.events:
        return [RingSchedule(ring_id=ring.id, ring_name=ring.name, events=[]) for ring in tournament.rings]
    if not tournament.rings:
        raise ScheduleError("No rings are available for scheduling.")
    if not tournament.referee_crews:
        raise ScheduleError("No referee crews are available for scheduling.")

    num_mats = len(tournament.rings)
    total_refs = len(tournament.referees) if tournament.referees else max(num_mats * 4, num_mats * 5)

    sparring: dict[str, Match] = {}
    poomsae_m: dict[str, Match] = {}
    div_to_sp: dict[str, list[str]] = defaultdict(list)
    div_to_po: dict[str, list[str]] = defaultdict(list)
    poomsae_types = {"poomsae", "pair_poomsae", "team_poomsae"}

    for evt in tournament.events:
        div = next((d for d in tournament.divisions if d.id == evt.division_id), None)
        belt = _belt_label(evt.belt_rank_group)
        if evt.event_type in poomsae_types:
            poomsae_m[evt.event_id] = _tournament_event_as_match(event_kind="poomsae", belt=belt, evt=evt)
            div_to_po[evt.division_id].append(evt.event_id)
        else:
            sparring[evt.event_id] = _tournament_event_as_match(event_kind="sparring", belt=belt, evt=evt)
            div_to_sp[evt.division_id].append(evt.event_id)

    def division_records(dmap: dict[str, list[str]]) -> list[dict]:
        records: list[dict] = []
        for div_id, mids in dmap.items():
            div = next((d for d in tournament.divisions if d.id == div_id), None)
            label = div.name if div else div_id
            age_src = div.age_group if div else "junior"
            records.append(
                {
                    "id": div_id,
                    "match_ids": mids,
                    "age_group": _friend_age_group(age_src),
                    "label": label,
                }
            )
        return records

    sp_divs = division_records(div_to_sp)
    po_divs = division_records(div_to_po)

    cfg = SchedulerConfig(
        num_mats=num_mats,
        total_refs=total_refs,
        day_start=0,
        athlete_rest_min=5,
        solver_time_limit=float(solver_time_limit_seconds),
    )

    raw = schedule(sparring, poomsae_m, sp_divs, po_divs, cfg)
    if not raw:
        raise ScheduleError("No feasible schedule found under current constraints (teammate CP-SAT).")

    ring_list = list(tournament.rings)
    ring_by_mat_idx = {i: ring_list[i] for i in range(len(ring_list))}

    events_by_ring: dict[str, list[ScheduledEvent]] = {ring.id: [] for ring in tournament.rings}

    event_by_id = {e.event_id: e for e in tournament.events}
    for mid, sm in raw.items():
        evt = event_by_id.get(mid)
        if evt is None:
            continue
        mat_idx = sm.mat - 1
        ring = ring_by_mat_idx.get(mat_idx)
        if ring is None:
            continue
        sm_start = sm.start_abs - cfg.day_start
        sm_end = sm.end_abs - cfg.day_start
        placeholder_crew = tournament.referee_crews[0]
        scheduled = ScheduledEvent(
            event_id=evt.event_id,
            division_id=evt.division_id,
            division_name=evt.division_name,
            event_type=evt.event_type,
            age_group=evt.age_group,
            belt_rank_group=evt.belt_rank_group,
            weight_class=evt.weight_class,
            ring_id=ring.id,
            ring_name=ring.name,
            referee_crew_id=placeholder_crew.id,
            referee_crew_name=placeholder_crew.name,
            start_minute=sm_start,
            end_minute=sm_end,
            estimated_duration_minutes=evt.estimated_duration_minutes,
            buffer_minutes=evt.buffer_minutes,
            athlete_ids=evt.athlete_ids,
            team_ids=evt.team_ids,
            required_coach_ids=evt.required_coach_ids,
            required_referee_count=evt.required_referee_count,
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
    schedules = _assign_crews_greedy(tournament, schedules)
    if tournament.referees:
        from .schedule_ops import assign_referees_to_schedule

        schedules = assign_referees_to_schedule(tournament, schedules)
    return schedules
