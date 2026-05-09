from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Literal

from .models import Athlete, Coach, Division, RefereeCrew, Ring, Team, Tournament, TournamentEvent

EVENT_TYPES: list[Literal["kyorugi", "poomsae", "team_poomsae"]] = ["kyorugi", "poomsae", "team_poomsae"]
DIVISION_SIZE_PATTERN = [2, 4, 6, 8, 10, 12, 16, 18]


@dataclass(frozen=True)
class GeneratorParams:
    number_of_rings: int = 3
    number_of_athletes: int = 48
    number_of_teams: int = 8
    number_of_referee_crews: int = 4
    seed: int = 42


def generate_tournament(
    number_of_rings: int = 3,
    number_of_athletes: int = 48,
    number_of_teams: int = 8,
    number_of_referee_crews: int = 4,
    seed: int = 42,
) -> Tournament:
    params = GeneratorParams(
        number_of_rings=max(1, number_of_rings),
        number_of_athletes=max(8, number_of_athletes),
        number_of_teams=max(2, number_of_teams),
        number_of_referee_crews=max(1, number_of_referee_crews),
        seed=seed,
    )
    rng = random.Random(params.seed)

    rings = [Ring(id=f"ring-{idx + 1}", name=f"Ring {idx + 1}") for idx in range(params.number_of_rings)]
    referee_crews = [
        RefereeCrew(id=f"ref-crew-{idx + 1}", name=f"Referee Crew {idx + 1}")
        for idx in range(params.number_of_referee_crews)
    ]

    teams, coaches = _build_teams_and_coaches(params.number_of_teams)
    athletes = _build_athletes(params.number_of_athletes, teams, coaches, rng)
    divisions, events = _build_divisions_and_events(athletes, teams, rng)

    return Tournament(
        id="tkf-demo-open",
        name="TaekwonFlo Demo Open",
        rings=rings,
        teams=teams,
        coaches=coaches,
        athletes=athletes,
        divisions=divisions,
        referee_crews=referee_crews,
        events=events,
    )


def _build_teams_and_coaches(number_of_teams: int) -> tuple[list[Team], list[Coach]]:
    teams: list[Team] = []
    coaches: list[Coach] = []
    coach_counter = 1

    for team_idx in range(number_of_teams):
        team_id = f"team-{team_idx + 1}"
        team_name = f"Dojang {team_idx + 1}"

        # Guarantees a mix of one-coach and multi-coach teams.
        coaches_for_team = 1 if team_idx % 3 == 0 else (2 if team_idx % 3 == 1 else 3)
        coach_ids: list[str] = []
        for _ in range(coaches_for_team):
            coach_id = f"coach-{coach_counter}"
            coach_counter += 1
            coach_ids.append(coach_id)
            coaches.append(Coach(id=coach_id, name=f"Coach {coach_id.split('-')[-1]}", team_id=team_id))
        teams.append(Team(id=team_id, name=team_name, coach_ids=coach_ids))

    return teams, coaches


def _build_athletes(
    number_of_athletes: int,
    teams: list[Team],
    coaches: list[Coach],
    rng: random.Random,
) -> list[Athlete]:
    del coaches  # Team objects already contain coach assignments.
    athletes: list[Athlete] = []
    team_cycle = [team.id for team in teams]
    team_index = 0

    for athlete_idx in range(number_of_athletes):
        team_id = team_cycle[team_index]
        team_index = (team_index + 1) % len(team_cycle)
        team = next(team for team in teams if team.id == team_id)
        coach_count = 1 if len(team.coach_ids) == 1 else rng.choice([1, min(2, len(team.coach_ids))])
        assigned_coaches = rng.sample(team.coach_ids, k=coach_count)
        athletes.append(
            Athlete(
                id=f"athlete-{athlete_idx + 1}",
                name=f"Athlete {athlete_idx + 1}",
                team_id=team_id,
                coach_ids=assigned_coaches,
            )
        )

    return athletes


def _build_divisions_and_events(
    athletes: list[Athlete],
    teams: list[Team],
    rng: random.Random,
) -> tuple[list[Division], list[TournamentEvent]]:
    del teams
    athlete_by_id = {athlete.id: athlete for athlete in athletes}
    athlete_ids = [athlete.id for athlete in athletes]
    base_divisions = max(6, len(athlete_ids) // 8)
    crossover_ids = rng.sample(athlete_ids, k=min(max(4, len(athlete_ids) // 12), len(athlete_ids)))

    divisions: list[Division] = []
    events: list[TournamentEvent] = []

    for division_index in range(base_divisions):
        event_type = EVENT_TYPES[division_index % len(EVENT_TYPES)]
        requested_size = DIVISION_SIZE_PATTERN[division_index % len(DIVISION_SIZE_PATTERN)]
        size = min(requested_size, len(athlete_ids))
        if size < 2:
            continue

        selected_set = set(rng.sample(athlete_ids, k=size))
        if division_index < len(crossover_ids):
            selected_set.add(crossover_ids[division_index])
        if division_index % 2 == 0 and crossover_ids:
            selected_set.add(crossover_ids[(division_index + 1) % len(crossover_ids)])

        while len(selected_set) < size:
            selected_set.add(rng.choice(athlete_ids))
        selected_athletes = sorted(rng.sample(list(selected_set), k=size))
        final_size = len(selected_athletes)
        division_id = f"division-{division_index + 1}"
        division_name = _division_name(division_index + 1, event_type, final_size)
        division_athletes = [athlete_by_id[athlete_id] for athlete_id in selected_athletes]
        team_ids = sorted({athlete.team_id for athlete in division_athletes})
        required_coach_ids = sorted({coach_id for athlete in division_athletes for coach_id in athlete.coach_ids})

        estimated_duration_minutes = _estimate_duration(event_type, final_size)
        buffer_minutes = 5 if event_type != "team_poomsae" else 7

        divisions.append(
            Division(
                id=division_id,
                name=division_name,
                event_type=event_type,
                athlete_ids=selected_athletes,
                team_ids=team_ids,
                estimated_duration_minutes=estimated_duration_minutes,
            )
        )
        events.append(
            TournamentEvent(
                event_id=f"event-{division_index + 1}",
                division_id=division_id,
                division_name=division_name,
                event_type=event_type,
                athlete_ids=selected_athletes,
                team_ids=team_ids,
                required_coach_ids=required_coach_ids,
                estimated_duration_minutes=estimated_duration_minutes,
                buffer_minutes=buffer_minutes,
                status="unscheduled",
            )
        )

    # Ensure some athletes are explicitly present in multiple events.
    if events and crossover_ids:
        for idx, athlete_id in enumerate(crossover_ids[:3]):
            target_event = events[idx % len(events)]
            if athlete_id not in target_event.athlete_ids:
                target_event.athlete_ids.append(athlete_id)
                target_event.athlete_ids = sorted(set(target_event.athlete_ids))
                event_athletes = [athlete_by_id[item] for item in target_event.athlete_ids]
                target_event.team_ids = sorted({athlete.team_id for athlete in event_athletes})
                target_event.required_coach_ids = sorted(
                    {coach_id for athlete in event_athletes for coach_id in athlete.coach_ids}
                )
                matching_division = next(div for div in divisions if div.id == target_event.division_id)
                matching_division.athlete_ids = target_event.athlete_ids
                matching_division.team_ids = target_event.team_ids

    # Keep division and event names consistent with the final athlete counts.
    event_by_division_id = {event.division_id: event for event in events}
    for division_index, division in enumerate(divisions, start=1):
        final_size = len(division.athlete_ids)
        final_name = _division_name(division_index, division.event_type, final_size)
        division.name = final_name
        event_by_division_id[division.id].division_name = final_name

    return divisions, events


def _estimate_duration(event_type: str, size: int) -> int:
    if event_type == "kyorugi":
        return 10 + size * 4
    if event_type == "poomsae":
        return 8 + size * 3
    return 12 + size * 3


def _division_name(index: int, event_type: str, size: int) -> str:
    type_label = {
        "kyorugi": "Kyorugi",
        "poomsae": "Poomsae",
        "team_poomsae": "Team Poomsae",
    }[event_type]
    return f"{type_label} Division {index} ({size} competitors)"
