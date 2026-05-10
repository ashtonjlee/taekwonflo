from __future__ import annotations

from dataclasses import dataclass, field

from .availability import coach_ids_for_match
from .brackets import build_division_detail
from .models import RingSchedule, Tournament
from .rescheduler import EmergencyConfig, RescheduleError, reoptimize_future_events
from .schedule_ops import assign_referees_to_schedule


@dataclass(frozen=True)
class DemoScenario:
    emergency_type: str
    current_minute: int
    delay_minutes: int
    ring_id: str | None = None
    referee_crew_id: str | None = None
    coach_id: str | None = None
    pause_start_minute: int = 0
    pause_duration_minutes: int = 20
    unavailable_start_minute: int = 0
    unavailable_duration_minutes: int = 20
    unavailable_referee_ids: list[str] = field(default_factory=list)
    affected_event_id: str | None = None
    reason: str = ""


def find_impactful_demo_scenario(
    *,
    tournament: Tournament,
    original_schedule: list[RingSchedule],
    emergency_type: str,
    default_current_minute: int = 60,
    default_delay_minutes: int = 20,
) -> DemoScenario:
    if emergency_type == "medical_delay":
        return _find_medical_delay_scenario(
            tournament=tournament,
            original_schedule=original_schedule,
            default_current_minute=default_current_minute,
            default_delay_minutes=default_delay_minutes,
        )
    if emergency_type == "referee_shortage":
        return _find_referee_shortage_scenario(
            tournament=tournament,
            original_schedule=original_schedule,
            default_current_minute=default_current_minute,
            default_delay_minutes=default_delay_minutes,
        )
    if emergency_type == "coach_conflict":
        return _find_coach_conflict_scenario(
            tournament=tournament,
            original_schedule=original_schedule,
            default_current_minute=default_current_minute,
            default_delay_minutes=default_delay_minutes,
        )
    return DemoScenario(
        emergency_type=emergency_type,
        current_minute=default_current_minute,
        delay_minutes=default_delay_minutes,
        pause_start_minute=default_current_minute,
        pause_duration_minutes=default_delay_minutes,
        unavailable_start_minute=default_current_minute,
        unavailable_duration_minutes=default_delay_minutes,
        reason="Fallback deterministic scenario.",
    )


def _all_events(schedule: list[RingSchedule]):
    return sorted((event for ring in schedule for event in ring.events), key=lambda row: row.start_minute)


def _find_medical_delay_scenario(
    *,
    tournament: Tournament,
    original_schedule: list[RingSchedule],
    default_current_minute: int,
    default_delay_minutes: int,
) -> DemoScenario:
    rings = sorted(original_schedule, key=lambda ring: ring.ring_id)
    for ring in rings:
        future = [event for event in sorted(ring.events, key=lambda row: row.start_minute) if event.start_minute > 0]
        if len(future) < 2:
            continue
        for affected in future[:4]:
            current = max(0, affected.start_minute - 2)
            delay = max(default_delay_minutes, affected.end_minute - current + 2)
            config = EmergencyConfig(
                emergency_type="medical_delay",
                current_minute=current,
                ring_id=ring.ring_id,
                delay_minutes=delay,
                pause_start_minute=current,
                pause_duration_minutes=delay,
                unavailable_start_minute=current,
                unavailable_duration_minutes=delay,
            )
            try:
                _, changed_events = reoptimize_future_events(
                    tournament=tournament,
                    original_schedule=original_schedule,
                    config=config,
                )
            except RescheduleError:
                continue
            if changed_events:
                return DemoScenario(
                    emergency_type="medical_delay",
                    current_minute=current,
                    delay_minutes=delay,
                    ring_id=ring.ring_id,
                    pause_start_minute=current,
                    pause_duration_minutes=delay,
                    unavailable_start_minute=current,
                    unavailable_duration_minutes=delay,
                    affected_event_id=affected.event_id,
                    reason=(
                        f"Pause overlaps {affected.event_id} on {ring.ring_name} and forces at least one downstream "
                        "future event change."
                    ),
                )
    # deterministic fallback
    fallback_ring = rings[0] if rings else None
    return DemoScenario(
        emergency_type="medical_delay",
        current_minute=default_current_minute,
        delay_minutes=default_delay_minutes,
        ring_id=fallback_ring.ring_id if fallback_ring else None,
        pause_start_minute=default_current_minute,
        pause_duration_minutes=default_delay_minutes,
        unavailable_start_minute=default_current_minute,
        unavailable_duration_minutes=default_delay_minutes,
        reason="Fallback deterministic ring pause; no guaranteed downstream shift candidate found.",
    )


def _find_referee_shortage_scenario(
    *,
    tournament: Tournament,
    original_schedule: list[RingSchedule],
    default_current_minute: int,
    default_delay_minutes: int,
) -> DemoScenario:
    crew_by_id = {crew.id: crew for crew in tournament.referee_crews}
    assigned_schedule = assign_referees_to_schedule(tournament, original_schedule) if tournament.referees else original_schedule
    future_events = [event for event in _all_events(assigned_schedule) if event.start_minute > 0]
    future_events.sort(key=lambda event: (-event.required_referee_count, event.start_minute, event.event_id))

    for affected in future_events:
        if not affected.assigned_referee_ids or len(affected.assigned_referee_ids) < affected.required_referee_count:
            continue
        current = max(0, affected.start_minute - 2)
        duration = max(default_delay_minutes, min(30, affected.end_minute - affected.start_minute + 2))
        crew = crew_by_id.get(affected.referee_crew_id)
        if not crew:
            continue
        unavailable_ref_ids = [sorted(affected.assigned_referee_ids)[0]]
        config = EmergencyConfig(
            emergency_type="referee_shortage",
            current_minute=current,
            referee_crew_id=affected.referee_crew_id,
            delay_minutes=default_delay_minutes,
            pause_start_minute=current,
            pause_duration_minutes=duration,
            unavailable_start_minute=current,
            unavailable_duration_minutes=duration,
        )
        try:
            _, changed_events = reoptimize_future_events(
                tournament=tournament,
                original_schedule=original_schedule,
                config=config,
            )
        except RescheduleError:
            continue

        if changed_events or unavailable_ref_ids:
            return DemoScenario(
                emergency_type="referee_shortage",
                current_minute=current,
                delay_minutes=default_delay_minutes,
                referee_crew_id=affected.referee_crew_id,
                pause_start_minute=current,
                pause_duration_minutes=duration,
                unavailable_start_minute=current,
                unavailable_duration_minutes=duration,
                unavailable_referee_ids=unavailable_ref_ids,
                affected_event_id=affected.event_id,
                reason=(
                    f"Targets event {affected.event_id}, which has exactly assigned officials for a "
                    f"{affected.required_referee_count}-referee slot, and removes one assigned referee."
                ),
            )

    first_crew = tournament.referee_crews[0] if tournament.referee_crews else None
    return DemoScenario(
        emergency_type="referee_shortage",
        current_minute=default_current_minute,
        delay_minutes=default_delay_minutes,
        referee_crew_id=first_crew.id if first_crew else None,
        pause_start_minute=default_current_minute,
        pause_duration_minutes=default_delay_minutes,
        unavailable_start_minute=default_current_minute,
        unavailable_duration_minutes=default_delay_minutes,
        unavailable_referee_ids=(sorted(first_crew.referee_ids)[:1] if first_crew else []),
        reason="Fallback deterministic referee shortage scenario.",
    )


def _find_coach_conflict_scenario(
    *,
    tournament: Tournament,
    original_schedule: list[RingSchedule],
    default_current_minute: int,
    default_delay_minutes: int,
) -> DemoScenario:
    candidates = [
        event
        for event in _all_events(original_schedule)
        if event.start_minute > 0 and event.required_coach_ids
    ]
    candidates.sort(
        key=lambda event: (
            0 if event.event_type in {"poomsae", "pair_poomsae", "team_poomsae"} else 1,
            event.start_minute,
            event.event_id,
        )
    )
    for event in candidates:
        current = max(0, event.start_minute - 2)
        try:
            detail = build_division_detail(
                tournament=tournament,
                schedule=original_schedule,
                division_id=event.division_id,
                current_minute=current,
            )
        except (KeyError, ValueError):
            continue
        ordered_matches = sorted(detail.bracket.matches, key=lambda match: (match.start_minute, match.match_id))
        for affected_match in ordered_matches:
            if affected_match.end_minute <= current:
                continue
            affected_coaches = coach_ids_for_match(tournament, affected_match)
            for coach_id in sorted(affected_coaches):
                replacement = next(
                    (
                        match
                        for match in ordered_matches
                        if match.match_id != affected_match.match_id
                        and match.start_minute > affected_match.start_minute
                        and match.status in {"waiting", "staging"}
                        and coach_id not in coach_ids_for_match(tournament, match)
                    ),
                    None,
                )
                if replacement:
                    return DemoScenario(
                        emergency_type="coach_conflict",
                        current_minute=current,
                        delay_minutes=default_delay_minutes,
                        coach_id=coach_id,
                        ring_id=event.ring_id,
                        pause_start_minute=current,
                        pause_duration_minutes=default_delay_minutes,
                        unavailable_start_minute=current,
                        unavailable_duration_minutes=default_delay_minutes,
                        affected_event_id=event.event_id,
                        reason=f"Targets {event.event_id} with a same-division ready match available for local coach-delay repair.",
                    )

    for event in candidates:
        current = max(0, event.start_minute - 2)
        return DemoScenario(
            emergency_type="coach_conflict",
            current_minute=current,
            delay_minutes=default_delay_minutes,
            coach_id=sorted(event.required_coach_ids)[0],
            ring_id=event.ring_id,
            pause_start_minute=current,
            pause_duration_minutes=default_delay_minutes,
            unavailable_start_minute=current,
            unavailable_duration_minutes=default_delay_minutes,
            affected_event_id=event.event_id,
            reason=f"Targets near-future event {event.event_id} with assigned coach conflict pressure.",
        )
    return DemoScenario(
        emergency_type="coach_conflict",
        current_minute=default_current_minute,
        delay_minutes=default_delay_minutes,
        pause_start_minute=default_current_minute,
        pause_duration_minutes=default_delay_minutes,
        unavailable_start_minute=default_current_minute,
        unavailable_duration_minutes=default_delay_minutes,
        reason="Fallback deterministic coach conflict scenario.",
    )
