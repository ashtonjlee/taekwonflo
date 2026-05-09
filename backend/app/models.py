from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Ring(BaseModel):
    id: str
    name: str


class Team(BaseModel):
    id: str
    name: str
    coach_ids: list[str]


class Coach(BaseModel):
    id: str
    name: str
    team_id: str


class Athlete(BaseModel):
    id: str
    name: str
    team_id: str
    coach_ids: list[str]
    age_group: Literal["peewee", "cadet", "junior", "senior"] = "junior"
    gender: Literal["male", "female"] = "male"
    belt_level: Literal["color_belt", "black_belt", "world_class"] = "black_belt"


class RefereeCrew(BaseModel):
    id: str
    name: str


class Division(BaseModel):
    id: str
    name: str
    event_type: Literal["kyorugi", "poomsae", "team_poomsae"]
    age_group: Literal["peewee", "cadet", "junior", "senior"] = "junior"
    gender: Literal["male", "female", "mixed"] = "mixed"
    weight_class: str = "Open"
    belt_level: Literal["color_belt", "black_belt", "world_class"] = "black_belt"
    bracket_type: Literal["single_elimination", "poomsae_rounds", "team_poomsae_rounds"] = "single_elimination"
    poomsae_rounds: list[str] = Field(default_factory=list)
    athlete_ids: list[str]
    team_ids: list[str]
    estimated_duration_minutes: int


class TournamentEvent(BaseModel):
    event_id: str
    division_id: str
    division_name: str
    event_type: Literal["kyorugi", "poomsae", "team_poomsae"]
    athlete_ids: list[str]
    team_ids: list[str]
    required_coach_ids: list[str]
    required_referee_count: int = Field(default=3, ge=1)
    estimated_duration_minutes: int = Field(ge=5)
    buffer_minutes: int = Field(default=5, ge=0)
    status: Literal["unscheduled", "scheduled", "in_progress", "completed", "delayed"]


class Tournament(BaseModel):
    id: str
    name: str
    rings: list[Ring]
    teams: list[Team]
    coaches: list[Coach]
    athletes: list[Athlete]
    divisions: list[Division]
    referee_crews: list[RefereeCrew]
    events: list[TournamentEvent]


class ScheduledEvent(BaseModel):
    event_id: str
    division_id: str
    division_name: str
    event_type: Literal["kyorugi", "poomsae", "team_poomsae"]
    ring_id: str
    ring_name: str
    referee_crew_id: str
    referee_crew_name: str
    start_minute: int = Field(ge=0)
    end_minute: int = Field(ge=0)
    estimated_duration_minutes: int = Field(ge=5)
    buffer_minutes: int = Field(default=5, ge=0)
    athlete_ids: list[str]
    team_ids: list[str]
    required_coach_ids: list[str]
    required_referee_count: int = Field(default=3, ge=1)
    status: Literal["scheduled", "in_progress", "completed", "delayed"]


class RingSchedule(BaseModel):
    ring_id: str
    ring_name: str
    events: list[ScheduledEvent]


class NotificationMessage(BaseModel):
    id: str
    channel: str
    text: str


class SnapshotResponse(BaseModel):
    tournament: Tournament
    schedule: list[RingSchedule]
    notifications: list[NotificationMessage]


class SnapshotValidationResponse(BaseModel):
    valid: bool
    errors: list[str]
    warnings: list[str]


class ChangedEvent(BaseModel):
    event_id: str
    changes: list[str]
    original_ring_id: str
    new_ring_id: str
    original_referee_crew_id: str
    new_referee_crew_id: str
    original_start_minute: int
    new_start_minute: int


class RescheduleDemoResponse(BaseModel):
    original_schedule: list[RingSchedule]
    rescheduled_schedule: list[RingSchedule]
    changed_events: list[ChangedEvent]
    notifications: list[NotificationMessage]
    validation: SnapshotValidationResponse


class MatchCompetitor(BaseModel):
    competitor_id: str
    name: str
    team_id: str
    team_name: str
    seed: int
    age_group: Literal["peewee", "cadet", "junior", "senior"]
    gender: Literal["male", "female"]
    belt_level: Literal["color_belt", "black_belt", "world_class"]


class MatchScore(BaseModel):
    competitor_1_points: int | None = None
    competitor_2_points: int | None = None
    competitor_1_poomsae: float | None = None
    competitor_2_poomsae: float | None = None
    winner_margin: str | None = None


class Match(BaseModel):
    match_id: str
    division_id: str
    round_name: str
    bracket_position: int
    competitor_1: MatchCompetitor
    competitor_2: MatchCompetitor | None = None
    winner_id: str | None = None
    score: MatchScore | None = None
    status: Literal["waiting", "staging", "in_progress", "completed"]
    scheduled_event_id: str
    ring_id: str
    start_minute: int
    end_minute: int
    estimated_duration_minutes: int
    required_referee_count: int = Field(default=3, ge=1)
    repair_note: str | None = None
    swapped_from_match_id: str | None = None


class Bracket(BaseModel):
    division_id: str
    bracket_type: Literal["single_elimination", "poomsae_rounds", "team_poomsae_rounds"]
    rounds: list[str]
    matches: list[Match]


class DivisionDetail(BaseModel):
    division: Division
    competitors: list[MatchCompetitor]
    bracket: Bracket
    current_match: Match | None
    waiting_competitors: list[MatchCompetitor]
    staging_competitors: list[MatchCompetitor]
    completed_matches: list[Match]
    advanced_competitors: list[MatchCompetitor]


class ResourceLocation(BaseModel):
    resource_type: str
    resource_id: str
    location: str
    reason: str | None = None
    until_minute: int | None = None


class ChangedMatch(BaseModel):
    match_id: str
    change_type: str
    original_start_minute: int
    new_start_minute: int
    original_status: str
    new_status: str
    reason: str


class RepairDemoResponse(BaseModel):
    original_schedule: list[RingSchedule]
    repaired_schedule: list[RingSchedule]
    repair_strategy_used: Literal[
        "same_division_match_swap",
        "same_ring_match_swap",
        "local_shift",
        "global_reschedule",
        "infeasible",
    ]
    affected_match: Match | None = None
    replacement_match: Match | None = None
    changed_events: list[ChangedEvent]
    changed_matches: list[ChangedMatch]
    resource_locations: list[ResourceLocation]
    notifications: list[NotificationMessage]
    validation: SnapshotValidationResponse
    division_detail: DivisionDetail | None = None
