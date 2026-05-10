from __future__ import annotations

import hashlib
import math
from collections import defaultdict

from .models import (
    Bracket,
    Coach,
    CoachToReport,
    Division,
    DivisionDetail,
    DivisionDetailValidation,
    KyorugiBracketRound,
    Match,
    MatchCompetitor,
    MatchScore,
    RankedBracketEntry,
    RankedBracketRound,
    Ring,
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
    focus_match_id: str | None = None,
    match_number_by_match_id: dict[str, int] | None = None,
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

    ring_name = scheduled_event.ring_name
    team_by_id = {team.id: team for team in tournament.teams}
    coach_lookup = {coach.id: coach for coach in tournament.coaches}
    competitor_roster = [
        _competitor_for_athlete(
            athlete_id,
            seed,
            tournament=tournament,
            team_by_id=team_by_id,
            coach_by_id=coach_lookup,
        )
        for seed, athlete_id in enumerate(division.athlete_ids, start=1)
    ]

    kyorugi_blocks: list[KyorugiBracketRound] = []
    ranked_blocks: list[RankedBracketRound] = []

    if division.event_type == "kyorugi":
        label_order = _round_names_for_division(division, len(competitor_roster))
        matches = _build_kyorugi_matches(
            division,
            competitor_roster,
            scheduled_event,
            current_minute,
            ring_name,
            label_order,
            match_number_by_match_id=match_number_by_match_id,
            rings=tournament.rings,
        )
        kyorugi_blocks = _assign_kyorugi_next_matches(matches, label_order)
        bracket_rounds = label_order
        kyorugi_losers = {
            matchup.loser_id
            for matchup in matches
            if matchup.loser_id and matchup.status == "completed" and not matchup.bye
        }
    else:
        matches, ranked_blocks = _build_ranked_rounds(
            division,
            competitor_roster,
            tournament,
            team_by_id,
            coach_lookup,
            scheduled_event,
            current_minute,
            ring_name,
            match_number_by_match_id=match_number_by_match_id,
            rings=tournament.rings,
        )
        bracket_rounds = [panel.round_name for panel in ranked_blocks]
        kyorugi_losers = set()

    matches_ordered = sorted(
        matches,
        key=lambda duel: (
            duel.start_minute,
            duel.round_name,
            duel.bracket_position,
            duel.match_id,
        ),
    )

    bracket_bundle = Bracket(
        division_id=division.id,
        bracket_type=division.bracket_type,
        rounds=bracket_rounds,
        matches=matches_ordered,
    )

    active_duel = next((duel for duel in matches_ordered if duel.status == "in_progress"), None)
    finished_duels = [duel for duel in matches_ordered if duel.status == "completed"]

    awaiting = _participant_ids_with_status(matches_ordered, "waiting")
    staging_hold = _participant_ids_with_status(matches_ordered, "staging")

    survivor_lookup = _advanced_candidates(
        division.event_type,
        competitor_roster,
        matches_ordered,
        kyorugi_losers,
        ranked_blocks,
    )

    coach_board = _build_coach_sheet(
        tournament,
        competitor_roster,
        matches_ordered,
        scheduled_event,
        ring_name,
        division,
        current_minute,
    )

    detail_audit = audit_division_graph(
        division=division,
        matches=matches_ordered,
        kyorugi_blocks=kyorugi_blocks,
        ranked_blocks=ranked_blocks,
        coach_lookup=coach_lookup,
        ranked_entry_builder=lambda: build_poomsae_entries(division, tournament, team_by_id, coach_lookup),
    )

    return DivisionDetail(
        division=division,
        competitors=competitor_roster,
        bracket=bracket_bundle,
        current_match=active_duel,
        waiting_competitors=[human for human in competitor_roster if human.competitor_id in awaiting],
        staging_competitors=[human for human in competitor_roster if human.competitor_id in staging_hold],
        completed_matches=sorted(finished_duels, key=lambda duel: (duel.start_minute, duel.match_id)),
        advanced_competitors=survivor_lookup,
        kyorugi_rounds=kyorugi_blocks,
        ranked_rounds=ranked_blocks,
        coach_report=coach_board,
        detail_validation=detail_audit,
        focused_match_id=focus_match_id,
    )


def _competitor_for_athlete(
    athlete_id: str,
    seed: int,
    *,
    tournament: Tournament,
    team_by_id: dict[str, Team],
    coach_by_id: dict[str, Coach],
) -> MatchCompetitor:
    athlete = next(item for item in tournament.athletes if item.id == athlete_id)
    team = team_by_id[athlete.team_id]
    coach_labels = [coach_by_id[item].name for item in athlete.coach_ids if item in coach_by_id]
    return MatchCompetitor(
        competitor_id=athlete.id,
        name=athlete.name,
        team_id=team.id,
        team_name=team.name,
        seed=seed,
        age_group=athlete.age_group,
        gender=athlete.gender,
        belt_level=athlete.belt_level,
        coach_ids=list(athlete.coach_ids),
        coach_names=coach_labels,
    )


def athlete_ids_involved(match_record: Match) -> list[str]:
    if match_record.participant_athlete_ids:
        return list(match_record.participant_athlete_ids)
    bundle: list[str] = []
    if match_record.competitor_1:
        bundle.append(match_record.competitor_1.competitor_id)
    if match_record.competitor_2:
        bundle.append(match_record.competitor_2.competitor_id)
    return bundle


def assigned_coach_ids_involved(match_record: Match) -> list[str]:
    coach_ids: set[str] = set()
    for side in (match_record.competitor_1, match_record.competitor_2):
        if side and side.assigned_coach_id:
            coach_ids.add(side.assigned_coach_id)
    return sorted(coach_ids)


def competitor_ids_for_audit(match_record: Match) -> list[str]:
    """Known lineup only (revealed competitors — excludes placeholders)."""
    ids: list[str] = []
    if match_record.competitor_1:
        ids.append(match_record.competitor_1.competitor_id)
    if match_record.competitor_2:
        ids.append(match_record.competitor_2.competitor_id)
    return ids


def _seed_even_spaced_positions(fighters: list[MatchCompetitor], bracket_capacity: int) -> list[MatchCompetitor | None]:
    """Spread athletes across bracket leaves so phantom byes stay isolated."""
    platter: list[MatchCompetitor | None] = [None] * bracket_capacity

    roster_order = sorted(fighters, key=lambda athlete: athlete.seed)

    stroll = 0

    for warrior in roster_order:

        positioned = False

        for leap in range(0, bracket_capacity, 2):

            candidate_slot = (stroll + leap) % bracket_capacity

            if platter[candidate_slot] is None:

                platter[candidate_slot] = warrior

                stroll = (candidate_slot + 2) % bracket_capacity

                positioned = True

                break

        if not positioned:

            filler = next(hole for hole in range(bracket_capacity) if platter[hole] is None)

            platter[filler] = warrior

            stroll = filler + 2

    return platter


def _match_window_round_parallel(
    scheduled_event: ScheduledEvent,
    round_depth: int,
    minutes_per_match: int,
    round_gap_min: int = 5,
) -> tuple[int, int]:
    """Start/end shared by every match in the same kyorugi round (parallel wave)."""
    gap = max(0, round_gap_min)
    phase = round_depth * (minutes_per_match + gap)
    start = scheduled_event.start_minute + phase
    end = min(start + minutes_per_match, scheduled_event.end_minute)
    if end <= start:
        end = min(start + 1, scheduled_event.end_minute)
    return start, max(start + 1, end)


def _kyorugi_ring_assignment(
    *,
    ring_slots: list[Ring],
    scheduled_event: ScheduledEvent,
    legacy_ring_name: str,
    round_label: str,
    bracket_position: int,
) -> tuple[str, str]:
    """Spread early kyorugi across rings; consolidate finals onto ring 1."""
    if not ring_slots:
        return scheduled_event.ring_id, legacy_ring_name
    if round_label == "final":
        picked = ring_slots[0]
    elif round_label == "semifinal":
        picked = ring_slots[(bracket_position - 1) % min(2, len(ring_slots))]
    else:
        picked = ring_slots[(bracket_position - 1) % len(ring_slots)]
    return picked.id, picked.name


def _build_kyorugi_matches(
    division: Division,
    competitors: list[MatchCompetitor],
    scheduled_event: ScheduledEvent,
    current_minute: int,
    ring_name: str,
    rounds: list[str],
    match_number_by_match_id: dict[str, int] | None = None,
    rings: list[Ring] | None = None,
    round_gap_minutes: int = 5,
) -> list[Match]:
    roster_lookup = {person.competitor_id: person for person in competitors}
    bracket_size = 1 << math.ceil(math.log2(max(2, len(competitors))))

    first_slots = _seed_even_spaced_positions(competitors, bracket_size)
    bouts: list[Match] = []
    ring_slots = list(rings) if rings else [Ring(id=scheduled_event.ring_id, name=ring_name)]
    minutes_per_segment = max(6, scheduled_event.estimated_duration_minutes // max(1, len(rounds)))
    sequence = 0
    assigned_refs = list(scheduled_event.assigned_referee_ids)

    prior_round: list[Match] = []
    first_label = rounds[0]

    for pairing in range(0, bracket_size, 2):
        left_corner = first_slots[pairing]
        right_corner = first_slots[pairing + 1]
        if left_corner is None and right_corner is None:
            continue
        sequence += 1
        bracket_position = (pairing // 2) + 1
        match_id = f"{division.id}-ky-{first_label}-{bracket_position}"
        start_slice, stop_slice = _match_window_round_parallel(
            scheduled_event, 0, minutes_per_segment, round_gap_minutes
        )
        duel_state = _match_status(start_slice, stop_slice, current_minute)

        bye_path = left_corner is None or right_corner is None
        display_one = _competitor_with_assigned_coach(
            left_corner if left_corner else right_corner,
            match_id=match_id,
        )
        display_two = _competitor_with_assigned_coach(
            right_corner if left_corner and right_corner else None,
            match_id=match_id,
        )

        victor: MatchCompetitor | None = None
        fail_id: str | None = None
        duel_score: MatchScore | None = None

        if duel_state == "completed":
            victor = _mock_kyorugi_winner(left_corner, right_corner, match_id=match_id, salt=sequence)
            if left_corner and right_corner and victor is not None:
                fail_id = (
                    left_corner.competitor_id if victor.competitor_id == right_corner.competitor_id else right_corner.competitor_id
                )
            duel_score = (
                _kyorugi_score(sequence, victor, display_one, display_two)
                if display_two is not None
                else MatchScore(winner_margin="bye")
            )

        rid, rnm = _kyorugi_ring_assignment(
            ring_slots=ring_slots,
            scheduled_event=scheduled_event,
            legacy_ring_name=ring_name,
            round_label=first_label,
            bracket_position=bracket_position,
        )
        bout = _match(
            division=division,
            scheduled_event=scheduled_event,
            ring_name=rnm,
            ring_id=rid,
            round_name=first_label,
            bracket_position=bracket_position,
            competitor_1=display_one,
            competitor_2=display_two,
            winner_id=victor.competitor_id if victor is not None and duel_state == "completed" else None,
            loser_id=None if duel_state != "completed" or bye_path else fail_id,
            score=duel_score,
            status=duel_state,
            start=start_slice,
            end=stop_slice,
            match_index=sequence,
            required_referee_count=3,
            match_id_override=match_id,
            match_number=_resolve_match_number(match_number_by_match_id, match_id, sequence),
            bye_flag=bye_path,
            feeder_1_match_number=None,
            feeder_2_match_number=None,
            assigned_referee_ids=assigned_refs,
        )
        bouts.append(bout)
        prior_round.append(bout)

    prior_round = sorted(prior_round, key=lambda duel: duel.bracket_position)

    for ladder_index, label in enumerate(rounds[1:], start=1):
        next_round: list[Match] = []
        for offset in range(0, len(prior_round), 2):
            left_feed = prior_round[offset]
            right_feed = prior_round[offset + 1]
            sequence += 1
            bracket_position = (offset // 2) + 1
            match_id = f"{division.id}-ky-{label}-{bracket_position}"
            slice_start, slice_stop = _match_window_round_parallel(
                scheduled_event, ladder_index, minutes_per_segment, round_gap_minutes
            )
            progress = _match_status(slice_start, slice_stop, current_minute)

            lw = roster_lookup[left_feed.winner_id] if left_feed.winner_id and left_feed.status == "completed" else None
            rw = roster_lookup[right_feed.winner_id] if right_feed.winner_id and right_feed.status == "completed" else None

            competitors_ready = lw is not None and rw is not None

            victor: MatchCompetitor | None = None
            loser_token: str | None = None
            score_line: MatchScore | None = None

            if competitors_ready and progress == "completed":
                victor = _mock_kyorugi_winner(lw, rw, match_id=match_id, salt=sequence + ladder_index)
                loser_token = lw.competitor_id if victor.competitor_id == rw.competitor_id else rw.competitor_id
                score_line = _kyorugi_score(sequence, victor, lw, rw)

            competitor_one = _competitor_with_assigned_coach(lw, match_id=match_id)
            competitor_two = _competitor_with_assigned_coach(rw, match_id=match_id)

            rid, rnm = _kyorugi_ring_assignment(
                ring_slots=ring_slots,
                scheduled_event=scheduled_event,
                legacy_ring_name=ring_name,
                round_label=label,
                bracket_position=bracket_position,
            )
            bout = _match(
                division=division,
                scheduled_event=scheduled_event,
                ring_name=rnm,
                ring_id=rid,
                round_name=label,
                bracket_position=bracket_position,
                competitor_1=competitor_one,
                competitor_2=competitor_two,
                winner_id=victor.competitor_id if victor is not None and progress == "completed" else None,
                loser_id=None if progress != "completed" or not competitors_ready else loser_token,
                score=score_line,
                status=progress,
                start=slice_start,
                end=slice_stop,
                match_index=sequence,
                required_referee_count=3,
                match_id_override=match_id,
                match_number=_resolve_match_number(match_number_by_match_id, match_id, sequence),
                bye_flag=False,
                feeder_1_match_number=left_feed.match_number,
                feeder_2_match_number=right_feed.match_number,
                assigned_referee_ids=assigned_refs,
            )
            next_round.append(bout)
            bouts.append(bout)

        prior_round = sorted(next_round, key=lambda duel: duel.bracket_position)

    _annotate_kyorugi_placeholder_labels(bouts, rounds[0])
    return sorted(bouts, key=lambda match: match.match_number)


def _annotate_kyorugi_placeholder_labels(bouts: list[Match], first_round_label: str) -> None:
    by_number = {duel.match_number: duel for duel in bouts}
    for duel in bouts:
        if duel.round_name == first_round_label:
            duel.source_1_label = None
            duel.source_2_label = None
            continue

        for feeder_num, comp_attr, label_attr in (
            (duel.feeder_1_match_number, "competitor_1", "source_1_label"),
            (duel.feeder_2_match_number, "competitor_2", "source_2_label"),
        ):
            if feeder_num is None:
                setattr(duel, label_attr, None)
                continue
            setattr(duel, label_attr, None)
            comp = getattr(duel, comp_attr)
            feeder = by_number.get(feeder_num)

            feeder_done = feeder and feeder.status == "completed" and feeder.winner_id
            revealed = feeder_done

            if not revealed and comp is None:
                setattr(duel, label_attr, f"Winner of Match {feeder_num}")


def _assign_kyorugi_next_matches(bouts: list[Match], label_order: list[str]) -> list[KyorugiBracketRound]:
    grouped: defaultdict[str, list[Match]] = defaultdict(list)
    for contest in bouts:
        grouped[contest.round_name].append(contest)

    panels = [KyorugiBracketRound(round_name=label_fragment, matches=grouped[label_fragment]) for label_fragment in label_order]

    for index in range(len(panels) - 1):
        child_panel = panels[index]
        parent_panel = panels[index + 1]
        ordered_children = sorted(child_panel.matches, key=lambda duel: duel.bracket_position)

        for child in ordered_children:
            ancestor_slot = (child.bracket_position - 1) // 2 + 1

            lineage = next(
                (ancestor for ancestor in parent_panel.matches if ancestor.bracket_position == ancestor_slot),
                None,
            )

            if lineage:
                child.next_match_id = lineage.match_id

    return panels


def _build_ranked_rounds(
    division: Division,
    athlete_roster: list[MatchCompetitor],
    tournament: Tournament,
    team_bundle: dict[str, Team],
    coach_bundle: dict[str, Coach],
    scheduled_segment: ScheduledEvent,
    current_minute: int,
    ring_name: str,
    match_number_by_match_id: dict[str, int] | None = None,
    rings: list[Ring] | None = None,
) -> tuple[list[Match], list[RankedBracketRound]]:
    entries = build_poomsae_entries(division, tournament, team_bundle, coach_bundle)

    roadmap = list(division.poomsae_rounds or rounds_for_ranked_entries(len(entries)))
    workloads = len(entries) * len(roadmap)

    slices = max(5, scheduled_segment.estimated_duration_minutes // max(1, workloads))

    backlog = list(entries)
    matches_out: list[Match] = []
    panels_out: list[RankedBracketRound] = []

    ticker = 0
    ring_slots = list(rings) if rings else [Ring(id=scheduled_segment.ring_id, name=ring_name)]

    for ladder_pos, milestone in enumerate(roadmap):
        finals_only = ladder_pos == len(roadmap) - 1
        survivor_quota = advancing_count_for_round(ladder_pos, roadmap, len(backlog))

        ordering = sorted(
            backlog,
            key=lambda specimen: (-_rank_score(specimen.entry_id, division.id, ladder_pos), sum(ord(ch) for ch in specimen.entry_id), specimen.members[0].seed),
        )

        qualifiers = (
            {}
            if finals_only
            else {candidate.entry_id for candidate in ordering[:survivor_quota]}
        )

        crew_need = (
            5 if milestone in {"semifinal", "final"} and len(entries) >= 6 else 3
        )

        rank_rows: list[RankedBracketEntry] = []

        for podium_spot, specimen in enumerate(ordering, start=1):

            tally = _rank_score(specimen.entry_id, division.id, ladder_pos)

            window_start, window_stop = _match_window(scheduled_segment, ticker, slices)

            ticker += 1

            pace = _match_status(window_start, window_stop, current_minute)

            duel_label = f"{division.id}-{milestone}-{specimen.entry_id}-r{ladder_pos}"
            figurehead = _competitor_with_assigned_coach(specimen.to_aggregate_competitor(), match_id=duel_label)
            assigned_entry_coach_ids = [figurehead.assigned_coach_id] if figurehead.assigned_coach_id else []
            assigned_entry_coach_names = [figurehead.assigned_coach_name] if figurehead.assigned_coach_name else []

            if ladder_pos == 0 and len(ring_slots) > 1:
                flight_ring = ring_slots[(podium_spot - 1) % len(ring_slots)]
                use_ring_id, use_ring_name = flight_ring.id, flight_ring.name
            else:
                use_ring_id, use_ring_name = scheduled_segment.ring_id, ring_name

            rank_rows.append(
                RankedBracketEntry(
                    entry_id=specimen.entry_id,
                    round_name=milestone,
                    display_name=specimen.display_name,
                    athlete_members=list(specimen.members),
                    team_id=specimen.team_id,
                    team_name=specimen.team_name,
                    coach_ids=assigned_entry_coach_ids,
                    coach_names=assigned_entry_coach_names,
                    score_value=float(tally),
                    rank_in_round=podium_spot,
                    advanced=(not finals_only and specimen.entry_id in qualifiers),
                    final_placement=podium_spot if finals_only else None,
                    status=pace,
                    performance_match_id=duel_label,
                )
            )

            score_card = MatchScore(competitor_1_poomsae=float(tally), winner_margin="rank demo")
            match_number_seed = len(matches_out) + 1

            matches_out.append(
                _match(
                    division=division,
                    scheduled_event=scheduled_segment,
                    ring_name=use_ring_name,
                    ring_id=use_ring_id,
                    round_name=milestone,
                    bracket_position=podium_spot,
                    competitor_1=figurehead,
                    competitor_2=None,
                    winner_id=None,
                    loser_id=None,
                    score=score_card if pace == "completed" else None,
                    status=pace,
                    start=window_start,
                    end=window_stop,
                    match_index=match_number_seed,
                    required_referee_count=crew_need,
                    match_id_override=duel_label,
                    participant_ids=list(specimen.athlete_member_ids),
                    match_number=_resolve_match_number(
                        match_number_by_match_id,
                        duel_label,
                        match_number_seed,
                    ),
                    assigned_referee_ids=list(scheduled_segment.assigned_referee_ids),
                )
            )

        panels_out.append(RankedBracketRound(round_name=milestone, entries=rank_rows))

        if finals_only:

            break

        backlog = ordering[:survivor_quota]

    return matches_out, panels_out


class PoomsaeEntry:
    """Single judging unit shown to officials (solo, pair synchronization, trio team)."""

    def __init__(
        self,
        *,
        entry_id: str,
        display_name: str,
        members: list[MatchCompetitor],
        athlete_member_ids: list[str],
        team_id: str,
        team_name: str,
        coach_ids: list[str],
        coach_names: list[str],
    ) -> None:

        self.entry_id = entry_id

        self.display_name = display_name

        self.members = members

        self.athlete_member_ids = athlete_member_ids

        self.team_id = team_id

        self.team_name = team_name

        merged = sorted(zip(coach_ids, coach_names))

        self.coach_ids = [bond[0] for bond in merged]

        self.coach_names = [bond[1] for bond in merged]

    def to_aggregate_competitor(self) -> MatchCompetitor:

        sentinel = self.members[0]

        roster_line = ", ".join(member.name for member in self.members)

        coach_roll: dict[str, str] = {}

        for teammate in self.members:

            for coach_label, readable in zip(teammate.coach_ids, teammate.coach_names):

                coach_roll.setdefault(coach_label, readable)

        sorted_ids = sorted(coach_roll)

        sorted_names = [coach_roll[token] for token in sorted_ids]

        banner = f"{self.display_name} ({roster_line})"

        return MatchCompetitor(
            competitor_id=self.entry_id,
            name=banner,
            team_id=self.team_id,
            team_name=self.team_name,
            seed=sentinel.seed,
            age_group=sentinel.age_group,
            gender=sentinel.gender,
            belt_level=sentinel.belt_level,
            coach_ids=sorted_ids,
            coach_names=sorted_names,
        )


def build_poomsae_entries(
    division: Division,
    tournament_payload: Tournament,
    team_bundle: dict[str, Team],
    coach_bundle: dict[str, Coach],
) -> list[PoomsaeEntry]:
    accumulator: list[PoomsaeEntry] = []

    manifest = division.athlete_ids

    if division.event_type == "pair_poomsae":

        groupings = [manifest[j : j + 2] for j in range(0, len(manifest) // 2 * 2, 2)]

        for slice_index, pair_ids in enumerate(groupings, start=1):

            members = [
                _competitor_for_athlete(
                    athlete_key,
                    (slice_index - 1) * 2 + index_key + 1,
                    tournament=tournament_payload,
                    team_by_id=team_bundle,
                    coach_by_id=coach_bundle,
                )
                for index_key, athlete_key in enumerate(pair_ids)
            ]

            prime_team_id = sorted({member.team_id for member in members})[0]

            coach_mix = sorted(
                {
                    (cid_key, coach_bundle[cid_key].name if cid_key in coach_bundle else cid_key)
                    for athlete in members
                    for cid_key in athlete.coach_ids
                }
            )

            accumulator.append(
                PoomsaeEntry(
                    entry_id=f"{division.id}-pair-{slice_index}",
                    display_name=f"Pair Entry {slice_index}",
                    members=members,
                    athlete_member_ids=list(pair_ids),
                    team_id=prime_team_id,
                    team_name=team_bundle[prime_team_id].name,
                    coach_ids=[pair_bundle[0] for pair_bundle in coach_mix],
                    coach_names=[pair_bundle[1] for pair_bundle in coach_mix],
                )
            )

        return accumulator

    if division.event_type == "team_poomsae":

        trio_width = 3

        bundles = [
            manifest[cursor_cursor : cursor_cursor + trio_width]
            for cursor_cursor in range(0, len(manifest) // trio_width * trio_width, trio_width)
        ]

        for bundle_index, cluster in enumerate(bundles, start=1):

            roster_bundle = [
                _competitor_for_athlete(
                    teammate_id,
                    bundle_index * 10 + teammate_index + 1,
                    tournament=tournament_payload,
                    team_by_id=team_bundle,
                    coach_by_id=coach_bundle,
                )
                for teammate_index, teammate_id in enumerate(cluster)
            ]

            anchor_team_id = sorted({player.team_id for player in roster_bundle})[0]

            coach_roll = sorted(
                {
                    (cid_token, coach_bundle[cid_token].name if cid_token in coach_bundle else cid_token)
                    for player in roster_bundle
                    for cid_token in player.coach_ids
                }
            )

            accumulator.append(
                PoomsaeEntry(
                    entry_id=f"{division.id}-team-{bundle_index}",
                    display_name=f"Team Entry {bundle_index}",
                    members=roster_bundle,
                    athlete_member_ids=list(cluster),
                    team_id=anchor_team_id,
                    team_name=team_bundle[anchor_team_id].name,
                    coach_ids=[element[0] for element in coach_roll],
                    coach_names=[element[1] for element in coach_roll],
                )
            )

        return accumulator

    for seed_counter, lone in enumerate(manifest, start=1):

        solo_row = [_competitor_for_athlete(lone, seed_counter, tournament=tournament_payload, team_by_id=team_bundle, coach_by_id=coach_bundle)]

        club_id_token = solo_row[0].team_id

        accumulator.append(
            PoomsaeEntry(
                entry_id=f"{division.id}-{lone}",
                display_name=f"{solo_row[0].name} (solo)",
                members=solo_row,
                athlete_member_ids=[lone],
                team_id=club_id_token,
                team_name=team_bundle[club_id_token].name,
                coach_ids=list(solo_row[0].coach_ids),
                coach_names=list(solo_row[0].coach_names),
            )
        )

    return accumulator


def rounds_for_ranked_entries(volume: int) -> list[str]:
    if volume <= 4:
        return ["final"]
    if volume <= 8:
        return ["semifinal", "final"]

    return ["preliminary", "semifinal", "final"]


def advancing_count_for_round(step: int, itinerary: list[str], live_slots: int) -> int:

    if step >= len(itinerary) - 1:

        return live_slots

    if len(itinerary) == 2:

        return min(4, live_slots)

    if itinerary[step] == "preliminary":

        return min(8, live_slots)

    if itinerary[step] == "semifinal":

        return min(4, live_slots)

    return live_slots


def _rank_score(entry_stamp: str, division_stamp: str, stage_index: int) -> float:
    scrambled = "".join([entry_stamp, division_stamp, str(stage_index)])
    shaker = sum((idx + 1) * ord(ch) for idx, ch in enumerate(scrambled))

    return round(7.0 + ((shaker % 380) / 100), 3)


def _participant_ids_with_status(bouts: list[Match], target_state: str) -> set[str]:
    bucket = set()

    for duel in bouts:

        if duel.status != target_state:

            continue

        bucket.update(athlete_ids_involved(duel))

    return bucket


def _advanced_candidates(
    sport: str,
    roster_cards: list[MatchCompetitor],
    duel_list: list[Match],
    kyorugi_losses: set[str],
    ranked_panels: list[RankedBracketRound],
) -> list[MatchCompetitor]:
    pending_ids = set()

    for duel in duel_list:

        if duel.status != "completed":

            pending_ids.update(athlete_ids_involved(duel))
    lookup = {

        teammate.competitor_id: teammate

        for teammate in roster_cards

    }

    if sport == "kyorugi":

        promoted = sorted(
            (
                lookup[candidate]

                for candidate in pending_ids

                if candidate in lookup

                if candidate not in kyorugi_losses

            ),

            key=lambda candidate: candidate.seed,

        )

        if promoted:

            return promoted

        final_layer = [duel for duel in duel_list if duel.round_name == "final"]

        champion_id = final_layer[-1].winner_id if final_layer else None

        return [lookup[champion_id]] if champion_id and champion_id in lookup else []

    still_active = sorted(

        [lookup[token] for token in pending_ids if token in lookup],

        key=lambda card: card.seed,

    )

    if still_active:

        return still_active

    if ranked_panels:

        medalists = []

        finale_table = ranked_panels[-1].entries

        for row_entry in sorted(finale_table, key=lambda ribbon: ribbon.rank_in_round):

            medalists.extend(row_entry.athlete_members)

        dedup_board: dict[str, MatchCompetitor] = {}

        for contender in medalists:

            dedup_board.setdefault(contender.competitor_id, contender)

        return list(dedup_board.values())

    return []


def _build_coach_sheet(
    arena: Tournament,

    competitor_cards: list[MatchCompetitor],

    duels: list[Match],

    schedule_slot: ScheduledEvent,

    ring_banner: str,

    division_sheet: Division,

    current_tick: int,
) -> list[CoachToReport]:
    teammate_directory = {card.competitor_id: card for card in competitor_cards}
    coach_by_id = {coach.id: coach for coach in arena.coaches}

    urgency = {"done": 0, "waiting": 1, "in_holding": 2, "report_now": 3, "currently_coaching": 4}

    board: dict[str, CoachToReport] = {}

    for duel in duels:
        lead_time = duel.start_minute - current_tick

        if duel.status == "in_progress":
            urgency_label = "currently_coaching"
        elif duel.status == "staging":
            urgency_label = "report_now"
        elif duel.status == "waiting" and 0 <= lead_time <= 25:
            urgency_label = "in_holding"
        elif duel.status == "waiting":
            urgency_label = "waiting"
        elif duel.status == "completed":
            urgency_label = "done"
        else:
            urgency_label = "waiting"

        for side in (duel.competitor_1, duel.competitor_2):
            if not side:
                continue

            assigned_coach_id = side.assigned_coach_id
            if not assigned_coach_id and side.coach_ids:
                assigned_coach_id = sorted(side.coach_ids)[0]
            if not assigned_coach_id:
                continue

            coach_identity = coach_by_id.get(assigned_coach_id)
            readable = side.assigned_coach_name or (coach_identity.name if coach_identity else assigned_coach_id)
            teammate = teammate_directory.get(side.competitor_id)
            tentative = CoachToReport(
                coach_id=assigned_coach_id,
                coach_name=readable,
                team_id=(teammate.team_id if teammate else side.team_id),
                team_name=(teammate.team_name if teammate else side.team_name),
                ring_id=schedule_slot.ring_id,
                ring_name=ring_banner,
                division_id=division_sheet.id,
                division_name=division_sheet.name,
                related_display=side.name,
                related_entry_id=duel.match_id,
                status=urgency_label,
            )

            incumbent = board.get(assigned_coach_id)
            if incumbent is None or urgency[urgency_label] >= urgency[incumbent.status]:
                board[assigned_coach_id] = tentative

    if current_tick >= schedule_slot.end_minute:

        board = {

            cid_value: roster_line.model_copy(update={"status": "done"})

            for cid_value, roster_line in board.items()

        }

    return sorted(board.values(), key=lambda row: (-urgency[row.status], row.coach_id))


def audit_division_graph(
    *,
    division: Division,
    matches: list[Match],
    kyorugi_blocks: list[KyorugiBracketRound],
    ranked_blocks: list[RankedBracketRound],
    coach_lookup: dict[str, Coach],
    ranked_entry_builder,
) -> DivisionDetailValidation:
    errors: list[str] = []
    warnings: list[str] = []

    for bout in matches:
        for side_name, side in (("competitor_1", bout.competitor_1), ("competitor_2", bout.competitor_2)):
            if not side:
                continue
            if side.coach_ids and not side.assigned_coach_id:
                errors.append(
                    f"Match '{bout.match_id}' {side_name} has coach options but no assigned_coach_id."
                )
            if side.assigned_coach_id and side.coach_ids and side.assigned_coach_id not in side.coach_ids:
                errors.append(
                    f"Match '{bout.match_id}' {side_name} assigned coach '{side.assigned_coach_id}' not in available coach_ids."
                )

    if division.event_type == "kyorugi":
        cohort = len(division.athlete_ids)
        padded_bracket_size = bracket_power_of_two(cohort)

        expected_bouts_total = padded_bracket_size - 1
        if len(matches) != expected_bouts_total:
            errors.append(
                f"Kyorugi match rows ({len(matches)}) should equal padded bracket minus one ({expected_bouts_total})."
            )

        head_to_head = [bout for bout in matches if not bout.bye]

        need_non_bye_max = max(0, cohort - 1)

        if len(head_to_head) != need_non_bye_max:
            errors.append(
                f"Kyorugi head-to-head bouts must equal competitor_count-1={need_non_bye_max}; found {len(head_to_head)}."
            )

        semis_only = [bout for bout in matches if bout.round_name == "semifinal"]

        if padded_bracket_size >= 4 and len(semis_only) != 2:
            errors.append("Semifinals must expose exactly two bouts unless bracket is finals-only sizing.")

        by_number = {bout.match_number: bout for bout in matches}
        for bout in matches:
            for feeder_num, side_comp, side_label in (
                (bout.feeder_1_match_number, bout.competitor_1, bout.source_1_label),
                (bout.feeder_2_match_number, bout.competitor_2, bout.source_2_label),
            ):
                if feeder_num is None:
                    continue
                feeder = by_number.get(feeder_num)
                feeder_completed = bool(feeder and feeder.status == "completed" and feeder.winner_id)
                if not feeder_completed and side_comp is not None:
                    errors.append(
                        f"Future bracket slot in '{bout.match_id}' prefilled before feeder Match {feeder_num} completes."
                    )
                if not feeder_completed and side_label != f"Winner of Match {feeder_num}":
                    errors.append(
                        f"Future bracket slot in '{bout.match_id}' must show 'Winner of Match {feeder_num}'."
                    )

        finals = [bout for bout in matches if bout.round_name == "final"]
        if finals:
            final_bout = finals[-1]
            semis_done = all(sem.status == "completed" and sem.winner_id for sem in semis_only)
            if not semis_done and (final_bout.competitor_1 or final_bout.competitor_2):
                errors.append("Final should not prefill athletes before both semifinals are completed.")

        order_labels = _round_labels_kyorugi(cohort)
        precedence = {label: index for index, label in enumerate(order_labels)}

        for bout in matches:
            if bout.loser_id and not bout.bye and bout.status == "completed":
                knocked_layer = precedence.get(bout.round_name, 0)
                for future in matches:
                    if bout.match_id == future.match_id:
                        continue
                    if precedence.get(future.round_name, 0) <= knocked_layer:
                        continue
                    contenders = competitor_ids_for_audit(future)
                    if bout.loser_id in contenders:
                        errors.append(
                            f"Loser '{bout.loser_id}' resurfaced inside {future.round_name} after elimination."
                        )

        signature_log: dict[tuple[str, str], int] = {}
        for bout in matches:
            if bout.bye:
                continue
            if bout.competitor_1 and bout.competitor_2:
                key = tuple(sorted((bout.competitor_1.competitor_id, bout.competitor_2.competitor_id)))

                signature_log[key] = signature_log.get(key, 0) + 1

        for signature, repetitions in signature_log.items():

            if repetitions > 1:

                warnings.append(f"Repeated pairing signature {signature} spotted {repetitions} times.")
    else:
        entries_manifest = ranked_entry_builder()

        if division.event_type == "pair_poomsae":

            for entry in entries_manifest:

                if len(entry.athlete_member_ids) != 2:

                    errors.append(f"Pair entry '{entry.entry_id}' must reference exactly two athletes.")

        elif division.event_type == "team_poomsae":

            for entry in entries_manifest:

                if len(entry.athlete_member_ids) != 3:

                    errors.append(
                        "Demo team poomsae expects three-member squads — "
                        f"'{entry.entry_id}' bundled {len(entry.athlete_member_ids)} roster ids."
                    )

        expected_wave = list(division.poomsae_rounds or rounds_for_ranked_entries(len(entries_manifest)))

        actual_wave = [panel.round_name for panel in ranked_blocks]

        if actual_wave != expected_wave:

            errors.append(
                "Wave order mismatch expected "
                + f"[{','.join(expected_wave)}] "
                + f"but received [{','.join(actual_wave)}]."
            )

        if len(entries_manifest) <= 4 and any(panel.round_name == "preliminary" for panel in ranked_blocks):

            warnings.append("Tiny divisions omit preliminary waves in the deterministic demo.")

    if division.event_type != "kyorugi":
        for grouping in ranked_entry_builder():
            for mentor in grouping.coach_ids:
                if mentor not in coach_lookup:
                    errors.append(f"Coach id '{mentor}' missing master roster.")

            for athlete_piece in grouping.members:

                for mentor in athlete_piece.coach_ids:

                    if mentor not in coach_lookup:

                        errors.append(f"Athlete '{athlete_piece.competitor_id}' references unknown coach '{mentor}'.")

    return DivisionDetailValidation(errors=errors, warnings=warnings, valid=len(errors) == 0)


def _competitor_with_assigned_coach(competitor: MatchCompetitor | None, *, match_id: str) -> MatchCompetitor | None:
    if not competitor:
        return None
    if competitor.assigned_coach_id:
        return competitor
    if not competitor.coach_ids:
        return competitor

    ordered = sorted(zip(competitor.coach_ids, competitor.coach_names or []), key=lambda row: row[0])
    if len(ordered) < len(competitor.coach_ids):
        known = {cid: name for cid, name in ordered}
        for cid in sorted(competitor.coach_ids):
            if cid not in known:
                ordered.append((cid, cid))

    token = f"{match_id}:{competitor.competitor_id}"
    pick = sum(ord(ch) for ch in token) % len(ordered)
    assigned_id, assigned_name = ordered[pick]
    return competitor.model_copy(update={"assigned_coach_id": assigned_id, "assigned_coach_name": assigned_name})


def _match(
    *,
    division: Division,
    scheduled_event: ScheduledEvent,
    ring_name: str,
    round_name: str,
    bracket_position: int,
    competitor_1: MatchCompetitor | None,
    competitor_2: MatchCompetitor | None,
    winner_id: str | None,
    loser_id: str | None = None,
    score: MatchScore | None,
    status: str,
    start: int,
    end: int,
    match_index: int,
    required_referee_count: int,
    ring_id: str | None = None,
    match_id_override: str | None = None,
    bye_flag: bool = False,
    participant_ids: list[str] | None = None,
    next_match_id: str | None = None,
    feeder_1_match_number: int | None = None,
    feeder_2_match_number: int | None = None,
    match_number: int = 0,
    assigned_referee_ids: list[str] | None = None,
) -> Match:
    return Match(
        match_id=match_id_override or f"{division.id}-match-{match_index}",
        division_id=division.id,
        match_number=match_number,
        round_name=round_name,
        bracket_position=bracket_position,
        competitor_1=competitor_1,
        competitor_2=competitor_2,
        winner_id=winner_id,
        loser_id=loser_id,
        score=score,
        status=status,
        scheduled_event_id=scheduled_event.event_id,
        ring_id=ring_id if ring_id is not None else scheduled_event.ring_id,
        ring_name=ring_name,
        start_minute=start,
        end_minute=end,
        estimated_duration_minutes=end - start,
        required_referee_count=required_referee_count,
        participant_athlete_ids=participant_ids or [],
        bye=bye_flag,
        next_match_id=next_match_id,
        feeder_1_match_number=feeder_1_match_number,
        feeder_2_match_number=feeder_2_match_number,
        assigned_referee_ids=list(assigned_referee_ids or []),
    )


def _resolve_match_number(
    match_number_by_match_id: dict[str, int] | None,
    match_id: str,
    fallback_number: int,
) -> int:
    if not match_number_by_match_id:
        return fallback_number
    return match_number_by_match_id.get(match_id, fallback_number)


def bracket_power_of_two(cohort_total: int) -> int:
    return 1 << math.ceil(math.log2(max(2, cohort_total)))


def _round_labels_kyorugi(competitor_total: int) -> list[str]:
    bracket_slots = bracket_power_of_two(competitor_total)

    if bracket_slots <= 2:
        return ["final"]

    if bracket_slots <= 4:
        return ["semifinal", "final"]

    if bracket_slots <= 8:
        return ["quarterfinal", "semifinal", "final"]

    return ["round of 16", "quarterfinal", "semifinal", "final"]


def _round_names_for_division(division: Division, competitor_count: int) -> list[str]:
    if division.event_type != "kyorugi":
        return division.poomsae_rounds or ["final"]

    return _round_labels_kyorugi(competitor_count)


def _mock_kyorugi_winner(
    competitor_1: MatchCompetitor | None,
    competitor_2: MatchCompetitor | None,
    *,
    match_id: str,
    salt: int,
) -> MatchCompetitor | None:
    """
    Deterministic mock winner for completed demo kyorugi only.

    Uses a stable hash of ``match_id`` and both competitor ids so the same tournament seed
    replays identically, without always advancing ``competitor_1``. This is simulation noise,
    not a model of who would win in real competition.
    """
    if competitor_1 and not competitor_2:
        return competitor_1
    if competitor_2 and not competitor_1:
        return competitor_2
    if not competitor_1 or not competitor_2:
        return None
    payload = f"{match_id}|{competitor_1.competitor_id}|{competitor_2.competitor_id}|{salt}"
    digest = hashlib.sha256(payload.encode()).hexdigest()
    pick_first = int(digest[:16], 16) % 2 == 0
    return competitor_1 if pick_first else competitor_2


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
    competitor_1: MatchCompetitor | None,
    competitor_2: MatchCompetitor | None,
) -> MatchScore:
    if not competitor_1:
        return MatchScore(winner_margin="bye")
    if not competitor_2:
        return MatchScore(winner_margin="bye")
    base = 7 + (match_index % 6)
    losing = max(0, base - 2 - (match_index % 3))
    return MatchScore(
        competitor_1_points=base if winner.competitor_id == competitor_1.competitor_id else losing,
        competitor_2_points=base if winner.competitor_id == competitor_2.competitor_id else losing,
        winner_margin=f"{abs(base - losing)} point margin",
    )
