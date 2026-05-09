from __future__ import annotations

from dataclasses import dataclass

from .brackets import build_division_detail
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
    index = AvailabilityIndex()
    athlete_by_id = {athlete.id: athlete for athlete in tournament.athletes}
    event_by_id = {event.event_id: event for event in tournament.events}

    for ring in schedule:
        for event in ring.events:
            event_payload = event_by_id[event.event_id]
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
                )
                _add_match_locations(index, match, requirements)
            index.add_interval("ring", event.ring_id, event.start_minute, event.end_minute, event.event_id, event.ring_id)
            index.add_interval(
                "referee_crew",
                event.referee_crew_id,
                event.start_minute,
                event.end_minute,
                event.event_id,
                event.ring_id,
            )
            for athlete_id in event.athlete_ids:
                if athlete_id in athlete_by_id:
                    _add_staging_intervals(index, "athlete", athlete_id, event.start_minute, event.ring_id)
            for coach_id in event.required_coach_ids:
                _add_staging_intervals(index, "coach", coach_id, event.start_minute, event.ring_id)

    return index


def resource_requirements_for_match(
    match: Match,
    coach_ids: list[str],
    referee_crew_id: str,
) -> dict[str, list[str]]:
    athlete_ids = [match.competitor_1.competitor_id]
    if match.competitor_2:
        athlete_ids.append(match.competitor_2.competitor_id)
    return {
        "athlete": athlete_ids,
        "coach": coach_ids,
        "referee_crew": [referee_crew_id],
        "ring": [match.ring_id],
    }


def coach_ids_for_match(tournament: Tournament, match: Match) -> list[str]:
    athlete_by_id = {athlete.id: athlete for athlete in tournament.athletes}
    competitor_ids = [match.competitor_1.competitor_id]
    if match.competitor_2:
        competitor_ids.append(match.competitor_2.competitor_id)
    return sorted(
        {
            coach_id
            for athlete_id in competitor_ids
            for coach_id in athlete_by_id[athlete_id].coach_ids
        }
    )


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
