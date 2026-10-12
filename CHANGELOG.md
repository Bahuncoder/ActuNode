# Changelog

What changed, per commit, newest first. Status and plans are in [docs/PROGRESS.md](docs/PROGRESS.md).

## Unreleased

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
