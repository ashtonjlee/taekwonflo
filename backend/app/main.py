from __future__ import annotations

import csv
import io
import re
from typing import Annotated
from typing import Literal

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Query
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel, Field

from .brackets import build_division_detail
from .data_generator import generate_tournament
from .demo_scenarios import find_impactful_demo_scenario
from .local_repair import RepairRequest
from .match_numbers import build_published_match_number_map
from .models import Athlete, ChangedEvent, Coach, Division, DivisionDetail, Referee, RefereeCrew, RepairDemoResponse, RescheduleDemoResponse, Ring, RingSchedule, ScheduledEvent, SnapshotResponse, SnapshotValidationResponse, Team, Tournament, TournamentEvent
from .notifications import build_mock_notifications
from .rescheduler import EmergencyConfig, RescheduleError
from .scheduler import ScheduleError, build_optimized_schedule, count_schedulable_units
from .scheduling_layers import run_global_repair_fallback, run_initial_scheduling, run_local_repair
from .schedule_ops import (
    assign_referees_to_schedule,
    assign_referees_to_schedule_with_unavailability,
    build_coordination_board,
    diff_referee_assignments,
    enrich_schedule_changes,
    summarize_ring_operations,
)
from .validation import sort_schedule, validate_schedule_hard_constraints, validate_snapshot

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


class DivisionDetailRequest(BaseModel):
    tournament: Tournament
    schedule: list[RingSchedule]
    current_minute: int = Field(default=0, ge=0)
    focus_match_id: str | None = None


class DemoRescheduleRequest(BaseModel):
    tournament: Tournament
    original_schedule: list[RingSchedule]
    emergency_type: Literal["medical_delay", "ring_pause", "referee_shortage", "coach_conflict"] = "medical_delay"
    ring_id: str | None = None
    referee_crew_id: str | None = None
    coach_id: str | None = None
    current_minute: int = Field(default=60, ge=0)
    delay_minutes: int = Field(default=5, ge=1)
    pause_start_minute: int | None = None
    pause_duration_minutes: int | None = None
    unavailable_start_minute: int | None = None
    unavailable_duration_minutes: int | None = None


class DemoRepairRequest(BaseModel):
    tournament: Tournament
    original_schedule: list[RingSchedule]
    emergency_type: Literal["medical_delay", "ring_pause", "referee_shortage", "coach_conflict", "athlete_conflict"] = "coach_conflict"
    current_minute: int = Field(default=0, ge=0)
    coach_id: str | None = None
    athlete_id: str | None = None
    referee_crew_id: str | None = None
    ring_id: str | None = None
    delay_minutes: int = Field(default=5, ge=1)


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


def _medical_pause_shift(
    schedule: list[RingSchedule],
    *,
    ring_id: str,
    pause_start_minute: int,
    pause_duration_minutes: int,
) -> tuple[list[RingSchedule], list[ChangedEvent]]:
    changed: list[ChangedEvent] = []
    shifted: list[RingSchedule] = []
    duration = max(1, pause_duration_minutes)
    for ring in schedule:
        events: list = []
        for event in ring.events:
            updated = event.model_copy()
            if event.ring_id == ring_id and event.end_minute > pause_start_minute:
                updated.start_minute = event.start_minute + duration
                updated.end_minute = event.end_minute + duration
                changed.append(
                    ChangedEvent(
                        event_id=event.event_id,
                        changes=["medical_pause_delay", "start_time_changed"],
                        original_ring_id=event.ring_id,
                        new_ring_id=event.ring_id,
                        original_referee_crew_id=event.referee_crew_id,
                        new_referee_crew_id=event.referee_crew_id,
                        original_start_minute=event.start_minute,
                        new_start_minute=updated.start_minute,
                    )
                )
            events.append(updated)
        shifted.append(RingSchedule(ring_id=ring.ring_id, ring_name=ring.ring_name, events=sorted(events, key=lambda row: row.start_minute)))
    return shifted, changed


def _slug(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return cleaned or fallback


def _norm_column(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def _pick(row: dict[str, str], *keys: str, default: str = "") -> str:
    for key in keys:
        value = row.get(key)
        if value:
            return value.strip()
    return default


def _enum_age(value: str) -> str:
    text = value.lower()
    if "peewee" in text or "pee wee" in text:
        return "peewee"
    if "cadet" in text:
        return "cadet"
    if "senior" in text or "adult" in text:
        return "senior"
    return "junior"


def _enum_gender(value: str) -> str:
    text = value.lower()
    if text.startswith("f"):
        return "female"
    if text.startswith("m"):
        return "male"
    return "male"


def _enum_belt(value: str) -> str:
    text = value.lower()
    if "world" in text:
        return "world_class"
    if "color" in text or "colour" in text or "green" in text or "blue" in text or "red" in text:
        return "color_belt"
    return "black_belt"


def _enum_event_type(value: str) -> str:
    text = value.lower()
    if "team" in text and "poom" in text:
        return "team_poomsae"
    if "pair" in text and "poom" in text:
        return "pair_poomsae"
    if "poom" in text or "form" in text:
        return "poomsae"
    return "kyorugi"


def _weight_bucket_for_kyorugi(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return "Open"
    lowered = raw.lower()
    if lowered in {"open", "light", "middle", "heavy"}:
        return raw.title()
    digits = "".join(ch for ch in lowered if ch.isdigit())
    if not digits:
        return raw
    try:
        number = int(digits)
    except ValueError:
        return raw
    if number <= 45:
        return "Light"
    if number <= 63:
        return "Middle"
    if number <= 78:
        return "Heavy"
    return "Ultra"


def _max_division_size(event_type: str) -> int:
    if event_type == "kyorugi":
        return 8
    if event_type == "poomsae":
        return 24
    if event_type == "pair_poomsae":
        return 16
    if event_type == "team_poomsae":
        return 12
    return 12


def _division_name_from_bucket(
    *,
    event_type: str,
    age_group: str,
    gender_key: str,
    belt: str,
    weight_key: str,
    flight_index: int = 0,
) -> str:
    event_label = {
        "poomsae": "Individual Poomsae",
        "pair_poomsae": "Pair Poomsae",
        "team_poomsae": "Team Poomsae",
        "kyorugi": "Olympic Sparring",
    }[event_type]
    name = (
        f"{age_group.title()} {gender_key.title()} "
        f"{belt.replace('_', ' ').title()} {weight_key} {event_label}"
    ).strip()
    if flight_index > 0:
        suffix = chr(ord("A") + flight_index - 1)
        return f"{name} Flight {suffix}"
    return name


def _marked(value: str) -> bool:
    return value.strip().lower() in {"x", "yes", "y", "true", "1", "registered"}


def _age_group_from_competition_age(value: str) -> str:
    try:
        age = int(float(value))
    except (TypeError, ValueError):
        return _enum_age(value)
    if age <= 11:
        return "peewee"
    if age <= 14:
        return "cadet"
    if age <= 17:
        return "junior"
    return "senior"


def _event_registrations(row: dict[str, str]) -> list[str]:
    events: list[str] = []
    if _marked(row.get("forms", "")):
        events.append("poomsae")
    if _marked(row.get("forms_pair", "")):
        events.append("pair_poomsae")
    if _marked(row.get("olympic_sparring", "")):
        events.append("kyorugi")
    if _marked(row.get("team_forms", "")):
        events.append("team_poomsae")
    explicit = _pick(row, "event_type", "event", "category")
    if explicit:
        events.append(_enum_event_type(explicit))
    return sorted(set(events))


def _csv_rows_with_detected_header(csv_text: str) -> tuple[list[str], list[dict[str, str]], list[str]]:
    raw_rows = list(csv.reader(io.StringIO(csv_text)))
    warnings: list[str] = []
    header_index: int | None = None
    for idx, raw in enumerate(raw_rows):
        normalized = {_norm_column(col) for col in raw}
        if "name" in normalized and ("school" in normalized or "org_id" in normalized):
            header_index = idx
            break
    if header_index is None:
        raise HTTPException(status_code=422, detail="Could not find attendee CSV header row with Name/School columns.")
    if header_index > 0:
        warnings.append(f"Skipped {header_index} title/preamble row(s) before the real CSV header.")
    header = [_norm_column(col) for col in raw_rows[header_index]]
    original_header = raw_rows[header_index]
    rows: list[dict[str, str]] = []
    for raw in raw_rows[header_index + 1 :]:
        if not any(cell.strip() for cell in raw):
            continue
        padded = raw + [""] * max(0, len(header) - len(raw))
        rows.append({header[col_idx]: (padded[col_idx] or "").strip() for col_idx in range(len(header))})
    return original_header, rows, warnings


def _parse_csv_tournament(
    csv_text: str,
    *,
    rings_count: int = 5,
    referee_crews_count: int = 10,
) -> tuple[Tournament, list[str], list[str], dict[str, object]]:
    original_columns, rows, warnings = _csv_rows_with_detected_header(csv_text)
    if not rows:
        raise HTTPException(status_code=422, detail="CSV has no athlete rows.")
    required = {"name", "school"}
    missing = sorted(required - set(rows[0].keys()))
    if missing:
        warnings.append(f"Missing common column(s): {', '.join(missing)}. Defaults/inference were used where possible.")

    teams_by_name: dict[str, Team] = {}
    coaches_by_key: dict[tuple[str, str], Coach] = {}
    official_names: list[str] = []
    athletes: list[Athlete] = []
    athletes_by_identity: dict[tuple[str, str], Athlete] = {}
    division_rosters: dict[tuple[str, str, str, str, str], dict[str, object]] = {}

    for idx, row in enumerate(rows, start=1):
        person_name = _pick(row, "athlete_name", "athlete", "name", default=f"Attendee {idx}")
        team_name = _pick(row, "team_name", "team", "school", "club", default="Independent")
        is_coach = _marked(row.get("coach", ""))
        is_official = _marked(row.get("official", ""))
        team = teams_by_name.get(team_name)
        if not team:
            team = Team(id=f"team-{len(teams_by_name)+1}", name=team_name, coach_ids=[])
            teams_by_name[team_name] = team
        if is_coach:
            coach_key = (team.id, person_name)
            if coach_key not in coaches_by_key:
                coach = Coach(id=f"coach-{len(coaches_by_key)+1}", name=person_name, team_id=team.id)
                coaches_by_key[coach_key] = coach
                team.coach_ids.append(coach.id)
        if is_official:
            official_names.append(person_name)

    for idx, row in enumerate(rows, start=1):
        person_name = _pick(row, "athlete_name", "athlete", "name", default=f"Attendee {idx}")
        team_name = _pick(row, "team_name", "team", "school", "club", default="Independent")
        registrations = _event_registrations(row)
        team = teams_by_name[team_name]
        if not registrations:
            continue

        if not team.coach_ids:
            placeholder_name = f"{team_name} Coach"
            coach_key = (team.id, placeholder_name)
            if coach_key not in coaches_by_key:
                coach = Coach(id=f"coach-{len(coaches_by_key)+1}", name=placeholder_name, team_id=team.id)
                coaches_by_key[coach_key] = coach
                team.coach_ids.append(coach.id)
                warnings.append(f"No explicit coach for {team_name}; created placeholder coach.")

        age_source = _pick(row, "competition_age", "age", "age_group", default="junior")
        age_group = _age_group_from_competition_age(age_source)
        gender = _enum_gender(_pick(row, "gender", "sex", default="male"))
        belt = _enum_belt(_pick(row, "belt_rank", "rank", "belt", "belt_level", default="black_belt"))
        weight = _pick(row, "weight_class", "weight", default="Open")

        identity_key = (person_name.strip().lower(), team.id)
        athlete = athletes_by_identity.get(identity_key)
        if athlete is None:
            athlete = Athlete(
                id=f"athlete-{len(athletes)+1}",
                name=person_name,
                team_id=team.id,
                coach_ids=[team.coach_ids[0]],
                age_group=age_group,  # type: ignore[arg-type]
                gender=gender,  # type: ignore[arg-type]
                belt_level=belt,  # type: ignore[arg-type]
            )
            athletes.append(athlete)
            athletes_by_identity[identity_key] = athlete
        for event_type in registrations:
            weight_key = _weight_bucket_for_kyorugi(weight) if event_type == "kyorugi" else "Open"
            gender_key = gender if event_type in {"kyorugi", "poomsae"} else "mixed"
            div_key = (event_type, age_group, gender_key, belt, weight_key)
            division_rosters.setdefault(
                div_key,
                {
                    "event_type": event_type,
                    "age_group": age_group,
                    "gender": gender_key,
                    "belt": belt,
                    "weight": weight_key,
                    "athletes": [],
                    "teams": set(),
                },
            )
            if athlete.id not in division_rosters[div_key]["athletes"]:  # type: ignore[index,operator]
                division_rosters[div_key]["athletes"].append(athlete.id)  # type: ignore[index,union-attr]
            division_rosters[div_key]["teams"].add(team.id)  # type: ignore[index,union-attr]

    if not athletes:
        raise HTTPException(status_code=422, detail="CSV did not contain any athlete event registrations marked with X.")

    divisions: list[Division] = []
    events: list[TournamentEvent] = []
    division_counter = 0
    event_counter = 0
    athlete_lookup = {athlete.id: athlete for athlete in athletes}
    competitors_per_division: list[dict[str, object]] = []

    for bucket_key in sorted(division_rosters):
        data = division_rosters[bucket_key]
        athlete_ids_full = sorted(list(data["athletes"]))  # type: ignore[arg-type]
        event_type = str(data["event_type"])
        max_size = _max_division_size(event_type)
        flight_chunks = [
            athlete_ids_full[idx : idx + max_size]
            for idx in range(0, len(athlete_ids_full), max_size)
        ]

        for flight_index, athlete_ids in enumerate(flight_chunks):
            if len(athlete_ids) < 2:
                warnings.append(
                    f"Skipped tiny {event_type} bucket ({bucket_key}) with <2 competitors after grouping."
                )
                continue
            division_counter += 1
            event_counter += 1
            div_id = f"division-{division_counter}"
            division_name = _division_name_from_bucket(
                event_type=event_type,
                age_group=str(data["age_group"]),
                gender_key=str(data["gender"]),
                belt=str(data["belt"]),
                weight_key=str(data["weight"]),
                flight_index=flight_index if len(flight_chunks) > 1 else 0,
            )
            duration = max(12, len(athlete_ids) * (4 if event_type == "kyorugi" else 3))
            divisions.append(
                Division(
                    id=div_id,
                    name=division_name,
                    event_type=event_type,  # type: ignore[arg-type]
                    age_group=data["age_group"],  # type: ignore[arg-type]
                    gender=data["gender"],  # type: ignore[arg-type]
                    weight_class=str(data["weight"]),
                    belt_level=data["belt"],  # type: ignore[arg-type]
                    belt_rank_group=data["belt"],  # type: ignore[arg-type]
                    bracket_type="single_elimination" if event_type == "kyorugi" else "poomsae_rounds",
                    poomsae_rounds=[] if event_type == "kyorugi" else ["preliminary", "final"],
                    bracket_size=len(athlete_ids),
                    competitor_count=len(athlete_ids),
                    round_structure=[],
                    athlete_ids=athlete_ids,
                    team_ids=sorted({athlete_lookup[athlete_id].team_id for athlete_id in athlete_ids}),
                    estimated_duration_minutes=duration,
                )
            )
            required_coaches = sorted(
                {cid for athlete_id in athlete_ids for cid in athlete_lookup[athlete_id].coach_ids}
            )
            flight_team_ids = sorted({athlete_lookup[athlete_id].team_id for athlete_id in athlete_ids})
            events.append(
                TournamentEvent(
                    event_id=f"event-{event_counter}",
                    division_id=div_id,
                    division_name=division_name,
                    event_type=event_type,  # type: ignore[arg-type]
                    age_group=data["age_group"],  # type: ignore[arg-type]
                    belt_rank_group=data["belt"],  # type: ignore[arg-type]
                    weight_class=str(data["weight"]),
                    athlete_ids=athlete_ids,
                    team_ids=flight_team_ids,
                    required_coach_ids=required_coaches,
                    required_referee_count=5 if event_type != "kyorugi" and len(athlete_ids) >= 8 else 3,
                    estimated_duration_minutes=duration,
                    buffer_minutes=5,
                    status="unscheduled",
                )
            )
            competitors_per_division.append(
                {
                    "division_id": div_id,
                    "division_name": division_name,
                    "competitor_count": len(athlete_ids),
                }
            )

    if divisions:
        tiny_count = sum(1 for row in competitors_per_division if int(row["competitor_count"]) <= 2)
        if tiny_count >= max(8, len(divisions) // 3):
            warnings.append(
                f"Suspicious import shape: {tiny_count}/{len(divisions)} divisions have 2 or fewer competitors."
            )

    rings = [Ring(id=f"ring-{idx}", name=f"Ring {idx}") for idx in range(1, rings_count + 1)]
    referee_names = official_names or []
    while len(referee_names) < referee_crews_count * 4:
        referee_names.append(f"Referee {len(referee_names) + 1}")
    referees = [
        Referee(
            referee_id=f"ref-{idx}",
            name=name,
            home_crew_id=f"ref-crew-{((idx - 1) % referee_crews_count) + 1}",
            qualifications=["kyorugi", "poomsae", "judge"],
        )
        for idx, name in enumerate(referee_names, start=1)
    ]
    crews = [
        RefereeCrew(
            id=f"ref-crew-{idx}",
            name=f"Crew {idx}",
            referee_ids=[ref.referee_id for ref in referees if ref.home_crew_id == f"ref-crew-{idx}"],
        )
        for idx in range(1, referee_crews_count + 1)
    ]
    tournament = Tournament(
        id="csv-import",
        name="Imported CSV Tournament",
        rings=rings,
        teams=list(teams_by_name.values()),
        coaches=list(coaches_by_key.values()),
        athletes=athletes,
        divisions=divisions,
        referee_crews=crews,
        referees=referees,
        events=events,
    )
    diagnostics = {
        "rows_parsed": len(rows),
        "athletes_created": len(athletes),
        "divisions_created": len(divisions),
        "competitors_per_division": competitors_per_division,
    }
    return tournament, original_columns, warnings, diagnostics


def _extract_uploaded_csv(body: bytes, content_type: str) -> str:
    if "multipart/form-data" not in content_type:
        return body.decode("utf-8-sig")
    match = re.search(r"boundary=([^;]+)", content_type)
    if not match:
        raise HTTPException(status_code=400, detail="Multipart upload missing boundary.")
    boundary = ("--" + match.group(1).strip().strip('"')).encode()
    for part in body.split(boundary):
        if b"filename=" not in part:
            continue
        _, _, payload = part.partition(b"\r\n\r\n")
        payload = payload.rsplit(b"\r\n", 1)[0]
        return payload.decode("utf-8-sig")
    raise HTTPException(status_code=400, detail="Multipart upload did not include a file.")


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
        schedule = run_initial_scheduling(tournament)
    except ScheduleError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    notifications = build_mock_notifications(schedule)
    return SnapshotResponse(tournament=tournament, schedule=schedule, notifications=notifications)


@app.post("/api/demo/tournament")
def generate_demo_tournament(
    number_of_rings: Annotated[int, Query(ge=1, le=20)] = 5,
    number_of_athletes: Annotated[int, Query(ge=8, le=1000)] = 360,
    number_of_teams: Annotated[int, Query(ge=2, le=100)] = 24,
    number_of_referee_crews: Annotated[int, Query(ge=1, le=20)] = 10,
    number_of_divisions: Annotated[int, Query(ge=1, le=200)] = 61,
    target_tournament_minutes: Annotated[int, Query(ge=120, le=900)] = 480,
    seed: int = 42,
) -> dict[str, object]:
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
        schedule = run_initial_scheduling(tournament, solver_time_limit_seconds=8.0)
        schedule = _finalize_api_schedule(tournament, schedule, source="demo tournament scheduler")
    except ScheduleError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    notifications = build_mock_notifications(schedule)
    competitors_per_division = [
        {
            "division_id": division.id,
            "division_name": division.name,
            "competitor_count": division.competitor_count or len(division.athlete_ids),
        }
        for division in tournament.divisions
    ]
    preview = {
        "athlete_count": len(tournament.athletes),
        "team_count": len(tournament.teams),
        "division_count": len(tournament.divisions),
        "detected_columns": [],
        "warnings": [],
        "rows_parsed": len(tournament.athletes),
        "athletes_created": len(tournament.athletes),
        "divisions_created": len(tournament.divisions),
        "competitors_per_division": competitors_per_division,
        "solver_status": "CP_SAT_OR_COMPACT",
        "fallback_used": False,
    }
    return {
        "tournament": tournament.model_dump(),
        "schedule": [ring.model_dump() for ring in schedule],
        "notifications": [note.model_dump() for note in notifications],
        "preview": preview,
        "diagnostics": {
            "rows_parsed": preview["rows_parsed"],
            "athletes_created": preview["athletes_created"],
            "divisions_created": preview["divisions_created"],
            "competitors_per_division": competitors_per_division,
            "solver_status": preview["solver_status"],
            "fallback_used": preview["fallback_used"],
            "warnings": [],
        },
    }


def _finalize_api_schedule(tournament: Tournament, schedule: list[RingSchedule], *, source: str) -> list[RingSchedule]:
    sorted_schedule = sort_schedule(schedule)
    validation = validate_schedule_hard_constraints(tournament, sorted_schedule)
    if not validation.valid:
        raise HTTPException(
            status_code=422,
            detail=f"{source} produced an invalid schedule: {'; '.join(validation.errors[:5])}",
        )
    return sorted_schedule


def _csv_solver_failure_diagnostics(tournament: Tournament, message: str, warnings: list[str]) -> dict[str, object]:
    solver_status = "UNKNOWN"
    if "solver status:" in message.lower():
        try:
            solver_status = message.split("solver status:")[-1].split(")")[0].strip()
        except Exception:
            solver_status = "UNKNOWN"
    likely_bottlenecks: list[str] = []
    if len(tournament.referee_crews) < len(tournament.rings):
        likely_bottlenecks.append("fewer referee crews than rings")
    if not tournament.events:
        likely_bottlenecks.append("no schedulable divisions were created from CSV")
    coach_load: dict[str, int] = {}
    athlete_load: dict[str, int] = {}
    for event in tournament.events:
        for coach_id in event.required_coach_ids:
            coach_load[coach_id] = coach_load.get(coach_id, 0) + 1
        for athlete_id in event.athlete_ids:
            athlete_load[athlete_id] = athlete_load.get(athlete_id, 0) + 1
    if coach_load and max(coach_load.values()) >= max(3, len(tournament.events) // 3):
        likely_bottlenecks.append("one coach is required by many divisions")
    if athlete_load and max(athlete_load.values()) >= 3:
        likely_bottlenecks.append("one athlete appears in several divisions")

    return {
        "solver_status": solver_status,
        "units": count_schedulable_units(tournament),
        "rings": len(tournament.rings),
        "athletes": len(tournament.athletes),
        "coaches": len(tournament.coaches),
        "referee_crews": len(tournament.referee_crews),
        "likely_bottleneck_warnings": likely_bottlenecks,
        "import_warnings": warnings,
        "error": message,
    }


@app.post("/api/import/csv")
async def import_csv_schedule(
    request: Request,
    number_of_rings: Annotated[int, Query(ge=1, le=20)] = 5,
    number_of_referee_crews: Annotated[int, Query(ge=1, le=20)] = 10,
    relaxed_import_mode: Annotated[bool, Query()] = False,
) -> dict[str, object]:
    """Import a tournament CSV.

    The import path uses CP-SAT only. `relaxed_import_mode` is accepted for backwards
    compatibility but no longer enables greedy fallback.
    """
    csv_text = _extract_uploaded_csv(await request.body(), request.headers.get("content-type", ""))
    tournament, columns, warnings, import_diagnostics = _parse_csv_tournament(
        csv_text,
        rings_count=number_of_rings,
        referee_crews_count=number_of_referee_crews,
    )
    fallback_used = False
    solver_status = "CP_SAT"
    try:
        schedule = build_optimized_schedule(tournament, solver_time_limit_seconds=8.0)
        schedule = _finalize_api_schedule(tournament, schedule, source="CP-SAT CSV scheduler")
    except ScheduleError as error:
        message = str(error)
        diagnostics = _csv_solver_failure_diagnostics(tournament, message, warnings)
        raise HTTPException(status_code=422, detail=diagnostics) from error
    notifications = build_mock_notifications(schedule)
    preview = {
        "athlete_count": len(tournament.athletes),
        "team_count": len(tournament.teams),
        "division_count": len(tournament.divisions),
        "detected_columns": columns,
        "warnings": warnings,
        "rows_parsed": import_diagnostics["rows_parsed"],
        "athletes_created": import_diagnostics["athletes_created"],
        "divisions_created": import_diagnostics["divisions_created"],
        "competitors_per_division": import_diagnostics["competitors_per_division"],
        "solver_status": solver_status,
        "fallback_used": fallback_used,
    }
    return {
        "tournament": tournament.model_dump(),
        "schedule": [ring.model_dump() for ring in schedule],
        "notifications": [note.model_dump() for note in notifications],
        "preview": preview,
        "diagnostics": {
            "rows_parsed": preview["rows_parsed"],
            "athletes_created": preview["athletes_created"],
            "divisions_created": preview["divisions_created"],
            "competitors_per_division": import_diagnostics["competitors_per_division"],
            "solver_status": solver_status,
            "fallback_used": fallback_used,
            "warnings": warnings,
        },
    }


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
        schedule = run_initial_scheduling(tournament)
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
        schedule = run_initial_scheduling(tournament)
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
        schedule = run_initial_scheduling(tournament)
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


@app.post("/api/divisions/{division_id}/detail", response_model=DivisionDetail)
def post_division_detail(division_id: str, payload: DivisionDetailRequest) -> DivisionDetail:
    try:
        stable_match_numbers = build_published_match_number_map(payload.tournament, payload.schedule)
        return build_division_detail(
            tournament=payload.tournament,
            schedule=payload.schedule,
            division_id=division_id,
            current_minute=payload.current_minute,
            focus_match_id=payload.focus_match_id,
            match_number_by_match_id=stable_match_numbers,
        )
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
            original_schedule = run_initial_scheduling(tournament)
        except ScheduleError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        try:
            response = run_local_repair(
                tournament=tournament,
                original_schedule=original_schedule,
                request=request,
            )
        except RuntimeError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
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
                original_schedule = run_initial_scheduling(tournament)
            except ScheduleError:
                continue
            scenario = find_impactful_demo_scenario(
                tournament=tournament,
                original_schedule=original_schedule,
                emergency_type="coach_conflict",
                default_current_minute=current_minute,
                default_delay_minutes=delay_minutes,
            )
            try:
                repair_response = run_local_repair(
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
                )
            except RuntimeError:
                continue
            candidate = _decorate(
                repair_response,
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


@app.post("/api/repair/apply", response_model=RepairDemoResponse)
def apply_repair_demo(payload: DemoRepairRequest) -> RepairDemoResponse:
    if not payload.original_schedule:
        raise HTTPException(status_code=422, detail="Generate or upload a tournament first.")
    request = RepairRequest(
        emergency_type=payload.emergency_type,
        current_minute=payload.current_minute,
        coach_id=payload.coach_id,
        athlete_id=payload.athlete_id,
        referee_crew_id=payload.referee_crew_id,
        ring_id=payload.ring_id,
        delay_minutes=payload.delay_minutes,
    )
    try:
        return run_local_repair(
            tournament=payload.tournament,
            original_schedule=payload.original_schedule,
            request=request,
        )
    except RuntimeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


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
    delay_minutes: Annotated[int, Query(ge=1)] = 5,
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
        original_schedule = run_initial_scheduling(tournament)
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
        rescheduled_schedule, changed_events = run_global_repair_fallback(
            tournament=tournament,
            original_schedule=original_schedule,
            config=config,
        )
    except (RescheduleError, ScheduleError) as error:
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
    hydrated_schedule = _finalize_api_schedule(tournament, hydrated_schedule, source="hydrated reschedule")

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


@app.post("/api/reschedule/apply", response_model=RescheduleDemoResponse)
def apply_reschedule_demo(payload: DemoRescheduleRequest) -> RescheduleDemoResponse:
    if not payload.original_schedule:
        raise HTTPException(status_code=422, detail="Generate or upload a tournament first.")

    original_schedule = _finalize_api_schedule(
        payload.tournament,
        payload.original_schedule,
        source="submitted original schedule",
    )
    defaults = _resolve_emergency_defaults(
        emergency_type=payload.emergency_type,
        current_minute=payload.current_minute,
        delay_minutes=payload.delay_minutes,
        ring_id=payload.ring_id,
        referee_crew_id=payload.referee_crew_id,
        coach_id=payload.coach_id,
        pause_start_minute=payload.pause_start_minute,
        pause_duration_minutes=payload.pause_duration_minutes,
        unavailable_start_minute=payload.unavailable_start_minute,
        unavailable_duration_minutes=payload.unavailable_duration_minutes,
        tournament=payload.tournament,
        schedule=original_schedule,
    )
    config = EmergencyConfig(
        emergency_type=payload.emergency_type,
        current_minute=payload.current_minute,
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
        rescheduled_schedule, changed_events = run_global_repair_fallback(
            tournament=payload.tournament,
            original_schedule=original_schedule,
            config=config,
        )
    except (RescheduleError, ScheduleError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    baseline_schedule = assign_referees_to_schedule(payload.tournament, original_schedule) if payload.tournament.referees else original_schedule
    hydrated_schedule = (
        assign_referees_to_schedule(payload.tournament, rescheduled_schedule)
        if payload.tournament.referees
        else rescheduled_schedule
    )
    hydrated_schedule = _finalize_api_schedule(payload.tournament, hydrated_schedule, source="hydrated reschedule")

    adjustment_reason = f"Emergency {payload.emergency_type.replace('_', ' ')} reschedule"
    referee_moves = (
        diff_referee_assignments(
            payload.tournament,
            baseline_schedule,
            hydrated_schedule,
            reason=adjustment_reason,
        )
        if payload.tournament.referees
        else []
    )
    referee_moves = [move for move in referee_moves if _is_meaningful_referee_adjustment(move)]
    changed_events = _add_referee_assignment_change_events(changed_events, baseline_schedule, hydrated_schedule, referee_moves)

    notifications = build_mock_notifications(hydrated_schedule)
    validation = validate_snapshot(tournament=payload.tournament, schedule=hydrated_schedule, demo_mode=True)
    enriched_changes = enrich_schedule_changes(
        payload.tournament,
        prior_schedule=baseline_schedule,
        next_schedule=hydrated_schedule,
        changed_events=changed_events,
        reason=adjustment_reason,
    )
    coordination = build_coordination_board(
        payload.tournament,
        hydrated_schedule,
        current_minute=config.current_minute,
        published_schedule=baseline_schedule,
    )
    annotated_original = _annotate_schedule_for_gantt(payload.tournament, baseline_schedule, [], coordination)
    annotated_schedule = _annotate_schedule_for_gantt(payload.tournament, hydrated_schedule, changed_events, coordination)
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
        demo_scenario_reason="Applied demo to submitted tournament schedule.",
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
