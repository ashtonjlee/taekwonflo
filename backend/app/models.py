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


class RefereeCrew(BaseModel):
    id: str
    name: str


class Division(BaseModel):
    id: str
    name: str
    event_type: Literal["kyorugi", "poomsae", "team_poomsae"]
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
