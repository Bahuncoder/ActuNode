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
10 Oct 2026 · Accepted · implemented 10 Oct 2026 (issue 8, ahead of the Week 5 plan)

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
components rendering malformed robot data. Real-browser tests: D-29.

## D-20 · Validate against the official VDA 5050 2.1.0 schemas
10 Oct 2026 · Accepted · supersedes the hand-written-schema part of D-8

**Context.** D-8 used a hand-written subset of the schemas (issue 7), which could disagree with the
standard. The official 2.1.0 schemas are MIT-licensed and set no `additionalProperties`, so extensions
are allowed; every message ActuNode produces (recorded and freshly generated, all mission states)
passes them.
**Decision.** Vendor the six official 2.1.0 schemas unchanged (pinned commit, license kept) and check
every VDA 5050 topic against its schema. Keep ActuNode's own schemas only for the `actunode` extension
and the inject command. Checks the official schema does not make become separately named plausibility
warnings, not `schema` errors: the 2.1.0 schema leaves `batteryCharge` unbounded, so 140 % is reported
as `value-range` (warning).
**Consequences.** `schema` errors now mean "violates the official standard", nothing more; all six
topics are covered (before: three). Groundwork for 3.0 (D-15): add the 3.0 set next to it.

## D-21 · Never route commands from observed traffic
10 Oct 2026 · Accepted

**Context.** For 3.0 support, orders were first sent to the version/manufacturer a robot was last seen
with. Three successive security reviews each found a way to abuse that: a spoofed state message
redirected orders; then one spoofed message blocked a robot; then a spoofer outlasting a silent robot,
or flooding the robot list, could again decide routing. The root cause is not a bug in any one rule:
the broker is anonymous, so **no observation proves who sent it**, and any routing inferred from
observations can be steered by whoever produces them.
**Decision.** The backend routes an order exactly to the `manufacturer` / `vda_version` named in the
request, or to the configured default (`ActuNode`, `ACTUNODE_VDA_MAJOR_VERSION`). Observed identities
are kept (capped) for display and advice only: the mission response carries a `warning` when the
robot was seen but never under the identity used, and the UI's Target select shows the observed
identities so a person chooses. *Amended after security review 4:* nothing is preselected (an observed
identity may be spoofed); the form keeps the chosen identity itself, not a list position or an encoded
string; names the server would reject are shown disabled.
**Consequences.** Simple, deterministic and not spoofable through the backend; sending to a 3.0 robot
needs `vda_version: "3"` (the UI fills it from what it sees). Authenticity of robots requires broker
authentication with per-robot topic permissions (issue 12).

## D-22 · Detect near-collisions; never avoid them
10 Oct 2026 · Accepted

**Context.** Simulated robots drive straight lines and pass through each other (issue 5). Avoiding
collisions is traffic management: the job of the fleet manager under test (or Open-RMF), which the plan
positions ActuNode to complement, not replace. Building it would make ActuNode a fleet manager and
break the founder rule "do not start as a generic fleet dashboard; start at the debugging pain".
**Decision.** Stage 1 (debugging lab) detects and records, it does not steer: the backend reports a
`proximity` warning when two live robots on the same map come closer than `ACTUNODE_PROXIMITY_M`
(default 1.0 m), once per incident (re-armed beyond 1.2×), attached to the state message so it lands in
the stream, the Validation panel and recordings; current pairs are shown on the map and at
`GET /api/proximity`. ActuNode's own mission sender is a **test driver, not a fleet manager**. Planned
for Week 6: realistic safety stops in the simulator (robot halts and reports `safetyState.fieldViolation`
when another robot is in its path), which produces the deadlocks a fleet manager must handle. Never:
path planning or traffic control inside ActuNode.
**Consequences.** Near-misses become evidence; later (stage 2, test infrastructure) a scenario can assert
"no proximity warnings". The detector immediately found real near-misses in our own demo: robots leaving
the parking grid for CHARGING pass within 0.5 m of parked neighbours.

## D-23 · Broker logins with per-robot topic permissions; secrets in a Docker volume
11 Oct 2026 · Accepted (issue 12, part A)

**Context.** The broker accepted anonymous clients, so any process able to reach it could publish as
any robot or send orders (D-21 explains why the backend cannot fix that by guessing). The real fix is
authenticating publishers at the broker.
**Decision.** `allow_anonymous false`. Logins: `actunode-backend` (full access: orders, failure commands,
replay), `tools` (read only, for people), `healthcheck`, and one login per robot named after its serial
number. The ACL lets a robot publish only its own `state`/`connection`/`visualization`/`factsheet` and
read only its own `order`/`instantActions`/`zoneSet`/`responses`/inject topics. An `mqtt-init` service
(same mosquitto image) generates random passwords on first start into the `mqtt-secrets` volume, never
in git or on the host; each service mounts only its own subfolder read-only, files owned by that
service's user (0400): the simulator cannot read the backend's password. Real robots get a login with
`docker compose run --rm mqtt-init add-robot <serial>`; the tools password with `... show tools`.
*Amended by D-28:* robot logins are now `<manufacturer>.<serial>` and pin the manufacturer.
Without a username configured, backend and simulator connect anonymously (local development broker).
**Consequences.** Spoofing another robot or sending orders without the backend's login is refused by the
broker (verified: 7 attempts blocked, own messages delivered; permanent e2e tests). Needs Docker ≥ 26
for volume subpaths. Passwords still travel unencrypted on the wire: TLS is part C of issue 12 (shared
mode); the default bind to 127.0.0.1 (D-18) keeps that off the network meanwhile.

## D-24 · Refuse requests from other web pages: Host and Origin checks
11 Oct 2026 · Accepted (issue 12, part B)

**Context.** Binding to 127.0.0.1 keeps other machines out, not other *web pages* in the user's own
browser. Demonstrated against the running stack: a request with `Host: attacker.example` (DNS
rebinding) was served (200); a cross-site WebSocket was accepted and streamed 34 KB of live robot data;
a cross-site `text/plain` POST started a recording (201).
**Decision.** An ASGI middleware in front of the whole API (HTTP and WebSocket): the `Host` name must
be in `ACTUNODE_ALLOWED_HOSTS` (default `localhost,127.0.0.1,::1`; add the machine's name when
sharing), and WebSocket handshakes and state-changing requests (anything but GET/HEAD/OPTIONS) carrying
an `Origin` of another host (or `null`) are refused. Requests without `Origin` (curl, scripts) are not
browser pages and are allowed. No CORS headers are sent, so cross-site reads stay hidden from pages.
**Consequences.** All three attacks now refused (400/403/403), the UI unaffected; unit tests and an e2e
test through nginx. A real API login is still needed for shared networks (part C).

## D-25 · Login required when the lab is shared beyond this computer
11 Oct 2026 · Accepted (issue 12, part C1)

**Context.** Locally the lab is protected by the 127.0.0.1 bind (D-18) and Host/Origin checks (D-24).
Shared on a network (publishing ports beyond this machine and allowing the machine's name in
`ACTUNODE_ALLOWED_HOSTS`), the API had no login at all.
**Decision.** `ACTUNODE_REQUIRE_LOGIN=1` closes every API path and the live feed (except health, login,
logout, session status) behind a session. `POST /api/login` compares the generated API token (`secrets`
volume, `mqtt-init show api-token`) in constant time and returns a random session id in an HttpOnly,
SameSite=Strict cookie (Secure under HTTPS), valid 12 h, kept in backend memory (a restart logs everyone
out). Failed logins are limited to 5 per minute per client (nginx sets `X-Real-IP`). **Interlock:** the
backend refuses to start when `ACTUNODE_BIND_ADDRESS` is not a loopback address and login is off, so the
lab cannot be shared by accident. The UI shows a login screen when needed and a Log out button.
**Consequences.** Shared mode is authenticated; local mode unchanged (no token to paste). Without TLS the
token and session cookie still cross the network in clear text: TLS is part C2.

## D-26 · TLS for everything that leaves the computer; plain ports pinned to 127.0.0.1
11 Oct 2026 · Accepted (issue 12, part C2)

**Context.** With login (D-25) and MQTT logins (D-23), shared use still sent the API token, session
cookie and MQTT passwords unencrypted across the network.
**Decision.** One rule: unencrypted ports never leave this computer. Plain HTTP 8080, the direct API
8000 and plain MQTT 1883/9001 are published on 127.0.0.1 always; HTTPS (nginx, 8443) and MQTT over TLS
(mosquitto, 8883, TLS ≥ 1.2) follow `ACTUNODE_BIND_ADDRESS`. A `cert-init` step (python:3.12-slim,
which has openssl; the broker image does not) creates a local CA once (P-256, 10 years) and a server
certificate (825 days) for localhost, 127.0.0.1, ::1, mosquitto and every name in
`ACTUNODE_ALLOWED_HOSTS`, renewed when that list changes or within 30 days of expiry. The CA key stays
in the `secrets` volume; browsers and robots trust the CA certificate (`cert-init show ca`). Session
cookies are Secure under HTTPS. Inside the Docker network the backend and simulator keep using 1883.
**Consequences.** Shared mode is encrypted end to end on the network side; verified that plain ports are
unreachable from the LAN and that clients not trusting the CA are refused. Browsers warn until the CA
is imported. Issue 12 closed.

## D-27 · A robot is (version, manufacturer, serial number)
11 Oct 2026 · Accepted (issue 19)

**Context.** VDA 5050 makes serial numbers unique per manufacturer only, and the topic carries version,
manufacturer and serial. The live hub keyed robots by serial alone, so robots from two vendors with the
same serial (or one robot heard under v2 and v3) shared one entry: the table, map and near-collision
check showed whichever spoke last, and two such robots could never be reported as too close.
**Decision.** The hub keeps one entry per `(major, manufacturer, serial)`, with a `key` field
`"<major>/<manufacturer>/<serial>"` (e.g. `v2/ActuNode/robot_01`); `robotId` stays the serial. Proximity
pairs (`GET /api/proximity`, WebSocket, snapshot) name robots by key. Lookups that only have a serial
(failure injection, the "robot is live" check before replay, the mission warning) use every entry with
that serial. The per-robot `identities` list is gone: the UI derives it from the entries sharing a
serial, and routing is unchanged: orders go only where the request says (D-21). The 1,000-robot cap
now also bounds the identities a publisher can create.
**Consequences.** Mixed fleets with colliding serials show as separate rows (with manufacturer and
version when serials collide) and markers. Breaking change for API clients reading proximity pairs or
`identities`. Broker logins are still per serial (issue 20).

## D-28 · Robot logins are `<manufacturer>.<serial>`, with one generated ACL block per robot
11 Oct 2026 · Accepted (issue 20, amends D-23)

**Context.** D-23 named each robot login after its serial and used Mosquitto `%u` patterns
(`uagv/+/+/%u/state`). VDA 5050 serials are unique per manufacturer only, so two vendors' robots with the
same serial could not both get a login, and one robot's login could publish under any manufacturer
name, i.e. appear as a different robot in the hub (D-27). A pattern cannot fix this: `%u` stands for
one topic level, and Mosquitto refuses pattern substitution for usernames containing `/`.
**Decision.** A robot logs in as `<manufacturer>.<serial>`; both parts are limited to `[A-Za-z0-9_-]`, so
the dot splits them unambiguously. `mqtt-init` builds the broker's ACL on every start: the static rules
(`mosquitto/config/acl`: backend, tools, healthcheck) plus one `user` block per robot login, with
manufacturer and serial written into the topics (`uagv/+/<manufacturer>/<serial>/state` ...). The VDA
major version stays a wildcard, so a firmware update from 2.x to 3.0 needs no new login (the hub shows
it as another robot, D-27). Simulated robots are `ActuNode.robot_NN` and alone get the `inject` topic.
Real robots: `add-robot <manufacturer> <serial>`. An old serial-only login file is ignored with a
warning naming the command to re-create it; ActuNode does not guess its manufacturer.
**Consequences.** Mixed fleets with colliding serials can all connect; a login can no longer publish under
another manufacturer (verified live and in e2e). The ACL is generated (≈24 KB for 50 simulated robots)
and lives in the secrets volume; the broker must be recreated with `mqtt-init` after upgrading, and real
robot logins made before this change must be re-created.

## D-29 · Real-browser tests: Playwright (Python) inside the end-to-end suite
11 Oct 2026 · Accepted (issue 6)

**Context.** Frontend tests run in jsdom (D-19); nothing checked the UI in a real browser against the
real stack (WebSocket, layout, login screen).
**Decision.** Chromium driven by Playwright's Python sync API, as `tests/e2e/test_05_browser.py`, using
the e2e suite's `stack` fixture, so it runs in every CI configuration (2.1, 3.0, 2.1 with login) with no
second harness. No pytest plugin: fixtures stay explicit. Every test fails on any browser console error
or page error from the first page load on, including before login. The browser uses the local plain-HTTP
UI (127.0.0.1 only, present in every mode): the suite never turns certificate checks off, and TLS is
already covered by `test_04_security.py`; the module is skipped when the stack is reached over the
network. It runs last, because sending a mission moves robots that earlier tests expect parked.
**Consequences.** Three tests: live robots, map markers and stream over a real WebSocket; a mission sent
from the form (choosing the observed target on 3.0, D-21) reaches COMPLETED; the login screen refuses a
wrong token. On its first run in login mode it found a real bug: the lab mounted before the first session
check answered and opened the live feed and API calls without a session (401/403 in the console). CI
installs Chromium (`playwright install --with-deps chromium`), adding about a minute to each e2e job.
