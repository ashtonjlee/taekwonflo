from __future__ import annotations

from .local_repair import RepairRequest, try_repair_next_match
from .models import RepairDemoResponse, RingSchedule, Tournament
from .rescheduler import EmergencyConfig, reoptimize_future_events
from .scheduler import ScheduleError, build_balanced_greedy_schedule, build_optimized_schedule
from .validation import sort_schedule, validate_schedule_hard_constraints


def _finalize_schedule(tournament: Tournament, schedule: list[RingSchedule], *, source: str) -> list[RingSchedule]:
    sorted_schedule = sort_schedule(schedule)
    validation = validate_schedule_hard_constraints(tournament, sorted_schedule)
    if not validation.valid:
        sample = "; ".join(validation.errors[:5])
        raise ScheduleError(f"{source} produced an invalid schedule: {sample}")
    return sorted_schedule


def run_initial_scheduling(
    tournament: Tournament,
    *,
    solver_time_limit_seconds: float = 5.0,
) -> list[RingSchedule]:
    """Stage 3: initial compact schedule generation."""
    try:
        schedule = build_optimized_schedule(tournament, solver_time_limit_seconds=solver_time_limit_seconds)
        return _finalize_schedule(tournament, schedule, source="CP-SAT scheduler")
    except ScheduleError:
        schedule = build_balanced_greedy_schedule(tournament)
        return _finalize_schedule(tournament, schedule, source="compact fallback scheduler")


def run_local_repair(
    *,
    tournament: Tournament,
    original_schedule: list[RingSchedule],
    request: RepairRequest,
) -> RepairDemoResponse:
    """Stage 4: local repair (swaps, waits, same-ring reorder, local shift)."""
    return try_repair_next_match(tournament=tournament, original_schedule=original_schedule, request=request)


def run_global_repair_fallback(
    *,
    tournament: Tournament,
    original_schedule: list[RingSchedule],
    config: EmergencyConfig,
    solver_time_limit_seconds: float = 5.0,
) -> tuple[list[RingSchedule], list]:
    """Stage 5: global reschedule fallback when local repair cannot restore feasibility."""
    schedule, changes = reoptimize_future_events(
        tournament=tournament,
        original_schedule=original_schedule,
        config=config,
        solver_time_limit_seconds=solver_time_limit_seconds,
    )
    return _finalize_schedule(tournament, schedule, source="global rescheduler"), changes
