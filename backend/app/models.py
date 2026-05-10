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


class Referee(BaseModel):
    referee_id: str
    name: str
    home_crew_id: str
    current_crew_id: str | None = None
    qualifications: list[
        Literal["kyorugi", "poomsae", "center_referee", "judge", "corner"]
    ] = Field(default_factory=list)


class RefereeCrew(BaseModel):
    id: str
    name: str
    referee_ids: list[str] = Field(default_factory=list)


class Division(BaseModel):
    id: str
    name: str
    event_type: Literal["kyorugi", "poomsae", "pair_poomsae", "team_poomsae"]
    age_group: Literal["peewee", "cadet", "junior", "senior"] = "junior"
    gender: Literal["male", "female", "coed", "mixed"] = "mixed"
    weight_class: str = "Open"
    belt_level: Literal["color_belt", "black_belt", "world_class"] = "black_belt"
    belt_rank_group: Literal["color_belt", "black_belt", "world_class"] = "black_belt"
    bracket_type: Literal["single_elimination", "poomsae_rounds", "team_poomsae_rounds"] = "single_elimination"
    poomsae_rounds: list[str] = Field(default_factory=list)
    bracket_size: int = Field(default=0, ge=0)
    competitor_count: int = Field(default=0, ge=0)
    round_structure: list[str] = Field(default_factory=list)
    athlete_ids: list[str]
    team_ids: list[str]
    estimated_duration_minutes: int


class TournamentEvent(BaseModel):
    event_id: str
    division_id: str
    division_name: str
    event_type: Literal["kyorugi", "poomsae", "pair_poomsae", "team_poomsae"]
    athlete_ids: list[str]
    team_ids: list[str]
    required_coach_ids: list[str]
    assigned_referee_ids: list[str] = Field(default_factory=list)
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
    referees: list[Referee] = Field(default_factory=list)
    events: list[TournamentEvent]
    lunch_start_minute: int = Field(default=180, ge=0)
    lunch_duration_minutes: int = Field(default=60, ge=0)
    lunch_grace_minutes: int = Field(default=20, ge=0)


class ScheduledEvent(BaseModel):
    event_id: str
    division_id: str
    division_name: str
    event_type: Literal["kyorugi", "poomsae", "pair_poomsae", "team_poomsae"]
    ring_id: str
    ring_name: str
    referee_crew_id: str
    referee_crew_name: str
    assigned_referee_ids: list[str] = Field(default_factory=list)
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


CoordinatorPhase = Literal["warm_up_now", "report_holding", "report_staging", "currently_competing", "completed"]

CoordinatorUrgency = Literal["now", "soon", "later"]


class CoordinatorMatchRow(BaseModel):
    phase: CoordinatorPhase
    urgency: CoordinatorUrgency
    division_id: str
    division_name: str
    event_id: str
    ring_id: str
    ring_name: str
    match_id: str
    match_number: int
    round_name: str
    status: str
    start_minute: int
    end_minute: int
    athlete_display: list[str]
    team_names: list[str]
    coach_labels: list[str]


class CoordinationBoard(BaseModel):
    current_minute: int
    rows: list[CoordinatorMatchRow] = Field(default_factory=list)


class ScheduleChangeDetail(BaseModel):
    event_id: str
    division_id: str
    division_name: str
    summary_reason: str = ""
    original_ring_id: str
    new_ring_id: str
    original_ring_name: str = ""
    new_ring_name: str = ""
    original_referee_crew_id: str
    new_referee_crew_id: str
    original_referee_crew_name: str = ""
    new_referee_crew_name: str = ""
    original_start_minute: int
    new_start_minute: int
    changes: list[str] = Field(default_factory=list)
    original_assigned_referee_ids: list[str] = Field(default_factory=list)
    new_assigned_referee_ids: list[str] = Field(default_factory=list)
    coach_names_involved: list[str] = Field(default_factory=list)
    athlete_summaries: list[str] = Field(default_factory=list)
    match_breakdown: list[str] = Field(default_factory=list)
    affected_match_numbers: list[int] = Field(default_factory=list)


class RefereeAdjustment(BaseModel):
    referee_id: str
    referee_name: str
    home_crew_id: str
    from_crew_id: str
    from_crew_name: str = ""
    to_crew_id: str
    to_crew_name: str = ""
    ring_id: str = ""
    ring_name: str = ""
    window_start_minute: int | None = None
    window_end_minute: int | None = None
    scope: Literal["temporary", "rest_of_day"] = "temporary"
    reason: str = ""


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
    schedule_changes: list[ScheduleChangeDetail] = Field(default_factory=list)
    referee_adjustments: list[RefereeAdjustment] = Field(default_factory=list)
    coordination_board: CoordinationBoard | None = None


class MatchCompetitor(BaseModel):
    competitor_id: str
    name: str
    team_id: str
    team_name: str
    seed: int
    age_group: Literal["peewee", "cadet", "junior", "senior"]
    gender: Literal["male", "female"]
    belt_level: Literal["color_belt", "black_belt", "world_class"]
    coach_ids: list[str] = Field(default_factory=list)
    coach_names: list[str] = Field(default_factory=list)


class MatchScore(BaseModel):
    competitor_1_points: int | None = None
    competitor_2_points: int | None = None
    competitor_1_poomsae: float | None = None
    competitor_2_poomsae: float | None = None
    winner_margin: str | None = None


class Match(BaseModel):
    match_id: str
    division_id: str
    match_number: int = 0
    round_name: str
    bracket_position: int
    competitor_1: MatchCompetitor | None = None
    competitor_2: MatchCompetitor | None = None
    source_1_label: str | None = None
    source_2_label: str | None = None
    feeder_1_match_number: int | None = None
    feeder_2_match_number: int | None = None
    winner_id: str | None = None
    loser_id: str | None = None
    score: MatchScore | None = None
    status: Literal["waiting", "staging", "in_progress", "completed"]
    scheduled_event_id: str
    ring_id: str
    ring_name: str = ""
    start_minute: int
    end_minute: int
    estimated_duration_minutes: int
    required_referee_count: int = Field(default=3, ge=1)
    assigned_referee_ids: list[str] = Field(default_factory=list)
    repair_note: str | None = None
    swapped_from_match_id: str | None = None
    next_match_id: str | None = None
    bye: bool = False
    participant_athlete_ids: list[str] = Field(default_factory=list)


class Bracket(BaseModel):
    division_id: str
    bracket_type: Literal["single_elimination", "poomsae_rounds", "team_poomsae_rounds"]
    rounds: list[str]
    matches: list[Match]


class KyorugiBracketRound(BaseModel):
    round_name: str
    matches: list[Match]


class RankedBracketEntry(BaseModel):
    entry_id: str
    round_name: str
    display_name: str
    athlete_members: list[MatchCompetitor]
    team_id: str
    team_name: str
    coach_ids: list[str]
    coach_names: list[str]
    score_value: float | None = None
    rank_in_round: int
    advanced: bool
    final_placement: int | None = None
    status: Literal["waiting", "staging", "in_progress", "completed"]
    performance_match_id: str | None = None


class RankedBracketRound(BaseModel):
    round_name: str
    entries: list[RankedBracketEntry]


class CoachToReport(BaseModel):
    coach_id: str
    coach_name: str
    team_id: str
    team_name: str
    ring_id: str
    ring_name: str
    division_id: str
    division_name: str
    related_display: str
    related_entry_id: str | None = None
    status: Literal["report_now", "in_holding", "waiting", "currently_coaching", "done"]


class DivisionDetailValidation(BaseModel):
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    valid: bool = True


class DivisionDetail(BaseModel):
    division: Division
    competitors: list[MatchCompetitor]
    bracket: Bracket
    current_match: Match | None
    waiting_competitors: list[MatchCompetitor]
    staging_competitors: list[MatchCompetitor]
    completed_matches: list[Match]
    advanced_competitors: list[MatchCompetitor]
    kyorugi_rounds: list[KyorugiBracketRound] = Field(default_factory=list)
    ranked_rounds: list[RankedBracketRound] = Field(default_factory=list)
    coach_report: list[CoachToReport] = Field(default_factory=list)
    detail_validation: DivisionDetailValidation = Field(default_factory=DivisionDetailValidation)
    focused_match_id: str | None = None


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
    schedule_changes: list[ScheduleChangeDetail] = Field(default_factory=list)
    referee_adjustments: list[RefereeAdjustment] = Field(default_factory=list)
    coordination_board: CoordinationBoard | None = None
