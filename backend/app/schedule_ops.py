"""Referee roster assignment + live coordination summaries."""

from __future__ import annotations

from collections import defaultdict

from .brackets import build_division_detail
from .match_numbers import build_published_match_number_map
from .models import (
    CoordinationBoard,
    CoordinatorMatchRow,
    RefereeAdjustment,
    Referee,
    RingSchedule,
    ScheduleChangeDetail,
    ScheduledEvent,
    Tournament,
)


def assign_referees_to_schedule(tournament: Tournament, schedule: list[RingSchedule]) -> list[RingSchedule]:
    """Greedy per-event referee pick: prefer home crew, fill required_referee_count, borrow minimally."""
    return assign_referees_to_schedule_with_unavailability(tournament, schedule)


def assign_referees_to_schedule_with_unavailability(
    tournament: Tournament,
    schedule: list[RingSchedule],
    *,
    unavailable_by_referee: dict[str, list[tuple[int, int]]] | None = None,
) -> list[RingSchedule]:
    """Greedy per-event referee pick with optional temporary referee blackouts."""
    referees = list(tournament.referees)
    crew_bundle = {crew.id: list(crew.referee_ids) for crew in tournament.referee_crews}
    referee_models = {r.referee_id: r for r in referees}
    unavailable_windows = unavailable_by_referee or {}

    intervals: dict[str, list[tuple[int, int]]] = defaultdict(list)

    def free_for(referee_id: str, start: int, end: int) -> bool:
        for s, e in unavailable_windows.get(referee_id, []):
            if not (end <= s or start >= e):
                return False
        for s, e in intervals[referee_id]:
            if not (end <= s or start >= e):
                return False
        return True

    def occupy(referee_id: str, start: int, end: int) -> None:
        intervals[referee_id].append((start, end))

    events_time_order = sorted(
        (evt for ring in schedule for evt in ring.events),
        key=lambda item: item.start_minute,
    )

    assigns: dict[str, list[str]] = {}

    deterministic_pool = sorted(
        (r.referee_id for r in referees),
        key=lambda rid: (_crew_rank(referee_models[rid]), rid),
    )

    for evt in events_time_order:
        need = max(1, evt.required_referee_count)
        crew_ids = crew_bundle.get(evt.referee_crew_id, [])
        chosen: list[str] = []
        # First try home crew in stable order
        for rid in sorted(crew_ids, key=lambda x: x):
            if len(chosen) >= need:
                break
            if rid in referee_models and free_for(rid, evt.start_minute, evt.end_minute):
                chosen.append(rid)
        borrow_idx = 0
        while len(chosen) < need and borrow_idx < len(deterministic_pool):
            cand = deterministic_pool[borrow_idx]
            borrow_idx += 1
            if cand in chosen:
                continue
            ref = referee_models.get(cand)
            if not ref:
                continue
            if not ref.qualifications or _qual_ok(ref, evt.event_type):
                if free_for(cand, evt.start_minute, evt.end_minute):
                    chosen.append(cand)

        assigns[evt.event_id] = sorted(chosen)[:need]
        for rid in assigns[evt.event_id]:
            occupy(rid, evt.start_minute, evt.end_minute)

    return _apply_ref_assignments(schedule, assigns)


def _crew_rank(ref: Referee) -> tuple[int, str]:
    ky = 0 if any(q in {"kyorugi", "center_referee", "corner"} for q in ref.qualifications) else 1
    return (ky, ref.home_crew_id)


def _qual_ok(ref: Referee, event_type: str) -> bool:
    if event_type == "kyorugi":
        return any(q in ref.qualifications for q in {"kyorugi", "center_referee", "corner", "judge"})
    return any(q in ref.qualifications for q in {"poomsae", "judge", "kyorugi"})


def _apply_ref_assignments(schedule: list[RingSchedule], assigns: dict[str, list[str]]) -> list[RingSchedule]:
    return [
        RingSchedule(
            ring_id=ring.ring_id,
            ring_name=ring.ring_name,
            events=[
                ScheduledEvent(**{**evt.model_dump(), "assigned_referee_ids": assigns.get(evt.event_id, [])})
                for evt in sorted(ring.events, key=lambda item: item.start_minute)
            ],
        )
        for ring in schedule
    ]


def diff_referee_assignments(
    tournament: Tournament,
    original_schedule: list[RingSchedule],
    updated_schedule: list[RingSchedule],
    *,
    reason: str,
) -> list[RefereeAdjustment]:
    original_by_evt = _event_by_id(original_schedule)
    updated_by_evt = _event_by_id(updated_schedule)
    referees_by_id = {r.referee_id: r for r in tournament.referees}
    crew_by_id = {c.id: c for c in tournament.referee_crews}

    rows: list[RefereeAdjustment] = []
    for event_id, new_evt in updated_by_evt.items():
        old_evt = original_by_evt.get(event_id)
        if not old_evt:
            continue
        old_ids = set(old_evt.assigned_referee_ids)
        new_ids = set(new_evt.assigned_referee_ids)
        unchanged_ids = old_ids.intersection(new_ids)

        def crew_name(cid: str) -> str:
            block = crew_by_id.get(cid)
            return block.name if block else cid

        # Individual add/remove rows (bench -> slot or slot -> bench).
        for rid in sorted(old_ids.union(new_ids)):
            was = rid in old_ids
            now = rid in new_ids
            if was and now:
                continue

            ref = referees_by_id.get(rid)
            if not ref:
                continue

            borrowed = ref.home_crew_id != (new_evt.referee_crew_id if now else old_evt.referee_crew_id)
            rows.append(
                RefereeAdjustment(
                    referee_id=rid,
                    referee_name=ref.name,
                    home_crew_id=ref.home_crew_id,
                    from_crew_id=old_evt.referee_crew_id if was else "",
                    from_crew_name=crew_name(old_evt.referee_crew_id) if was else "",
                    to_crew_id=new_evt.referee_crew_id if now else "",
                    to_crew_name=crew_name(new_evt.referee_crew_id) if now else "",
                    from_ring_id=old_evt.ring_id if was else "",
                    from_ring_name=old_evt.ring_name if was else "",
                    to_ring_id=new_evt.ring_id if now else "",
                    to_ring_name=new_evt.ring_name if now else "",
                    ring_id=new_evt.ring_id if now else old_evt.ring_id,
                    ring_name=new_evt.ring_name if now else old_evt.ring_name,
                    from_window_start_minute=old_evt.start_minute if was else None,
                    from_window_end_minute=old_evt.end_minute if was else None,
                    window_start_minute=new_evt.start_minute,
                    window_end_minute=new_evt.end_minute,
                    scope="temporary" if borrowed else "rest_of_day",
                    reason=reason + (" — added to slot" if now else " — released from slot"),
                )
            )

        # If the same officials stayed assigned but the slot moved (ring/time/crew), emit relocation rows.
        moved_slot = (
            old_evt.ring_id != new_evt.ring_id
            or old_evt.referee_crew_id != new_evt.referee_crew_id
            or old_evt.start_minute != new_evt.start_minute
            or old_evt.end_minute != new_evt.end_minute
        )
        if moved_slot:
            for rid in sorted(unchanged_ids):
                ref = referees_by_id.get(rid)
                if not ref:
                    continue
                rows.append(
                    RefereeAdjustment(
                        referee_id=rid,
                        referee_name=ref.name,
                        home_crew_id=ref.home_crew_id,
                        from_crew_id=old_evt.referee_crew_id,
                        from_crew_name=crew_name(old_evt.referee_crew_id),
                        to_crew_id=new_evt.referee_crew_id,
                        to_crew_name=crew_name(new_evt.referee_crew_id),
                        from_ring_id=old_evt.ring_id,
                        from_ring_name=old_evt.ring_name,
                        to_ring_id=new_evt.ring_id,
                        to_ring_name=new_evt.ring_name,
                        ring_id=new_evt.ring_id,
                        ring_name=new_evt.ring_name,
                        from_window_start_minute=old_evt.start_minute,
                        from_window_end_minute=old_evt.end_minute,
                        window_start_minute=new_evt.start_minute,
                        window_end_minute=new_evt.end_minute,
                        scope="temporary",
                        reason=reason + " — slot moved",
                    )
                )

    dedup_keys: dict[tuple[str, str, str, int | None, int | None], RefereeAdjustment] = {}
    for row in rows:
        if (
            row.from_crew_id == row.to_crew_id
            and row.from_ring_id == row.to_ring_id
            and row.from_window_start_minute == row.window_start_minute
            and row.from_window_end_minute == row.window_end_minute
        ):
            continue
        dedup_keys[(row.referee_id, row.to_crew_id, row.ring_id, row.window_start_minute, row.window_end_minute)] = row
    return sorted(dedup_keys.values(), key=lambda r: (r.ring_id, r.window_start_minute or 0, r.referee_id))


def enrich_schedule_changes(
    tournament: Tournament,
    *,
    prior_schedule: list[RingSchedule],
    next_schedule: list[RingSchedule],
    changed_events: list,
    reason: str,
) -> list[ScheduleChangeDetail]:
    prior_by_evt = _event_by_id(prior_schedule)
    next_by_evt = _event_by_id(next_schedule)
    coach_bundle = {c.id: c for c in tournament.coaches}
    athlete_bundle = {a.id: a for a in tournament.athletes}

    published_match_numbers = build_published_match_number_map(tournament, prior_schedule)

    details: list[ScheduleChangeDetail] = []
    for row in sorted(changed_events, key=lambda r: getattr(r, "event_id")):
        new_evt = next_by_evt[row.event_id]
        old_evt = prior_by_evt.get(row.event_id)
        if not old_evt:
            continue
        payload = ScheduleChangeDetail(
            event_id=row.event_id,
            division_id=new_evt.division_id,
            division_name=new_evt.division_name,
            summary_reason=reason,
            original_ring_id=old_evt.ring_id,
            new_ring_id=new_evt.ring_id,
            original_ring_name=old_evt.ring_name,
            new_ring_name=new_evt.ring_name,
            original_referee_crew_id=old_evt.referee_crew_id,
            new_referee_crew_id=new_evt.referee_crew_id,
            original_referee_crew_name=old_evt.referee_crew_name,
            new_referee_crew_name=new_evt.referee_crew_name,
            original_start_minute=old_evt.start_minute,
            new_start_minute=new_evt.start_minute,
            changes=list(row.changes),
            original_assigned_referee_ids=list(old_evt.assigned_referee_ids),
            new_assigned_referee_ids=list(new_evt.assigned_referee_ids),
        )

        athlete_labels = [_athlete_pick(aid, athlete_bundle) for aid in new_evt.athlete_ids][:12]

        division_matches = _division_matches_snapshot(
            tournament,
            next_schedule,
            new_evt.division_id,
            new_evt.start_minute,
            match_number_by_match_id=published_match_numbers,
        )
        coaches = sorted(
            {
                side.assigned_coach_name
                or (coach_bundle[side.assigned_coach_id].name if side.assigned_coach_id in coach_bundle else side.assigned_coach_id)
                for duel in division_matches
                if duel.scheduled_event_id == new_evt.event_id
                for side in (duel.competitor_1, duel.competitor_2)
                if side and side.assigned_coach_id
            }
        )

        match_lines = _summarize_matches(
            tournament,
            next_schedule,
            new_evt.division_id,
            new_evt.start_minute,
            match_number_by_match_id=published_match_numbers,
        )
        affected_nums = sorted(
            {
                duel.match_number
                for duel in _division_matches_snapshot(
                    tournament,
                    next_schedule,
                    new_evt.division_id,
                    new_evt.start_minute,
                    match_number_by_match_id=published_match_numbers,
                )
                if duel.scheduled_event_id == new_evt.event_id
            }
        )

        payload.athlete_summaries = athlete_labels
        payload.coach_names_involved = coaches
        payload.match_breakdown = match_lines
        payload.affected_match_numbers = affected_nums
        details.append(payload)

    return details


def _division_matches_snapshot(
    tournament: Tournament,
    schedule: list[RingSchedule],
    division_id: str,
    current_minute: int,
    match_number_by_match_id: dict[str, int] | None = None,
) -> list:
    try:
        detail = build_division_detail(
            tournament,
            schedule,
            division_id,
            current_minute=current_minute,
            match_number_by_match_id=match_number_by_match_id,
        )
    except (KeyError, ValueError):
        return []
    return list(detail.bracket.matches)


def _summarize_matches(
    tournament: Tournament,
    schedule: list[RingSchedule],
    division_id: str,
    current_minute: int,
    match_number_by_match_id: dict[str, int] | None = None,
) -> list[str]:
    try:
        detail = build_division_detail(
            tournament,
            schedule,
            division_id,
            current_minute=current_minute,
            match_number_by_match_id=match_number_by_match_id,
        )
    except (KeyError, ValueError):
        return []
    lines: list[str] = []
    for duel in sorted(detail.bracket.matches, key=lambda m: (m.start_minute, m.match_number)):
        left = duel.competitor_1.name if duel.competitor_1 else duel.source_1_label or "TBD"
        right_side = duel.competitor_2.name if duel.competitor_2 else duel.source_2_label or "TBD"
        lines.append(f"M#{duel.match_number} {duel.round_name}: {left} vs {right_side}")
    return lines[:24]


def _athlete_pick(aid: str, athletes: dict) -> str:
    row = athletes.get(aid)
    return row.name if row else aid


def build_coordination_board(
    tournament: Tournament,
    schedule: list[RingSchedule],
    current_minute: int,
    *,
    published_schedule: list[RingSchedule] | None = None,
    match_number_by_match_id: dict[str, int] | None = None,
) -> CoordinationBoard:
    stable_match_numbers = match_number_by_match_id or build_published_match_number_map(
        tournament,
        published_schedule or schedule,
    )
    detail_cache: dict[str, tuple] = {}
    rows: list[CoordinatorMatchRow] = []

    for ring in schedule:
        for evt in sorted(ring.events, key=lambda item: item.start_minute):
            if evt.division_id not in detail_cache:
                try:
                    detail_cache[evt.division_id] = build_division_detail(
                        tournament=tournament,
                        schedule=schedule,
                        division_id=evt.division_id,
                        current_minute=current_minute,
                        match_number_by_match_id=stable_match_numbers,
                    )
                except (KeyError, ValueError):
                    detail_cache[evt.division_id] = None

            memo = detail_cache.get(evt.division_id)
            if not memo:
                continue
            for duel in memo.bracket.matches:
                phase, urgency = _phase_bucket(duel, current_minute, evt)
                athlete_bits: list[str] = []
                if duel.competitor_1:
                    athlete_bits.append(duel.competitor_1.name)
                elif duel.source_1_label:
                    athlete_bits.append(duel.source_1_label)
                if duel.competitor_2:
                    athlete_bits.append(duel.competitor_2.name)
                elif duel.source_2_label:
                    athlete_bits.append(duel.source_2_label)
                if duel.participant_athlete_ids and not duel.competitor_2:
                    athlete_bits.append(", ".join(duel.participant_athlete_ids[:4]))

                teams_seen: set[str] = set()
                for comp in filter(None, [duel.competitor_1, duel.competitor_2]):
                    if comp.team_name:
                        teams_seen.add(comp.team_name)

                coaches: set[str] = set()
                for comp in filter(None, [duel.competitor_1, duel.competitor_2]):
                    if comp.assigned_coach_id:
                        coaches.add(comp.assigned_coach_name or comp.assigned_coach_id)

                rows.append(
                    CoordinatorMatchRow(
                        phase=phase,
                        urgency=urgency,
                        division_id=evt.division_id,
                        division_name=evt.division_name,
                        event_id=evt.event_id,
                        ring_id=ring.ring_id,
                        ring_name=ring.ring_name or ring.ring_id,
                        match_id=duel.match_id,
                        match_number=duel.match_number,
                        round_name=duel.round_name,
                        status=duel.status,
                        start_minute=duel.start_minute,
                        end_minute=duel.end_minute,
                        athlete_display=sorted(set(athlete_bits)),
                        team_names=sorted(teams_seen),
                        coach_labels=sorted(coaches),
                    )
                )

    rows.sort(key=lambda r: (r.start_minute, r.ring_id, r.match_number))
    return CoordinationBoard(current_minute=current_minute, rows=rows)


def _phase_bucket(duel, current_minute: int, event) -> tuple[str, str]:
    del event
    if duel.status == "completed" or duel.end_minute <= current_minute:
        return "completed", "later"

    if duel.status == "in_progress" or (duel.start_minute <= current_minute < duel.end_minute):
        return "currently_competing", "now"

    lead = duel.start_minute - current_minute

    if lead > 30:
        return "warm_up_now", "later"

    if 15 < lead <= 30:
        return "warm_up_now", "soon"

    if 10 < lead <= 15:
        return "report_holding", "soon"

    if 0 < lead <= 10:
        return "report_staging", "now"

    return "report_staging", "later"


def _empty_ring_ops() -> dict[str, object | None]:
    return {
        "current_event_id": None,
        "current_division_name": None,
        "current_match_number": None,
        "next_event_id": None,
        "next_division_name": None,
        "next_match_number": None,
        "remaining_event_count": 0,
        "rescheduled_division_events": 0,
        "material_reschedule_count": 0,
        "total_delay_minutes": 0,
        "idle": True,
    }


def summarize_ring_operations(
    *,
    tournament: Tournament,
    ring_id: str,
    schedule: list[RingSchedule],
    changed_event_rows: list,
    current_minute: int,
    published_schedule: list[RingSchedule] | None = None,
    match_number_by_match_id: dict[str, int] | None = None,
) -> dict:
    stable_match_numbers = match_number_by_match_id or build_published_match_number_map(
        tournament,
        published_schedule or schedule,
    )
    ring = next((candidate for candidate in schedule if candidate.ring_id == ring_id), None)
    if not ring:
        return _empty_ring_ops()

    evts = sorted(ring.events or [], key=lambda item: item.start_minute)
    remaining = sum(1 for evt in evts if evt.end_minute > current_minute)

    in_prog = None
    for evt in evts:
        if evt.start_minute <= current_minute < evt.end_minute:
            in_prog = evt
            break

    next_evt = None
    busy_id = in_prog.event_id if in_prog else None
    for evt in evts:
        if evt.start_minute > current_minute and evt.event_id != busy_id:
            next_evt = evt
            break
    if next_evt is None and not in_prog:
        for evt in evts:
            if evt.start_minute >= current_minute:
                next_evt = evt
                break

    rescheduled_hits = [
        row for row in changed_event_rows if row.original_ring_id == ring_id or row.new_ring_id == ring_id
    ]
    divisions_moved_in = sum(
        1
        for row in changed_event_rows
        if row.new_ring_id == ring_id and row.original_ring_id != row.new_ring_id and "ring_changed" in row.changes
    )
    material_reschedule_count = sum(
        1
        for row in rescheduled_hits
        if row.new_start_minute != row.original_start_minute or row.original_ring_id != row.new_ring_id
    )
    total_delay_minutes = sum(max(0, row.new_start_minute - row.original_start_minute) for row in rescheduled_hits)

    def primary_match(div_id: str) -> int | None:
        try:
            detail_local = build_division_detail(
                tournament,
                schedule,
                div_id,
                current_minute,
                match_number_by_match_id=stable_match_numbers,
            )
        except (KeyError, ValueError):
            return None

        in_prog_match = next((m for m in detail_local.bracket.matches if m.status == "in_progress"), None)
        if in_prog_match:
            return in_prog_match.match_number

        contenders = sorted(
            detail_local.bracket.matches,
            key=lambda m: (abs(m.start_minute - current_minute), m.match_number),
        )
        return contenders[0].match_number if contenders else None

    current_match_number = primary_match(in_prog.division_id) if in_prog else None
    next_match_number = primary_match(next_evt.division_id) if next_evt else None

    idle = not in_prog and all(evt.end_minute <= current_minute for evt in evts)

    return {
        "current_event_id": in_prog.event_id if in_prog else None,
        "current_division_name": in_prog.division_name if in_prog else None,
        "current_match_number": current_match_number,
        "next_event_id": next_evt.event_id if next_evt else None,
        "next_division_name": next_evt.division_name if next_evt else None,
        "next_match_number": next_match_number,
        "remaining_event_count": remaining,
        "rescheduled_division_events": divisions_moved_in,
        "material_reschedule_count": material_reschedule_count,
        "total_delay_minutes": total_delay_minutes,
        "idle": idle,
    }


def _event_by_id(schedule: list[RingSchedule]) -> dict[str, ScheduledEvent]:
    return {evt.event_id: evt for ring in schedule for evt in ring.events}
