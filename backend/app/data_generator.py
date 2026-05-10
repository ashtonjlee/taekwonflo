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
    divisions: list[Division] = []
    events: list[TournamentEvent] = []
    all_specs = _division_specs()
    kyorugi_specs = [spec for spec in all_specs if spec["event_type"] == "kyorugi"]
    poomsae_specs = [spec for spec in all_specs if spec["event_type"] != "kyorugi"]
    rng.shuffle(kyorugi_specs)
    rng.shuffle(poomsae_specs)

    requested = params.number_of_divisions
    kyorugi_target = min(len(kyorugi_specs), max(1, round(requested * 0.72)))
    selected_specs = kyorugi_specs[:kyorugi_target]
    need_more = requested - len(selected_specs)
    if need_more > 0:
        selected_specs.extend(poomsae_specs[:need_more])
    if len(selected_specs) < requested:
        leftovers = [spec for spec in all_specs if spec not in selected_specs]
        selected_specs.extend(leftovers[: requested - len(selected_specs)])
    selected_specs = selected_specs[:requested]

    duplicate_counts: dict[str, int] = {}

    for division_index, spec in enumerate(selected_specs, start=1):
        event_type = spec["event_type"]
        age_group = spec["age_group"]
        gender = spec["gender"]
        belt_level = spec["belt_level"]
        weight_class = spec["weight_class"]
        division_gender = spec["division_gender"]

        eligible_ids = _eligible_athletes(athletes, spec)
        requested_size = _target_size(event_type, rng)
        size = min(requested_size, len(eligible_ids))
        if size < 2:
            continue

        selected_athletes = sorted(rng.sample(eligible_ids, k=size))
        canonical_ids = _normalize_demo_roster(event_type, selected_athletes)
        if not canonical_ids:
            continue
        selected_athletes = canonical_ids
        final_size = len(selected_athletes)

        base_name = _division_name(
            event_type=event_type,
            age_group=age_group,
            gender=division_gender,
            belt_level=belt_level,
            weight_class=weight_class,
        )
        duplicate_counts[base_name] = duplicate_counts.get(base_name, 0) + 1
        flight_label = _flight_name(duplicate_counts[base_name]) if duplicate_counts[base_name] > 1 else None
        division_name = f"{base_name} {flight_label}" if flight_label else base_name

        division_id = f"division-{division_index}"
        division_athletes = [athlete_by_id[athlete_id] for athlete_id in selected_athletes]
        team_ids = sorted({athlete.team_id for athlete in division_athletes})
        required_coach_ids = sorted(
            {
                _primary_coach_for_event(athlete, division_id, event_type)
                for athlete in division_athletes
                if _primary_coach_for_event(athlete, division_id, event_type)
            }
        )

        estimated_duration_minutes = _estimate_duration(event_type, final_size, belt_level)
        buffer_minutes = _buffer_minutes(event_type, final_size)
        bracket_type = _bracket_type(event_type)
        poomsae_rounds = _poomsae_rounds(event_type, final_size)
        round_structure = _round_structure(event_type, final_size)
        required_referee_count = _required_referee_count(event_type, final_size)
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
                event_id=f"event-{division_index}",
                division_id=division_id,
                division_name=division_name,
                event_type=event_type,
                age_group=age_group,
                belt_rank_group=belt_level,
                weight_class=weight_class,
                athlete_ids=selected_athletes,
                team_ids=team_ids,
                required_coach_ids=required_coach_ids,
                required_referee_count=required_referee_count,
                estimated_duration_minutes=estimated_duration_minutes,
                buffer_minutes=buffer_minutes,
                status="unscheduled",
            )
        )

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


def _division_name(
    *,
    event_type: str,
    age_group: str,
    gender: str,
    belt_level: str,
    weight_class: str,
) -> str:
    belt_label = _belt_label(belt_level)
    age_label = age_group.title()
    gender_label = "Coed" if gender in {"coed", "mixed"} else gender.title()
    if event_type == "kyorugi":
        return f"{age_label} {gender_label} {belt_label} {_weight_label(weight_class)} Kyorugi"
    event_label = {
        "poomsae": "Individual Poomsae",
        "pair_poomsae": "Pair Poomsae",
        "team_poomsae": "Team Poomsae",
    }[event_type]
    return f"{age_label} {gender_label} {belt_label} {event_label}"


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

    if units >= 36:
        return ["preliminary flight A", "preliminary flight B", "preliminary flight C", "semifinal", "final"]
    if units >= 24:
        return ["preliminary flight A", "preliminary flight B", "semifinal", "final"]
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


def _division_specs() -> list[dict[str, str]]:
    specs: list[dict[str, str]] = []
    for age_group in AGE_GROUPS:
        for gender in GENDERS:
            for belt_level in BELT_LEVELS:
                for wc in KYORUGI_WEIGHT_CLASSES[age_group][gender]:
                    specs.append(
                        {
                            "event_type": "kyorugi",
                            "age_group": age_group,
                            "gender": gender,
                            "division_gender": gender,
                            "belt_level": belt_level,
                            "weight_class": wc,
                        }
                    )

    for age_group in AGE_GROUPS:
        for belt_level in BELT_LEVELS:
            for gender in GENDERS:
                specs.append(
                    {
                        "event_type": "poomsae",
                        "age_group": age_group,
                        "gender": gender,
                        "division_gender": gender,
                        "belt_level": belt_level,
                        "weight_class": "Open",
                    }
                )
            for event_type in ("pair_poomsae", "team_poomsae"):
                specs.append(
                    {
                        "event_type": event_type,
                        "age_group": age_group,
                        "gender": "mixed",
                        "division_gender": "coed",
                        "belt_level": belt_level,
                        "weight_class": "Open",
                    }
                )
    return specs


def _eligible_athletes(athletes: list[Athlete], spec: dict[str, str]) -> list[str]:
    event_type = spec["event_type"]
    age_group = spec["age_group"]
    belt_level = spec["belt_level"]
    gender = spec["gender"]
    if event_type in {"pair_poomsae", "team_poomsae"}:
        pool = [a.id for a in athletes if a.age_group == age_group and a.belt_level == belt_level]
    else:
        pool = [
            a.id
            for a in athletes
            if a.age_group == age_group
            and a.belt_level == belt_level
            and (event_type != "kyorugi" or a.gender == gender)
            and (event_type == "kyorugi" or a.gender == gender)
        ]
    if len(pool) >= 2:
        return pool
    return [a.id for a in athletes if a.age_group == age_group and a.belt_level == belt_level] or [a.id for a in athletes]


def _target_size(event_type: str, rng: random.Random) -> int:
    if event_type == "kyorugi":
        return rng.choice([2, 3, 4, 5, 6, 8])
    if event_type == "poomsae":
        return rng.choice([8, 10, 12, 16, 20, 24])
    if event_type == "pair_poomsae":
        return rng.choice([6, 8, 10, 12, 14, 16])
    return rng.choice([6, 9, 12, 15, 18])


def _primary_coach_for_event(athlete: Athlete, division_id: str, event_type: str) -> str | None:
    if not athlete.coach_ids:
        return None
    ordered = sorted(athlete.coach_ids)
    token = f"{athlete.id}:{division_id}:{event_type}"
    return ordered[sum(ord(ch) for ch in token) % len(ordered)]


def _belt_label(belt_level: str) -> str:
    return {
        "color_belt": "Color Belt",
        "black_belt": "Black Belt",
        "world_class": "World Class",
    }.get(belt_level, belt_level.replace("_", " ").title())


def _weight_label(weight_class: str) -> str:
    if weight_class in {"Open", "Light", "Middle", "Heavy"}:
        return weight_class
    if weight_class.startswith(("+", "-")) and weight_class[1:].isdigit():
        return f"{weight_class}kg"
    return weight_class


def _flight_name(flight_index: int) -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    slot = (flight_index - 2) % len(alphabet)
    return f"Flight {alphabet[slot]}"


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
