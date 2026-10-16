# Changelog

What changed, per commit, newest first. Status and plans are in [docs/PROGRESS.md](docs/PROGRESS.md).

## Unreleased

### Week 13: a real ROS 2 robot stack (D-51)
- Optional profile `ros2`: Nav2 on ROS 2 Humble with a fake TurtleBot3 behind InOrbit's open-source VDA 5050
  connector, on a map generated from the warehouse; logs in as a robot over MQTT/TLS.
- Missions take an optional `theta` (heading); the start node carries the robot's own heading.
- Findings running it: docs/research/ROS2_CONNECTOR.md. Weekly CI workflow and an opt-in e2e test.
- A retention test that failed once the calendar passed its fixed date now uses the real clock.

### Full audit of weeks 0–12 (D-50, docs/AUDIT_2026-10-14.md)
- Security: strict JSON numbers end to end; topics from files validated before publishing; one cookie parser;
  API docs pinned and off when login is required; WebSocket feed and queue limits; failed logins logged;
  broker memory/queue/connection limits; name-constrained CA; network listener without internal logins;
  AEAD-only TLS; hardened containers (no capabilities, read-only, limits, restart policies); CI pinned to
  commits, least-privilege tokens, Dependabot; customer CI template without persisted credentials.
- Robustness: replay never stalls the API; hostile session files refused (huge snapshot lines, wrong types,
  absurd times, control characters); simulator inbox bounded and work per tick budgeted, order graphs validated
  (sequence ids, edges, released prefix, map, version, manufacturer), no slowdown on long-running orders;
  UI panels survive any robot data, hidden tabs no longer grow memory, reconnect with backoff.
- Operations: `mqtt-init remove-robot | remove-master | rotate | backup | restore | recreate-ca`, applied
  with SIGHUP; scenarios can address other manufacturers' robots; import never destroys its input.
- Correctness: empty battery always reported; duplicate/rejected orders publish state; validator: strict UTC
  timestamps, FAILED → WAITING allowed; 5xx = could not run; cleanup always stops the recording.

### Week 12: scenarios in CI, site captures (D-49)
- `docker compose run --rm runner test scenarios/`: the scenario runner in a container, inside the lab's
  network; your own scenarios with `ACTUNODE_SCENARIOS`; JUnit to `ACTUNODE_RESULTS`.
- CI job `scenarios` (VDA 2.1 and 3.0): sample scenarios and the example fleet manager, reports and
  recordings as artifacts. `examples/ci/github-actions.yml`: the same for your repository.
- `actunode import`: a `mosquitto_sub` capture from a site becomes a session to upload, validate and replay.
- `ACTUNODE_TOKEN_FILE` as the default for `--token-file`.

### Week 11: testing a fleet manager (D-48)
- `examples/fleet_manager/`: an example fleet manager with a choice of reaction to a blocked path, and
  `blocked_path_reaction.yaml`, which asks "does it cancel, reroute or escalate?" (pass/fail on the real stack).
- New failure `UNRESPONSIVE` (`duration_s`): online but silent, commands ignored (the plan's "timeouts").
- Replay option **Current time** (`current_time`): replayed messages carry the time they are sent again.
- Scenarios: a `message` list means "any of these"; `never` counts messages from its own start; sixth sample
  scenario `unresponsive_robot.yaml`; cleanup no longer tries to clear a block that is already over.

### Product audit after Week 10 (D-47)
- Outside fleet managers (master controls) can connect: `mqtt-init add-master <name> [<manufacturer> ...]`
  creates `master@<name>`, which may command those robots and read their traffic, nothing else.
- Security headers: strict Content-Security-Policy and no framing on the UI, `nosniff` and `no-referrer`
  everywhere; nginx version hidden.
- npm refuses a Node older than 24 (`engine-strict`) instead of failing confusingly.
- docs/USE_CASES.md: who uses ActuNode for what, and what works today.

### Week 10: timing, message expectations, sample scenarios (D-46)
- `expect … for: N` (keeps holding) and a `never` step (must not happen during N s).
- `message` condition: a message on an MQTT topic filter whose payload contains a JSON pattern, from the lab's
  live feed (none missed between polls); it sees messages since the previous step began.
- The live feed is opened with retries (a stalled connection no longer makes a scenario "could not run").
- Every scenario run is recorded as a lab session (id in the console and the JUnit report); `--no-record`.
- Five sample scenarios: P-1042 blocked path, low battery during a mission, disconnect during a mission,
  invalid traffic, cancel and resume.

### Week 9: scenario tests (D-45)
- `actunode test` (`cli/`, `pip install ./cli`): runs YAML scenario files against a running lab. Steps:
  send mission, inject and clear failures, cancel, wait, expect (robot status, order, error and level,
  connection, validation rules) within N seconds. Readable log, `--junit` XML, exit codes 0/1/2/3,
  `--dry-run`, login (`--token-file`) and TLS (`--ca-file`); cleans up injected failures and its own
  running orders afterwards.
- `scenarios/p1042_blocked_path.yaml`: the pitch demo's blocked-path incident as a passing test.
- CI runs the runner's unit tests; e2e runs P-1042 and a failing scenario on the real stack.
- Gate: YAML aliases refused, failure params passed as written, redirects explained (D-45).

## 0.1.0 — 2026-10-13

First public release: all eight weeks of the plan (D-1 to D-43). Apache-2.0.

### Week 8: publishing (D-43)
- Apache-2.0 LICENSE, NOTICE (vendored VDA 5050 schemas, MIT), SECURITY.md, CONTRIBUTING.md, issue and
  pull request templates.
- README rewritten (verified claims, quick start, tour with curl commands, CLI, troubleshooting);
  docs/DEMO.md 3-minute script; `tests/demo/record_demo.py` records the demo video and README screenshots
  from the real product.
- Retention and trusted-proxy settings now reach the backend under Docker (they were silently ignored).
- `POST /api/recording/stop` reports the stopped state (it returned `recording: true`).
- Load test re-run on the release code: 18/18 thresholds at 10, 25 and 50 robots.

### Week 6: failure injection (D-42)
- Four failures from the UI or `POST /api/failures` with parameters: BLOCKED_PATH, LOW_BATTERY (level),
  DISCONNECT (duration, abrupt or clean), INVALID_PAYLOAD (kind, count). Robots report `batteryLow` below
  20 % and which failures are injected.
- VDA 5050 3.0 error levels per the spec: `batteryLow` URGENT, `pathBlocked` CRITICAL (2.1: WARNING).
- The broker's last will no longer produces a false header-id warning.
- E2E: each failure observed on the real stack (state, last will, validator rules).
- UI: robot updates no longer slow down with many robots (1,500 updates 4.5 s → 0.3 s).

### Weeks 5 and 7: offline validation, retention, upload (D-40, D-41)
- Validate a saved session with the live validator: `POST /api/sessions/{id}/validate`, a Validate button,
  and `python -m app.validate_session file.jsonl` (exit 1 on errors, 2 on a bad file) for CI.
- Retention: `ACTUNODE_SESSIONS_KEEP_DAYS` (30) and `ACTUNODE_SESSIONS_MAX_TOTAL_MB` (2000); usage shown in the
  Sessions panel (`GET /api/sessions/storage`).
- Upload a session file someone sent you: `POST /api/sessions/upload` and an Upload button; untrusted input,
  strictly checked; never deletes other sessions (507 when storage is full).
- Recorder stores why a payload was rejected; offline validation matches live validation.
- Session list refreshes in every tab when it changes (WebSocket `sessions` event).
- Shared contract fixtures for the session responses (`contracts/session_*.json`).

### Code-quality backlog (issues 21–24, D-39)
- Very large robot states are stored as a trimmed copy (≤ 64 KiB, marked `_truncated`, shown in the UI).
- Validation counters can no longer double count around a reset (`epoch` / `validationEpoch`); recording
  counters follow the current recording, whoever started it.
- Login rate limit trusts `X-Real-IP` only from the nginx proxy (`ACTUNODE_TRUSTED_PROXIES`).
- CI: weekly security scans (pip-audit, npm audit, Trivy) and a weekly/on-demand load test.

### Week 4: many robots, one map, live feed at scale (D-37, D-38)
- Load test `tests/load/run_load.py` (isolated stack, 10/25/50 robots with missions, 18 thresholds, ~4 min).
- One warehouse map in `backend/app/warehouse.py`, served at `GET /api/map`; the UI draws it, simulator tests
  check against it. New PARKING zone; robots park in the charging area, then PARKING, never on racks or in
  working zones.
- Live feed: proximity events only when pairs change (distances ≤ 1/s); a state's event carries it once;
  events encoded once for all clients; a lagging client is closed (1013) and reconnects for a snapshot.
- UI: events applied once per frame; unchanged rows and markers don't re-render; off-map and other-map robots
  shown; 3.0 position read like the backend.
- Shared contract fixture `contracts/live_message_event.json` (backend generates, frontend tests read): a
  shape mismatch between the two had broken the live view and was caught only by the browser tests.

### Week 3 second review (D-36)
- Security: a robot could make the backend publish an order over the broker limit (disconnecting the
  backend); a crafted session file could pass the replay live check and fake a live robot. Fixed: every
  publish is size-checked, robot-reported values are validated before reuse, replay checks exactly the
  topics it publishes.
- `extend` no longer locks itself out after one rejected or lost update.
- Simulator limits: ids ≤ 128 characters, ≤ 300 nodes/edges/actions per order, payload size/depth/NaN
  limits on incoming messages; a hostile message can no longer make a state exceed the broker limit.
- Simulator split into `protocol`, `validation`, `orders`, `instant`, `messages`, `robot` with one
  version profile per VDA 5050 version (maintainability C → A).
- UI: PAUSED badge; per-robot cancel state and errors.
- The offline demo `python3 main.py` works again (broken by the Week 3 start-node rule) and is tested.

### Week 3: orders, order updates, instant actions (D-35)
- Simulator follows VDA 5050 2.1 and 3.0 order handling: version-specific errors kept until a new order,
  start node must be reachable, never drives into the horizon (new mission status `WAITING`, plus
  `newBaseRequest`), order updates stitched at the decision point, edge actions, `loads`, duplicate and
  malformed orders rejected before anything changes.
- `instantActions`: `cancelOrder` (new status `CANCELLED`), `startPause`/`stopPause` (`paused`),
  `stateRequest`, `factsheetRequest`, 3.0 `clearInstantActions`; listed in the factsheet.
- Backend: orders start at the robot's reported position; `POST /api/missions/{robot_id}/cancel` and
  `POST /api/missions/{robot_id}/extend` (built from the robot's own state, serialised, 409 when unsafe).
- UI: Cancel button for robots on a route (and FAILED ones), Load column, WAITING/CANCELLED badges.
- A robot that ran empty keeps its order (errors never clear an order); after charging it resumes on an
  order update or needs a cancel (D-33 amended).
- Validator: `WAITING` and `CANCELLED` in the mission state machine.

### Week 2 quality gate (D-33, D-34)
- Battery charges while a robot has no order and stands in the charging area (1 %/s); `charging` is
  reported truthfully; a robot that ran empty there takes orders again once charged. Before, every robot
  died after ~500 m until the simulator restarted.
- State is published on VDA 5050 events (node traversal, action and error changes, driving start/stop),
  not only every second; `driving`/`vx` reflect real movement; `theta` stays within −π…π.
- Each robot publishes its `factsheet` (retained, QoS 0), validated against the official 2.1.0 and 3.0.0
  schemas.
- Validator: `driving-consistency` flags only driving outside a route (standing still on a route is
  truthful, not an error).
- Measured on the real stack: state every second holds at 1, 10 and 50 robots (worst interval 1.064 s,
  no headerId gaps, no drift).

### Security and robustness (Week 1 quality gate, D-30 to D-32)
Found by an independent review; each item reproduced first and covered by a regression test.
- One MQTT message could break the backend: wrong-shaped fields crashed the validator (message lost),
  deeply nested JSON broke the API, live feed and recording until restart, NaN/Infinity blanked every
  browser, and there was no size limit. Now: 256 KiB broker and backend limit, depth limit 32, NaN and
  Infinity rejected with precise issues, type-checked validators, large payloads previewed (D-31).
- Any MQTT login could disconnect the backend or a robot by reusing its fixed client id: ids now carry a
  random suffix.
- One malformed order crashed the whole simulator; orders are now type-checked and rejected with an
  `orderError` naming the field; duplicate orders are ignored, stale `orderUpdateId`s rejected.
- Same-origin check now compares scheme, host and port: another web app on the same host (another port)
  can no longer control the lab; nginx forwards the Host header with its port (D-32).
- Open live feeds end on logout or session expiry (checked at least every 5 s).
- Default replay no longer republishes VDA 5050 3.0 `zoneSet` and `responses` (commands).
- Frontend image: nginx 1.27 (end of life, 43 HIGH/CRITICAL fixable CVEs) → `nginx-unprivileged` 1.30,
  runs as uid 101; 0 HIGH/CRITICAL in trivy.
- Failed-login table and per-robot history are capped; container logs rotate; message-handler tracebacks
  are rate-limited.
- Upgrading: `docker compose up -d --build --force-recreate` (the broker and nginx configuration changed).

### Fixed (Week 1 quality gate)
- Command traffic (our own orders echoed back, instantActions, …) created ghost robots, could evict real
  ones and hid the mission warning.
- Validator history and failure injection mixed robots with the same serial (D-27); replay was blocked by
  any same-serial robot from another manufacturer.
- Near-collision pairs stayed active after a robot changed map, hiding the next incident.
- `POST /api/failures` returned 500 when a robot's `actunode` field was null.
- Replay scanned the session file on the event loop (≈2.5 s stall at 200 MB).
- Simulator: the last will carried the first headerId and the process-start timestamp.
- UI: a bad frame lost the whole live snapshot; `null` payloads or object-valued fields crashed the
  message stream and robot table; robot and failure lists grew without limit; an old session answer could
  override a newer one.

### Added
- Real-browser tests: Chromium via Playwright in the e2e suite, run in every CI configuration (D-29, #6).
- TLS: HTTPS on 8443 and MQTT over TLS on 8883 with a local CA from `cert-init` (`show ca`); plain ports are always published on 127.0.0.1 only (D-26, #12 part C2).
- Web login for sharing the lab (`ACTUNODE_REQUIRE_LOGIN`, token from `mqtt-init show api-token`, HttpOnly session cookie, rate-limited); backend refuses to start shared without it; login screen and Log out in the UI (D-25, #12 part C1).
- Host and Origin checks for the API and live feed (`ACTUNODE_ALLOWED_HOSTS`): other web pages can no longer use it via DNS rebinding or cross-site requests (D-24, #12 part B).
- MQTT logins with per-robot topic permissions; generated secrets in a Docker volume; `mqtt-init add-robot` / `show tools`; security e2e tests (D-23, #12 part A).
- Near-collision detection: `proximity` warning, map highlight, `GET /api/proximity`, `ACTUNODE_PROXIMITY_M` (D-22, #5).
- Simulator `--vda-version 3` (`ACTUNODE_VDA_VERSION`): robots speak VDA 5050 3.0.0 (part B of #8).
- Orders and replay use each robot's own VDA 5050 version and manufacturer; UI reads 3.0 fields and shows a VDA column; e2e runs for 2.1 and 3.0 in CI (parts C–D of #8).
- VDA 5050 3.0 (part A of #8): validation against the official 3.0.0 schemas on `v3` topics; 3.0 robots appear in the robot list.
- Frontend tests (Vitest + React Testing Library, `npm test`), run in CI (D-19).
- Sessions: size limit (`ACTUNODE_MAX_SESSION_MB`, default 200), end record `reason`, delete
  (`DELETE /api/sessions/{id}` and a UI button), size shown while recording, auto-stop notice and
  SIZE LIMIT / WRITE ERROR badges in the UI.
- End-to-end tests (`tests/e2e`) against the real Docker stack, run in CI (D-16). They check
  state every second, the mission state machine, BLOCKED_PATH, validation, record/replay,
  last will on a killed simulator, recovery after a broker restart, and shutdown with an open recording.
- Compose: health checks for backend and frontend; configurable host ports and sessions directory.
- Customer discovery kit: [outreach messages](docs/discovery/OUTREACH.md) and [interview guide](docs/discovery/INTERVIEW_GUIDE.md).
- [docs/research/VDA5050_3_0.md](docs/research/VDA5050_3_0.md): VDA 5050 3.0 vs 2.1 comparison and plan (D-15).
- ruff lint and format for Python (`ruff.toml`, 120 columns) and a `lint` job in CI (D-14).
- Project tracking and documentation: [docs/PROGRESS.md](docs/PROGRESS.md),
  [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/DECISIONS.md](docs/DECISIONS.md), this changelog.
- [docs/PLAN.md](docs/PLAN.md) is now the plan reference with calendar dates; status moved to PROGRESS.md.

### Changed
- **Robot MQTT logins are now `<manufacturer>.<serial>`** (simulated: `ActuNode.robot_01`), and each
  login may publish only under its own manufacturer and serial; the broker ACL is generated by
  `mqtt-init` (D-28, #20). `add-robot` takes `<manufacturer> <serial>`. Upgrading: re-create real robot
  logins, then `docker compose up -d --force-recreate mqtt-init mosquitto`.
- A robot is now `(version, manufacturer, serial)`: robots with the same serial from different
  manufacturers or versions get their own row, marker and near-collision check. Robot entries carry a
  `key` (`v2/ActuNode/robot_01`); **proximity pairs name robots by key**; the per-robot `identities`
  list is removed (D-27, #19).
- API docs moved to `/api/docs` (and `/api/openapi.json`), so they are reachable through the UI port.
- The credentials volume is now called `secrets` (was `mqtt-secrets`); it also holds the web login token.
- Validator uses the official VDA 5050 2.1.0 schemas (vendored, MIT) for all six topics instead of a
  hand-written subset; `batteryCharge` outside 0–100 % is a `value-range` warning (D-20).
- Frontend moved from end-of-life Node.js 20 to Node.js 24 LTS (dev, CI, Docker) (D-19).
- CI: GitHub Actions upgraded to v7 (Node.js 24); runner pinned to `ubuntu-24.04`.
- Compose: containers no longer have fixed names (`actunode-backend` → `actunode-backend-1`, etc.).
- CI: the `compose` build job is replaced by the `e2e` job, which builds and runs the stack.

### Fixed
- In login mode the UI opened the live feed and API calls before its first session check answered (401 and
  WebSocket 403 in the browser console); it now shows "Connecting to ActuNode…" until the check answers
  (found by the new browser tests, #6).
- Starting a recording within the same second as the previous one failed (409, same session id); a
  suffix (`_2`, `-2`) now keeps them apart.
- Security: orders were routed by the identity a robot was last seen with, so any MQTT client could
  redirect them; two rounds of patches still left ways around it. Orders now go only where the request
  says (`manufacturer`, `vda_version`) or to the configured default; observed identities produce a
  `warning` and are offered in the UI's new Target select (D-21). At most 8 identities per robot and
  1,000 robots are kept.
- Mission form: a spoofed manufacturer name containing `|` could make the Target show one identity and
  send to another; nothing is preselected from observed (possibly spoofed) traffic.
- Mission form could show one robot while sending to another (the default `robot_01` when it was not
  in the live list).
- A write error (e.g. disk full) during recording logged a traceback for every message and silently
  dropped messages; recording now stops once with the reason.
- Replay loaded the whole session into memory twice (90 MB peak for a 25 MB file); it now streams
  (0.03 MB).
- Listing sessions parsed every line of every file; it now reads the first and last line.
- Security: all ports were published on every network interface, so anyone on the same network could
  connect to the anonymous broker and the API. Ports are now published on 127.0.0.1 by default
  (`ACTUNODE_BIND_ADDRESS` to change, D-18).
- Orders were published (and subscribed) with MQTT QoS 1; VDA 5050 section 6.2 requires QoS 0.
- A robot whose battery ran out mid-mission kept reporting MOVING and `driving: true`. It now stops
  exactly where the battery runs out, the mission becomes FAILED with a FATAL `batteryEmpty` error,
  and orders are rejected while the battery is empty (D-17).
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
