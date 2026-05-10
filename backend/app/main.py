from __future__ import annotations

from typing import Annotated
from typing import Literal

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Query
from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel, Field

from .brackets import build_division_detail
from .data_generator import generate_tournament
from .demo_scenarios import find_impactful_demo_scenario
from .local_repair import RepairRequest, try_repair_next_match
from .match_numbers import build_published_match_number_map
from .models import ChangedEvent, DivisionDetail, RepairDemoResponse, RescheduleDemoResponse, RingSchedule, SnapshotResponse, SnapshotValidationResponse, Tournament
from .notifications import build_mock_notifications
from .rescheduler import EmergencyConfig, RescheduleError, reoptimize_future_events
from .scheduler import ScheduleError, build_optimized_schedule
from .schedule_ops import (
    assign_referees_to_schedule,
    assign_referees_to_schedule_with_unavailability,
    build_coordination_board,
    diff_referee_assignments,
    enrich_schedule_changes,
    summarize_ring_operations,
)
from .validation import validate_snapshot

app = FastAPI(title="TaekwonFlo API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class LiveOperationsRequest(BaseModel):
    tournament: Tournament
    schedule: list[RingSchedule]
    original_schedule: list[RingSchedule] | None = None
    current_minute: int = Field(default=0, ge=0)
    changed_events: list[ChangedEvent] = Field(default_factory=list)


@app.post("/api/operations/live")
def live_operations_dashboard(payload: LiveOperationsRequest) -> dict[str, object]:
    published_schedule = payload.original_schedule or payload.schedule
    stable_match_numbers = build_published_match_number_map(payload.tournament, published_schedule)
    board = build_coordination_board(
        payload.tournament,
        payload.schedule,
        payload.current_minute,
        published_schedule=published_schedule,
        match_number_by_match_id=stable_match_numbers,
    )
    hints = {
        ring.id: summarize_ring_operations(
            tournament=payload.tournament,
            ring_id=ring.id,
            schedule=payload.schedule,
            changed_event_rows=payload.changed_events,
            current_minute=payload.current_minute,
            published_schedule=published_schedule,
            match_number_by_match_id=stable_match_numbers,
        )
        for ring in payload.tournament.rings
    }
    return {"coordination_board": board.model_dump(), "ring_hints": hints}


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


def _is_meaningful_referee_adjustment(move) -> bool:
    return not (
        move.from_crew_id == move.to_crew_id
        and move.from_ring_id == move.to_ring_id
        and move.from_window_start_minute == move.window_start_minute
        and move.from_window_end_minute == move.window_end_minute
    )


def _annotate_schedule_for_gantt(
    tournament: Tournament,
    schedule: list[RingSchedule],
    changed_events: list[ChangedEvent],
    coordination_board,
) -> list[RingSchedule]:
    division_by_id = {division.id: division for division in tournament.divisions}
    changed_by_event = {row.event_id: row for row in changed_events}
    event_match_number: dict[str, int] = {}
    for row in (coordination_board.rows if coordination_board else []):
        event_match_number.setdefault(row.event_id, row.match_number)

    annotated: list[RingSchedule] = []
    for ring in schedule:
        ring_events = []
        for event in ring.events:
            div = division_by_id.get(event.division_id)
            change = changed_by_event.get(event.event_id)
            ring_events.append(
                event.model_copy(
                    update={
                        "age_group": (div.age_group if div else event.age_group),
                        "belt_rank_group": (div.belt_rank_group if div else event.belt_rank_group),
                        "weight_class": (div.weight_class if div else event.weight_class),
                        "match_number": event_match_number.get(event.event_id),
                        "is_rescheduled": change is not None,
                        "original_ring_id": change.original_ring_id if change else None,
                        "original_start_minute": change.original_start_minute if change else None,
                        "delay_minutes": max(0, change.new_start_minute - change.original_start_minute) if change else 0,
                        "changed_fields": list(change.changes) if change else [],
                    }
                )
            )
        annotated.append(RingSchedule(ring_id=ring.ring_id, ring_name=ring.ring_name, events=ring_events))
    return annotated


def _change_metrics(changed_events: list[ChangedEvent]) -> tuple[int, float, int]:
    delays = [max(0, row.new_start_minute - row.original_start_minute) for row in changed_events]
    average_delay = round(sum(delays) / len(delays), 1) if delays else 0.0
    max_delay = max(delays) if delays else 0
    return len(changed_events), average_delay, max_delay


@app.get("/api/mock/snapshot", response_model=SnapshotResponse)
def get_mock_snapshot(
    number_of_rings: Annotated[int, Query(ge=1, le=20)] = 5,
    number_of_athletes: Annotated[int, Query(ge=8, le=1000)] = 360,
    number_of_teams: Annotated[int, Query(ge=2, le=100)] = 24,
    number_of_referee_crews: Annotated[int, Query(ge=1, le=20)] = 10,
    number_of_divisions: Annotated[int, Query(ge=1, le=200)] = 61,
    target_tournament_minutes: Annotated[int, Query(ge=120, le=900)] = 480,
    seed: int = 42,
) -> SnapshotResponse:
    tournament = generate_tournament(
        number_of_rings=number_of_rings,
        number_of_athletes=number_of_athletes,
        number_of_teams=number_of_teams,
        number_of_referee_crews=number_of_referee_crews,
        number_of_divisions=number_of_divisions,
        target_tournament_minutes=target_tournament_minutes,
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
    number_of_rings: Annotated[int, Query(ge=1, le=20)] = 5,
    number_of_athletes: Annotated[int, Query(ge=8, le=1000)] = 360,
    number_of_teams: Annotated[int, Query(ge=2, le=100)] = 24,
    number_of_referee_crews: Annotated[int, Query(ge=1, le=20)] = 10,
    number_of_divisions: Annotated[int, Query(ge=1, le=200)] = 61,
    target_tournament_minutes: Annotated[int, Query(ge=120, le=900)] = 480,
    seed: int = 42,
) -> SnapshotResponse:
    tournament = generate_tournament(
        number_of_rings=number_of_rings,
        number_of_athletes=number_of_athletes,
        number_of_teams=number_of_teams,
        number_of_referee_crews=number_of_referee_crews,
        number_of_divisions=number_of_divisions,
        target_tournament_minutes=target_tournament_minutes,
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
    number_of_rings: Annotated[int, Query(ge=1, le=20)] = 5,
    number_of_athletes: Annotated[int, Query(ge=8, le=1000)] = 360,
    number_of_teams: Annotated[int, Query(ge=2, le=100)] = 24,
    number_of_referee_crews: Annotated[int, Query(ge=1, le=20)] = 10,
    number_of_divisions: Annotated[int, Query(ge=1, le=200)] = 61,
    target_tournament_minutes: Annotated[int, Query(ge=120, le=900)] = 480,
    seed: int = 42,
) -> SnapshotValidationResponse:
    tournament = generate_tournament(
        number_of_rings=number_of_rings,
        number_of_athletes=number_of_athletes,
        number_of_teams=number_of_teams,
        number_of_referee_crews=number_of_referee_crews,
        number_of_divisions=number_of_divisions,
        target_tournament_minutes=target_tournament_minutes,
        seed=seed,
    )
    try:
        schedule = build_optimized_schedule(tournament)
    except ScheduleError as error:
        return SnapshotValidationResponse(valid=False, errors=[str(error)], warnings=[])
    return validate_snapshot(tournament=tournament, schedule=schedule, demo_mode=True)


@app.get("/api/divisions/{division_id}/detail", response_model=DivisionDetail)
def get_division_detail(
    division_id: str,
    number_of_rings: Annotated[int, Query(ge=1, le=20)] = 5,
    number_of_athletes: Annotated[int, Query(ge=8, le=1000)] = 360,
    number_of_teams: Annotated[int, Query(ge=2, le=100)] = 24,
    number_of_referee_crews: Annotated[int, Query(ge=1, le=20)] = 10,
    number_of_divisions: Annotated[int, Query(ge=1, le=200)] = 61,
    target_tournament_minutes: Annotated[int, Query(ge=120, le=900)] = 480,
    seed: int = 42,
    current_minute: Annotated[int, Query(ge=0)] = 60,
    focus_match_id: Annotated[str | None, Query()] = None,
) -> DivisionDetail:
    tournament = generate_tournament(
        number_of_rings=number_of_rings,
        number_of_athletes=number_of_athletes,
        number_of_teams=number_of_teams,
        number_of_referee_crews=number_of_referee_crews,
        number_of_divisions=number_of_divisions,
        target_tournament_minutes=target_tournament_minutes,
        seed=seed,
    )
    try:
        schedule = build_optimized_schedule(tournament)
        stable_match_numbers = build_published_match_number_map(tournament, schedule)
        return build_division_detail(
            tournament=tournament,
            schedule=schedule,
            division_id=division_id,
            current_minute=current_minute,
            focus_match_id=focus_match_id,
            match_number_by_match_id=stable_match_numbers,
        )
    except ScheduleError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except KeyError as error:
        raise HTTPException(status_code=404, detail=f"Division detail not found for '{division_id}'.") from error


@app.get("/api/repair/demo", response_model=RepairDemoResponse)
def repair_demo(
    number_of_rings: Annotated[int, Query(ge=1, le=20)] = 5,
    number_of_athletes: Annotated[int, Query(ge=8, le=1000)] = 360,
    number_of_teams: Annotated[int, Query(ge=2, le=100)] = 24,
    number_of_referee_crews: Annotated[int, Query(ge=1, le=20)] = 10,
    number_of_divisions: Annotated[int, Query(ge=1, le=200)] = 61,
    target_tournament_minutes: Annotated[int, Query(ge=120, le=900)] = 480,
    seed: int = 42,
    emergency_type: Literal["medical_delay", "ring_pause", "referee_shortage", "coach_conflict", "athlete_conflict"] = "coach_conflict",
    scripted: bool = True,
    current_minute: Annotated[int, Query(ge=0)] = 0,
    coach_id: str | None = None,
    athlete_id: str | None = None,
    referee_crew_id: str | None = None,
    ring_id: str | None = None,
    delay_minutes: Annotated[int, Query(ge=1)] = 20,
) -> RepairDemoResponse:
    def _decorate(response: RepairDemoResponse, *, reason: str) -> RepairDemoResponse:
        impactful = bool(response.changed_matches or response.changed_events)
        return response.model_copy(
            update={
                "demo_was_impactful": impactful,
                "demo_scenario_reason": reason,
                "no_op_reason": (None if impactful else "No swap/shift was possible in this deterministic scenario."),
            }
        )

    def _run_for_seed(active_seed: int, request: RepairRequest, reason: str) -> RepairDemoResponse:
        tournament = generate_tournament(
            number_of_rings=number_of_rings,
            number_of_athletes=number_of_athletes,
            number_of_teams=number_of_teams,
            number_of_referee_crews=number_of_referee_crews,
            number_of_divisions=number_of_divisions,
            target_tournament_minutes=target_tournament_minutes,
            seed=active_seed,
        )
        try:
            original_schedule = build_optimized_schedule(tournament)
        except ScheduleError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        response = try_repair_next_match(
            tournament=tournament,
            original_schedule=original_schedule,
            request=request,
        )
        return _decorate(response, reason=reason)

    if emergency_type == "coach_conflict" and scripted and not coach_id:
        fallback_response: RepairDemoResponse | None = None
        fallback_reason = "Fallback scripted coach-delay scenario."
        for active_seed in [seed, 7, 19]:
            tournament = generate_tournament(
                number_of_rings=number_of_rings,
                number_of_athletes=number_of_athletes,
                number_of_teams=number_of_teams,
                number_of_referee_crews=number_of_referee_crews,
                number_of_divisions=number_of_divisions,
                target_tournament_minutes=target_tournament_minutes,
                seed=active_seed,
            )
            try:
                original_schedule = build_optimized_schedule(tournament)
            except ScheduleError:
                continue
            scenario = find_impactful_demo_scenario(
                tournament=tournament,
                original_schedule=original_schedule,
                emergency_type="coach_conflict",
                default_current_minute=current_minute,
                default_delay_minutes=delay_minutes,
            )
            candidate = _decorate(
                try_repair_next_match(
                    tournament=tournament,
                    original_schedule=original_schedule,
                    request=RepairRequest(
                        emergency_type="coach_conflict",
                        current_minute=scenario.current_minute,
                        coach_id=scenario.coach_id,
                        athlete_id=athlete_id,
                        referee_crew_id=referee_crew_id,
                        ring_id=ring_id or scenario.ring_id,
                        delay_minutes=delay_minutes,
                    ),
                ),
                reason=f"{scenario.reason} (seed {active_seed})",
            )
            if candidate.demo_was_impactful and candidate.repair_strategy_used != "global_reschedule":
                return candidate
            if fallback_response is None:
                fallback_response = candidate
                fallback_reason = f"{scenario.reason} (seed {active_seed})"
        if fallback_response is not None:
            return fallback_response.model_copy(
                update={
                    "demo_scenario_reason": fallback_reason,
                    "no_op_reason": "No impactful swap/shift found after scripted seed/window fallback.",
                }
            )

    request = RepairRequest(
        emergency_type=emergency_type,
        current_minute=current_minute,
        coach_id=coach_id,
        athlete_id=athlete_id,
        referee_crew_id=referee_crew_id,
        ring_id=ring_id,
        delay_minutes=delay_minutes,
    )
    return _run_for_seed(seed, request, reason="Manual repair demo parameters.")


@app.get("/api/reschedule/demo", response_model=RescheduleDemoResponse)
def reschedule_demo(
    number_of_rings: Annotated[int, Query(ge=1, le=20)] = 5,
    number_of_athletes: Annotated[int, Query(ge=8, le=1000)] = 360,
    number_of_teams: Annotated[int, Query(ge=2, le=100)] = 24,
    number_of_referee_crews: Annotated[int, Query(ge=1, le=20)] = 10,
    number_of_divisions: Annotated[int, Query(ge=1, le=200)] = 61,
    target_tournament_minutes: Annotated[int, Query(ge=120, le=900)] = 480,
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
        number_of_divisions=number_of_divisions,
        target_tournament_minutes=target_tournament_minutes,
        seed=seed,
    )
    try:
        original_schedule = build_optimized_schedule(tournament)
    except ScheduleError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    scripted_scenario = None
    if emergency_type == "referee_shortage" and referee_crew_id is None:
        scripted_scenario = find_impactful_demo_scenario(
            tournament=tournament,
            original_schedule=original_schedule,
            emergency_type="referee_shortage",
            default_current_minute=current_minute,
            default_delay_minutes=delay_minutes,
        )
        current_minute = scripted_scenario.current_minute
        delay_minutes = scripted_scenario.delay_minutes
        referee_crew_id = scripted_scenario.referee_crew_id
        unavailable_start_minute = scripted_scenario.unavailable_start_minute
        unavailable_duration_minutes = scripted_scenario.unavailable_duration_minutes

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

    baseline_schedule = assign_referees_to_schedule(tournament, original_schedule) if tournament.referees else original_schedule
    unavailable_referee_ids = scripted_scenario.unavailable_referee_ids if scripted_scenario else []
    unavailable_windows = {
        referee_id: [
            (
                config.unavailable_start_minute,
                config.unavailable_start_minute + max(1, config.unavailable_duration_minutes),
            )
        ]
        for referee_id in unavailable_referee_ids
    }
    hydrated_schedule = (
        assign_referees_to_schedule_with_unavailability(
            tournament,
            rescheduled_schedule,
            unavailable_by_referee=unavailable_windows,
        )
        if tournament.referees
        else rescheduled_schedule
    )

    adjustment_reason = f"Emergency {emergency_type.replace('_', ' ')} reschedule"
    referee_moves = (
        diff_referee_assignments(
            tournament,
            baseline_schedule,
            hydrated_schedule,
            reason=adjustment_reason,
        )
        if tournament.referees
        else []
    )
    referee_moves = [move for move in referee_moves if _is_meaningful_referee_adjustment(move)]
    changed_events = _add_referee_assignment_change_events(changed_events, baseline_schedule, hydrated_schedule, referee_moves)

    notifications = build_mock_notifications(hydrated_schedule)
    validation = validate_snapshot(tournament=tournament, schedule=hydrated_schedule, demo_mode=True)
    enriched_changes = enrich_schedule_changes(
        tournament,
        prior_schedule=baseline_schedule,
        next_schedule=hydrated_schedule,
        changed_events=changed_events,
        reason=adjustment_reason,
    )

    coordination = build_coordination_board(
        tournament,
        hydrated_schedule,
        current_minute=config.current_minute,
        published_schedule=baseline_schedule,
    )
    annotated_original = _annotate_schedule_for_gantt(tournament, baseline_schedule, [], coordination)
    annotated_schedule = _annotate_schedule_for_gantt(tournament, hydrated_schedule, changed_events, coordination)
    changed_count, average_delay, max_delay = _change_metrics(changed_events)

    return RescheduleDemoResponse(
        original_schedule=annotated_original,
        rescheduled_schedule=annotated_schedule,
        changed_events=changed_events,
        notifications=notifications,
        validation=validation,
        schedule_changes=enriched_changes,
        referee_adjustments=referee_moves,
        coordination_board=coordination,
        changed_match_count=changed_count,
        average_delay_minutes=average_delay,
        max_delay_minutes=max_delay,
        demo_was_impactful=bool(changed_events or referee_moves),
        demo_scenario_reason=scripted_scenario.reason if scripted_scenario else "",
        no_op_reason=None if (changed_events or referee_moves) else "No schedule or referee assignment change was required.",
    )


def _add_referee_assignment_change_events(
    changed_events: list[ChangedEvent],
    baseline_schedule: list[RingSchedule],
    hydrated_schedule: list[RingSchedule],
    referee_moves,
) -> list[ChangedEvent]:
    if not referee_moves:
        return changed_events
    existing = {row.event_id for row in changed_events}
    baseline_by_id = {event.event_id: event for ring in baseline_schedule for event in ring.events}
    added: list[ChangedEvent] = []
    for move in referee_moves:
        for ring in hydrated_schedule:
            for event in ring.events:
                if event.event_id in existing:
                    continue
                same_window = event.ring_id == move.ring_id and event.start_minute == move.window_start_minute and event.end_minute == move.window_end_minute
                if not same_window:
                    continue
                original = baseline_by_id.get(event.event_id)
                if not original:
                    continue
                existing.add(event.event_id)
                added.append(
                    ChangedEvent(
                        event_id=event.event_id,
                        changes=["referee_assignment_changed"],
                        original_ring_id=original.ring_id,
                        new_ring_id=event.ring_id,
                        original_referee_crew_id=original.referee_crew_id,
                        new_referee_crew_id=event.referee_crew_id,
                        original_start_minute=original.start_minute,
                        new_start_minute=event.start_minute,
                    )
                )
                break
    return sorted([*changed_events, *added], key=lambda row: (row.original_start_minute, row.event_id))
