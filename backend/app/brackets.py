from __future__ import annotations

import math

from .models import (
    Bracket,
    Division,
    DivisionDetail,
    Match,
    MatchCompetitor,
    MatchScore,
    RingSchedule,
    ScheduledEvent,
    Team,
    Tournament,
)


def build_division_detail(
    tournament: Tournament,
    schedule: list[RingSchedule],
    division_id: str,
    current_minute: int = 60,
) -> DivisionDetail:
    division = next((item for item in tournament.divisions if item.id == division_id), None)
    if not division:
        raise KeyError(division_id)

    scheduled_event = next(
        (event for ring in schedule for event in ring.events if event.division_id == division_id),
        None,
    )
    if not scheduled_event:
        raise KeyError(f"scheduled event for {division_id}")

    team_by_id = {team.id: team for team in tournament.teams}
    competitors = [
        _competitor_for_athlete(athlete_id, seed, tournament=tournament, team_by_id=team_by_id)
        for seed, athlete_id in enumerate(division.athlete_ids, start=1)
    ]

    matches = (
        _build_kyorugi_matches(division, competitors, scheduled_event, current_minute)
        if division.event_type == "kyorugi"
        else _build_poomsae_matches(division, competitors, scheduled_event, current_minute)
    )
    bracket = Bracket(
        division_id=division.id,
        bracket_type=division.bracket_type,
        rounds=_round_names_for_division(division, len(competitors)),
        matches=matches,
    )

    current_match = next((match for match in matches if match.status == "in_progress"), None)
    completed_matches = [match for match in matches if match.status == "completed"]
    advanced_ids = {match.winner_id for match in completed_matches if match.winner_id}
    advanced_competitors = [competitor for competitor in competitors if competitor.competitor_id in advanced_ids]

    waiting_ids = _competitor_ids_for_status(matches, "waiting") - advanced_ids
    staging_ids = _competitor_ids_for_status(matches, "staging")

    return DivisionDetail(
        division=division,
        competitors=competitors,
        bracket=bracket,
        current_match=current_match,
        waiting_competitors=[competitor for competitor in competitors if competitor.competitor_id in waiting_ids],
        staging_competitors=[competitor for competitor in competitors if competitor.competitor_id in staging_ids],
        completed_matches=completed_matches,
        advanced_competitors=advanced_competitors,
    )


def _competitor_for_athlete(
    athlete_id: str,
    seed: int,
    *,
    tournament: Tournament,
    team_by_id: dict[str, Team],
) -> MatchCompetitor:
    athlete = next(item for item in tournament.athletes if item.id == athlete_id)
    team = team_by_id[athlete.team_id]
    return MatchCompetitor(
        competitor_id=athlete.id,
        name=athlete.name,
        team_id=team.id,
        team_name=team.name,
        seed=seed,
        age_group=athlete.age_group,
        gender=athlete.gender,
        belt_level=athlete.belt_level,
    )


def _build_kyorugi_matches(
    division: Division,
    competitors: list[MatchCompetitor],
    scheduled_event: ScheduledEvent,
    current_minute: int,
) -> list[Match]:
    bracket_size = 1 << math.ceil(math.log2(max(2, len(competitors))))
    rounds = _round_names_for_division(division, len(competitors))
    first_round_slots: list[MatchCompetitor | None] = competitors + [None] * (bracket_size - len(competitors))
    matches: list[Match] = []
    prior_round_winners: list[MatchCompetitor] = []
    minutes_per_match = max(6, scheduled_event.estimated_duration_minutes // max(1, bracket_size - 1))
    match_index = 0

    for position in range(0, bracket_size, 2):
        competitor_1 = first_round_slots[position]
        competitor_2 = first_round_slots[position + 1]
        if competitor_1 is None and competitor_2 is None:
            continue
        match_index += 1
        winner = _deterministic_winner(competitor_1, competitor_2, match_index)
        start, end = _match_window(scheduled_event, match_index - 1, minutes_per_match)
        status = _match_status(start, end, current_minute)
        score = _kyorugi_score(match_index, winner, competitor_1, competitor_2) if status == "completed" else None
        matches.append(
            _match(
                division=division,
                scheduled_event=scheduled_event,
                round_name=rounds[0],
                bracket_position=(position // 2) + 1,
                competitor_1=competitor_1 or competitor_2,
                competitor_2=competitor_2 if competitor_1 else None,
                winner_id=winner.competitor_id if status == "completed" else None,
                score=score,
                status=status,
                start=start,
                end=end,
                match_index=match_index,
                required_referee_count=3,
            )
        )
        prior_round_winners.append(winner)

    for round_index, round_name in enumerate(rounds[1:], start=1):
        next_round_winners: list[MatchCompetitor] = []
        for position in range(0, len(prior_round_winners), 2):
            competitor_1 = prior_round_winners[position]
            competitor_2 = prior_round_winners[position + 1] if position + 1 < len(prior_round_winners) else None
            match_index += 1
            winner = _deterministic_winner(competitor_1, competitor_2, match_index + round_index)
            start, end = _match_window(scheduled_event, match_index - 1, minutes_per_match)
            status = _match_status(start, end, current_minute)
            score = _kyorugi_score(match_index, winner, competitor_1, competitor_2) if status == "completed" else None
            matches.append(
                _match(
                    division=division,
                    scheduled_event=scheduled_event,
                    round_name=round_name,
                    bracket_position=(position // 2) + 1,
                    competitor_1=competitor_1,
                    competitor_2=competitor_2,
                    winner_id=winner.competitor_id if status == "completed" else None,
                    score=score,
                    status=status,
                    start=start,
                    end=end,
                    match_index=match_index,
                    required_referee_count=3,
                )
            )
            next_round_winners.append(winner)
        prior_round_winners = next_round_winners

    return matches


def _build_poomsae_matches(
    division: Division,
    competitors: list[MatchCompetitor],
    scheduled_event: ScheduledEvent,
    current_minute: int,
) -> list[Match]:
    rounds = _round_names_for_division(division, len(competitors))
    minutes_per_group = max(7, scheduled_event.estimated_duration_minutes // max(1, len(rounds)))
    matches: list[Match] = []
    active_competitors = competitors

    for round_index, round_name in enumerate(rounds):
        start, end = _match_window(scheduled_event, round_index, minutes_per_group)
        status = _match_status(start, end, current_minute)
        required_referee_count = 5 if round_name in {"semifinal", "final"} and len(competitors) >= 6 else 3
        ranked = sorted(active_competitors, key=lambda item: ((item.seed * 17 + round_index * 5) % 23, item.seed))
        winner = ranked[0]
        score = _poomsae_score(round_index, ranked[0], ranked[1] if len(ranked) > 1 else None) if status == "completed" else None
        matches.append(
            _match(
                division=division,
                scheduled_event=scheduled_event,
                round_name=round_name,
                bracket_position=1,
                competitor_1=ranked[0],
                competitor_2=ranked[1] if len(ranked) > 1 else None,
                winner_id=winner.competitor_id if status == "completed" else None,
                score=score,
                status=status,
                start=start,
                end=end,
                match_index=round_index + 1,
                required_referee_count=required_referee_count,
            )
        )
        active_competitors = ranked[: max(2, len(ranked) // 2)]

    return matches


def _match(
    *,
    division: Division,
    scheduled_event: ScheduledEvent,
    round_name: str,
    bracket_position: int,
    competitor_1: MatchCompetitor,
    competitor_2: MatchCompetitor | None,
    winner_id: str | None,
    score: MatchScore | None,
    status: str,
    start: int,
    end: int,
    match_index: int,
    required_referee_count: int,
) -> Match:
    return Match(
        match_id=f"{division.id}-match-{match_index}",
        division_id=division.id,
        round_name=round_name,
        bracket_position=bracket_position,
        competitor_1=competitor_1,
        competitor_2=competitor_2,
        winner_id=winner_id,
        score=score,
        status=status,
        scheduled_event_id=scheduled_event.event_id,
        ring_id=scheduled_event.ring_id,
        start_minute=start,
        end_minute=end,
        estimated_duration_minutes=end - start,
        required_referee_count=required_referee_count,
    )


def _round_names_for_division(division: Division, competitor_count: int) -> list[str]:
    if division.event_type != "kyorugi":
        return division.poomsae_rounds or ["final"]
    bracket_size = 1 << math.ceil(math.log2(max(2, competitor_count)))
    if bracket_size <= 2:
        return ["final"]
    if bracket_size <= 4:
        return ["semifinal", "final"]
    if bracket_size <= 8:
        return ["quarterfinal", "semifinal", "final"]
    return ["round of 16", "quarterfinal", "semifinal", "final"]


def _deterministic_winner(
    competitor_1: MatchCompetitor | None,
    competitor_2: MatchCompetitor | None,
    salt: int,
) -> MatchCompetitor:
    if competitor_1 and not competitor_2:
        return competitor_1
    if competitor_2 and not competitor_1:
        return competitor_2
    if not competitor_1 or not competitor_2:
        raise ValueError("A match requires at least one competitor.")
    return competitor_1 if (competitor_1.seed + salt) % 3 != 0 else competitor_2


def _match_window(scheduled_event: ScheduledEvent, match_offset: int, minutes_per_match: int) -> tuple[int, int]:
    start = scheduled_event.start_minute + match_offset * minutes_per_match
    end = min(start + minutes_per_match, scheduled_event.end_minute)
    return start, max(start + 1, end)


def _match_status(start: int, end: int, current_minute: int) -> str:
    if end <= current_minute:
        return "completed"
    if start <= current_minute < end:
        return "in_progress"
    if start - current_minute <= 10:
        return "staging"
    return "waiting"


def _kyorugi_score(
    match_index: int,
    winner: MatchCompetitor,
    competitor_1: MatchCompetitor,
    competitor_2: MatchCompetitor | None,
) -> MatchScore:
    if not competitor_2:
        return MatchScore(winner_margin="bye")
    base = 7 + (match_index % 6)
    losing = max(0, base - 2 - (match_index % 3))
    return MatchScore(
        competitor_1_points=base if winner.competitor_id == competitor_1.competitor_id else losing,
        competitor_2_points=base if winner.competitor_id == competitor_2.competitor_id else losing,
        winner_margin=f"{abs(base - losing)} point margin",
    )


def _poomsae_score(
    round_index: int,
    competitor_1: MatchCompetitor,
    competitor_2: MatchCompetitor | None,
) -> MatchScore:
    first_score = round(7.2 + ((competitor_1.seed + round_index) % 12) / 10, 1)
    second_score = round(first_score - 0.2, 1) if competitor_2 else None
    return MatchScore(
        competitor_1_poomsae=first_score,
        competitor_2_poomsae=second_score,
        winner_margin="highest presentation and accuracy total",
    )


def _competitor_ids_for_status(matches: list[Match], status: str) -> set[str]:
    ids: set[str] = set()
    for match in matches:
        if match.status != status:
            continue
        ids.add(match.competitor_1.competitor_id)
        if match.competitor_2:
            ids.add(match.competitor_2.competitor_id)
    return ids
