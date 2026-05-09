from __future__ import annotations

from typing import Annotated
from typing import Literal

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Query
from fastapi.middleware.cors import CORSMiddleware

from .brackets import build_division_detail
from .data_generator import generate_tournament
from .local_repair import RepairRequest, try_repair_next_match
from .models import DivisionDetail, RepairDemoResponse, RescheduleDemoResponse, SnapshotResponse, SnapshotValidationResponse
from .notifications import build_mock_notifications
from .rescheduler import EmergencyConfig, RescheduleError, reoptimize_future_events
from .scheduler import ScheduleError, build_optimized_schedule
from .validation import validate_snapshot

app = FastAPI(title="TaekwonFlo API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


def _pick_impactful_future_event(schedule: list, current_minute: int):
    future_events = [event for ring in schedule for event in ring.events if event.start_minute > current_minute]
    if not future_events:
        return None
    return min(future_events, key=lambda event: event.start_minute - current_minute)


def _resolve_emergency_defaults(
    *,
    emergency_type: Literal["medical_delay", "ring_pause", "referee_shortage", "coach_conflict"],
    current_minute: int,
    delay_minutes: int,
    ring_id: str | None,
    referee_crew_id: str | None,
    coach_id: str | None,
    pause_start_minute: int | None,
    pause_duration_minutes: int | None,
    unavailable_start_minute: int | None,
    unavailable_duration_minutes: int | None,
    tournament,
    schedule,
) -> dict[str, int | str | None]:
    impactful_event = _pick_impactful_future_event(schedule, current_minute)
    frozen_events = [
        event
        for ring in schedule
        for event in ring.events
        if event.end_minute <= current_minute or (event.start_minute <= current_minute < event.end_minute)
    ]

    resolved_delay = delay_minutes
    resolved_ring_id = ring_id
    resolved_referee_crew_id = referee_crew_id
    resolved_coach_id = coach_id
    resolved_pause_start = pause_start_minute if pause_start_minute is not None else current_minute
    resolved_pause_duration = pause_duration_minutes if pause_duration_minutes is not None else delay_minutes
    resolved_unavailable_start = unavailable_start_minute if unavailable_start_minute is not None else current_minute
    resolved_unavailable_duration = (
        unavailable_duration_minutes if unavailable_duration_minutes is not None else delay_minutes
    )

    if impactful_event:
        if emergency_type in {"medical_delay", "ring_pause"} and not resolved_ring_id:
            resolved_ring_id = impactful_event.ring_id
        if emergency_type == "referee_shortage" and not resolved_referee_crew_id:
            resolved_referee_crew_id = impactful_event.referee_crew_id
        if emergency_type == "coach_conflict" and not resolved_coach_id and impactful_event.required_coach_ids:
            resolved_coach_id = impactful_event.required_coach_ids[0]

        if emergency_type == "medical_delay" and delay_minutes == 20:
            min_needed_delay = max(1, impactful_event.start_minute - current_minute + 5)
            resolved_delay = max(delay_minutes, min_needed_delay)

        if emergency_type == "ring_pause" and pause_start_minute is None:
            resolved_pause_start = max(current_minute + 1, impactful_event.start_minute - 2)
        if emergency_type == "ring_pause" and pause_duration_minutes is None:
            resolved_pause_duration = max(
                delay_minutes,
                impactful_event.end_minute - resolved_pause_start + 2,
            )

        if emergency_type in {"referee_shortage", "coach_conflict"} and unavailable_start_minute is None:
            resolved_unavailable_start = max(current_minute + 1, impactful_event.start_minute - 2)
        if emergency_type in {"referee_shortage", "coach_conflict"} and unavailable_duration_minutes is None:
            resolved_unavailable_duration = max(
                delay_minutes,
                impactful_event.end_minute - resolved_unavailable_start + 2,
            )

    # Keep auto-picked windows out of frozen events so default demos are feasible.
    if emergency_type == "ring_pause" and resolved_ring_id:
        frozen_end = max(
            [event.end_minute for event in frozen_events if event.ring_id == resolved_ring_id],
            default=current_minute,
        )
        if pause_start_minute is None:
            resolved_pause_start = max(resolved_pause_start, frozen_end)
            if impactful_event and impactful_event.ring_id == resolved_ring_id and resolved_pause_start >= impactful_event.end_minute:
                resolved_pause_start = max(impactful_event.start_minute, frozen_end)
            if impactful_event and impactful_event.ring_id == resolved_ring_id and pause_duration_minutes is None:
                resolved_pause_duration = max(
                    resolved_pause_duration,
                    impactful_event.end_minute - resolved_pause_start + 2,
                )

    if emergency_type == "referee_shortage" and resolved_referee_crew_id:
        frozen_end = max(
            [event.end_minute for event in frozen_events if event.referee_crew_id == resolved_referee_crew_id],
            default=current_minute,
        )
        if unavailable_start_minute is None:
            resolved_unavailable_start = max(resolved_unavailable_start, frozen_end)
            if (
                impactful_event
                and impactful_event.referee_crew_id == resolved_referee_crew_id
                and resolved_unavailable_start >= impactful_event.end_minute
            ):
                resolved_unavailable_start = max(impactful_event.start_minute, frozen_end)
            if (
                impactful_event
                and impactful_event.referee_crew_id == resolved_referee_crew_id
                and unavailable_duration_minutes is None
            ):
                resolved_unavailable_duration = max(
                    resolved_unavailable_duration,
                    impactful_event.end_minute - resolved_unavailable_start + 2,
                )

    if emergency_type == "coach_conflict" and resolved_coach_id:
        frozen_end = max(
            [event.end_minute for event in frozen_events if resolved_coach_id in event.required_coach_ids],
            default=current_minute,
        )
        if unavailable_start_minute is None:
            resolved_unavailable_start = max(resolved_unavailable_start, frozen_end)
            if (
                impactful_event
                and resolved_coach_id in impactful_event.required_coach_ids
                and resolved_unavailable_start >= impactful_event.end_minute
            ):
                resolved_unavailable_start = max(impactful_event.start_minute, frozen_end)
            if (
                impactful_event
                and resolved_coach_id in impactful_event.required_coach_ids
                and unavailable_duration_minutes is None
            ):
                resolved_unavailable_duration = max(
                    resolved_unavailable_duration,
                    impactful_event.end_minute - resolved_unavailable_start + 2,
                )

    if not resolved_ring_id and tournament.rings:
        resolved_ring_id = tournament.rings[0].id
    if not resolved_referee_crew_id and tournament.referee_crews:
        resolved_referee_crew_id = tournament.referee_crews[0].id
    if not resolved_coach_id and tournament.coaches:
        resolved_coach_id = tournament.coaches[0].id

    return {
        "ring_id": resolved_ring_id,
        "referee_crew_id": resolved_referee_crew_id,
        "coach_id": resolved_coach_id,
        "delay_minutes": resolved_delay,
        "pause_start_minute": resolved_pause_start,
        "pause_duration_minutes": resolved_pause_duration,
        "unavailable_start_minute": resolved_unavailable_start,
        "unavailable_duration_minutes": resolved_unavailable_duration,
    }


@app.get("/api/mock/snapshot", response_model=SnapshotResponse)
def get_mock_snapshot(
    number_of_rings: Annotated[int, Query(ge=1, le=20)] = 3,
    number_of_athletes: Annotated[int, Query(ge=8, le=1000)] = 48,
    number_of_teams: Annotated[int, Query(ge=2, le=100)] = 8,
    number_of_referee_crews: Annotated[int, Query(ge=1, le=20)] = 4,
    seed: int = 42,
) -> SnapshotResponse:
    tournament = generate_tournament(
        number_of_rings=number_of_rings,
        number_of_athletes=number_of_athletes,
        number_of_teams=number_of_teams,
        number_of_referee_crews=number_of_referee_crews,
        seed=seed,
    )
    try:
        schedule = build_optimized_schedule(tournament)
    except ScheduleError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    notifications = build_mock_notifications(schedule)
    return SnapshotResponse(tournament=tournament, schedule=schedule, notifications=notifications)


@app.get("/api/schedule", response_model=SnapshotResponse)
def get_schedule(
    number_of_rings: Annotated[int, Query(ge=1, le=20)] = 3,
    number_of_athletes: Annotated[int, Query(ge=8, le=1000)] = 48,
    number_of_teams: Annotated[int, Query(ge=2, le=100)] = 8,
    number_of_referee_crews: Annotated[int, Query(ge=1, le=20)] = 4,
    seed: int = 42,
) -> SnapshotResponse:
    tournament = generate_tournament(
        number_of_rings=number_of_rings,
        number_of_athletes=number_of_athletes,
        number_of_teams=number_of_teams,
        number_of_referee_crews=number_of_referee_crews,
        seed=seed,
    )
    try:
        schedule = build_optimized_schedule(tournament)
    except ScheduleError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    notifications = build_mock_notifications(schedule)
    return SnapshotResponse(tournament=tournament, schedule=schedule, notifications=notifications)


@app.get("/api/validate/snapshot", response_model=SnapshotValidationResponse)
def validate_mock_snapshot(
    number_of_rings: Annotated[int, Query(ge=1, le=20)] = 3,
    number_of_athletes: Annotated[int, Query(ge=8, le=1000)] = 48,
    number_of_teams: Annotated[int, Query(ge=2, le=100)] = 8,
    number_of_referee_crews: Annotated[int, Query(ge=1, le=20)] = 4,
    seed: int = 42,
) -> SnapshotValidationResponse:
    tournament = generate_tournament(
        number_of_rings=number_of_rings,
        number_of_athletes=number_of_athletes,
        number_of_teams=number_of_teams,
        number_of_referee_crews=number_of_referee_crews,
        seed=seed,
    )
    try:
        schedule = build_optimized_schedule(tournament)
    except ScheduleError as error:
        return SnapshotValidationResponse(valid=False, errors=[str(error)], warnings=[])
    return validate_snapshot(tournament=tournament, schedule=schedule)


@app.get("/api/divisions/{division_id}/detail", response_model=DivisionDetail)
def get_division_detail(
    division_id: str,
    number_of_rings: Annotated[int, Query(ge=1, le=20)] = 3,
    number_of_athletes: Annotated[int, Query(ge=8, le=1000)] = 48,
    number_of_teams: Annotated[int, Query(ge=2, le=100)] = 8,
    number_of_referee_crews: Annotated[int, Query(ge=1, le=20)] = 4,
    seed: int = 42,
    current_minute: Annotated[int, Query(ge=0)] = 60,
) -> DivisionDetail:
    tournament = generate_tournament(
        number_of_rings=number_of_rings,
        number_of_athletes=number_of_athletes,
        number_of_teams=number_of_teams,
        number_of_referee_crews=number_of_referee_crews,
        seed=seed,
    )
    try:
        schedule = build_optimized_schedule(tournament)
        return build_division_detail(
            tournament=tournament,
            schedule=schedule,
            division_id=division_id,
            current_minute=current_minute,
        )
    except ScheduleError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except KeyError as error:
        raise HTTPException(status_code=404, detail=f"Division detail not found for '{division_id}'.") from error


@app.get("/api/repair/demo", response_model=RepairDemoResponse)
def repair_demo(
    number_of_rings: Annotated[int, Query(ge=1, le=20)] = 3,
    number_of_athletes: Annotated[int, Query(ge=8, le=1000)] = 48,
    number_of_teams: Annotated[int, Query(ge=2, le=100)] = 8,
    number_of_referee_crews: Annotated[int, Query(ge=1, le=20)] = 4,
    seed: int = 42,
    emergency_type: Literal["medical_delay", "ring_pause", "referee_shortage", "coach_conflict", "athlete_conflict"] = "coach_conflict",
    current_minute: Annotated[int, Query(ge=0)] = 60,
    coach_id: str | None = None,
    athlete_id: str | None = None,
    referee_crew_id: str | None = None,
    ring_id: str | None = None,
    delay_minutes: Annotated[int, Query(ge=1)] = 20,
) -> RepairDemoResponse:
    tournament = generate_tournament(
        number_of_rings=number_of_rings,
        number_of_athletes=number_of_athletes,
        number_of_teams=number_of_teams,
        number_of_referee_crews=number_of_referee_crews,
        seed=seed,
    )
    try:
        original_schedule = build_optimized_schedule(tournament)
    except ScheduleError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    return try_repair_next_match(
        tournament=tournament,
        original_schedule=original_schedule,
        request=RepairRequest(
            emergency_type=emergency_type,
            current_minute=current_minute,
            coach_id=coach_id,
            athlete_id=athlete_id,
            referee_crew_id=referee_crew_id,
            ring_id=ring_id,
            delay_minutes=delay_minutes,
        ),
    )


@app.get("/api/reschedule/demo", response_model=RescheduleDemoResponse)
def reschedule_demo(
    number_of_rings: Annotated[int, Query(ge=1, le=20)] = 3,
    number_of_athletes: Annotated[int, Query(ge=8, le=1000)] = 48,
    number_of_teams: Annotated[int, Query(ge=2, le=100)] = 8,
    number_of_referee_crews: Annotated[int, Query(ge=1, le=20)] = 4,
    seed: int = 42,
    emergency_type: Literal["medical_delay", "ring_pause", "referee_shortage", "coach_conflict"] = "medical_delay",
    ring_id: str | None = None,
    referee_crew_id: str | None = None,
    coach_id: str | None = None,
    current_minute: Annotated[int, Query(ge=0)] = 60,
    delay_minutes: Annotated[int, Query(ge=1)] = 20,
    pause_start_minute: int | None = None,
    pause_duration_minutes: int | None = None,
    unavailable_start_minute: int | None = None,
    unavailable_duration_minutes: int | None = None,
) -> RescheduleDemoResponse:
    tournament = generate_tournament(
        number_of_rings=number_of_rings,
        number_of_athletes=number_of_athletes,
        number_of_teams=number_of_teams,
        number_of_referee_crews=number_of_referee_crews,
        seed=seed,
    )
    try:
        original_schedule = build_optimized_schedule(tournament)
    except ScheduleError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    defaults = _resolve_emergency_defaults(
        emergency_type=emergency_type,
        current_minute=current_minute,
        delay_minutes=delay_minutes,
        ring_id=ring_id,
        referee_crew_id=referee_crew_id,
        coach_id=coach_id,
        pause_start_minute=pause_start_minute,
        pause_duration_minutes=pause_duration_minutes,
        unavailable_start_minute=unavailable_start_minute,
        unavailable_duration_minutes=unavailable_duration_minutes,
        tournament=tournament,
        schedule=original_schedule,
    )

    config = EmergencyConfig(
        emergency_type=emergency_type,
        current_minute=current_minute,
        ring_id=defaults["ring_id"],
        referee_crew_id=defaults["referee_crew_id"],
        coach_id=defaults["coach_id"],
        delay_minutes=int(defaults["delay_minutes"]),
        pause_start_minute=int(defaults["pause_start_minute"]),
        pause_duration_minutes=int(defaults["pause_duration_minutes"]),
        unavailable_start_minute=int(defaults["unavailable_start_minute"]),
        unavailable_duration_minutes=int(defaults["unavailable_duration_minutes"]),
    )

    try:
        rescheduled_schedule, changed_events = reoptimize_future_events(
            tournament=tournament,
            original_schedule=original_schedule,
            config=config,
        )
    except RescheduleError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    notifications = build_mock_notifications(rescheduled_schedule)
    validation = validate_snapshot(tournament=tournament, schedule=rescheduled_schedule)
    return RescheduleDemoResponse(
        original_schedule=original_schedule,
        rescheduled_schedule=rescheduled_schedule,
        changed_events=changed_events,
        notifications=notifications,
        validation=validation,
    )
