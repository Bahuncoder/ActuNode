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
10 Oct 2026 · Superseded by D-30 (11 Oct 2026)

**Context.** The first sprint built first versions of most of the 8-week feature list in two days.
**Decision.** Keep to the 8-week calendar (Week 1 = 9–15 Oct 2026). Use time ahead of schedule for
verification, tests, documentation and user conversations, not for pulling the next weeks' features
forward. Track everything in [PROGRESS.md](PROGRESS.md).
**Consequences.** Slower feature growth, better-understood and better-tested code.

## D-12 · Containers run as non-root; the backend runs as the host user
10 Oct 2026 · Accepted · *Amended 11 Oct 2026:* nginx too (uid 101, `nginx-unprivileged`), see D-31

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
*Amended 12 Oct (D-37):* at 25–50 robots, straight-line driving out of the parking grid produces frequent
warnings; that is expected.
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

## D-30 · A week is done when its work is fully done, not when the calendar says
11 Oct 2026 · Accepted (supersedes D-11)

**Context.** D-11 held features back to the calendar. The founder changed the rule: dates do not matter;
what matters is whether a week's work is complete.
**Decision.** Each week ends with a **quality gate**: an independent review for bugs and security (every
finding reproduced before it is fixed), dependency and image scans, tests for every fix, all suites and
the end-to-end runs green, docs updated. When the gate passes, the next week's work starts immediately.
Findings that are not fixed are logged as numbered issues with a reason.
**Consequences.** Progress is reported as weeks completed. The Week 1 gate (11 Oct) is the first one.

## D-31 · Treat every MQTT client as hostile: input limits, unguessable client ids, non-root nginx
11 Oct 2026 · Accepted (Week 1 quality gate)

**Context.** The Week 1 review showed that one message from any robot login could: drop silently
(validator crash on a wrong-shaped field), break the API, the live feed and recording until restart
(a ~600-level nested array, ~1.2 KB), blank every browser (NaN/Infinity, which Python accepts and browsers
cannot parse), or exhaust memory (no size limit; a 6 MB payload of `[[],[],…]` took 129 MB parsed). Any
login could also disconnect the backend or a robot by reusing its fixed MQTT client id, and one malformed
order killed the whole simulator process.
**Decision.**
- Broker `max_packet_size` 256 KiB; the backend applies the same limit before parsing, rejects NaN and
  Infinity and structures deeper than 32 levels. Rejected payloads are kept as text with a precise issue
  (`payload-too-large`, `non-finite-number`, `too-deep`, `invalid-json`) and never update a robot.
- Validators check types before reading nested fields; if the validator still fails, the message is kept
  with a `validator-error` issue. Parsing and validation run outside the hub lock (single MQTT thread);
  the WebSocket takes its snapshot off the event loop.
- Payloads over 16 KiB are shown as a 1 KiB preview in the log and live feed; the recorder gets them whole.
- Per-robot history (validator, proximity, header-id counters) is keyed by robot (D-27) and capped.
- MQTT client ids get a random per-process suffix (backend, simulated robots).
- The simulator validates order types strictly (rejecting with `orderError` naming the field), ignores
  duplicates, rejects stale `orderUpdateId`s, and no single message can stop its loop.
- nginx runs as uid 101 (`nginxinc/nginx-unprivileged`, stable line 1.30, `apk upgrade`); container logs
  rotate.
**Consequences.** Each attack above now has a regression test. Remaining risk is logged (issue 21: each
robot's last state is still stored whole, up to 256 KiB × 1,000 robots).

## D-32 · Same-origin check compares scheme, host and port
11 Oct 2026 · Accepted (amends D-24)

**Context.** D-24 compared only the Origin's host name with the allowed hosts, so any other web app on
the same host (a dev server on another port, Jupyter) could send state-changing requests and open the
live feed; with login off that is full control.
**Decision.** A state-changing request or WebSocket with an Origin is accepted only if the Origin equals
the site the browser asked for: same scheme (`X-Forwarded-Proto` behind nginx), same host and same port
as the Host header (default ports normalised). nginx forwards the browser's Host header with its port
(`$http_host`); the Vite dev proxy already does. Requests without Origin (scripts) are unchanged.
Open live feeds re-check their session at least every 5 s, so logout or expiry also ends them.
**Consequences.** Verified with unit tests (other port, other scheme, other allowed host name refused;
dev proxy, nginx HTTP and HTTPS accepted) and the e2e suite through nginx in all three configurations.

## D-33 · Simulated robots charge in the charging area
11 Oct 2026 · Accepted (Week 2 quality gate)

**Context.** The battery only ever drained (0.2 % per metre) and `charging` was always false, so every
robot was empty after about 500 m and refused orders until the simulator restarted, although robots park
in the charging area. A long lab session degraded silently.
**Decision.** A robot charges while it has no active order and stands inside the map's charging zone
(x 0–12 m, y 0–4 m, the same zone the UI draws and `warehouse.py` names), at 1 % per second, so a demo
robot is full within two minutes; `charging` is reported truthfully (2.1 `batteryState`, 3.0
`powerSupply`). Once an empty robot has charge again its FATAL `batteryEmpty` error is cleared: FATAL
means "needs a human", and keeping it would make a fleet manager stop sending orders. The mission stays
FAILED until the next accepted order. *Amended by D-35:* the robot keeps its order (errors never clear an
order, 3.0 §6.6.5.1), so after charging it needs a `cancelOrder` before it takes a new order. A robot
that runs empty outside the zone stays empty (that is a
real robot's situation too; low-battery behaviour is Week 6).
**Consequences.** The lab can run indefinitely. Charging is fast on purpose; it is a lab, not a battery
model.

## D-34 · State is published on VDA 5050 events; the robot publishes a factsheet
11 Oct 2026 · Accepted (Week 2 quality gate)

**Context.** A semantic review against the official 2.1 and 3.0 texts (the messages already passed the
schemas) found: node traversals, finished actions and new errors were published only on the next 1 s
tick (2.1 §6.10 and 3.0 §6.6 make them triggers); `driving: true` and a speed were reported while the
robot stood still; `theta` could be 3.142 (range is −π…π); and no `factsheet`, which both versions make
mandatory.
**Decision.** The simulator compares an event signature (mission status, last node, node/edge/action
states, errors, driving, order ids) before and after each tick and publishes on any change, at most once
per 0.1 s tick, besides the 1 s periodic message. `driving` and `vx` come from the distance actually
moved; `theta` is clamped after rounding. Each robot publishes its factsheet on every connect, retained,
QoS 0 (both versions: QoS 0 for every topic except `connection`). It declares what the simulator really
does (pick and drop node actions, no instant actions yet, 1 m/s); numbers the schema requires but the
simulator does not model (size, acceleration, load mass) are nominal and marked so in the code. Two
upstream 3.0.0 factsheet schema quirks are worked around and recorded in `backend/app/schemas/README.md`.
The backend's `driving-consistency` rule now flags only `driving: true` outside a route: a robot on a
*Amended by D-35:* the factsheet lists the supported instant actions.

route may truthfully stand still (found when the e2e validation check flagged the corrected robot).
**Consequences.** Remaining order-handling deviations found by the same review are Week 3 work (horizon
nodes, edge actions, unknown actions, version-specific error types, start node out of range, loads,
`instantActions`); listed in PROGRESS.

## D-35 · Week 3: order handling, order updates and instant actions per VDA 5050 2.1 and 3.0
12 Oct 2026 · Accepted (design before code)

**Context.** Week 3 is "mission sender and state transitions". The Week 2 review listed the deviations
(PROGRESS, Week 2 gate); the plan adds cancelling and order updates. Rules below quote the official texts
(2.1 §6.6, §6.8–6.11; 3.0 §6.1–6.2, §6.6). Where 2.1 names no error, ActuNode reuses the closest 2.1 name
and says so here.
**Decision (simulator).**
- *New order* (other `orderId`) only when idle: no node/edge states left and every action FINISHED or
  FAILED. Otherwise rejected: 3.0 `OTHER_ORDER_ACTIVE`; 2.1 names none → `orderError`.
- *First node* must be trivially reachable: within `allowedDeviationXY` (2.1 radius in m; 3.0 ellipse
  `{a, b, theta}`); 0 or absent → the simulator's tolerance (0.25 m). Otherwise rejected: 3.0
  `START_NODE_OUT_OF_RANGE`; 2.1 → `orderError`. Node 0 counts as traversed at acceptance (its actions run;
  3.0: not listed in `nodeStates`).
- *Malformed order*: 2.1 `validationError`, 3.0 `VALIDATION_FAILURE`. *Unsupported action type* (only
  `pick`, `drop` are supported): 2.1 `orderError`, 3.0 `INVALID_ORDER_ACTION`, with the field as reference.
  All are WARNING and stay until a new order is accepted.
- *Order update* (same `orderId`): lower `orderUpdateId` → 2.1 `orderUpdateError`, 3.0
  `OUTDATED_ORDER_UPDATE`; equal → ignored if identical, 3.0 `SAME_ORDER_UPDATE_ID` if different (2.1:
  ignored); after a cancel → 3.0 `ORDER_UPDATE_FOLLOWING_CANCEL` (2.1 → `orderUpdateError`). Accepted only
  if its first node equals the current decision point (last released node: `nodeId` and `sequenceId`; if
  everything is traversed, that is `lastNodeId`/`lastNodeSequenceId`). Its base is appended after the
  stitch node (whose actions are not run again), and its horizon replaces the old horizon. A stitch
  mismatch names no error in either version → 2.1 `orderUpdateError`, 3.0 `VALIDATION_FAILURE`.
- *Horizon*: `released` is kept from the order; the robot never traverses unreleased nodes or edges. It
  stops at the decision point: `driving` false, mission status `WAITING`, `newBaseRequest` true when the
  horizon is non-empty and the decision point is within 1 m.
- *Actions*: node actions WAITING → FINISHED on traversal (instant, allowed by 3.0 Table 12); edge actions
  WAITING → RUNNING when the edge is entered → FINISHED when its end node is traversed. Horizon actions
  stay WAITING. `blockingType` has no effect (all simulated actions are instant).
- *Loads*: the robot knows its load state, so `loads` is always sent: `[]` empty; after `pick`,
  `[{"loadId": <parameter or "">}]`; `drop` empties it. A `pick` while loaded or a `drop` while empty
  FAILS that action.
- *instantActions* (subscribed now): each gets an action state (2.1 `actionStates`, 3.0
  `instantActionStates`). `cancelOrder`: stop now (free navigation), clear `nodeStates`/`edgeStates`,
  WAITING/RUNNING order actions → FAILED, keep `orderId`/`orderUpdateId`/`lastNode*`, mission status
  `CANCELLED`, action FINISHED; with no active order (or, 3.0, another `orderId` given) → FAILED +
  `noOrderToCancel` / `NO_ORDER_TO_CANCEL`. `startPause`/`stopPause`: `paused` flag, no driving while
  paused, then resume. `stateRequest`, `factsheetRequest`: publish now, FINISHED. 3.0
  `clearInstantActions` empties `instantActionStates`. Unknown instant action: FAILED, plus 3.0
  `INVALID_INSTANT_ACTION` (2.1 names none: FAILED with a `resultDescription` only). Instant action states
  are capped (oldest finished first). The factsheet lists these instant actions. The `instantActions` message carries its
  list under `actions` in both versions (the official 2.1.0 and 3.0.0 schemas require that key).
**Decision (backend and UI).**
- Orders start where the robot is: node 0 at the robot's last reported position (observed from its own
  state; D-28 ties a state topic to the robot's login), followed by pick and drop. If the robot has no
  position yet, the old shape is sent and the response warns that the robot may reject it.
- `POST /api/missions/{robot_id}/cancel` sends `cancelOrder`; `POST /api/missions/{robot_id}/extend`
  sends an order update that continues from the decision point to a new destination. Both use the same
  addressing rules as orders (D-21: the request names the target or the defaults apply). The backend
  remembers the last order it sent per robot (memory only) to build updates.
- Mission statuses `WAITING` and `CANCELLED` join the state machine (validator transitions, UI badges);
  the UI gets a Cancel button for robots on a route.
*Amended after the Week 3 review (12 Oct):* `extend` takes the order, update id and decision point from
the robot's own latest state for the target identity, not from a memory of what was sent; the memory only
supplies the stitch node's contents. It refuses (409) when the robot has no state, cancelled, runs an
order ActuNode did not send, or has not confirmed the previous update, and one lock serialises extends
(two at once could both send the same update id). The simulator validates every field (including
`actionParameters`, duplicate action and sequence ids) before changing anything and applies an order
atomically; a recharged FAILED robot resumes on an order update, and an update while the battery is empty
is rejected (2.1 `orderUpdateError`; 3.0 `MOBILE_ROBOT_NOT_AVAILABLE`, the closest named type; the
3.0 schema's `errorType` is an extensible string). At most 50 instant actions are handled per message,
with one `INVALID_INSTANT_ACTION` per message, so a hostile message cannot make the state exceed the
broker's packet limit. Every `stateRequest` is answered with a publish.
**Consequences.** Week 3 closes the Week 2 review's order findings and adds cancel and order updates.
`blockingType`, retriable actions, corridors and zones stay out of scope (not used by ActuNode's
missions); listed as known limits in VDA5050_NOTES.

## D-36 · Week 3 second review: limits on everything a robot or file can make us publish; simulator split by job
12 Oct 2026 · Accepted

**Context.** After Week 3 was committed, three fresh reviews (code quality, security, correctness of the
first review's fixes) found: `extend` locked itself out for good after one rejected or lost update; a robot
could make the backend publish an order over the broker's packet limit (its own map name copied into node 0)
and so disconnect the backend; a crafted session file passed the replay live check and could fake a live
robot's state, which order building now reads; long ids or many nodes could still push a robot's state
over the broker limit; and `simulator/robot.py` had grown to 1,131 lines (maintainability index C, 0.00).
**Decision.**
- *Everything published is bounded*: the MQTT bridge refuses any payload over the broker limit (callers
  answer 422 or skip and count); payloads are compact UTF-8 JSON (ASCII-escaped only when a lone surrogate
  forces it); values copied from a robot's state into an order (map id, position) are validated first.
- *Extend*: the next update id comes from the robot's state; a 409 for "update in flight" only lasts 5 s.
  The order memory is its own module (`sent_orders.py`), capped (200 nodes per order, never evicting the
  order the robot runs); robot-reported sequence ids must be integers.
- *Replay* computes the live-check key from exactly the topic it publishes, validates ids, and also checks
  simulator injection topics.
- *Simulator limits*: ids ≤ 128 characters (advertised in the factsheet); ≤ 300 nodes, 300 edges and 300
  actions per order (1,000 would let a valid order's state exceed the limit); the backend's D-31 payload
  limits applied to incoming orders and instant actions; huge numbers rejected, not crashing.
- *Structure*: the simulator is split by job (`protocol`, `validation`, `orders`, `instant`, `messages`,
  `robot`) with one `VersionProfile` per VDA 5050 version instead of scattered version checks; instant
  actions live in one list (2.1 publishes them inside `actionStates`, after the order's actions).
**Consequences.** Every module now rates A for maintainability. The offline demo (`python3 main.py`), broken
by the Week 3 start-node rule without anyone noticing, is fixed and covered by a test.

## D-37 · One warehouse map; robots park in the charging area, then a parking zone
12 Oct 2026 · Accepted (Week 4)

**Context.** The map existed twice (UI constants and simulator constants; the backend had only named
locations), and the simulator parked robots 11–50 in rows climbing into RECEIVING and STORAGE RACKS, some on
rack rows and next to the receiving doors, where they also could not charge (D-33).
**Decision.** `backend/app/warehouse.py` is the map: size, zones, racks and locations, served at
`GET /api/map`; the UI draws from it (built-in fallback while it loads), and simulator tests read that file
to check its charging and parking areas. A new PARKING zone (x 0–8.5, y 5–10.5, free floor between charging
and receiving) holds the robots that do not fit the charging area. Parking spots: 21 in the charging area,
then 30 in PARKING; every spot ≥ 1.3 m from every other (above the 1.2 m proximity re-arm distance, so
parked robots never warn each other), ≥ 1.5 m from every named location, ≥ 0.5 m inside its zone, and
clear of every other zone and rack (tests for all 50). Robots in PARKING do not charge where they stand.
**Consequences.** The map shown, the map the simulator uses and the map the backend serves cannot drift.
Robots that leave the parking grid on straight lines still pass close to parked robots; near-collision
warnings during busy demos are expected (D-22: ActuNode reports, it does not steer).

## D-38 · Live feed at scale: send less, resync slow clients, render once per frame
12 Oct 2026 · Accepted (Week 4)

**Context.** The Week 4 load test (10/25/50 robots, all thresholds met) and review showed what grows with
the fleet: proximity events on every distance change (12.5/s at 50 robots, 19 % of the feed), every state
sent twice per event, events JSON-encoded once per client, a full UI re-render per WebSocket frame, and a
slow client whose queue overflowed lost events silently, possibly for good (proximity, failures).
**Decision.** Proximity events when the set of pairs changes, distances at most once a second; a state
message's event carries the state once (`stateFromMessage`); each event is encoded once for all clients;
an overflowing client is logged once and closed with 1013 so it reconnects for a fresh snapshot; the UI
batches events per animation frame and memoises rows and markers so unchanged robots do not re-render.
Validators were already built once; the remaining per-message cost is jsonschema itself (the load test
projects the 250 ms latency budget holding to roughly 170 robots).
**Consequences.** Measured before and after with the same load test (PROGRESS, Week 4).

## D-39 · Code-quality backlog closed: bounded robot state, validation epoch, trusted proxy, scans in CI
12 Oct 2026 · Accepted (issues 21–24)

**Decision.**
- *Issue 21 (amends D-31):* the hub stores a robot's state whole only up to 64 KiB; a larger state is kept
  as a reduced copy (lists cut to their first 50 entries, then top-level fields dropped until it fits) with a
  `_truncated` marker saying what was cut, which the UI shows as "state trimmed". The recorder still gets
  every message whole. Worst case for 1,000 robots: 64 MB instead of 256 MB.
- *Issue 22:* the validation summary has an `epoch` that increases on every reset, and each `message` event
  carries the `validationEpoch` it was counted under (counted and read under one lock); the UI counts a
  message only in its own epoch. Recording counters reset whenever the recording's session id changes,
  whoever started it, and stale poll answers are ignored.
- *Issue 23 (amends D-25):* the login rate limit uses `X-Real-IP` only when the TCP peer is a trusted proxy
  (`ACTUNODE_TRUSTED_PROXIES`, default the `frontend` nginx service, resolved in the background so a request
  never waits on DNS); otherwise the peer address.
- *Issue 24:* `.github/workflows/security.yml` runs pip-audit, npm audit and Trivy (images and Dockerfiles)
  weekly and whenever dependencies or images change; `.github/workflows/load.yml` runs the load test weekly
  and on demand, keeping the results as an artifact.
**Consequences.** No open issues. New CVEs or a load regression fail a scheduled run instead of waiting for a
person to remember the scans.

## D-40 · Week 5: validate a saved session offline, with the same validator
13 Oct 2026 · Accepted (design before code)

**Context.** Week 5 is "message inspector and validation". Live traffic is validated (D-15, D-20, D-31), but
a session file someone recorded, or sent from a customer site, could only be checked by replaying it.
**Decision.**
- `POST /api/sessions/{id}/validate` streams the file once through a fresh `Validator` (the one the live hub
  uses: version chosen by topic, same rules and D-31 limits) and returns `{sessionId, checked, withIssues,
  byRule: [{rule, description, severity, count}], issues: [{line, t, topic, rule, severity, message}],
  truncated}`; `issues` holds the first 100, `byRule` counts everything. 404 for an unknown session, 409
  while it is being recorded. Messages recorded as invalid JSON (`payloadRaw`) are checked as such.
- The same function runs without the stack: `python -m app.validate_session <file.jsonl>` prints the
  summary and exits 1 if any error-severity issue was found (usable in a customer's CI).
- UI: a Validate button per session in the Sessions panel shows the summary.
*Amended after the gate (13 Oct):* the recorder now stores why a payload was rejected (`rejected`:
invalid-json, non-finite-number, too-deep, payload-too-large), and offline validation reports that rule,
so it matches what the live hub saw message by message. Out of scope by design: near-collision warnings
(they come from the hub's position tracking, not the validator) and header-id history from before the
recording started. One validation at a time (429 otherwise) on its own worker, so it cannot starve the
live feed; results are cached per file version. The CLI applies the same limits and exits 2 on hostile or
malformed files.
**Consequences.** A file can be judged before replaying it; replay safety (D-36) is unchanged.

## D-41 · Week 7: session retention and uploading a session someone sent you
13 Oct 2026 · Accepted (design before code)

**Context.** Recordings are capped per file (`ACTUNODE_MAX_SESSION_MB`) but never deleted, so the sessions
folder grows without limit; and a session file from elsewhere could only be copied in by hand.
**Decision.**
- *Retention:* `ACTUNODE_SESSIONS_KEEP_DAYS` (default 30; 0 keeps forever) and `ACTUNODE_SESSIONS_MAX_TOTAL_MB`
  (default 2000; 0 unlimited). Enforced at startup and after every recording stops: oldest sessions go first,
  never the one being recorded or replayed. `GET /api/sessions/storage` → `{keepDays, maxTotalMb, usedMb,
  sessions}`; the UI shows the usage.
- *Upload:* `POST /api/sessions/upload?name=<optional>` with the raw file as the request body. The file is
  untrusted: size ≤ `ACTUNODE_MAX_SESSION_MB` (413), streamed to a temporary file, then checked line by line
  (session header first with `formatVersion` 1, every line a JSON object of a known record type, line length
  ≤ the D-31 payload limit plus overhead, at most one end record and only last) → 422 naming the first bad
  line. The server picks the session id (`YYYYMMDD-HHMMSS_<sanitised name>`), never a client path. Behind the
  same login and same-origin checks as every state-changing endpoint (D-25, D-32). An uploaded session is
  listed, validated (D-40) and replayed like a recorded one; replay keeps its safety rules (commands not
  replayed by default, live-robot check, D-36).
- UI: an Upload button in the Sessions panel.
*Amended after the gate (13 Oct):* uploads never delete anything: an upload that would exceed the total
limit is refused (507), so no user can push colleagues' recordings out; only recordings rotate old
sessions out, and never the session that just stopped. Upload limits: size ≤ the session limit plus a
small end-record reserve, one upload at a time (429), 10-minute body timeout (408), free disk ≥ 2 × the
limit (507), strict UTF-8, field types checked (a wrongly typed field had crashed the UI for everyone); a
torn last line (crash mid-write) is accepted and dropped; an upload without an end record gets one
(`reason: "uploaded"`) so listing stays cheap. nginx allows bodies up to 201 MB on the upload path only
(its 1 MB default had made every UI upload over 1 MB fail). Uploaded sessions are aged from the upload.
One record reader (`session_records.py`) serves listing, replay, validation and upload checks.
**Consequences.** Week 7's "session file can reproduce an incident" works for files from another site, and
disk use is bounded by configuration.

## D-42 · Week 6: failure injection — low battery, disconnect, invalid payload; spec error levels
13 Oct 2026 · Accepted (design before code)

**Context.** Week 6 is "failure injection: blocked path, low battery, disconnect, invalid payload". Only
BLOCKED_PATH existed (Day 5). The Week 2 review left the 3.0 error level of `pathBlocked` open. 3.0 §6.6.5
defines the levels: WARNING (no immediate attention), URGENT ("e.g., a low battery level… can continue its
current order"), CRITICAL ("shall not continue driving since it can not continue its current order but is
able to take new orders"), FATAL (needs a person). 2.1 has only WARNING and FATAL.
**Decision.** `POST /api/failures {robot_id, failure, action, params}` for simulated ActuNode robots only
(D-27); the command travels on the robot's own control topic as before (`actunode/v1/sim/<serial>/inject`,
validated by `actunode-inject.schema.json`; a shared contract fixture ties backend and simulator).
- `BLOCKED_PATH` (inject / clear, robot on a route): error `pathBlocked`, level 2.1 WARNING, **3.0
  CRITICAL** (changed from WARNING).
- `LOW_BATTERY` (inject with `level` 1–99, default 15; clear restores the level before injection): sets
  the battery. Independently of injection, the robot reports `batteryLow` while below 20 % (2.1 WARNING,
  **3.0 URGENT**), clears it once charged above, keeps driving; at 0 % the existing FATAL `batteryEmpty`.
- `DISCONNECT` (inject only; `duration_s` 1–300, default 10; `mode` `broken` (default) or `offline`):
  `broken` drops the connection without an MQTT DISCONNECT, so the broker publishes the last will
  (CONNECTIONBROKEN / 3.0 CONNECTION_BROKEN); `offline` publishes OFFLINE and disconnects cleanly. The robot
  keeps simulating and keeps its order while away (2.1 §6.14: it "fulfills the order up to the last
  released node"), publishes nothing, and reconnects after `duration_s` (ONLINE, factsheet, current state).
  No clear: a disconnected robot cannot receive one.
- `INVALID_PAYLOAD` (inject only; `kind` one of `not-json`, `schema`, `wrong-serial`, `wrong-version`;
  `count` 1–10, default 1): the robot publishes that many malformed messages on its own state topic, between
  its normal ones, so the validator and the inspector show them.
- The UI's failure panel offers all four with their parameters; every injection is logged and recorded.
*Amended after the gate (13 Oct):* the broker's last will carries an outdated headerId by design (2.1
§6.14), so the validator no longer flags or remembers it; the simulator's disconnect and reconnect run off
the simulation thread (one robot's DISCONNECT froze every robot for up to 1 s) and the reconnect handshake
is published from the simulation thread (thread safety), with the current state right after ONLINE; the
robot reports `actunode.injectedFailures`, and LOW_BATTERY clear needs an active injection (409 otherwise)
and carries no parameters; restoring the battery also clears `batteryEmpty`; at most 10 malformed messages
pending per robot; strict parameter types; the shared fixture `contracts/failure_commands.json` is checked
command by command against the simulator's exact results. A schema-invalid INVALID_PAYLOAD state replaces
the hub's last state for about a second: the hub shows what a robot sent (documented, not changed).
**Consequences.** The plan's four failures exist; each is verified end to end (what the backend, validator
and UI observe). Safety stops (`fieldViolation`) and silent robots (state timeouts) are not in the plan's
list and stay out of scope.

## D-43 · Week 8: publish under Apache-2.0; demo recorded from the real product; v0.1.0
13 Oct 2026 · Accepted (founder chose the license and the release)

**Context.** Week 8 is "demo + README + 3-minute video → GitHub repo + pitch demo". The repository had no
license, so nobody could legally use it.
**Decision.** Apache License 2.0 (permissive, with an explicit patent grant; compatible with the vendored
MIT-licensed VDA 5050 schemas, credited in NOTICE). A demo video is not filmed by hand: `tests/demo/record_
demo.py` drives the real UI through the pitch story on an isolated stack and records video and README
screenshots, so the demo cannot drift from the product; the founder adds the voice-over. The README states
only verified facts. Before release, a gate: an independent accuracy review of every public document
against the code, and a newcomer following the README from a fresh clone. Release v0.1.0 is tagged on the
verified commit.
**Consequences.** The gate found two real bugs (retention settings not passed through Docker; stale
`recording: true` on stop) and stale load figures; fixed and re-measured before tagging. GitHub's private
vulnerability reporting (SECURITY.md) must be switched on in the repository settings by the owner.

## D-44 · Phase 2 plan: scenario tests, sample scenarios, a real robot stack, first users
13 Oct 2026 · Accepted (founder: "go ahead")

**Context.** The eight-week plan is complete (v0.1.0). The plan names four six-month milestones without
weekly detail: developer credibility, real integrations, automated tests, first external users. One question
from the plan's demo scenario is still open: after a blocked path, does the system "cancel, reroute or
escalate"?
**Decision.** Weeks 9–16 (docs/PLAN.md, Phase 2): scenario format and `actunode test` runner (9), timing and
message expectations plus five sample scenarios (10), testing an external master control as the system under
test (11), scenarios in CI (12), a ROS 2 simulated robot behind the open-source VDA 5050 connector (13–14),
documentation for credibility (15), readiness for external users and v0.2.0 (16). Scenario tests come first
because they turn the lab into a test tool without needing hardware, and every later week builds on them.
A decision point after Week 10 lets the first user conversations reorder weeks 11–16. Same working rule
(D-30): completion and a quality gate, not dates.
**Consequences.** PROGRESS tracks weeks 9–16 like weeks 1–8. Outreach (milestone 4) stays the founder's and
feeds the decision point.

## D-45 · Scenario tests: a YAML format and `actunode test`, a black-box client of the HTTP API
13 Oct 2026 · Accepted

**Context.** Week 9 (Phase 2, D-44): a scenario file and a runner, so that an incident such as P-1042 becomes
a repeatable test with pass/fail, JUnit XML and exit codes. The runner has to work against the Docker lab on
the same machine, a shared lab behind login and TLS (D-25, D-26), and later CI (Week 12) and an external
system under test (Week 11).
**Decision.** A separate package, `cli/` (`actunode`, installable with `pip install ./cli`), that drives
the lab only through its public HTTP API, as the UI does: no backend imports, so it tests what users get
and runs from any machine. Format: YAML with a list of steps (`send_mission`, `inject`, `clear`,
`cancel_mission`, `wait`, `expect`). An `expect` passes once all its conditions hold at the same moment,
at the latest `within` N s (default 10); Week 10 adds "never" / "for N s" without renaming anything.
Orders are named with `as:` so `expect … order:` cannot be fooled by an earlier COMPLETED order (the
e2e tests' own lesson). Validation expectations count only issues since the scenario started (by
difference, so the lab's counters are never reset under other users). Strictness by default: unknown and
duplicate keys are errors with their location, safe YAML only without anchors or aliases, files up to
1 MB, failure parameters passed as written for the backend's strict check. The first failing step
ends a scenario; afterwards the runner clears the failures it injected and cancels its own orders that are
still running (also on Ctrl-C), so scenarios do not leak into each other or into people using the lab.
Exit codes separate failure (1) from invalid input (2) and an unusable environment (3). The token comes
from a file or the environment, never the command line; TLS is always verified (a CA file can be given).
**Consequences.** P-1042 passes as `scenarios/p1042_blocked_path.yaml` on the real stack (e2e, VDA 5050
2.1, 3.0 and login mode). `status` relies on ActuNode's `missionStatus`, which other robots do not report;
the Week 13 ROS 2 robot will need a status derived from plain VDA 5050 state. The unit tests' fake lab
must match the real answers: the first e2e run found `vdaMajor` is `"v2"`, not `"2"`, which the fake had
wrong too; a contract test on the backend's shared fixtures now pins it (D-38).

## D-46 · Scenario timing (`for`, `never`), message expectations from the live feed, every run recorded
13 Oct 2026 · Accepted

**Context.** Week 10: "within N s" / "never" timing, expectations on individual messages (topic and JSON
pattern), every run recorded as a session, and five sample scenarios. Week 11 will check what an external
fleet manager sends ("after pathBlocked, a cancelOrder within 10 s"), so message checks must see commands
as well as robot state, and must not miss a message between polls.
**Decision.** `expect` keeps `within` (eventually) and gains `for` (then keeps holding); a new `never` step
fails if its conditions all hold at any moment during `for` seconds. Robot and validation conditions are
polled every 0.25 s (documented: a state shorter than that can be missed). Messages come from the lab's live
feed (WebSocket `/api/ws`, the UI's own feed, opened only when a scenario has a `message` condition), read on
a background thread and stamped on arrival, so none is missed. A message condition sees messages since the
previous step began, so the expect after an action sees what the action caused even if it arrived first.
`match` is a subset pattern (object keys, list items in any order, scalars equal, booleans never equal
numbers). A feed that closes mid-scenario makes it "could not run", never a pass or a fail. Every run starts
a lab recording named after the file and stops it after cleanup; a recording someone else started is left
alone (the run is in it). The session id goes to the console and to JUnit `<properties>`.
**Consequences.** Five sample scenarios in `scenarios/` pass on the real stack in all three configurations;
the disconnect scenario ends with the robot ONLINE, closing the Week 9 open item. A failing CI run comes
with a recording to download and replay. The runner now depends on `websockets`. Opening the feed is retried (3 attempts of 5 s) after CI saw one
connection stall before reaching the proxy; a refused handshake is not retried.

## D-47 · Product audit after Week 10: outside fleet managers get a login; security headers
14 Oct 2026 · Accepted

**Context.** An audit of the product against the company plan (users, jobs, the demo question "does the
system cancel, reroute or escalate?"), with hands-on checks on a running lab and black-box attacks on it.
Found: an AMR vendor's robot could connect, be validated and receive missions, but an outside fleet manager
(master control) could not connect at all: only ActuNode's backend may publish orders (D-23). So the plan's
demo question, which is about the customer's system, could not be asked of a real fleet manager. Also: the
web UI had no security headers (a shared lab could be framed by another site and a logged-in user tricked
into clicking "Inject failure"); npm ran under an old Node with confusing results.
**Decision.** A master control login, `master@<name>`, created with `mqtt-init add-master <name>
[<manufacturer> ...]` (default `ActuNode`, the simulated robots). Its ACL block, per manufacturer: write
`order`, `instantActions`, `zoneSet`, `responses`; read `uagv/+/<manufacturer>/#`; nothing under
`actunode/#`. `@` cannot appear in a robot login (`<manufacturer>.<serial>`), so the two cannot collide.
nginx sends a strict Content-Security-Policy on the UI (own scripts only, `frame-ancestors 'none'`),
`X-Frame-Options DENY`, `nosniff`, `no-referrer` everywhere, and hides its version; no HSTS (it is per host
name and would break the plain local port). `engine-strict` for npm. docs/USE_CASES.md describes each user's
path and what works today.
**Consequences.** Week 11's prerequisite is done: an outside fleet manager drives the simulated robots (e2e
in all three configurations). Open, for the decision point: recording a site's own broker (bridge or
capture import), injecting "timeouts" and "duplicate missions" (named in the plan, not built), and replaying
an incident against a connected fleet manager (possible, untested).

## D-48 · Week 11: testing a fleet manager (example, scenario), UNRESPONSIVE, replay with current time
14 Oct 2026 · Accepted (founder: "go ahead" on the audit recommendations)

**Context.** Week 11: a scenario that answers the plan's question "after a blocked path, does the system
cancel, reroute or escalate?" about an outside fleet manager (D-47 gave it a login). The audit follow-up
recommended folding in two gaps: the plan's "timeouts" failure, and replayed messages carrying old timestamps.
**Decision.** (1) `examples/fleet_manager/`: a minimal fleet manager (VDA 5050 over MQTT only, its own
`master@` login) whose reaction to `pathBlocked` is a choice (`cancel`, `reroute`, `escalate`, `ignore`), and
`blocked_path_reaction.yaml`, which blocks the robot it drives and expects, within 10 s, a cancelOrder, a new
order or a startPause. A `message` condition may be a list meaning "any of these". The block is detected
from the robot's state message, not a status poll: a quick fleet manager clears it faster than the runner
polls. A `never` counts messages from its own start ("during the next N s"); an `expect` still from the
previous step's start. Cleanup does not "clear" a block that is already over. (2) `UNRESPONSIVE`
(`duration_s`): the robot stays connected (no last will) but sends no state and drops orders and instant
actions, while it keeps driving; it ends by itself. (3) Replay `current_time`: each message's `timestamp`
is set when it is sent again; payloads that are not JSON objects are replayed unchanged.
**Consequences.** With the example: cancel, reroute and escalate pass, ignore fails, on the real stack (e2e
in three configurations). Building the example found three classic fleet-manager bugs worth testing
customers for: sending an order twice before the robot confirms the first, reusing order ids after a
restart (the robot takes them as updates of an old order), and pausing a robot without ever resuming it.
Escalation by e-mail or dashboard is invisible to ActuNode; the scenario documents that.

## D-49 · Week 12: scenarios in CI (a Docker runner), and importing a site capture
14 Oct 2026 · Accepted

**Context.** Week 12: scenarios in CI, a Docker-based runner and a GitHub Actions example, ActuNode's own CI
running the sample scenarios. Also the audit's recommended way to bring a site's traffic in (D-47).
**Decision.** (1) `cli/Dockerfile` and a `runner` service in the `test` profile (`docker compose run --rm
runner test scenarios/`). It shares the frontend's network namespace, so it reaches the lab as
`http://localhost`, an allowed host name: no extra host names (D-24), no ports. It gets only the web login
token (one file of the secrets volume, as `ACTUNODE_TOKEN_FILE`), not the backend's MQTT password. It runs as
`ACTUNODE_UID:ACTUNODE_GID`; scenarios from `ACTUNODE_SCENARIOS`, reports to `ACTUNODE_RESULTS`.
(2) A CI job `scenarios` (VDA 2.1 and 3.0) does what a user does: the sample scenarios, then a `master@` login
for the example fleet manager and the blocked-path reaction scenario; JUnit reports, recordings and logs are
artifacts, counts in the job summary. `examples/ci/github-actions.yml` is the same steps for a customer's
repository, with two marked steps to replace, so the template is tested on every change. (3) `actunode
import`: a `mosquitto_sub -F '%U %t %p'` capture becomes a session file (the recorder's record format and
payload rules, copied, not imported), streamed; unreadable lines are skipped and listed. A file, not a live
bridge: offline, read-only, nobody needs access to the customer's network.
**Consequences.** A customer's CI can run their scenarios against the lab with five steps. A site incident
can be validated and replayed (also to a fleet manager) from a capture. The upload assigns its own session
id; the one the import writes is only a default. A live bridge stays open until a user asks for it.

## D-50 · Full audit of weeks 0–12: every component validates its own inputs; limits everywhere
14 Oct 2026 · Accepted (founder: review every line as system, frontend, backend, security, attacker, DevOps
and architecture engineers)

**Context.** Six independent reviews, every line in scope, each finding reproduced or traced
(docs/AUDIT_2026-10-14.md): about 95 findings, 13 High. Most Highs were one pattern: untrusted content valid
at one layer and trusted at the next (overflowing numbers, control characters in topics, wrong value kinds
in robot state, malformed order graphs) and floods with no bound (broker retained messages, simulator inbox,
WebSocket feeds, parsed-object memory).
**Decision.** Every component validates at its own boundary, whatever the previous one did, and every queue,
buffer and file has a bound. Concretely: strict JSON numbers everywhere (no NaN, Infinity or overflowing
integers in, `allow_nan=False` out); a cap of 10,000 values per message (rule `too-many-values`) and text
previews above 2,000; snapshot lines of session files at most 8 MB, robots checked one by one; topics from
files published only when every level is a valid identity (one pattern module, `fullmatch`); replay reads
off the event loop and yields every 10 ms; at most 50 live feeds of 8 MB queue each; the simulator's inbox
bounded, its work per tick budgeted, order graphs validated; the broker with memory, queue and connection
limits and explicit version levels in the ACL; containers without capabilities, read-only, with memory and
process limits; a name-constrained CA; login removal, rotation, backup and restore with a live reload
(SIGHUP); the network listener without internal logins; AEAD-only TLS; strict CSP and typed readers in the
UI; CI actions pinned to commits with least privilege and Dependabot. API docs pinned and off in shared mode.
**Consequences.** Each fix has a test that fails on the old code (backend 463 → 576, simulator 397 → 465,
runner 148 → 220, frontend 99 → 137). Behaviour changes users may notice: 2.1 orders need edge
`startNodeId`/`endNodeId` and `released` (the schema always required them); pick/drop on edges and orders
for an unknown map are refused; uploads need line 2 to be the snapshot; `/api/health` without a session in
login mode says only whether the lab is up; adding a robot or fleet manager login is applied with
`docker compose kill -s HUP mosquitto` (no disconnects). Open: per-user identity and an audit trail
(A3), metrics (A6), versioned scenario format and API, published images (A5, A7).

## D-51 · Week 13: a real ROS 2 robot stack behind InOrbit's open-source VDA 5050 connector
15 Oct 2026 · Accepted

**Context.** Week 13: a ROS 2 simulated robot (Nav2, headless) behind the open-source VDA 5050 connector, as an
optional Docker profile; ActuNode sends it a mission and validates its traffic. Research: InOrbit's
`vda5050_connector` is the maintained ROS 2 connector (VDA 5050 2.0, ROS 2 Humble, BSD-3), with a Python Nav2
adapter for TurtleBot3; TUM's targets VDA 5050 1.1 and ROS 1. Nav2's light loopback simulator exists only from
Jazzy.
**Decision.** Humble (the connector's distribution) with `turtlebot3_fake_node` (odometry only, no physics,
headless), Nav2 on a map generated from ActuNode's warehouse (`ros2/make_map.py`, tested against
`warehouse.py`), no AMCL (static start pose), costmaps from the static map. The connector and adapter are built
from pinned commits, not vendored. The robot logs in like a real robot over TLS (its own login `ROS2.nav2_01`,
created by `mqtt-init`, readable only by the robot; the CA certificate published world-readable as
`public/ca.crt`). Optional `ros2` profile; a weekly CI workflow and an opt-in e2e test. ActuNode gained optional
`theta` (heading) on missions, and puts the robot's own heading on the start node: legitimate for a master
control, and needed because the connector drops orders without headings.
**Consequences.** ActuNode drives a real ROS 2 stack: it plans around the racks and reaches the node. The lab
found eight deviations in the connector (docs/research/ROS2_CONNECTOR.md), among them an order dropped without
error and a node reported reached when navigation failed: Week 14 turns them into the conformance report and
upstream reports. The image is not in the weekly security scan (a large ROS base image; optional, local only).

## D-52 · Week 14: a VDA 5050 conformance suite, the connector's report, upstream drafts, the robot guide
15 Oct 2026 · Accepted

**Context.** Week 14: the scenarios run against the ROS 2 robot, a conformance report of what passes and fails,
upstream reports where the connector deviates, a "connect your own robot" guide. The sample scenarios rely on
ActuNode-only features (failure injection, `missionStatus`), which a real robot does not have.
**Decision.** A separate suite, `conformance/vda5050-2/`: nine scenarios using only plain VDA 5050 behaviour
(connection, order, the robot's own state messages, the validator's per-message verdict), so it runs against any
2.x robot; the robot is named in each file's header and replaced with `sed`. Scenario checks gained `rule:` on
`message` (a message the validator flagged with that rule: a per-robot verdict) and `theta` on `send_mission`.
Orders the mission sender would never build go through `conformance/raw_checks.py` with a fleet manager login.
Every result in the report cites the VDA 5050 2.1.0 text (fetched from the VDA's repository); claims were
corrected where the spec allows the behaviour (cancel at the next node) or the rule is 2.1-only (map check).
Upstream reports are drafts: filing them is the founder's call. The opt-in ROS 2 e2e test runs the suite and
fails if any result changes, so the report cannot go stale silently.
**Consequences.** Against InOrbit's connector: 4 of 9 checks pass; failures: schema-invalid state (empty
`operatingMode`), `positionInitialized` false, orders without headings dropped silently, `driving` always false;
raw checks: an unreachable node reported reached with no error. docs/CONFORMANCE_ROS2_CONNECTOR.md,
docs/research/upstream/, docs/CONNECT_YOUR_ROBOT.md.

## D-53 · Week 15: developer credibility from the lab's own evidence
16 Oct 2026 · Accepted

**Context.** Week 15: a failure-case catalogue, a scenario gallery, message-flow walkthroughs, and two blog post
drafts for the founder (plan milestone 1, "developer credibility").
**Decision.** Everything is built from evidence the lab produced, not from general claims: the message flows from
recorded sessions (timings, ids and header ids as recorded), catalogue entries only where the lab can reproduce or
detect the failure (open ones marked open: duplicate missions, WMS assumptions), failures "seen in the wild" only
where this project found them. The gallery is kept complete by a test. The blog drafts stay private
(`docs/company/`, not in git): the founder edits and publishes them, the conformance post after the upstream issues
are filed and the maintainers have had time to respond.
**Consequences.** docs/FAILURE_CATALOGUE.md, docs/SCENARIO_GALLERY.md, docs/MESSAGE_FLOWS.md (Mermaid diagrams,
rendered by GitHub); two drafts in docs/company/blog-drafts/.

## D-54 · Week 16: onboarding, a compatibility promise, a triage routine, v0.2.0
16 Oct 2026 · Accepted (founder: "continue and work on it")

**Context.** Week 16, the last of Phase 2: an onboarding path from the README to a first passing scenario, an
issue triage routine, release v0.2.0. The architecture review (D-50, A5) asked for a versioned scenario format and
a written API compatibility promise before outside users depend on them.
**Decision.** Getting started needs only Docker: the lab, then the runner container on a sample scenario, then a
deliberately failing copy, then a next step per kind of user; it is verified by following it from a fresh clone.
docs/COMPATIBILITY.md promises scenario format 1, session format 1, the `actunode test` command (options, exit
codes, JUnit), topics and logins; the HTTP API is kept compatible with breaks announced a release ahead; ActuNode's
extension fields, the UI and the WebSocket events are not promised. Scenario files may say `version: 1` (strict
integer); a runner refuses a later version. docs/TRIAGE.md: a reproducing file first (session, scenario, capture),
labels, a 3-working-day first response, reproduce before fixing, a test with every fix, conformance questions
answered with the spec's text. Version 0.2.0 everywhere (backend, frontend, runner); tag `v0.2.0` on the verified
commit; the CI template pins `ref: v0.2.0`.
**Consequences.** Outside users have a supported path and know what will not break under them. Publishing
container images is not part of 0.2.0 (users build locally, as before): it waits until a user asks.


## D-55 · Fix the ROS 2 robot's conformance failures as optional patches, proposed upstream
16 Oct 2026 · Accepted (founder: "can't we fix it", then "yeah")

**Context.** The Week 14 report (D-52) measured InOrbit's connector at 4/9 scenarios and 0/3 raw checks. Locating
each failure in the code showed that most are in the *example* TurtleBot3 adapter, not the connector: the adapter
never fills `operatingMode`, `positionInitialized`, `driving` or the battery, and reports every Nav2 goal as
succeeded (the connector's own failure handling is correct but never triggered). Only the mandatory `theta` and the
missing map check are in the connector. None of it was our configuration.
**Decision.** Patches in `ros2/patches/` (adapter: real navigation result and the four state fields; connector:
`theta` optional, and an opt-in `known_map_ids` check that rejects orders on other maps, VDA 5050 2.1 §6.7.1; undecodable orders
rejected with `validationError`; the refused-login `TypeError`), applied only when the build argument `ACTUNODE_ROS2_PATCHES=1` is set. The default build stays
exactly as pinned, so the published measurements remain reproducible; the weekly ROS 2 workflow runs both variants
(unpatched: the report's known failures; patched: all nine scenarios). The upstream drafts become five pull requests, one
per patch, each applying on its own to the current upstream branch; the founder approved opening them ("explicit
yes") and opened them on 17 Oct: ros_amr_interop #82–#85, vda5050_adapter_examples #14 (the browser form
failed with "must be a collaborator"; `gh pr create` worked). The report and the drafts name the adapter where it is the cause. `conformance/raw_checks.py` now
cancels open orders before and after and counts only errors raised during the run: an open order left by the
previous check had made the unknown-map check pass by accident.
**Consequences.** With the patches: 9/9 scenarios and 4/4 raw checks (a fourth was added: an undecodable order must
be rejected with an error), on repeated runs. Testing the map check found
one more connector bug, fixed in the same patch: validation rejections were typed `validationOrder`, not
`validationError`. Filing the PRs and issues is public and
remains the founder's decision. If upstream merges them, the pins move and the patches are deleted.


## D-56 · Per-person web logins, two roles, and an audit trail
17 Oct 2026 · Accepted (founder: "let's go"; chose two roles and an Activity panel)

**Context.** Audit item A3 (D-50): a shared lab had one web token for everyone, so sessions were anonymous and
nothing recorded who injected a failure, sent a mission or deleted a recording.
**Decision.** Each person gets a token from `mqtt-init add-user <name> operator|viewer`; it is printed once and
only its SHA-256 is kept (`secrets/users/`, root only). mqtt-init rebuilds `backend/users` (`name:role:sha256`) on
every run; the backend re-reads it when it changes, so adding, removing, rotating or re-roling a user needs no
restart, and a session whose user was removed or got a new token ends at its next request (the live feed within
5 s). Login stays one field: the token identifies the person; every credential is compared each time. The shared
API token remains and logs in as `admin`, an operator (D-25 setups, the CLI and CI keep working); `admin` and
`local` cannot be user names. Roles: *viewer* may use safe methods, validate recordings and log out; anything else
is 403 "Viewers cannot change the lab" (enforced in SessionGuard, so a new route is covered by default).
*operator* may do everything. The audit trail is a middleware: every state-changing /api request by a known user
is recorded after it ran (user, role, client address, action, path, status, plus details routes add: robot,
failure, destination, order, session); logins, failed logins and logouts too. JSON lines in `.audit.jsonl` next
to the recordings (not a session id: listing and retention skip it), rotated once at 10 MB; the newest 2,000
entries in memory for `GET /api/audit` and the UI's Activity panel. Login off: user `local`, an operator.
**Consequences.** A shared lab knows who did what, and can give people look-only access. Requests without a
session are not recorded (they did nothing); the client address is the one nginx saw. Not in scope: SSO, and an
audit trail protected against its own operators (the file is on the lab's disk).


## D-57 · Metrics in the Prometheus text format
17 Oct 2026 · Accepted (founder: "let's work on the rest")

**Context.** Audit item A6 (D-50): observability was logs only; nothing measured broker memory, queue depth, live
feeds or dropped messages, so a flood was noticed by its effects.
**Decision.** `GET /api/metrics`, Prometheus text format 0.0.4, written by hand (a few lines; no client library).
Counters are incremented where things happen: messages received, rejected by rule, validation issues by rule
(independent of the UI's reset), live feeds dropped (lagging, too many), broker disconnects, failed publishes
(too large, failed), message-handler errors. Gauges are read at scrape time: uptime, broker connection, live
feeds and the largest backlog, robots by connection state, recording and its size, replay, stored sessions and
their disk use (the folder scan cached 30 s). The broker's statistics come from Mosquitto's `$SYS/broker/#` (heap,
clients, stored, received, sent, dropped): the backend's broker login may now read them (ACL), and they are routed
to the metrics before the robot pipeline, so they are never shown, recorded or validated. The path needs a session
like every other, or `Authorization: Bearer <token>` with any web login's token, because a scraper cannot keep a
cookie; only this path accepts it, and wrong tokens count towards the same per-client limit as logins. A scrape is
a GET, so it is not in the audit trail.
**Consequences.** An operator can graph and alert on the lab's load; the load test's limits (D-38) become visible
in production. Metric names may still change in 0.x (COMPATIBILITY.md); a change is in the changelog.


## D-58 · Published images
17 Oct 2026 · Accepted (founder: "let's work on the rest"; reverses the deferral in D-54)

**Context.** Audit item A7 (D-50): every user built the images locally (minutes on a first start, more on a
small machine); D-54 deferred publishing until a user asked.
**Decision.** `.github/workflows/images.yml` runs on `v*` tags: the backend, simulator, frontend and runner images
(the services ActuNode builds; the ROS 2 robot stays local, it is optional and large), for linux/amd64 and
linux/arm64, pushed to `ghcr.io/<owner>/actunode-<name>` tagged `<version>` and `<major>.<minor>`, with
provenance (mode=max), an SBOM, and a GitHub build-provenance attestation pushed to the registry. Started by hand
it builds both architectures without pushing. Actions are pinned by commit, like the other workflows; the job
has `packages: write` only for this. Compose gives each built service an `image:` from `ACTUNODE_IMAGES` and
`ACTUNODE_VERSION` (default `actunode-<name>:local`) and `pull_policy: ${ACTUNODE_PULL_POLICY:-build}`, so
nothing changes unless a user opts in. The images take no build arguments (user ids are set at run time), so
one image serves everyone.
**Consequences.** A release can be run without building. The first push creates the packages on GitHub as
private: the founder makes each public once (package settings), and the release checklist says so. A release is
now also a supply chain: the workflow, its pinned actions and the base images are reviewed like code.


## D-59 · Scenario validation checks for one robot
17 Oct 2026 · Accepted (founder: "do both one by one")

**Context.** `validation: {no_errors: true}` counts the lab's validator totals, so in a shared lab any robot's
broken traffic fails every scenario that checks it. Found running the sample scenario next to the unpatched ROS 2
robot (D-55): 9 schema errors, all from `nav2_01`, failed `p1042_blocked_path`.
**Decision.** An optional `robot:` on the validation check (format 1 allows new optional fields, D-54): issues
are then counted on that robot's own messages (topic level 4, any VDA version and manufacturer) from the live
feed, since the scenario (or the `never`) started; failures name the robot. Without it, behaviour is unchanged.
The shipped scenarios that check for no errors name their robot.
**Consequences.** Scenarios hold in a lab shared with other robots. The live feed is opened for such a step, and
counts what the runner saw (its buffer holds 50,000 messages).


## D-60 · Keyboard: skip links and one Tab stop per long region
19 Oct 2026 · Accepted (founder: "go head")

**Context.** The accessibility review (package I) found that the session table added four Tab stops per saved
session (Replay, Validate, Download, Delete) and the message stream one per message: on a lab with 100+ sessions,
reaching the message stream took hundreds of Tab presses.
**Decision.** Two skip links are the first Tab stops (Sessions, Message stream; off screen until focused). Long
regions are one Tab stop each with a roving tab index: the message stream (rows are disclosure buttons, up/down,
Home/End) and the session actions (a grid: left/right within a session, up/down between sessions, Home/End;
disabled actions are skipped, so a viewer moves through Validate and Download only). The session table's roving
index is kept on the DOM (data attributes), so its buttons need no extra props.
**Consequences.** The page is about 25 Tab stops regardless of how many sessions or messages there are (measured).
Screen-reader behaviour of the patterns is still to be checked with a real screen reader.


## D-61 · A hosted service on actunode.com: one isolated lab per workspace
19 Oct 2026 · Accepted (founder: "I wanna go into shared online service", domain actunode.com; Hetzner, EU first;
GitHub and Google sign-in; billing after the beta)

**Context.** ActuNode was self-hosted only; the PRD listed hosted multitenancy and billing as out of scope. The
founder chose a shared online service. The backend deliberately holds one lab per process (TRD), and customer data
(site captures, recordings) must never cross between customers.
**Decision.** A control plane at app.actunode.com (sign-in with GitHub or Google, workspaces, members with owner,
operator or viewer, invitations, an invite-only allow list) and one isolated lab per workspace at
<workspace>.actunode.com, built from the published images (D-58) as its own Compose project and network. A Traefik
edge terminates TLS with a wildcard certificate and routes HTTPS by host name and MQTT (8883) by SNI. A separate
provisioner is the only component that starts containers, through a restricted Docker socket proxy. The lab gets a
single sign-on mode: a 60-second, single-use token signed with the workspace's own key opens a normal lab session
for that person and role. Hetzner Cloud, EU region first; SQLite for the beta control plane. Billing in phase 3.
Details: docs/HOSTED_SERVICE.md.
**Consequences.** Self-hosting stays first-class (same images). The hosted service reuses the lab unchanged except
for SSO; isolation comes from containers and networks, not from rewriting the backend for tenants. New risks: an
internet-facing service (security review before outside users), customer data (terms, privacy, deletion), and
operations (monitoring, backups, upgrades), all phase 2 gates.

## D-62 · Running the hosted service: idle labs, in-place upgrades, backups on the server, webhook alerts
20 Oct 2026 · Accepted (phase 2 of D-61, built before the founder's accounts exist)

**Context.** One server holds many workspace labs (D-61). Every lab costs memory whether anyone uses it; an upgrade
must reach every lab; Hetzner's server backups cover the root disk only, not the attached data volume that holds the
workspace folders; nobody is watching the server.
**Decision.** (1) **Idle labs stop**: the lab reports its idle time (people, external robots and fleet managers, and
commands count; its own simulator does not) to a single-use status token signed with the workspace's key; the control
plane stops a lab idle for 30 min and wakes it when a member opens it (an atomic state change; a stopped lab's own
address falls back to the wake page at the edge). (2) **Upgrades in place**: the provisioner re-renders every lab at
the current release and recreates the running ones; stopped labs upgrade at their next wake; the deploy scripts do it
at the end. (3) **Backups**: a daily archive on the server (the control database by SQLite's online backup, every
lab's secrets volume, the workspace folders, secrets and settings), 14 kept, with an optional off-site copy by rclone
to storage the founder chooses; `restore.sh` rebuilds a host from one; `restore-drill.sh` proves it locally and runs
after every change to these scripts. (4) **Alerts**: a 5-minute health check (app, certificate, containers, disk,
backup age, lab containers) posting to a webhook when the set of failures changes; an outside uptime monitor is still
the founder's. (5) **Abuse limits** at the edge per client address, 50 logins per workspace; (6) **account deletion**
takes sole-owned workspaces with it and retires the handle.
**Consequences.** A stopped lab takes no robot connections until opened; a connected robot keeps its lab awake. An
upgrade interrupts each running lab for a few seconds and ends its lab sessions. Backups live on the same server until
the off-site copy is configured (a phase 2 gate for outside users, with the security review). The idle timer resets
when a lab restarts.
