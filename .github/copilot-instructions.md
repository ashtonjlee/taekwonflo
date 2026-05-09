# Copilot Instructions for `taekwonflo` (TaekwonFlo MVP)

## Build, test, and lint commands

Build/test/lint commands are **not yet defined in-repo**. This repository currently has no backend or frontend manifests/scripts yet.

When scaffolding is added, keep this section updated with exact commands for:

- backend run/build, lint, tests, and single-test execution
- frontend dev/build, lint, tests, and single-test execution

Do not assume commands exist until corresponding project files are present.

## High-level architecture

TaekwonFlo is a hackathon MVP for **automatic tournament scheduling and live emergency rescheduling** for WT/Kukkiwon/USAT-style Taekwondo events.

Planned stack:

- Backend API: Python FastAPI
- Optimization engine: Google OR-Tools CP-SAT
- Frontend UI: React + Tailwind
- Data source: synthetic tournament data generator first
- Notifications: mock SMS/email/push pipeline

Planned backend modules:

- `app/main.py` - FastAPI app and API routes
- `app/models.py` - shared data models for tournaments, rings, people, events, schedule states
- `app/data_generator.py` - synthetic tournament input generation
- `app/scheduler.py` - initial CP-SAT schedule generation
- `app/rescheduler.py` - emergency re-optimization for future events only
- `app/notifications.py` - mock notification generation/dispatch

Planned frontend modules:

- `src/App.jsx` - app shell and page-level state
- `src/api.js` - API client wrappers
- `src/components/TournamentSetup.jsx`
- `src/components/ScheduleDashboard.jsx`
- `src/components/EmergencyControls.jsx`
- `src/components/RingColumn.jsx`
- `src/components/EventCard.jsx`
- `src/components/NotificationsPanel.jsx`

MVP pages:

1. Tournament Setup
2. Schedule Dashboard
3. Emergency Controls
4. Mock Notifications

## Key conventions

Optimization objective priorities:

- minimize total tournament finish time
- minimize ring idle time
- minimize athlete/referee/coach conflicts
- minimize unnecessary changes after publishing

Hard constraints to enforce:

1. One ring runs one event at a time.
2. One referee crew works one ring at a time.
3. Athletes cannot have overlapping events.
4. Coaches cannot be required in two rings at once.
5. If a team has one coach, avoid multi-ring overlap for that team’s athletes.
6. Include transition/staging buffer time between events.

Emergency rescheduling behavior:

1. Freeze completed events.
2. Freeze currently active events.
3. Re-optimize only future events.
4. Penalize unnecessary deviation from published schedule.
5. Recompute ETAs, warm-up calls, staging calls, and mock notifications.

Implementation style for this codebase:

- prioritize a working hackathon demo over production-grade architecture
- keep code readable and commented
- use clear, explicit data models
- avoid overengineering
- prefer deterministic optimization first; ML-based duration prediction is a later enhancement
