from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .availability import AvailabilityIndex, build_availability_index, coach_ids_for_match, resource_requirements_for_match
from .brackets import athlete_ids_involved, build_division_detail
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
from .schedule_ops import (
    assign_referees_to_schedule,
    build_coordination_board,
    diff_referee_assignments,
    enrich_schedule_changes,
)
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
    affected_match = _find_affected_match(affected_detail, request, tournament) if affected_detail else None

    if affected_event and affected_detail and affected_match and request.emergency_type == "coach_conflict":
        queue_repair = try_local_queue_repair(
            tournament=tournament,
            original_schedule=original_schedule,
            request=request,
            availability=availability,
            affected_event=affected_event,
            affected_match=affected_match,
        )
        if queue_repair:
            repaired_schedule, changed_events, replacement_event, replacement_match, changed_matches = queue_repair
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
                notifications=_repair_notifications(affected_match, replacement_match, "local ring queue repair"),
                validation=validate_snapshot(tournament=tournament, schedule=repaired_schedule, demo_mode=True),
                division_detail=build_division_detail(
                    tournament,
                    repaired_schedule,
                    affected_event.division_id,
                    request.current_minute,
                    focus_match_id=affected_match.match_id,
                ),
                operational_minute=request.current_minute,
                summary_reason=_reason_for_request(request),
            )

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
            changed_events = [
                ChangedEvent(
                    event_id=affected_event.event_id,
                    changes=["match_order_changed"],
                    original_ring_id=affected_event.ring_id,
                    new_ring_id=affected_event.ring_id,
                    original_referee_crew_id=affected_event.referee_crew_id,
                    new_referee_crew_id=affected_event.referee_crew_id,
                    original_start_minute=affected_event.start_minute,
                    new_start_minute=affected_event.start_minute,
                )
            ]
            return _response(
                tournament=tournament,
                original_schedule=original_schedule,
                repaired_schedule=original_schedule,
                strategy="same_division_match_swap",
                affected_match=affected_match,
                replacement_match=_match_by_id(repaired_detail, replacement.match_id),
                changed_events=changed_events,
                changed_matches=changed_matches,
                resource_locations=_resource_locations(availability, request),
                notifications=_repair_notifications(affected_match, replacement, "same division match swap"),
                validation=validate_snapshot(tournament=tournament, schedule=original_schedule, demo_mode=True),
                division_detail=repaired_detail,
                operational_minute=request.current_minute,
                summary_reason=_reason_for_request(request),
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
                validation=validate_snapshot(tournament=tournament, schedule=repaired_schedule, demo_mode=True),
                division_detail=affected_detail,
                operational_minute=request.current_minute,
                summary_reason=_reason_for_request(request),
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
            validation=validate_snapshot(tournament=tournament, schedule=repaired_schedule, demo_mode=True),
            division_detail=affected_detail,
            operational_minute=request.current_minute,
            summary_reason=_reason_for_request(request),
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
        validation=validate_snapshot(tournament=tournament, schedule=repaired_schedule, demo_mode=True),
        division_detail=affected_detail,
        operational_minute=request.current_minute,
        summary_reason=_reason_for_request(request),
    )


def try_local_queue_repair(
    *,
    tournament: Tournament,
    original_schedule: list[RingSchedule],
    request: RepairRequest,
    availability: AvailabilityIndex,
    affected_event: ScheduledEvent,
    affected_match: Match,
    scan_limit: int = 5,
) -> tuple[list[RingSchedule], list[ChangedEvent], ScheduledEvent, Match, list[ChangedMatch]] | None:
    """Rotate a small same-ring queue window so ready work runs while one coach is delayed."""
    if request.emergency_type != "coach_conflict" or not request.coach_id:
        return None

    ring = next((row for row in original_schedule if row.ring_id == affected_event.ring_id), None)
    if not ring:
        return None

    ring_events = sorted(ring.events, key=lambda row: (row.start_minute, row.event_id))
    try:
        affected_index = next(index for index, event in enumerate(ring_events) if event.event_id == affected_event.event_id)
    except StopIteration:
        return None

    protected_before = ring_events[:affected_index]
    queue_after = ring_events[affected_index + 1 : affected_index + 1 + scan_limit]
    cursor = affected_event.start_minute
    move_forward: list[tuple[ScheduledEvent, Match, int, int]] = []
    local_event_ids = {affected_event.event_id}
    local_match_ids = {affected_match.match_id}
    blocked_until = request.current_minute + max(1, request.delay_minutes)

    for candidate in queue_after:
        if len(move_forward) >= scan_limit:
            break
        if candidate.start_minute - affected_event.start_minute > max(60, request.delay_minutes * 3):
            break
        ready_match = _first_ready_match_for_event(
            tournament=tournament,
            schedule=original_schedule,
            event=candidate,
            request=request,
            availability=availability,
            slot_start=cursor,
            allowed_event_ids=local_event_ids,
            allowed_match_ids=local_match_ids,
        )
        if not ready_match:
            continue

        duration = candidate.end_minute - candidate.start_minute
        local_event_ids.add(candidate.event_id)
        local_match_ids.add(ready_match.match_id)
        move_forward.append((candidate, ready_match, cursor, cursor + duration))
        cursor += duration
        if cursor >= blocked_until:
            break

    if not move_forward:
        return None

    affected_duration = affected_event.end_minute - affected_event.start_minute
    affected_new_start = max(cursor, blocked_until)
    affected_new_end = affected_new_start + affected_duration

    affected_requirements = _event_requirements(affected_event)
    if not _event_slot_is_feasible(
        schedule=original_schedule,
        event=affected_event,
        start_minute=affected_new_start,
        end_minute=affected_new_end,
        ignored_event_ids=local_event_ids,
    ):
        return None
    if availability.get_conflicts(affected_requirements, affected_new_start, affected_new_end):
        if not _conflicts_are_local(
            availability.get_conflicts(affected_requirements, affected_new_start, affected_new_end),
            local_event_ids,
            local_match_ids,
        ):
            return None

    timeline_overrides: dict[str, tuple[int, int]] = {
        affected_event.event_id: (affected_new_start, affected_new_end),
    }
    for event, _, start, end in move_forward:
        timeline_overrides[event.event_id] = (start, end)

    # If the delayed event no longer fits before the next untouched ring item, slide only the tiny local tail needed
    # to make the same-ring queue non-overlapping.
    affected_window_ids = set(timeline_overrides)
    last_end = max(end for _, end in timeline_overrides.values())
    shifted_tail: dict[str, tuple[int, int]] = {}
    for later in ring_events[affected_index + 1 :]:
        if later.event_id in affected_window_ids:
            continue
        if later.start_minute >= last_end:
            break
        duration = later.end_minute - later.start_minute
        if not _event_slot_is_feasible(
            schedule=original_schedule,
            event=later,
            start_minute=last_end,
            end_minute=last_end + duration,
            ignored_event_ids=set(timeline_overrides).union(shifted_tail),
        ):
            return None
        shifted_tail[later.event_id] = (last_end, last_end + duration)
        last_end += duration
        if len(shifted_tail) >= 2:
            break

    timeline_overrides.update(shifted_tail)

    repaired: list[RingSchedule] = []
    changed_events: list[ChangedEvent] = []
    for schedule_ring in original_schedule:
        updated_events: list[ScheduledEvent] = []
        for event in schedule_ring.events:
            updated = ScheduledEvent(**event.model_dump())
            override = timeline_overrides.get(event.event_id)
            if override:
                updated.start_minute, updated.end_minute = override
                changes = ["queue_reordered"]
                if updated.start_minute != event.start_minute:
                    changes.append("start_time_changed")
                changed_events.append(
                    ChangedEvent(
                        event_id=updated.event_id,
                        changes=changes,
                        original_ring_id=event.ring_id,
                        new_ring_id=updated.ring_id,
                        original_referee_crew_id=event.referee_crew_id,
                        new_referee_crew_id=updated.referee_crew_id,
                        original_start_minute=event.start_minute,
                        new_start_minute=updated.start_minute,
                    )
                )
            updated_events.append(updated)
        repaired.append(
            RingSchedule(
                ring_id=schedule_ring.ring_id,
                ring_name=schedule_ring.ring_name,
                events=sorted(updated_events, key=lambda row: (row.start_minute, row.event_id)),
            )
        )

    replacement_event, replacement_match, replacement_start, _ = move_forward[0]
    changed_matches = [
        ChangedMatch(
            match_id=affected_match.match_id,
            change_type="same_ring_queue_repair",
            original_start_minute=affected_match.start_minute,
            new_start_minute=affected_new_start,
            original_status=affected_match.status,
            new_status="waiting",
            reason=_reason_for_request(request),
        ),
        ChangedMatch(
            match_id=replacement_match.match_id,
            change_type="same_ring_queue_repair",
            original_start_minute=replacement_match.start_minute,
            new_start_minute=replacement_start,
            original_status=replacement_match.status,
            new_status="in_progress" if replacement_start <= request.current_minute < replacement_match.end_minute else replacement_match.status,
            reason=_reason_for_request(request),
        ),
    ]

    return repaired, sorted(changed_events, key=lambda row: (row.original_start_minute, row.event_id)), replacement_event, replacement_match, changed_matches


def _first_ready_match_for_event(
    *,
    tournament: Tournament,
    schedule: list[RingSchedule],
    event: ScheduledEvent,
    request: RepairRequest,
    availability: AvailabilityIndex,
    slot_start: int,
    allowed_event_ids: set[str],
    allowed_match_ids: set[str],
) -> Match | None:
    detail = build_division_detail(tournament, schedule, event.division_id, request.current_minute)
    duration = event.end_minute - event.start_minute
    slot_end = slot_start + duration
    for match in detail.bracket.matches:
        if match.status not in {"waiting", "staging"}:
            continue
        if not _bracket_dependencies_ready(detail, match):
            continue
        coach_ids = coach_ids_for_match(tournament, match)
        if _match_uses_blocked_resource(match, coach_ids, event.referee_crew_id, request):
            continue
        requirements = _event_requirements(event)
        if not _event_slot_is_feasible(
            schedule=schedule,
            event=event,
            start_minute=slot_start,
            end_minute=slot_end,
            ignored_event_ids=allowed_event_ids.union({event.event_id}),
        ):
            continue
        conflicts = availability.get_conflicts(requirements, slot_start, slot_end)
        if _conflicts_are_local(conflicts, allowed_event_ids.union({event.event_id}), allowed_match_ids.union({match.match_id})):
            return match
    return None


def _event_requirements(event: ScheduledEvent) -> dict[str, list[str]]:
    req: dict[str, list[str]] = {
        "athlete": list(event.athlete_ids),
        "coach": list(event.required_coach_ids),
        "referee_crew": [event.referee_crew_id],
        "ring": [event.ring_id],
    }
    if event.assigned_referee_ids:
        req["referee"] = list(event.assigned_referee_ids)
    return req


def _event_slot_is_feasible(
    *,
    schedule: list[RingSchedule],
    event: ScheduledEvent,
    start_minute: int,
    end_minute: int,
    ignored_event_ids: set[str],
) -> bool:
    event_referees = set(event.assigned_referee_ids)
    for ring in schedule:
        for other in ring.events:
            if other.event_id == event.event_id or other.event_id in ignored_event_ids:
                continue
            if other.end_minute <= start_minute or end_minute <= other.start_minute:
                continue
            if other.ring_id == event.ring_id:
                return False
            if other.referee_crew_id == event.referee_crew_id:
                return False
            if set(other.athlete_ids).intersection(event.athlete_ids):
                return False
            if set(other.required_coach_ids).intersection(event.required_coach_ids):
                return False
            if event_referees and event_referees.intersection(other.assigned_referee_ids):
                return False
    return True


def _conflicts_are_local(
    conflicts,
    local_event_ids: set[str],
    local_match_ids: set[str],
) -> bool:
    local_reasons = set(local_event_ids).union(local_match_ids).union({"warmup", "holding"})
    return all(conflict.reason in local_reasons or conflict.reason.startswith("staging for ") for conflict in conflicts)


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


def _find_affected_match(detail: DivisionDetail | None, request: RepairRequest, tournament: Tournament | None = None) -> Match | None:
    if not detail:
        return None
    candidates = [
        match
        for match in detail.bracket.matches
        if match.end_minute > request.current_minute
        and (match.status in {"in_progress", "staging"} or match.start_minute >= request.current_minute)
    ]
    for match in candidates:
        competitor_ids = set(athlete_ids_involved(match))
        if request.athlete_id and request.athlete_id not in competitor_ids:
            continue
        if request.coach_id and tournament and request.coach_id not in coach_ids_for_match(tournament, match):
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
        requirements = resource_requirements_for_match(match, match_coach_ids, event.referee_crew_id, event.assigned_referee_ids)
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
        if event.start_minute - affected_event.start_minute > max(60, request.delay_minutes * 3):
            break
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
            requirements = resource_requirements_for_match(match, match_coach_ids, event.referee_crew_id, event.assigned_referee_ids)
            ignored = {affected_event.event_id, event.event_id}
            event_duration = event.end_minute - event.start_minute
            affected_duration = affected_event.end_minute - affected_event.start_minute
            if (
                _available_for_current_slot(availability, requirements, affected_match)
                and _event_slot_is_feasible(
                    schedule=schedule,
                    event=event,
                    start_minute=affected_event.start_minute,
                    end_minute=affected_event.start_minute + event_duration,
                    ignored_event_ids=ignored,
                )
                and _event_slot_is_feasible(
                    schedule=schedule,
                    event=affected_event,
                    start_minute=event.start_minute,
                    end_minute=event.start_minute + affected_duration,
                    ignored_event_ids=ignored,
                )
            ):
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
    competitor_ids = set(athlete_ids_involved(match))
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
    operational_minute: int = 60,
    summary_reason: str = "match repair adjustment",
) -> RepairDemoResponse:
    baseline_schedule = assign_referees_to_schedule(tournament, original_schedule) if tournament.referees else original_schedule
    hydrated_repair = assign_referees_to_schedule(tournament, repaired_schedule) if tournament.referees else repaired_schedule
    hydrated_repair = _annotate_schedule_changes(hydrated_repair, changed_events)
    referee_moves = (
        diff_referee_assignments(
            tournament,
            baseline_schedule,
            hydrated_repair,
            reason=summary_reason,
        )
        if tournament.referees
        else []
    )

    enriched = enrich_schedule_changes(
        tournament,
        prior_schedule=baseline_schedule,
        next_schedule=hydrated_repair,
        changed_events=changed_events,
        reason=summary_reason or strategy.replace("_", " "),
    )
    coordinator = build_coordination_board(
        tournament,
        hydrated_repair,
        operational_minute,
        published_schedule=baseline_schedule,
    )

    changed_count, average_delay, max_delay = _repair_metrics(changed_events, changed_matches)
    return RepairDemoResponse(
        original_schedule=baseline_schedule,
        repaired_schedule=hydrated_repair,
        repair_strategy_used=strategy,
        affected_match=affected_match,
        replacement_match=replacement_match,
        changed_events=changed_events,
        changed_matches=changed_matches,
        resource_locations=resource_locations,
        notifications=notifications,
        validation=validation,
        division_detail=division_detail,
        schedule_changes=enriched,
        referee_adjustments=referee_moves,
        coordination_board=coordinator,
        current_minute=operational_minute,
        changed_match_count=changed_count,
        average_delay_minutes=average_delay,
        max_delay_minutes=max_delay,
        queue_repair_applied=strategy in {"same_ring_match_swap", "same_division_match_swap"},
    )


def _annotate_schedule_changes(schedule: list[RingSchedule], changed_events: list[ChangedEvent]) -> list[RingSchedule]:
    changed_by_id = {row.event_id: row for row in changed_events}
    annotated: list[RingSchedule] = []
    for ring in schedule:
        ring_events: list[ScheduledEvent] = []
        for event in ring.events:
            change = changed_by_id.get(event.event_id)
            if change:
                delay = max(0, change.new_start_minute - change.original_start_minute)
                ring_events.append(
                    event.model_copy(
                        update={
                            "is_rescheduled": True,
                            "original_ring_id": change.original_ring_id,
                            "original_start_minute": change.original_start_minute,
                            "delay_minutes": delay,
                            "changed_fields": list(change.changes),
                        }
                    )
                )
            else:
                ring_events.append(
                    event.model_copy(
                        update={
                            "is_rescheduled": False,
                            "original_ring_id": event.original_ring_id,
                            "original_start_minute": event.original_start_minute,
                            "delay_minutes": 0,
                            "changed_fields": [],
                        }
                    )
                )
        annotated.append(RingSchedule(ring_id=ring.ring_id, ring_name=ring.ring_name, events=ring_events))
    return annotated


def _repair_metrics(changed_events: list[ChangedEvent], changed_matches: list[ChangedMatch]) -> tuple[int, float, int]:
    if changed_matches:
        delays = [max(0, row.new_start_minute - row.original_start_minute) for row in changed_matches]
    else:
        delays = [max(0, row.new_start_minute - row.original_start_minute) for row in changed_events]
    changed_count = len(changed_matches) if changed_matches else len(changed_events)
    average_delay = round(sum(delays) / len(delays), 1) if delays else 0.0
    max_delay = max(delays) if delays else 0
    return changed_count, average_delay, max_delay
