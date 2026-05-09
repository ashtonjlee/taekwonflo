# Backend (FastAPI)

## Setup

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Mock data endpoint

`GET /api/mock/snapshot` returns deterministic synthetic tournament data, an OR-Tools CP-SAT schedule, and mock notifications.

`GET /api/schedule` exposes the same scheduling flow directly.

`GET /api/validate/snapshot` runs lightweight validation on generated tournament + schedule consistency.

`GET /api/reschedule/demo` simulates an emergency disruption and re-optimizes only future events.

Query parameters:

- `number_of_rings` (default `3`)
- `number_of_athletes` (default `48`)
- `number_of_teams` (default `8`)
- `number_of_referee_crews` (default `4`)
- `seed` (default `42`)

Example:

```bash
curl "http://127.0.0.1:8000/api/mock/snapshot?number_of_rings=4&number_of_athletes=64&number_of_teams=10&number_of_referee_crews=6&seed=2026"
```

Validation example:

```bash
curl "http://127.0.0.1:8000/api/validate/snapshot?number_of_rings=4&number_of_athletes=64&number_of_teams=10&number_of_referee_crews=6&seed=2026"
```

Emergency reschedule examples:

```bash
# medical_delay
curl "http://127.0.0.1:8000/api/reschedule/demo?emergency_type=medical_delay&ring_id=ring-1&current_minute=60&delay_minutes=20"

# ring_pause
curl "http://127.0.0.1:8000/api/reschedule/demo?emergency_type=ring_pause&ring_id=ring-2&pause_start_minute=70&pause_duration_minutes=25&current_minute=60"

# referee_shortage
curl "http://127.0.0.1:8000/api/reschedule/demo?emergency_type=referee_shortage&referee_crew_id=ref-crew-1&unavailable_start_minute=60&unavailable_duration_minutes=30&current_minute=60"

# coach_conflict
curl "http://127.0.0.1:8000/api/reschedule/demo?emergency_type=coach_conflict&coach_id=coach-1&unavailable_start_minute=60&unavailable_duration_minutes=30&current_minute=60"
```

## Optimizer behavior (CP-SAT)

The scheduler in `app/scheduler.py` uses minute-based integer time and a short solve limit (5 seconds).

Hard constraints:

1. Each event is assigned exactly one ring.
2. Each event is assigned exactly one referee crew.
3. No overlap on the same ring.
4. No overlap on the same referee crew.
5. Events sharing athletes cannot overlap.
6. Events sharing required coaches cannot overlap.
7. Event duration is `estimated_duration_minutes + buffer_minutes`.

Objective (weighted):

1. Minimize tournament makespan.
2. Minimize total ring idle time.
3. Reduce workload imbalance across rings.

If the solver finds feasible (but not optimal) within the time limit, that schedule is returned.
If no feasible schedule exists, the API returns `422` with a clear error message.

### Quick test

```bash
curl "http://127.0.0.1:8000/api/schedule?number_of_rings=3&number_of_athletes=48&number_of_teams=8&number_of_referee_crews=4&seed=42"
```
