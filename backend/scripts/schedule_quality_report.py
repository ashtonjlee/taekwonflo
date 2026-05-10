from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.data_generator import generate_tournament
from app.main import _parse_csv_tournament
from app.models import RingSchedule, Tournament
from app.scheduling_layers import run_initial_scheduling
from app.validation import validate_snapshot


def _all_events(schedule: list[RingSchedule]):
    return [event for ring in schedule for event in ring.events]


def _ring_overlaps(schedule: list[RingSchedule]) -> list[str]:
    overlaps: list[str] = []
    for ring in schedule:
        ordered = sorted(ring.events, key=lambda event: (event.start_minute, event.end_minute, event.event_id))
        for left, right in zip(ordered, ordered[1:]):
            if left.end_minute > right.start_minute:
                overlaps.append(
                    f"{ring.ring_name}: {left.event_id} [{left.start_minute},{left.end_minute}) "
                    f"overlaps {right.event_id} [{right.start_minute},{right.end_minute})"
                )
    return overlaps


def _idle_stats(ring: RingSchedule) -> tuple[int, int]:
    ordered = sorted(ring.events, key=lambda event: event.start_minute)
    gaps = [max(0, right.start_minute - left.end_minute) for left, right in zip(ordered, ordered[1:])]
    return (max(gaps, default=0), sum(gaps))


def _load_tournament(args: argparse.Namespace) -> Tournament:
    if args.csv:
        text = Path(args.csv).read_text(encoding="utf-8-sig")
        tournament, _, warnings, _ = _parse_csv_tournament(
            text,
            rings_count=args.rings,
            referee_crews_count=args.referee_crews,
        )
        for warning in warnings:
            print(f"import_warning: {warning}")
        return tournament

    return generate_tournament(
        number_of_rings=args.rings,
        number_of_athletes=args.athletes,
        number_of_teams=args.teams,
        number_of_referee_crews=args.referee_crews,
        number_of_divisions=args.divisions,
        target_tournament_minutes=args.target_minutes,
        seed=args.seed,
    )


def print_report(tournament: Tournament, schedule: list[RingSchedule]) -> None:
    overlaps = _ring_overlaps(schedule)
    validation = validate_snapshot(tournament=tournament, schedule=schedule, demo_mode=True)

    print(f"ring_count: {len(schedule)}")
    print(f"event_count: {len(_all_events(schedule))}")
    print(f"total_overlaps: {len(overlaps)}")

    total_idle = 0
    for ring in schedule:
        ordered = sorted(ring.events, key=lambda event: event.start_minute)
        first_start = ordered[0].start_minute if ordered else None
        last_end = ordered[-1].end_minute if ordered else None
        max_gap, idle = _idle_stats(ring)
        total_idle += idle
        print(
            f"{ring.ring_name}: events={len(ordered)} first_start={first_start} "
            f"last_end={last_end} max_idle_gap={max_gap} idle_minutes={idle}"
        )

    print(f"total_idle_minutes: {total_idle}")
    if overlaps:
        print("overlaps:")
        for item in overlaps:
            print(f"  - {item}")

    print(f"validation_valid: {validation.valid}")
    print(f"validation_errors: {len(validation.errors)}")
    for error in validation.errors:
        print(f"  ERROR: {error}")
    print(f"validation_warnings: {len(validation.warnings)}")
    for warning in validation.warnings:
        print(f"  WARNING: {warning}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Print schedule quality diagnostics.")
    parser.add_argument("--csv", help="Optional CSV file to import before scheduling.")
    parser.add_argument("--rings", type=int, default=5)
    parser.add_argument("--referee-crews", type=int, default=10)
    parser.add_argument("--athletes", type=int, default=360)
    parser.add_argument("--teams", type=int, default=24)
    parser.add_argument("--divisions", type=int, default=61)
    parser.add_argument("--target-minutes", type=int, default=480)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    tournament = _load_tournament(args)
    schedule = run_initial_scheduling(tournament)
    print_report(tournament, schedule)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
