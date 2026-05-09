from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .availability import AvailabilityIndex, build_availability_index, coach_ids_for_match, resource_requirements_for_match
from .brackets import build_division_detail
from .models import (
    ChangedEvent,
    ChangedMatch,
    DivisionDetail,
    Match,
    NotificationMessage,
    RepairDemoResponse,
    ResourceLocation,
    RingSchedule,
    ScheduledEvent,
    Tournament,
)
from .notifications import build_mock_notifications
from .rescheduler import EmergencyConfig, reoptimize_future_events
from .validation import validate_snapshot

RepairEmergencyType = Literal["medical_delay", "ring_pause", "referee_shortage", "coach_conflict", "athlete_conflict"]


@dataclass(frozen=True)
class RepairRequest:
    emergency_type: RepairEmergencyType
    current_minute: int
    coach_id: str | None = None
    athlete_id: str | None = None
    referee_crew_id: str | None = None
    ring_id: str | None = None
    delay_minutes: int = 20


def try_repair_next_match(
    *,
    tournament: Tournament,
    original_schedule: list[RingSchedule],
    request: RepairRequest,
) -> RepairDemoResponse:
    availability = build_availability_index(tournament, original_schedule, request.current_minute)
    affected_event = _find_affected_event(tournament, original_schedule, request)
    affected_detail = (
        build_division_detail(tournament, original_schedule, affected_event.division_id, request.current_minute)
        if affected_event
        else None
    )
    affected_match = _find_affected_match(affected_detail, request) if affected_detail else None

    if affected_event and affected_detail and affected_match and request.emergency_type != "medical_delay":
        replacement = _find_same_division_replacement(
            tournament=tournament,
            event=affected_event,
            detail=affected_detail,
            affected_match=affected_match,
            request=request,
            availability=availability,
        )
        if replacement:
            repaired_detail, changed_matches = _swap_matches_in_detail(
                affected_detail,
                affected_match,
                replacement,
                _reason_for_request(request),
                "same_division_match_swap",
            )
            return _response(
                tournament=tournament,
                original_schedule=original_schedule,
                repaired_schedule=original_schedule,
                strategy="same_division_match_swap",
                affected_match=affected_match,
                replacement_match=_match_by_id(repaired_detail, replacement.match_id),
                changed_events=[],
                changed_matches=changed_matches,
                resource_locations=_resource_locations(availability, request),
                notifications=_repair_notifications(affected_match, replacement, "same division match swap"),
                validation=validate_snapshot(tournament=tournament, schedule=original_schedule),
                division_detail=repaired_detail,
            )

        ring_replacement = _find_same_ring_replacement(
            tournament=tournament,
            schedule=original_schedule,
            affected_event=affected_event,
            affected_match=affected_match,
            request=request,
            availability=availability,
        )
        if ring_replacement:
            replacement_event, replacement_match = ring_replacement
            repaired_schedule, changed_events = _swap_events_in_same_ring(
                original_schedule,
                affected_event,
                replacement_event,
            )
            changed_matches = [
                ChangedMatch(
                    match_id=replacement_match.match_id,
                    change_type="same_ring_match_swap",
                    original_start_minute=replacement_match.start_minute,
                    new_start_minute=affected_match.start_minute,
                    original_status=replacement_match.status,
                    new_status="in_progress",
                    reason=_reason_for_request(request),
                )
            ]
            return _response(
                tournament=tournament,
                original_schedule=original_schedule,
                repaired_schedule=repaired_schedule,
                strategy="same_ring_match_swap",
                affected_match=affected_match,
                replacement_match=replacement_match,
                changed_events=changed_events,
                changed_matches=changed_matches,
                resource_locations=_resource_locations(availability, request),
                notifications=_repair_notifications(affected_match, replacement_match, "same ring match swap"),
                validation=validate_snapshot(tournament=tournament, schedule=repaired_schedule),
                division_detail=affected_detail,
            )

    if request.emergency_type in {"medical_delay", "ring_pause"} and affected_event:
        repaired_schedule, changed_events = _shift_ring_locally(
            original_schedule,
            ring_id=affected_event.ring_id,
            current_minute=request.current_minute,
            delay_minutes=request.delay_minutes,
        )
        return _response(
            tournament=tournament,
            original_schedule=original_schedule,
            repaired_schedule=repaired_schedule,
            strategy="local_shift",
            affected_match=affected_match,
            replacement_match=None,
            changed_events=changed_events,
            changed_matches=[],
            resource_locations=_resource_locations(availability, request),
            notifications=[
                NotificationMessage(
                    id="repair-local-shift",
                    channel="ops",
                    text=f"{affected_event.ring_name} paused; later matches resume on the same ring after {request.delay_minutes} minutes.",
                )
            ],
            validation=validate_snapshot(tournament=tournament, schedule=repaired_schedule),
            division_detail=affected_detail,
        )

    try:
        repaired_schedule, changed_events = reoptimize_future_events(
            tournament=tournament,
            original_schedule=original_schedule,
            config=EmergencyConfig(
                emergency_type="coach_conflict" if request.emergency_type == "athlete_conflict" else request.emergency_type,
                current_minute=request.current_minute,
                ring_id=request.ring_id,
                referee_crew_id=request.referee_crew_id,
                coach_id=request.coach_id,
                delay_minutes=request.delay_minutes,
                pause_start_minute=request.current_minute,
                pause_duration_minutes=request.delay_minutes,
                unavailable_start_minute=request.current_minute,
                unavailable_duration_minutes=request.delay_minutes,
            ),
        )
        strategy = "global_reschedule"
    except Exception:
        repaired_schedule = original_schedule
        changed_events = []
        strategy = "infeasible"

    return _response(
        tournament=tournament,
        original_schedule=original_schedule,
        repaired_schedule=repaired_schedule,
        strategy=strategy,
        affected_match=affected_match,
        replacement_match=None,
        changed_events=changed_events,
        changed_matches=[],
        resource_locations=_resource_locations(availability, request),
        notifications=build_mock_notifications(repaired_schedule),
        validation=validate_snapshot(tournament=tournament, schedule=repaired_schedule),
        division_detail=affected_detail,
    )


def _find_affected_event(
    tournament: Tournament,
    schedule: list[RingSchedule],
    request: RepairRequest,
) -> ScheduledEvent | None:
    event_by_id = {event.event_id: event for event in tournament.events}
    events = sorted(
        [event for ring in schedule for event in ring.events if event.end_minute > request.current_minute],
        key=lambda event: (0 if event.start_minute <= request.current_minute < event.end_minute else 1, event.start_minute),
    )
    for event in events:
        payload = event_by_id[event.event_id]
        if request.ring_id and event.ring_id != request.ring_id:
            continue
        if request.referee_crew_id and event.referee_crew_id != request.referee_crew_id:
            continue
        if request.coach_id and request.coach_id not in payload.required_coach_ids:
            continue
        if request.athlete_id and request.athlete_id not in payload.athlete_ids:
            continue
        return event
    return events[0] if events else None


def _find_affected_match(detail: DivisionDetail | None, request: RepairRequest) -> Match | None:
    if not detail:
        return None
    candidates = [
        match
        for match in detail.bracket.matches
        if match.end_minute > request.current_minute
        and (match.status in {"in_progress", "staging"} or match.start_minute >= request.current_minute)
    ]
    for match in candidates:
        competitor_ids = {match.competitor_1.competitor_id}
        if match.competitor_2:
            competitor_ids.add(match.competitor_2.competitor_id)
        if request.athlete_id and request.athlete_id not in competitor_ids:
            continue
        return match
    return candidates[0] if candidates else None


def _find_same_division_replacement(
    *,
    tournament: Tournament,
    event: ScheduledEvent,
    detail: DivisionDetail,
    affected_match: Match,
    request: RepairRequest,
    availability: AvailabilityIndex,
) -> Match | None:
    for match in detail.bracket.matches:
        if match.match_id == affected_match.match_id or match.start_minute <= affected_match.start_minute:
            continue
        if not _bracket_dependencies_ready(detail, match):
            continue
        if request.emergency_type == "referee_shortage" and match.required_referee_count >= affected_match.required_referee_count:
            continue
        match_coach_ids = coach_ids_for_match(tournament, match)
        if _match_uses_blocked_resource(match, match_coach_ids, event.referee_crew_id, request):
            continue
        requirements = resource_requirements_for_match(match, match_coach_ids, event.referee_crew_id)
        if _available_for_current_slot(availability, requirements, affected_match):
            return match
    return None


def _find_same_ring_replacement(
    *,
    tournament: Tournament,
    schedule: list[RingSchedule],
    affected_event: ScheduledEvent,
    affected_match: Match,
    request: RepairRequest,
    availability: AvailabilityIndex,
) -> tuple[ScheduledEvent, Match] | None:
    event_by_id = {event.event_id: event for event in tournament.events}
    same_ring_events = sorted(
        [
            event
            for ring in schedule
            for event in ring.events
            if event.ring_id == affected_event.ring_id and event.start_minute > affected_event.start_minute
        ],
        key=lambda event: event.start_minute,
    )
    for event in same_ring_events:
        detail = build_division_detail(tournament, schedule, event.division_id, request.current_minute)
        payload = event_by_id[event.event_id]
        for match in detail.bracket.matches:
            if match.status not in {"waiting", "staging"}:
                continue
            if not _bracket_dependencies_ready(detail, match):
                continue
            if request.emergency_type == "referee_shortage" and match.required_referee_count >= affected_match.required_referee_count:
                continue
            match_coach_ids = coach_ids_for_match(tournament, match)
            if _match_uses_blocked_resource(match, match_coach_ids, event.referee_crew_id, request):
                continue
            requirements = resource_requirements_for_match(match, match_coach_ids, event.referee_crew_id)
            if _available_for_current_slot(availability, requirements, affected_match):
                return event, match
    return None


def _available_for_current_slot(
    availability: AvailabilityIndex,
    requirements: dict[str, list[str]],
    affected_match: Match,
) -> bool:
    conflicts = availability.get_conflicts(requirements, affected_match.start_minute, affected_match.end_minute)
    current_slot_reasons = {affected_match.match_id, affected_match.scheduled_event_id}
    return all(conflict.reason in current_slot_reasons for conflict in conflicts)


def _bracket_dependencies_ready(detail: DivisionDetail, match: Match) -> bool:
    round_names = detail.bracket.rounds
    current_round_index = round_names.index(match.round_name) if match.round_name in round_names else 0
    if current_round_index == 0:
        return True
    prior_rounds = set(round_names[:current_round_index])
    return all(
        prior_match.status == "completed"
        for prior_match in detail.bracket.matches
        if prior_match.round_name in prior_rounds
    )


def _match_uses_blocked_resource(
    match: Match,
    coach_ids: list[str],
    referee_crew_id: str,
    request: RepairRequest,
) -> bool:
    competitor_ids = {match.competitor_1.competitor_id}
    if match.competitor_2:
        competitor_ids.add(match.competitor_2.competitor_id)
    return bool(
        (request.athlete_id and request.athlete_id in competitor_ids)
        or (request.coach_id and request.coach_id in coach_ids)
        or (request.referee_crew_id and request.referee_crew_id == referee_crew_id)
        or (request.ring_id and request.emergency_type in {"medical_delay", "ring_pause"} and request.ring_id == match.ring_id)
    )


def _swap_matches_in_detail(
    detail: DivisionDetail,
    affected_match: Match,
    replacement_match: Match,
    reason: str,
    strategy: str,
) -> tuple[DivisionDetail, list[ChangedMatch]]:
    affected_start, affected_end = affected_match.start_minute, affected_match.end_minute
    replacement_start, replacement_end = replacement_match.start_minute, replacement_match.end_minute
    updated_matches: list[Match] = []

    for match in detail.bracket.matches:
        updated = Match(**match.model_dump())
        if match.match_id == affected_match.match_id:
            updated.start_minute = replacement_start
            updated.end_minute = replacement_end
            updated.status = "waiting"
            updated.repair_note = f"{reason}; blocked match delayed."
        elif match.match_id == replacement_match.match_id:
            updated.start_minute = affected_start
            updated.end_minute = affected_end
            updated.status = "in_progress"
            updated.repair_note = f"{reason}; next eligible match inserted."
            updated.swapped_from_match_id = affected_match.match_id
        updated_matches.append(updated)

    repaired = DivisionDetail(**detail.model_dump())
    repaired.bracket.matches = updated_matches
    repaired.current_match = next((match for match in updated_matches if match.status == "in_progress"), None)
    repaired.completed_matches = [match for match in updated_matches if match.status == "completed"]
    repaired.waiting_competitors = detail.waiting_competitors
    repaired.staging_competitors = detail.staging_competitors

    return repaired, [
        ChangedMatch(
            match_id=affected_match.match_id,
            change_type=strategy,
            original_start_minute=affected_start,
            new_start_minute=replacement_start,
            original_status=affected_match.status,
            new_status="waiting",
            reason=reason,
        ),
        ChangedMatch(
            match_id=replacement_match.match_id,
            change_type=strategy,
            original_start_minute=replacement_start,
            new_start_minute=affected_start,
            original_status=replacement_match.status,
            new_status="in_progress",
            reason=reason,
        ),
    ]


def _swap_events_in_same_ring(
    schedule: list[RingSchedule],
    affected_event: ScheduledEvent,
    replacement_event: ScheduledEvent,
) -> tuple[list[RingSchedule], list[ChangedEvent]]:
    repaired: list[RingSchedule] = []
    changed: list[ChangedEvent] = []
    for ring in schedule:
        updated_events: list[ScheduledEvent] = []
        for event in ring.events:
            updated = ScheduledEvent(**event.model_dump())
            if event.event_id == affected_event.event_id:
                duration = updated.end_minute - updated.start_minute
                updated.start_minute = replacement_event.start_minute
                updated.end_minute = updated.start_minute + duration
            elif event.event_id == replacement_event.event_id:
                duration = updated.end_minute - updated.start_minute
                updated.start_minute = affected_event.start_minute
                updated.end_minute = updated.start_minute + duration
            if updated.start_minute != event.start_minute:
                changed.append(
                    ChangedEvent(
                        event_id=updated.event_id,
                        changes=["start_time_changed"],
                        original_ring_id=event.ring_id,
                        new_ring_id=updated.ring_id,
                        original_referee_crew_id=event.referee_crew_id,
                        new_referee_crew_id=updated.referee_crew_id,
                        original_start_minute=event.start_minute,
                        new_start_minute=updated.start_minute,
                    )
                )
            updated_events.append(updated)
        repaired.append(RingSchedule(ring_id=ring.ring_id, ring_name=ring.ring_name, events=sorted(updated_events, key=lambda item: item.start_minute)))
    return repaired, changed


def _shift_ring_locally(
    schedule: list[RingSchedule],
    *,
    ring_id: str,
    current_minute: int,
    delay_minutes: int,
) -> tuple[list[RingSchedule], list[ChangedEvent]]:
    repaired: list[RingSchedule] = []
    changed: list[ChangedEvent] = []
    for ring in schedule:
        updated_events: list[ScheduledEvent] = []
        for event in ring.events:
            updated = ScheduledEvent(**event.model_dump())
            if event.ring_id == ring_id and event.start_minute > current_minute:
                updated.start_minute += delay_minutes
                updated.end_minute += delay_minutes
                changed.append(
                    ChangedEvent(
                        event_id=updated.event_id,
                        changes=["start_time_changed"],
                        original_ring_id=event.ring_id,
                        new_ring_id=updated.ring_id,
                        original_referee_crew_id=event.referee_crew_id,
                        new_referee_crew_id=updated.referee_crew_id,
                        original_start_minute=event.start_minute,
                        new_start_minute=updated.start_minute,
                    )
                )
            updated_events.append(updated)
        repaired.append(RingSchedule(ring_id=ring.ring_id, ring_name=ring.ring_name, events=updated_events))
    return repaired, changed


def _resource_locations(
    availability: AvailabilityIndex,
    request: RepairRequest,
) -> list[ResourceLocation]:
    requested = [
        ("coach", request.coach_id),
        ("athlete", request.athlete_id),
        ("referee_crew", request.referee_crew_id),
        ("ring", request.ring_id),
    ]
    locations: list[ResourceLocation] = []
    for resource_type, resource_id in requested:
        if not resource_id:
            continue
        active = availability.get_active_interval(resource_type, resource_id, request.current_minute)
        locations.append(
            ResourceLocation(
                resource_type=resource_type,
                resource_id=resource_id,
                location=active.location if active else "available",
                reason=active.reason if active else None,
                until_minute=active.end_minute if active else None,
            )
        )
    return locations


def _repair_notifications(
    affected_match: Match,
    replacement_match: Match,
    strategy_label: str,
) -> list[NotificationMessage]:
    return [
        NotificationMessage(
            id="repair-match-swap",
            channel="ops",
            text=f"{strategy_label}: {replacement_match.match_id} inserted while {affected_match.match_id} waits.",
        )
    ]


def _reason_for_request(request: RepairRequest) -> str:
    if request.coach_id:
        return f"Coach {request.coach_id} unavailable"
    if request.athlete_id:
        return f"Athlete {request.athlete_id} unavailable"
    if request.referee_crew_id:
        return f"Referee crew {request.referee_crew_id} unavailable"
    if request.ring_id:
        return f"Ring {request.ring_id} paused"
    return f"{request.emergency_type} repair"


def _match_by_id(detail: DivisionDetail, match_id: str) -> Match | None:
    return next((match for match in detail.bracket.matches if match.match_id == match_id), None)


def _response(
    *,
    tournament: Tournament,
    original_schedule: list[RingSchedule],
    repaired_schedule: list[RingSchedule],
    strategy: str,
    affected_match: Match | None,
    replacement_match: Match | None,
    changed_events: list[ChangedEvent],
    changed_matches: list[ChangedMatch],
    resource_locations: list[ResourceLocation],
    notifications: list[NotificationMessage],
    validation,
    division_detail: DivisionDetail | None,
) -> RepairDemoResponse:
    del tournament
    return RepairDemoResponse(
        original_schedule=original_schedule,
        repaired_schedule=repaired_schedule,
        repair_strategy_used=strategy,
        affected_match=affected_match,
        replacement_match=replacement_match,
        changed_events=changed_events,
        changed_matches=changed_matches,
        resource_locations=resource_locations,
        notifications=notifications,
        validation=validation,
        division_detail=division_detail,
    )
