# Changelog

What changed, per commit, newest first. Status and plans are in [docs/PROGRESS.md](docs/PROGRESS.md).

## Unreleased

### Added
- Customer discovery kit: [outreach messages](docs/discovery/OUTREACH.md) and [interview guide](docs/discovery/INTERVIEW_GUIDE.md).
- [docs/research/VDA5050_3_0.md](docs/research/VDA5050_3_0.md): VDA 5050 3.0 vs 2.1 comparison and plan (D-15).
- ruff lint and format for Python (`ruff.toml`, 120 columns) and a `lint` job in CI (D-14).
- Project tracking and documentation: [docs/PROGRESS.md](docs/PROGRESS.md),
  [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/DECISIONS.md](docs/DECISIONS.md), this changelog.
- [docs/PLAN.md](docs/PLAN.md) is now the plan reference with calendar dates; status moved to PROGRESS.md.

### Fixed
- HTTP errors raised from recorder/replay errors now keep the original error as their cause.
- Backend hung on shutdown when no MQTT traffic flowed (idle WebSocket handler), so Docker killed it
  and an open recording lost its end line. Handler now watches for the close; uvicorn has a 5 s
  graceful-shutdown limit.
- Simulator crashed on shutdown when the broker had already stopped.
- Docker: session files were written as `root`; backend and simulator now run as a non-root user,
  and the backend as the host user (D-12).
- Docker: recreating the backend container broke the UI with 502 until nginx restarted; nginx now
  re-resolves the backend through Docker's DNS (D-13).

## 2026-10-10

### `b97fe43` Week 5: validation, schemas, VDA 5050 notes
- Added: JSON Schemas for state, order, connection and the inject command; validator with sequence
  rules; issues on every message, in recordings and in the UI; Validation panel; `GET /api/validation`,
  `POST /api/validation/reset`; [docs/VDA5050_NOTES.md](docs/VDA5050_NOTES.md).
- Fixed: UI went blank on malformed robot data; each panel now has an error boundary.
- Fixed: simulator `headerId` now counts per topic.

### `99a1df5` Week 4: 5–10 robots
- Changed: robots park in a grid in a wider charging area; map labels robots by number;
  `--robots` limited to 1–50; CHARGING location moved.

## 2026-10-09

### `c28ec6c` Day 7: replay
- Added: replay with original timing at 0.1–20×, robot-side only by default, refused while live
  robots publish; replay banner and controls; [docs/DEMO.md](docs/DEMO.md).
- Fixed: replay refused after a backend restart (retained connection messages looked live).

### `e019357` Day 6: recording
- Added: JSONL session recording, session list and download, Sessions panel, Docker volume for sessions.

### `aecb40b` Day 5: BLOCKED_PATH
- Added: BLOCKED status, `pathBlocked` error, `POST /api/failures`, failure log, failure panel.
- Fixed: an order rejection no longer wipes other robot errors.

### `a67b0d4` Day 4: map and message stream
- Added: live hub and WebSocket feed, warehouse map, robot table, message stream.

### `7718132` Day 3: missions
- Added: `POST /api/missions` (VDA 5050 orders), robot state machine, mission form.
- Fixed: ACCEPTED is published before MOVING; busy-order errors clear on completion; robots ignore
  messages from other topics.

### `841f493` Day 2: simulator
- Added: simulated robots publishing VDA 5050 state and connection (with last will).

### `5045226` Day 1: skeleton
- Added: Docker Compose with Mosquitto, FastAPI skeleton, React app, CI.
