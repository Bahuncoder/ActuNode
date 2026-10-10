# Decision log

Significant technical decisions: what was decided, why, and what it costs. Add a new entry
instead of editing an old one; if a decision is reversed, add an entry that supersedes it and mark the
old one **Superseded by D-n**.

Format: **D-n · title** · date · status (Accepted / Superseded).

---

## D-1 · Stack: Python simulator, FastAPI, React + TypeScript, Mosquitto, Docker Compose
9 Oct 2026 · Accepted

**Context.** The plan (*Technical architecture*) recommends exactly this stack, aimed at two students
building without hardware.
**Decision.** Follow it. SQLite is not used yet: sessions are files (D-6) and live state is in memory.
**Consequences.** One language on the server side; easy to run on a laptop. ROS 2 and a database
come later, when a feature needs them.

## D-2 · Speak VDA 5050 2.x (`uagv/v2`, version `2.1.0`) for now
9 Oct 2026 · Accepted

**Context.** VDA 5050 3.0 was published in April 2026, but its details have not been worked through
yet; 2.x is widely implemented and well understood.
**Decision.** Implement 2.x message shapes and topics. Keep the interface name and major version
configurable (`ACTUNODE_VDA_INTERFACE`, `ACTUNODE_VDA_MAJOR_VERSION`).
**Consequences.** 3.0-only features (zones, path sharing) are not supported. The plan's risk table says
*keep schema/version support modular*; revisit after researching 3.0 (PROGRESS issue 9).

## D-3 · One MQTT client per simulated robot
9 Oct 2026 · Accepted

**Context.** VDA 5050 uses the MQTT last will on the `connection` topic to report
`CONNECTIONBROKEN`. A last will belongs to a client, not to a topic.
**Decision.** Each robot gets its own MQTT client and last will.
**Consequences.** Realistic connection behaviour (a crashed simulator reports every robot as broken),
at the cost of one connection and network thread per robot. Fine up to the 50-robot limit.

## D-4 · Mission status as an ActuNode extension field
9 Oct 2026 · Accepted

**Context.** The plan's state machine (`IDLE → ACCEPTED → MOVING → COMPLETED`) is not a VDA 5050
concept; VDA 5050 conveys progress through `orderId`, `nodeStates`, `driving`, `actionStates`.
**Decision.** Keep the VDA 5050 fields correct, and add `state.actunode.missionStatus` for the
simulator's own state machine.
**Consequences.** Messages stay valid VDA 5050 (extra properties are allowed); the UI and validator can
use the simpler status. Real robots will not send this field, so nothing may *depend* on it for
non-simulated robots.

## D-5 · Failure injection on a separate `actunode/` topic
9 Oct 2026 · Accepted

**Context.** Failures must be triggered in the simulator from the UI. VDA 5050 has no such message,
and hijacking `instantActions` would confuse anyone testing a real fleet manager.
**Decision.** Commands go to `actunode/v1/sim/<robot>/inject`. The backend refuses injections that
cannot apply (robot offline, unknown, or not on a route).
**Consequences.** VDA 5050 topics carry only VDA 5050 traffic; injections are still visible in the
message stream and recordings because the backend subscribes to `actunode/#`.

## D-6 · Sessions are JSONL files, format version 1
9 Oct 2026 · Accepted

**Context.** Plan Day 6: *record messages to a JSONL session file*. Engineers should be able to read,
`grep`, `jq` and attach session files to bug reports.
**Decision.** Header line, robot snapshot, one line per message with `t` (seconds since start), end
line. Invalid JSON kept verbatim in `payloadRaw`. A missing end line means the recording was cut off.
**Consequences.** Simple and inspectable; replay currently loads the whole file into memory
(PROGRESS issue 11). Any format change must bump `formatVersion`.

## D-7 · Replay is robot-side only by default, and refuses to mix with live robots
9 Oct 2026 · Accepted

**Context.** A session contains orders and failure commands. Replaying them would make any listening
robot, simulated or real, act on them. Replaying while the simulator runs the same robot ids would
interleave live and recorded traffic.
**Decision.** By default replay only robot-originated topics (`state`, `connection`). Commands only
with `include_commands`. Refuse to replay while robots in the session are publishing live state
(judged by state messages in the last 3 s, not by connection messages, which are retained).
Replayed messages are never retained.
**Consequences.** Safe by default; the user has to stop the simulator before replaying.

## D-8 · Validator: own schema subset + sequence rules; errors vs warnings
10 Oct 2026 · Accepted

**Context.** Plan Week 5: *validator checks schema, required fields and state transitions*. Official
VDA 5050 JSON schemas exist but were not used, to keep the first version understood line by line.
**Decision.** Hand-written JSON Schemas (draft 2020-12) for the messages ActuNode uses, plus rules a
schema cannot express (headerId per topic, order sequence, state machine, topic consistency).
Protocol violations are **errors**; legal-but-suspicious sequences are **warnings**. Extra properties
are allowed.
**Consequences.** May disagree with the official schemas in places (PROGRESS issue 7); compare in Week 5.

## D-9 · Robot data is untrusted in the UI
10 Oct 2026 · Accepted

**Context.** A malformed state message (battery as a string) blanked the whole UI. ActuNode exists
to show broken integrations, so it must render whatever arrives.
**Decision.** Components read robot fields through type-checking helpers (`live.ts`) instead of
trusting TypeScript types; each panel has an error boundary.
**Consequences.** Slightly more code per field; one bad message can no longer take the lab down.

## D-10 · Company documents stay out of the repository
9 Oct 2026 · Accepted

**Context.** The plan says the core goes open source; the pitch deck and full plan are private.
**Decision.** `docs/company/` is in `.gitignore`. Only the logo is committed.
**Consequences.** A fresh clone does not contain the plan PDFs; [PLAN.md](PLAN.md) carries the
schedule.

## D-11 · Follow the calendar; spend time ahead on quality
10 Oct 2026 · Accepted

**Context.** The first sprint built first versions of most of the 8-week feature list in two days.
**Decision.** Keep to the 8-week calendar (Week 1 = 9–15 Oct 2026). Use time ahead of schedule for
verification, tests, documentation and user conversations, not for pulling the next weeks' features
forward. Track everything in [PROGRESS.md](PROGRESS.md).
**Consequences.** Slower feature growth, better-understood and better-tested code.

## D-12 · Containers run as non-root; the backend runs as the host user
10 Oct 2026 · Accepted

**Context.** The first Docker run wrote session files into the mounted `./sessions` directory as
`root`, so the user could not delete or edit their own recordings without `sudo`. Running services
as root is also needless privilege.
**Decision.** Backend and simulator images create and switch to an unprivileged user. Compose runs
the backend as `${ACTUNODE_UID:-1000}:${ACTUNODE_GID:-1000}` so files it writes belong to the host user.
nginx (frontend) keeps the official image's default.
**Consequences.** Users whose uid/gid is not 1000 must set `ACTUNODE_UID` / `ACTUNODE_GID`
(documented in the README).

## D-13 · nginx resolves the backend per request
10 Oct 2026 · Accepted

**Context.** nginx resolved `backend` once at start-up. When the backend container was recreated
with a new IP, every `/api` request failed with 502 until nginx was restarted.
**Decision.** Use Docker's embedded DNS (`resolver 127.0.0.11 valid=10s`) and a variable in
`proxy_pass`, so the name is re-resolved.
**Consequences.** Restarting or rebuilding the backend alone no longer breaks the UI.

## D-14 · ruff for Python lint and format, 120 columns
10 Oct 2026 · Accepted

**Context.** No style rules existed; editors flagged lines against pycodestyle's default of 79
columns while the code used up to ~120.
**Decision.** ruff (pinned) checks pycodestyle, pyflakes, import order, bugbear and pyupgrade rules
and formats the code; line length 120. CI fails on any finding. `.flake8` mirrors the line length for
editors; `ruff.toml` is the source of truth. The frontend keeps oxlint.
**Consequences.** One reformatting commit touched most Python files; from now on style is not
discussed in review, and bugbear catches likely bugs early.

## D-15 · Support VDA 5050 2.x and 3.0 side by side, selected by topic
10 Oct 2026 · Accepted (implementation planned for Week 5)

**Context.** VDA 5050 3.0 (March 2026) is breaking: renamed fields, new enums, edges without
start/end node ids ([research note](research/VDA5050_3_0.md)). Installed fleets probably stay on 2.x
for a while (unverified; to be asked in customer discovery). An integration lab is most useful where
versions meet.
**Decision.** Keep 2.1.0 as the default. In Week 5 make validation version-aware using the
**official** schemas of both versions, chosen per message by the topic's major version (`v2`/`v3`);
make the backend and UI read both; add a simulator `--vda-version` option. Zones, path sharing and
the `responses` topic are out of scope until users ask. Supersedes the "2.x for now" part of D-2.
**Consequences.** Two schema sets to maintain; one version-aware reading layer in backend and UI.
The official 3.0 `order.schema` needs a one-character local fix until upstream fixes it.

## D-16 · End-to-end tests run the real Docker Compose stack, isolated per run
10 Oct 2026 · Accepted

**Context.** Behaviour across processes (MQTT timing, last will, reconnects, shutdown order, nginx)
was verified only by hand, and several real bugs appeared only in Docker. Unit tests cannot see them.
**Decision.** `tests/e2e` starts the stack exactly as users run it (`docker compose up --build --wait`)
under its own project name, host ports and temporary sessions directory, drives it through the HTTP
API and MQTT, and removes it afterwards. Compose host ports and the sessions directory became
configurable for this; fixed container names were dropped so two copies can coexist. Runs in CI on
every push. After restarting a service, tests wait for robot state sent *after* the restart, never
for recent-looking state (a replay that just ended produces exactly that).
**Consequences.** CI takes ~2 minutes longer; a developer's own stack and recordings are never
touched by a test run. `ACTUNODE_E2E_HOST` exists for environments where loopback to Docker ports
misbehaves (issue 15).

## D-17 · Empty battery ends the mission in FAILED with a FATAL `batteryEmpty` error
10 Oct 2026 · Accepted

**Context.** A robot whose battery reached 0 % mid-mission stopped moving but kept reporting
`MOVING` and `driving: true` (issue 4): wrong state, and invisible to anyone watching.
**Decision.** Add mission status `FAILED` (ActuNode extension, like the others). At 0 % the robot stops
exactly where the battery ran out (steps are capped to the remaining range), reports `driving: false`
and an error `batteryEmpty` at level `FATAL` (it cannot recover on its own) referencing the next node
and the order. Orders are rejected while the battery is empty. `FAILED → ACCEPTED` is allowed once a
robot can drive again. Charging is not simulated yet.
**Consequences.** The state machine gains one state; validator and UI updated. Week 6's low-battery
failure builds on this (warning before empty, and a way to recharge).

## D-18 · Publish ports on 127.0.0.1 by default
10 Oct 2026 · Accepted

**Context.** Compose published every port on all interfaces. From the LAN address, an anonymous MQTT
client was accepted by the broker and the HTTP API answered: anyone on the same network (university or
café Wi-Fi) could command the robots, inject messages or start recordings.
**Decision.** Publish all ports on `127.0.0.1` unless `ACTUNODE_BIND_ADDRESS` says otherwise. Sharing
the lab on a network is an explicit choice, documented with its risk in the README. End-to-end tests
bind only to the address they connect to.
**Consequences.** Safe by default for a laptop lab. Real authentication (broker credentials, API login,
TLS) is still needed before any shared deployment (PROGRESS issue 12).

## D-19 · Node.js 24 LTS for the frontend; Vitest for frontend tests
10 Oct 2026 · Accepted

**Context.** The frontend was built on Node.js 20 (dev machine, CI, Docker image) because that was
installed on Day 1. Node 20 had its last release in March 2026 and is end-of-life. Adding frontend tests
showed it concretely: Vitest 5 and jsdom 30 require Node ≥ 22, and npm crashed installing them on 20.
**Decision.** Node.js 24 ("Krypton", current LTS) everywhere: `frontend/.nvmrc`, `engines` in
`package.json`, CI and the Docker build stage. Frontend tests use Vitest + React Testing Library on
jsdom (`npm test`), run in CI. The developer's nvm default is left unchanged; `nvm use` in `frontend/`
selects 24.
**Consequences.** Supported runtime with security fixes; tests for the live-data logic and for
components rendering malformed robot data. Real-browser tests are still to come (issue 6).
