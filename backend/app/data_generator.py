from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Literal

from .brackets import rounds_for_ranked_entries
from .models import Athlete, Coach, Division, Referee, RefereeCrew, Ring, Team, Tournament, TournamentEvent

EVENT_TYPES: list[Literal["kyorugi", "poomsae", "pair_poomsae", "team_poomsae"]] = [
    "kyorugi",
    "poomsae",
    "pair_poomsae",
    "team_poomsae",
]
DIVISION_SIZE_PATTERN = [4, 6, 8, 10, 12, 16, 18, 20]
AGE_GROUPS: list[Literal["peewee", "cadet", "junior", "senior"]] = ["peewee", "cadet", "junior", "senior"]
GENDERS: list[Literal["male", "female"]] = ["male", "female"]
BELT_LEVELS: list[Literal["color_belt", "black_belt", "world_class"]] = ["color_belt", "black_belt", "world_class"]

# Simplified WT/USAT-inspired buckets for demo data. This is intentionally not an official rulebook.
KYORUGI_WEIGHT_CLASSES: dict[str, dict[str, list[str]]] = {
    "peewee": {
        "male": ["Light", "Middle", "Heavy"],
        "female": ["Light", "Middle", "Heavy"],
    },
    "cadet": {
        "male": ["-33", "-37", "-41", "-45", "-49", "-53", "-57", "-61", "-65", "+65"],
        "female": ["-29", "-33", "-37", "-41", "-44", "-47", "-51", "-55", "-59", "+59"],
    },
    "junior": {
        "male": ["-45", "-48", "-51", "-55", "-59", "-63", "-68", "-73", "-78", "+78"],
        "female": ["-42", "-44", "-46", "-49", "-52", "-55", "-59", "-63", "-68", "+68"],
    },
    "senior": {
        "male": ["-54", "-58", "-63", "-68", "-74", "-80", "-87", "+87"],
        "female": ["-46", "-49", "-53", "-57", "-62", "-67", "-73", "+73"],
    },
}


def _normalize_demo_roster(event_type: str, roster_ids: list[str]) -> list[str]:
    trimmed = sorted(roster_ids)
    if event_type == "pair_poomsae":
        if len(trimmed) >= 2 and len(trimmed) % 2 == 1:
            trimmed = trimmed[:-1]
        return trimmed if len(trimmed) >= 2 else []

    if event_type == "team_poomsae":
        leftover = len(trimmed) % 3
        if leftover:
            trimmed = trimmed[:-leftover]

        return trimmed if len(trimmed) >= 3 else []

    return trimmed


def _scoring_slots(event_type: str, roster_count: int) -> int:
    if event_type == "poomsae":
        return roster_count

    if event_type == "pair_poomsae":
        return roster_count // 2

    if event_type == "team_poomsae":
        return roster_count // 3

    return roster_count


@dataclass(frozen=True)
class GeneratorParams:
    number_of_rings: int = 5
    number_of_athletes: int = 360
    number_of_teams: int = 24
    number_of_referee_crews: int = 10
    number_of_divisions: int = 61
    target_tournament_minutes: int = 480
    seed: int = 42


def generate_tournament(
    number_of_rings: int = 5,
    number_of_athletes: int = 360,
    number_of_teams: int = 24,
    number_of_referee_crews: int = 10,
    number_of_divisions: int = 61,
    target_tournament_minutes: int = 480,
    seed: int = 42,
) -> Tournament:
    params = GeneratorParams(
        number_of_rings=max(1, number_of_rings),
        number_of_athletes=max(8, number_of_athletes, number_of_divisions * 4),
        number_of_teams=max(2, number_of_teams),
        number_of_referee_crews=max(1, max(number_of_referee_crews, number_of_rings)),
        number_of_divisions=max(1, number_of_divisions),
        target_tournament_minutes=max(120, target_tournament_minutes),
        seed=seed,
    )
    rng = random.Random(params.seed)

    rings = [Ring(id=f"ring-{idx + 1}", name=f"Ring {idx + 1}") for idx in range(params.number_of_rings)]

    referees_manifest: list[Referee] = []
    referee_crews = []
    for crew_idx in range(params.number_of_referee_crews):
        crew_id = f"ref-crew-{crew_idx + 1}"
        qualification_sets = (
            ["kyorugi", "center_referee"],
            ["kyorugi", "corner"],
            ["poomsae", "judge"],
            ["kyorugi", "judge"],
        )
        referee_ids_local: list[str] = []
        roster_pattern = [3, 3, 4, 5, 5]
        roster_size = roster_pattern[crew_idx % len(roster_pattern)]
        for slot in range(roster_size):
            rid = f"referee-{len(referees_manifest) + 1}"
            referee_ids_local.append(rid)
            quals = list(qualification_sets[slot % len(qualification_sets)])
            referees_manifest.append(
                Referee(referee_id=rid, name=f"Official {rid.split('-')[-1]}", home_crew_id=crew_id, qualifications=quals)
            )
        referee_crews.append(
            RefereeCrew(id=crew_id, name=f"Referee Crew {crew_idx + 1}", referee_ids=referee_ids_local)
        )

    teams, coaches = _build_teams_and_coaches(params.number_of_teams)
    athletes = _build_athletes(params.number_of_athletes, teams, coaches, rng)
    divisions, events = _build_divisions_and_events(athletes, teams, rng, params)

    return Tournament(
        id="tkf-demo-open",
        name="TaekwonFlo Demo Open",
        rings=rings,
        teams=teams,
        coaches=coaches,
        athletes=athletes,
        divisions=divisions,
        referee_crews=referee_crews,
        referees=referees_manifest,
        events=events,
        lunch_start_minute=180,
        lunch_duration_minutes=60,
        lunch_grace_minutes=20,
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
                age_group=AGE_GROUPS[athlete_idx % len(AGE_GROUPS)],
                gender=GENDERS[(athlete_idx // 2) % len(GENDERS)],
                belt_level=BELT_LEVELS[(athlete_idx // 5) % len(BELT_LEVELS)],
            )
        )

    return athletes


def _build_divisions_and_events(
    athletes: list[Athlete],
    teams: list[Team],
    rng: random.Random,
    params: GeneratorParams,
) -> tuple[list[Division], list[TournamentEvent]]:
    del teams
    athlete_by_id = {athlete.id: athlete for athlete in athletes}
    athlete_ids = [athlete.id for athlete in athletes]
    base_divisions = params.number_of_divisions
    crossover_ids = rng.sample(athlete_ids, k=min(max(12, len(athlete_ids) // 10), len(athlete_ids)))

    divisions: list[Division] = []
    events: list[TournamentEvent] = []

    for division_index in range(base_divisions):
        event_type = EVENT_TYPES[division_index % len(EVENT_TYPES)]
        requested_size = DIVISION_SIZE_PATTERN[division_index % len(DIVISION_SIZE_PATTERN)]
        age_group = AGE_GROUPS[division_index % len(AGE_GROUPS)]
        gender = GENDERS[(division_index // 2) % len(GENDERS)]
        belt_level = BELT_LEVELS[(division_index // 3) % len(BELT_LEVELS)]
        weight_class = _weight_class(event_type, age_group, gender, division_index)
        eligible_ids = [
            athlete.id
            for athlete in athletes
            if athlete.age_group == age_group and athlete.gender == gender and athlete.belt_level == belt_level
        ]
        if len(eligible_ids) < 2:
            eligible_ids = [
                athlete.id
                for athlete in athletes
                if athlete.age_group == age_group and athlete.gender == gender
            ]
        if len(eligible_ids) < 2:
            eligible_ids = athlete_ids

        size = min(requested_size, len(eligible_ids))
        if size < 2:
            continue

        selected_set = set(rng.sample(eligible_ids, k=size))
        if division_index < len(crossover_ids):
            selected_set.add(crossover_ids[division_index])
        if division_index % 2 == 0 and crossover_ids:
            selected_set.add(crossover_ids[(division_index + 1) % len(crossover_ids)])

        while len(selected_set) < size:
            selected_set.add(rng.choice(eligible_ids))
        selected_athletes = sorted(rng.sample(list(selected_set), k=size))

        canonical_ids = _normalize_demo_roster(event_type, selected_athletes)

        if not canonical_ids:

            continue

        selected_athletes = canonical_ids

        final_size = len(selected_athletes)

        division_id = f"division-{division_index + 1}"
        division_name = _division_name(division_index + 1, event_type, final_size, age_group, gender, weight_class)
        division_athletes = [athlete_by_id[athlete_id] for athlete_id in selected_athletes]
        team_ids = sorted({athlete.team_id for athlete in division_athletes})
        required_coach_ids = sorted({coach_id for athlete in division_athletes for coach_id in athlete.coach_ids})

        estimated_duration_minutes = _estimate_duration(event_type, final_size, belt_level)
        buffer_minutes = _buffer_minutes(event_type, final_size)
        bracket_type = _bracket_type(event_type)
        poomsae_rounds = _poomsae_rounds(event_type, final_size)
        round_structure = _round_structure(event_type, final_size)
        required_referee_count = _required_referee_count(event_type, final_size)
        division_gender = "coed" if event_type in {"pair_poomsae", "team_poomsae"} else gender
        bracket_size = _bracket_size(event_type, final_size)

        divisions.append(
            Division(
                id=division_id,
                name=division_name,
                event_type=event_type,
                age_group=age_group,
                gender=division_gender,
                weight_class=weight_class,
                belt_level=belt_level,
                belt_rank_group=belt_level,
                bracket_type=bracket_type,
                poomsae_rounds=poomsae_rounds,
                bracket_size=bracket_size,
                competitor_count=final_size,
                round_structure=round_structure,
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
                required_referee_count=required_referee_count,
                estimated_duration_minutes=estimated_duration_minutes,
                buffer_minutes=buffer_minutes,
                status="unscheduled",
            )
        )

    # Ensure some athletes are explicitly present in multiple events.
    if events and crossover_ids:
        for idx, athlete_id in enumerate(crossover_ids[:3]):
            target_event = events[idx % len(events)]

            matching_division = next(div_item for div_item in divisions if div_item.id == target_event.division_id)

            athlete_roster_snapshot = sorted(set(target_event.athlete_ids + [athlete_id]))

            normalized_bundle = sorted(_normalize_demo_roster(matching_division.event_type, athlete_roster_snapshot))

            if len(normalized_bundle) < (2 if matching_division.event_type == "pair_poomsae" else (3 if matching_division.event_type == "team_poomsae" else 2)):

                continue

            target_event.athlete_ids = normalized_bundle

            crew_roster = [athlete_by_id[aid_token] for aid_token in normalized_bundle]

            target_event.team_ids = sorted({person.team_id for person in crew_roster})

            target_event.required_coach_ids = sorted({cid for person in crew_roster for cid in person.coach_ids})

            belt_signal_used = crew_roster[0].belt_level if crew_roster else matching_division.belt_level

            matching_division.athlete_ids = normalized_bundle

            matching_division.team_ids = target_event.team_ids

            matching_division.competitor_count = len(normalized_bundle)

            matching_division.bracket_size = _bracket_size(matching_division.event_type, matching_division.competitor_count)

            matching_division.poomsae_rounds = _poomsae_rounds(matching_division.event_type, matching_division.competitor_count)

            matching_division.round_structure = _round_structure(matching_division.event_type, matching_division.competitor_count)

            matching_division.estimated_duration_minutes = _estimate_duration(
                matching_division.event_type,

                matching_division.competitor_count,

                belt_signal_used,

            )

            target_event.estimated_duration_minutes = matching_division.estimated_duration_minutes

            target_event.required_referee_count = _required_referee_count(matching_division.event_type, matching_division.competitor_count)


    # Keep division and event names consistent with the final athlete counts.
    event_by_division_id = {ev.division_id: ev for ev in events}
    for division_index, division in enumerate(divisions, start=1):
        final_size = len(division.athlete_ids)
        final_name = _division_name(
            division_index,
            division.event_type,
            final_size,
            division.age_group,
            division.gender,
            division.weight_class,
        )
        division.name = final_name
        event_by_division_id[division.id].division_name = final_name
        division.competitor_count = final_size

    _scale_event_durations(events, divisions, params)

    return divisions, events


def _estimate_duration(event_type: str, size: int, belt_level: str) -> int:
    if event_type == "kyorugi":
        match_count = max(1, size - 1)
        minutes_per_match = 5 if belt_level == "color_belt" else 8
        return 8 + match_count * minutes_per_match

    rounds = len(_poomsae_rounds(event_type, size))

    if event_type == "poomsae":
        final_multiplier = 5 if belt_level in {"black_belt", "world_class"} else 4
        return 8 + max(1, rounds - 1) * round(size * 2.5) + min(size, 8) * final_multiplier

    if event_type == "pair_poomsae":
        return 8 + max(1, rounds - 1) * round(size * 3.0) + min(size, 8) * 5

    return 10 + max(1, rounds - 1) * round(size * 3.0) + min(size, 8) * 5


def _division_name(index: int, event_type: str, size: int, age_group: str, gender: str, weight_class: str) -> str:
    type_label = {
        "kyorugi": "Kyorugi",
        "poomsae": "Poomsae",
        "pair_poomsae": "Pair Poomsae",
        "team_poomsae": "Team Poomsae",
    }[event_type]
    class_label = weight_class if event_type == "kyorugi" else "Open"
    return f"{age_group.title()} {gender.title()} {class_label} {type_label} {index} ({size} competitors)"


def _weight_class(event_type: str, age_group: str, gender: str, division_index: int) -> str:
    if event_type != "kyorugi":
        return "Open"
    classes = KYORUGI_WEIGHT_CLASSES[age_group][gender]
    return classes[division_index % len(classes)]


def _bracket_type(event_type: str) -> Literal["single_elimination", "poomsae_rounds", "team_poomsae_rounds"]:
    if event_type == "kyorugi":
        return "single_elimination"
    if event_type == "poomsae":
        return "poomsae_rounds"
    return "team_poomsae_rounds"


def _poomsae_rounds(event_type: str, roster_size: int) -> list[str]:
    if event_type == "kyorugi":
        return []

    units = _scoring_slots(event_type, roster_size)

    if units <= 0:
        return ["final"]

    return rounds_for_ranked_entries(units)


def _required_referee_count(event_type: str, size: int) -> int:
    if event_type == "kyorugi":
        return 3
    if event_type in {"poomsae", "pair_poomsae"} and size >= 6:
        return 5
    if event_type == "team_poomsae" and size >= 6:
        return 5
    return 3


def _buffer_minutes(event_type: str, size: int) -> int:
    if event_type == "kyorugi":
        return 5 if size <= 8 else 7
    if event_type == "poomsae":
        return 6
    return 8


def _bracket_size(event_type: str, size: int) -> int:
    if event_type != "kyorugi":
        return size
    bracket_size = 1
    while bracket_size < max(2, size):
        bracket_size *= 2
    return bracket_size


def _round_structure(event_type: str, size: int) -> list[str]:
    if event_type != "kyorugi":
        return _poomsae_rounds(event_type, size)
    bracket_size = _bracket_size(event_type, size)
    if bracket_size <= 2:
        return ["final"]
    if bracket_size <= 4:
        return ["semifinal", "final"]
    if bracket_size <= 8:
        return ["quarterfinal", "semifinal", "final"]
    return ["round of 16", "quarterfinal", "semifinal", "final"]


def _scale_event_durations(
    events: list[TournamentEvent],
    divisions: list[Division],
    params: GeneratorParams,
) -> None:
    # Resource conflicts and shared coaches/athletes stretch the CP-SAT makespan beyond the raw ring workload.
    # Calibrate generated division durations below the theoretical ring total so the solved day lands near target.
    target_total_minutes = round(params.target_tournament_minutes * params.number_of_rings * 0.53)
    current_total_minutes = sum(event.estimated_duration_minutes + event.buffer_minutes for event in events)
    if current_total_minutes <= 0:
        return

    scale = target_total_minutes / current_total_minutes
    division_by_id = {division.id: division for division in divisions}
    for event in events:
        scaled_duration = max(8, round(event.estimated_duration_minutes * scale))
        event.estimated_duration_minutes = scaled_duration
        division_by_id[event.division_id].estimated_duration_minutes = scaled_duration
