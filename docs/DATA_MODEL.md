# TaekwonFlo Data Model

## Tournament Metadata

Synthetic tournaments contain rings, teams, coaches, athletes, divisions, referee crews, and scheduled events.

Athletes include:

- `age_group`: `peewee`, `cadet`, `junior`, `senior`
- `gender`: `male`, `female`
- `belt_level`: `color_belt`, `black_belt`, `world_class`
- team and coach assignments

Divisions include:

- event type: `kyorugi`, `poomsae`, `team_poomsae`
- age group, gender, belt level, and simplified weight class
- bracket type
- estimated division duration

The simplified kyorugi weight classes are WT/USAT-inspired demo buckets, not an official rulebook. Peewee divisions use local tournament-style `Light`, `Middle`, and `Heavy` buckets.

## Match-Level Detail

`GET /api/divisions/{division_id}/detail` returns a `DivisionDetail` payload:

- `division`: division metadata
- `competitors`: athletes with seed, team, age, gender, and belt data
- `bracket`: bracket type, rounds, and matches
- `current_match`: match currently competing, if any
- `waiting_competitors`
- `staging_competitors`
- `completed_matches`
- `advanced_competitors`

Each `Match` includes:

- `match_id`
- `division_id`
- `round_name`
- `bracket_position`
- `competitor_1`
- optional `competitor_2` for byes
- optional `winner_id`
- optional score
- status: `waiting`, `staging`, `in_progress`, `completed`
- scheduled event, ring, start, and end timing
- `required_referee_count`

## Demo Scores

Kyorugi scores are deterministic point totals. Poomsae scores are deterministic decimal scores. They are realistic enough for the live demo but are not judging logic.

