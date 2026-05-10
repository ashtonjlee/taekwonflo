from __future__ import annotations

from dataclasses import dataclass

from .brackets import assigned_coach_ids_involved, athlete_ids_involved, build_division_detail
from .models import Match, RingSchedule, Tournament


@dataclass(frozen=True)
class ResourceInterval:
    resource_type: str
    resource_id: str
    start_minute: int
    end_minute: int
    reason: str
    location: str


class AvailabilityIndex:
    def __init__(self) -> None:
        self._intervals: dict[tuple[str, str], list[ResourceInterval]] = {}

    def add_interval(
        self,
        resource_type: str,
        resource_id: str,
        start_minute: int,
        end_minute: int,
        reason: str,
        location: str | None = None,
    ) -> None:
        interval = ResourceInterval(
            resource_type=resource_type,
            resource_id=resource_id,
            start_minute=start_minute,
            end_minute=end_minute,
            reason=reason,
            location=location or reason,
        )
        self._intervals.setdefault((resource_type, resource_id), []).append(interval)

    def is_available(self, resource_type: str, resource_id: str, start_minute: int, end_minute: int) -> bool:
        return not self._conflicts_for(resource_type, resource_id, start_minute, end_minute)

    def are_all_available(
        self,
        resource_requirements: dict[str, list[str]],
        start_minute: int,
        end_minute: int,
    ) -> bool:
        return not self.get_conflicts(resource_requirements, start_minute, end_minute)

    def get_conflicts(
        self,
        resource_requirements: dict[str, list[str]],
        start_minute: int,
        end_minute: int,
    ) -> list[ResourceInterval]:
        conflicts: list[ResourceInterval] = []
        for resource_type, resource_ids in resource_requirements.items():
            for resource_id in resource_ids:
                conflicts.extend(self._conflicts_for(resource_type, resource_id, start_minute, end_minute))
        return conflicts

    def get_location(self, resource_type: str, resource_id: str, current_minute: int) -> str:
        intervals = self._intervals.get((resource_type, resource_id), [])
        active = [
            interval
            for interval in intervals
            if interval.start_minute <= current_minute < interval.end_minute
        ]
        if not active:
            return "available"
        return sorted(active, key=lambda interval: interval.start_minute)[-1].location

    def get_active_interval(
        self,
        resource_type: str,
        resource_id: str,
        current_minute: int,
    ) -> ResourceInterval | None:
        intervals = self._intervals.get((resource_type, resource_id), [])
        active = [
            interval
            for interval in intervals
            if interval.start_minute <= current_minute < interval.end_minute
        ]
        if not active:
            return None
        return sorted(active, key=lambda interval: interval.start_minute)[-1]

    def _conflicts_for(
        self,
        resource_type: str,
        resource_id: str,
        start_minute: int,
        end_minute: int,
    ) -> list[ResourceInterval]:
        intervals = self._intervals.get((resource_type, resource_id), [])
        return [
            interval
            for interval in intervals
            if not (interval.end_minute <= start_minute or end_minute <= interval.start_minute)
        ]


def build_availability_index(
    tournament: Tournament,
    schedule: list[RingSchedule],
    current_minute: int = 60,
) -> AvailabilityIndex:
    """Build an availability index keyed to *match-level* start times.

    Staging / holding / warmup windows are anchored to each match's own start_minute,
    not the encompassing division event's start_minute. This is the change that lets
    later-round matches occupy earlier slots inside their own division during local
    repair without phantom conflicts (see docs/SCHEDULER_ARCHITECTURE_NOTES.md §2).
    """
    index = AvailabilityIndex()
    athlete_by_id = {athlete.id: athlete for athlete in tournament.athletes}
    event_by_id = {event.event_id: event for event in tournament.events}

    for ring in schedule:
        for event in ring.events:
            event_payload = event_by_id[event.source_event_id or event.event_id]
            matches = build_division_detail(
                tournament=tournament,
                schedule=schedule,
                division_id=event.division_id,
                current_minute=current_minute,
            ).bracket.matches
            for match in matches:
                requirements = resource_requirements_for_match(
                    match,
                    coach_ids_for_match(tournament, match),
                    event.referee_crew_id,
                    event.assigned_referee_ids,
                )
                _add_match_locations(index, match, requirements)
                # Use match.start_minute (not event.start_minute) so each match's staging
                # window is local to that match, not the whole division event.
                for athlete_id in athlete_ids_involved(match):
                    if athlete_id in athlete_by_id:
                        _add_staging_intervals(index, "athlete", athlete_id, match.start_minute, event.ring_id)
                for coach_id in assigned_coach_ids_involved(match):
                    _add_staging_intervals(index, "coach", coach_id, match.start_minute, event.ring_id)
            index.add_interval("ring", event.ring_id, event.start_minute, event.end_minute, event.event_id, event.ring_id)
            index.add_interval(
                "referee_crew",
                event.referee_crew_id,
                event.start_minute,
                event.end_minute,
                event.event_id,
                event.ring_id,
            )
    return index


def resource_requirements_for_match(
    match: Match,
    coach_ids: list[str],
    referee_crew_id: str,
    assigned_referee_ids: list[str] | None = None,
) -> dict[str, list[str]]:
    athlete_ids_list = athlete_ids_involved(match)
    req: dict[str, list[str]] = {
        "athlete": athlete_ids_list,
        "coach": coach_ids,
        "referee_crew": [referee_crew_id],
        "ring": [match.ring_id],
    }
    refs = assigned_referee_ids if assigned_referee_ids is not None else match.assigned_referee_ids
    if refs:
        req["referee"] = list(refs)
    return req


def coach_ids_for_match(tournament: Tournament, match: Match) -> list[str]:
    assigned = assigned_coach_ids_involved(match)
    if assigned:
        return assigned
    athlete_by_id = {athlete.id: athlete for athlete in tournament.athletes}
    fallback: set[str] = set()
    for roster_id in athlete_ids_involved(match):
        athlete_row = athlete_by_id.get(roster_id)
        if athlete_row and athlete_row.coach_ids:
            fallback.add(sorted(athlete_row.coach_ids)[0])
    return sorted(fallback)


def _add_match_locations(
    index: AvailabilityIndex,
    match: Match,
    requirements: dict[str, list[str]],
) -> None:
    for resource_type, resource_ids in requirements.items():
        for resource_id in resource_ids:
            index.add_interval(
                resource_type,
                resource_id,
                match.start_minute,
                match.end_minute,
                match.match_id,
                match.ring_id,
            )


def _add_staging_intervals(
    index: AvailabilityIndex,
    resource_type: str,
    resource_id: str,
    event_start_minute: int,
    ring_id: str,
) -> None:
    index.add_interval(resource_type, resource_id, max(0, event_start_minute - 30), max(0, event_start_minute - 15), "warmup", "warmup")
    index.add_interval(resource_type, resource_id, max(0, event_start_minute - 15), max(0, event_start_minute - 5), "holding", "holding")
    index.add_interval(resource_type, resource_id, max(0, event_start_minute - 5), event_start_minute, "staging", f"staging for {ring_id}")
