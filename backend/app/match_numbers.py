from __future__ import annotations

from .brackets import build_division_detail
from .models import RingSchedule, Tournament


def build_published_match_number_map(
    tournament: Tournament,
    published_schedule: list[RingSchedule],
) -> dict[str, int]:
    """Assign stable global match numbers from the published schedule."""
    ordered_events = sorted(
        (event for ring in published_schedule for event in ring.events),
        key=lambda event: (
            event.start_minute,
            event.end_minute,
            event.ring_id,
            event.division_id,
            event.event_id,
        ),
    )

    division_ids: list[str] = []
    seen_divisions: set[str] = set()
    for event in ordered_events:
        if event.division_id in seen_divisions:
            continue
        seen_divisions.add(event.division_id)
        division_ids.append(event.division_id)

    all_matches = []
    for division_id in division_ids:
        try:
            detail = build_division_detail(
                tournament=tournament,
                schedule=published_schedule,
                division_id=division_id,
                current_minute=0,
            )
        except (KeyError, ValueError):
            continue
        all_matches.extend(detail.bracket.matches)

    all_matches.sort(
        key=lambda duel: (
            duel.start_minute,
            duel.end_minute,
            duel.ring_id,
            duel.division_id,
            duel.round_name,
            duel.bracket_position,
            duel.match_id,
        )
    )

    return {duel.match_id: index for index, duel in enumerate(all_matches, start=1)}
