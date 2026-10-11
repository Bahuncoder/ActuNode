# ActuNode progress

**The single place that says where the project is.** Update it at the end of every work session:
the status line, the schedule table, the session log, and the open issues.

- The plan itself (what to build and when) lives in [PLAN.md](PLAN.md) and does not change.
- Why things were built the way they were: [DECISIONS.md](DECISIONS.md).
- How the system fits together: [ARCHITECTURE.md](ARCHITECTURE.md).
- What changed in each commit: [CHANGELOG.md](../CHANGELOG.md).

## Where we are

| | |
|---|---|
| **Calendar** | Week 1 of 8 (Fri 9 Oct – Thu 15 Oct 2026) |
| **Last updated** | Sun 11 Oct 2026 |
| **Status** | Ahead on features, catching up on verification. The Docker stack now runs the full definition-of-done scenario end to end; there are still no end-to-end tests in CI. |
| **Working rule** | Follow the calendar. Being ahead is not a reason to start the next week's features: spare time goes into hardening, verification, documentation and user conversations. |

## Schedule

Week 1 started on Friday 9 October 2026 (Day 1). Each week runs Friday to Thursday.

| Week | Dates | Plan objective | Plan output | Feature state | Quality state |
|---|---|---|---|---|---|
| **1** | 9–15 Oct | VDA 5050 concepts, MQTT topics, AMR state machines | Notes + message schemas + Docker Mosquitto | ✅ Done | ✅ Docker stack verified end to end (10 Oct) |
| 2 | 16–22 Oct | One fake AMR with battery, pose, state | Robot publishes status every second | ✅ Built early (Day 2) | ✅ Hardened 10 Oct: E2E tests in CI, battery-at-0 fixed |
| 3 | 23–29 Oct | Mission sender + state transitions | Move job from start to destination | ✅ Built early (Day 3) | 🟡 No order updates, no cancel |
| 4 | 30 Oct – 5 Nov | 5–10 robots + simple warehouse map | Multi-robot screen with location/state | ✅ Built early (Day 4, 10 Oct) | 🟡 Not load-tested beyond 10 robots; no collision avoidance |
| 5 | 6–12 Nov | Message inspector + validation | Readable message stream + errors | ✅ Built early (Day 4, 10 Oct) | 🟡 Schemas are a hand-written subset; not compared with official ones |
| 6 | 13–19 Nov | Failure injection | Blocked path, low battery, disconnect, invalid payload | 🟡 1 of 4 (blocked path, Day 5) | ⬜ |
| 7 | 20–26 Nov | Record/replay | Session file can reproduce incident | ✅ Built early (Days 6–7) | 🟡 No size limits; whole file loaded for replay |
| 8 | 27 Nov – 3 Dec | Demo + README + 3-minute video | GitHub repo + pitch demo | 🟡 README + demo script written | ⬜ Video not recorded |

Legend: ✅ done · 🟡 partly done / known gaps · ⬜ not started

### How the 7-day sprint maps onto the 8 weeks

The plan has two schedules. *"What to build this week"* (Days 1–7) is a fast start that touches most of
the 8-week plan; the 8-week plan is the full roadmap. All of Days 1–7 were built in one session on
9 October.

| Sprint day | Built | Counts towards |
|---|---|---|
| Day 1 | Repo, Docker Compose + Mosquitto, FastAPI, React | Week 1 (Mosquitto) |
| Day 2 | Simulated robot publishing VDA 5050 state every second | Week 2 |
| Day 3 | Mission sender, `IDLE → ACCEPTED → MOVING → COMPLETED` | Week 3 |
| Day 4 | Robots on a map, raw MQTT message stream | Weeks 4 and 5 (first parts) |
| Day 5 | `BLOCKED_PATH` failure | Week 6 (1 of 4 failures) |
| Days 6–7 | Record to JSONL, replay | Week 7 |
| 10 Oct | 10 robots; validator, schemas, VDA 5050 notes | Weeks 4, 5, 1 (rest) |

## Week 2 (16–22 Oct): hardening, started early on 10 Oct

Plan objective: one fake AMR with battery, pose and state; status every second. The feature exists
since Day 2; this week makes it verified and correct (allowed early under D-11: no new features).

- [x] End-to-end tests against the real Docker stack, in CI (D-16); stable over 3 consecutive runs
- [x] Objective verified automatically: state every ~1 s, consecutive `headerId`s
- [x] Reconnect behaviour: robots and backend recover after a broker restart; killed simulator → CONNECTIONBROKEN
- [x] Fix battery at 0 % mid-mission: FAILED + FATAL `batteryEmpty`, orders rejected (issue 4, D-17)

## This week (Week 1, 9–15 Oct)

Plan objective is done. Remaining work for this week is verification and documentation, not features.

- [x] VDA 5050 notes ([VDA5050_NOTES.md](VDA5050_NOTES.md))
- [x] Message schemas ([backend/app/schemas](../backend/app/schemas))
- [x] Mosquitto in Docker Compose (config written)
- [x] Project documentation: progress, architecture, decisions, changelog
- [x] **Run the Docker Compose stack end to end**: definition of done passed on 10 Oct (record → mission → block → clear → replay, UI via nginx)
- [ ] Confirm `curl localhost:8000/api/health` works from a normal terminal (open issue 15)
- [x] Confirm the Day 1–5 CI compose failures are understood (issue 3: transient runner problem, closed 11 Oct)
- [x] Read the VDA 5050 3.0 release notes and record what changes for us ([research note](research/VDA5050_3_0.md), D-15)
- [x] Python linter and formatter (ruff, 120 columns) in CI (issue 16, D-14)
- [x] Customer discovery kit: [outreach messages](discovery/OUTREACH.md), [interview guide](discovery/INTERVIEW_GUIDE.md), private tracker
- [ ] Customer discovery: first outreach messages sent (plan: 30 conversations in 60 days)

Proposed focus for the coming weeks (each week's plan objective + hardening of what was built early):

| Week | Proposed engineering focus |
|---|---|
| 2 | End-to-end tests against real Mosquitto in CI (broker as a service container); fix battery-at-0; reconnect behaviour |
| 3 | `instantActions` cancelOrder (the "cancel" in *cancel, reroute or escalate*); order updates (`orderUpdateId`) |
| 4 | Load test 10/25/50 robots (CPU, message rate, UI frame rate); decide whether to model traffic/near-collisions |
| 5 | Version-aware validation with the official 2.1.0 and 3.0.0 schemas, chosen by topic (D-15); offline validation of session files |
| 6 | Remaining failures: low battery, disconnect, invalid payload, timeouts; simulator safety stops (`fieldViolation`) when a robot is in the path (D-22) |
| 7 | Session size limits and retention; upload a session someone sent you; streaming replay |
| 8 | Record the demo video ([DEMO.md](DEMO.md)); polish README; publish |

## Customer discovery

Target from the plan: **30 conversations in 60 days** (by 8 Dec 2026), about 5 a week. Names and
notes stay in the private tracker `docs/company/discovery_tracker.csv` (not in git); only counts and
anonymised learnings go here.

| Week | Messages sent | Replies | Conversations | Total conversations |
|---|---|---|---|---|
| 1 (9–15 Oct) | 0 | 0 | 0 | 0 / 30 |

**Learnings so far:** none yet. After every 5 conversations, add a summary of repeated pain points
to the session log.

## Verification status

What has actually been checked, and how. "Unit" = automated tests; "E2E" = the running system
exercised by hand with a real browser and MQTT traffic.

| Area | How it was verified | Gaps |
|---|---|---|
| Backend API | 66 unit/API tests (pytest), run in CI, including a shutdown test under a real uvicorn server | |
| Simulator | 34 unit tests (pytest), run in CI | |
| Python style | `ruff check` + `ruff format --check` in CI (backend, simulator) | |
| Frontend | Type check, lint, 10 unit/component tests (`npm test`, incl. malformed robot data) and production build, in CI | No real-browser tests (issue 6) |
| MQTT flow | Automated against Mosquitto in Docker (`tests/e2e`) | |
| Shutdown | Automated in `tests/e2e` (broker first, then backend; recording gets its end line) and `backend/tests/test_shutdown.py` | |
| Docker stack, end to end | **Automated** (`tests/e2e`, in CI): health, state every second, mission state machine, BLOCKED_PATH, validation clean, record/replay, last will on kill, broker restart recovery, shutdown with open recording | No frontend/browser tests |
| P-1042 scenario (mission → block → clear → complete) | E2E, several times | |
| Record → replay | E2E; replay timing matched the recording within ~25 ms at 5× | |
| Validator | Official VDA 5050 2.1.0 schemas (D-20); real and generated messages in every mission state pass them; planted bad messages flagged; e2e: all live traffic clean | 3.0 not supported (issue 8) |
| 10 robots, 6 concurrent missions | E2E screenshot | No load test |

## Open issues and technical debt

Numbered so they can be referenced from commits. Remove an item only when it is fixed and verified; numbers are never reused (fixed: 1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18).

| # | Issue | Impact | Plan |
|---|---|---|---|
| 6 | No real-browser tests (component and logic tests exist since D-19, but run in jsdom, not a browser) | Browser-only issues (layout, WebSocket in a real browser) are caught by hand | Add Playwright tests against the e2e stack |
| 19 | The live robot list is keyed by serial number only: robots with the same serial under different manufacturers or versions share one entry in the UI | Confusing display in mixed fleets with colliding serials (missions are safe since the ambiguity check) | Key robots by (version, manufacturer, serial) in hub and UI |

## Session log

Newest first. One entry per work session: what was done, what was learned, what is next.

### Sat 10 Oct 2026: working through open issues one by one

### Sun 11 Oct 2026: issue 12 part A, MQTT logins

- Broker: no anonymous clients; logins for backend, tools (read only), healthcheck and one per robot
  (serial = username); ACL lets a robot publish only its own topics (D-23). `mqtt-init` generates
  passwords into a Docker volume; each service mounts only its own subfolder, owned by its user, 0400
  (checked: simulator cannot read the backend password).
- Verified against the real broker: anonymous, wrong password and crossed passwords refused; tools
  reads but its publish is dropped; robot_01 cannot publish as robot_02, order it or inject into it; its
  own state arrives. `add-robot` for real robots works (invalid serials refused, exit 2). Found and
  fixed in the init script: noisy output burying the new login. Passwords stable across restarts.
- E2E suite logs in as `tools`; 3 permanent security tests; 14/14 for VDA 2.1 and 3.0.
- **Part B (D-24).** Demonstrated first on the running stack: DNS rebinding served (200), a cross-site
  WebSocket streamed 34 KB of live data, a cross-site POST started a recording (201). Added Host and
  Origin checks for HTTP and WebSocket; now 400/403/403 and the UI unaffected (browser check, 0 console
  errors). Found and fixed on the way: two recordings started in the same second got the same session
  id (409); and my own new test wrote into the real `sessions/` folder (two files removed, test fixed).
  Backend 124 tests; e2e 15/15 for 2.1 and 3.0.
- **Part C1 (D-25): web login for shared use.** Token → HttpOnly SameSite=Strict session cookie (12 h,
  memory), rate limit 5 failures/min per client, interlock: backend refuses to start with a non-loopback
  bind and no login (verified on a container). UI login screen, Log out. E2E runs in login mode when
  reaching the stack over the network; CI adds a VDA 2 + login job; new test: nothing works without a
  session. Found on the way: sessions end when the backend restarts, so the e2e harness logs in again
  after restarts; a missing explicit import in my own test. Browser check: local mode opens the lab,
  login mode shows only the login screen. Backend 136, frontend 24, e2e 16/16 for 2.1 and 3.0 (twice
  for 3.0).
- **Part C2 (D-26): TLS. Issue 12 closed.** One rule: plain ports never leave the computer (8080, 8000,
  1883, 9001 on 127.0.0.1); HTTPS 8443 and MQTT/TLS 8883 follow the bind address. `cert-init` makes a
  local CA and a server certificate for localhost and the allowed hosts (checked: SANs, chain, key
  permissions, idempotent). Verified in shared mode over the LAN: everything over HTTPS/MQTTS against
  the CA, plain ports unreachable from the network, clients not trusting the CA refused in the TLS
  handshake. Local stack: HTTP and HTTPS both serve the lab; backend and simulator reconnected on their
  own after the broker restart. E2E 18/18 for 2.1 and 3.0.
- **#17 closed: already reported upstream.** Before drafting a report, checked upstream: all three files
  are valid JSON on VDA5050 `main` (order.schema fixed in c7f4c15, 17 Jun 2026), there is no patch
  release yet, and the exact problem is already open as VDA5050/VDA5050#660. A duplicate report would
  add noise; our copy stays pinned to the 3.0.0 tag with the documented 7-comma fix until a fixed release
  appears. Exact lines recorded in `backend/app/schemas/README.md`.
- **#15 closed: root cause found, not ActuNode and not the sandbox.** The founder's own terminal also
  hung on `localhost:8000`, so it was real. Probing showed this computer could reach container port 80
  directly but not 8000 or 1883, while other containers and the LAN path could. The kernel log showed
  `[UFW BLOCK] OUT=br-… SRC=172.18.0.1 DST=… DPT=8000/1883`: the host firewall (ufw) denies outgoing
  connections by default (`DEFAULT_OUTPUT_POLICY="DROP"`), and Docker's loopback forwarding is an
  outgoing connection from the host. Changed in ActuNode: API docs now under `/api/docs` (reachable via
  the UI port); README troubleshooting with the check and a narrow optional ufw rule (system security
  settings are the founder's decision, not changed by the assistant).
- **#3 closed: transient CI runner problem, not the code.** The `compose` job on Days 1–5 (9 Oct,
  21:20–21:42 UTC) failed in `docker compose build` after 1 s, before any image could be pulled or built;
  GitHub's public annotations show only "exit code 1" (full logs need a login). Checked: the workflow
  file is identical in the last failing (aecb40b) and first passing (e019357) commit, and the only
  Compose change in between is the sessions volume. Reproduced locally from clean checkouts of
  5045226, aecb40b and e019357: `docker compose config` passes for all three and aecb40b builds in 18 s.
  Decisive test: pushed the unchanged aecb40b to a temporary branch so GitHub's runners ran it again;
  all four jobs passed, `docker compose build` in 12 s. Same code, same workflow, now green, so the
  failure came from the runner environment at that time. Temporary branch and worktrees deleted.
  Lesson kept: check CI after every push (since Day 6), and re-run an unchanged commit before
  hunting for a code cause.

### Sat 10 Oct 2026 (night, continued)

- **#5 closed by decision D-22: detect near-collisions, never avoid them.** Agreed with the founder:
  stage 1 is the debugging lab; traffic control belongs to the fleet manager under test. Built a
  `ProximityMonitor` (2.1 and 3.0 positions, same map, live robots only, once per incident with 1.2×
  re-arm, offline robots forgotten), wired into the hub as a `proximity` warning, map highlight,
  `GET /api/proximity`, WebSocket event. It immediately found real near-misses in our own e2e scenario
  (robots leaving the parking grid pass within 0.5 m of parked ones), so the "traffic is clean" e2e
  test now means "no protocol issues". Also found a latent **e2e race**: waiting for COMPLETED could
  match a robot's *previous* order; added `run_mission()` that waits for completion of the specific
  order. Backend 108, frontend 20, e2e 11/11 for both 2.1 and 3.0. Week 6 gets simulator safety stops.
- **Fourth security review (mission form, 2 findings), fixed with tests first.** (1) Shown ≠ sent: options
  encoded `manufacturer|version` and the form split on `|`, so a spoofed manufacturer named `Evil|v3` would
  display one target and send to another. Options now map to the identity object itself (not a parsed
  string, and not just a list index, since the list reorders by recency); names the server would reject
  are disabled. (2) Preselecting the single observed identity trusted possibly spoofed data: nothing is
  preselected now; a hint names the observed identities. Frontend 18 tests.
- **Third security review → redesign (D-21).** Two of three findings were visible (the third was cut off in
  the notification): a spoofer outlasting a silent robot still decided routing, and flooding the robot
  list erased the identity evidence. Each fix had opened a new hole because the premise was wrong: an
  anonymous broker cannot prove who sent anything. Orders now go exactly where the request says or to
  the configured default; observations only produce a `warning` and fill the UI's new Target select (a
  person chooses). Found on the way: the mission form could **show one robot and send to another**
  (`robot_01` default kept when absent from the list) — fixed with a test. Backend 101, frontend 16,
  e2e 10/10 with 3.0 robots.
- **Second security review (3 findings on the fix itself), all fixed with tests first.** (1) Naming only
  one of `manufacturer`/`vda_version` bypassed the ambiguity check and defaulted the other: a single
  field now narrows the candidates; 0 or several matches → 409. (2) One spoofed message made a robot
  ambiguous forever (missions refused until restart): identities now carry `lastSeen` and only those
  active in the last 10 s count. (3) No cap: at most 8 identities per robot; the robot list is capped at
  1,000 too. A first version of that cap picked the "longest silent" robot by millisecond timestamps,
  which tie, and evicted the wrong robot in a test; replaced by keeping robots in recency order (O(1),
  deterministic). 104 backend tests, stable over 3 runs.
- **Security review of the #8 commit (2 findings).** (1) Orders were routed by the version/manufacturer a
  serial was *last seen* with, so any MQTT client publishing as `uagv/v3/X/robot_01/state` could silently
  redirect robot_01's orders. Impact limited (broker local-only since D-18; a publisher could command
  robots directly anyway), but silent misrouting is a real correctness bug. Fixed: all identities per
  serial are recorded; with more than one the mission is refused (409) unless the request names
  `manufacturer` and `vda_version` (pattern-validated). Tests first. (2) `headerId` counters keyed by
  topic strings: acknowledged, no change — they are created only for orders ActuNode sends (validated
  robot id, one unambiguous identity), so publishers cannot grow them. New issue #19 (UI keyed by serial).
- **#8 closed (parts C–D).** Orders now go to each robot's own topic version **and manufacturer** (found
  while reading: orders always went to `ActuNode` + `v2`, so a robot of another vendor would never have
  received them); 3.0 orders omit start/end node ids and pass the official 3.0 order schema. Replay
  restores robots on their own version topic (old sessions default to v2). UI reads 3.0 position and
  charge, robot table has a VDA column. E2E suite runs for both versions: 10/10 with 3.0 robots,
  10/10 with 2.1; CI runs both.
- **#8 part B: simulator speaks 3.0.** `--vda-version 3` / `ACTUNODE_VDA_VERSION=3`: v3 topics, version
  3.0.0, 3.0 field names, `CONNECTION_BROKEN`. New permanent conformance test: every message in every
  mission state (IDLE, ACCEPTED, MOVING, BLOCKED, FAILED, 3 connection states) passes the official
  schema of **both** versions. Real-stack check with 3.0 robots: listed as v3, 57 messages validated
  against the official 3.0 schemas, 0 issues.
- **#8 part A: version-aware validation.** Vendored the official 3.0.0 schemas (commit e9ba560). Found
  **three** invalid upstream files, not one (factsheet, order, visualization: 7 trailing commas);
  removed only those (diff-verified); #17 widened. Topic parsing now accepts `v2` and `v3` and the
  validator picks the schema set per message. Found while reading the code: a 3.0 robot was **invisible**
  (not listed, not on the map) because topic parsing accepted only `v2` — fixed, robots record their
  version. 3.0 edges have no start/end node ids, so that check runs only where they exist; battery
  plausibility also reads 3.0 `powerSupply.stateOfCharge`. 3.0 fixtures built and checked against the
  official 3.0 schemas. Unit and e2e tests pass.
- **#7 closed.** Checked first: official 2.1.0 schemas are MIT and set no `additionalProperties`; all of
  ActuNode's messages (4 recorded, 6 generated incl. IDLE/MOVING/BLOCKED/FAILED) pass them. Vendored the
  six schemas unchanged (commit 511d01d, license kept), replaced the hand-written subset; own schemas only
  for the `actunode` extension and inject command. Found: the official schema does **not** bound
  `batteryCharge` (but does bound `batteryHealth`), so 140 % is now a `value-range` *warning*, not a
  schema error (D-20). Validation now covers all six topics (was three). Unit and e2e tests pass.
- **#6 narrowed; #18 found and closed.** Frontend tests: Vitest + React Testing Library, 10 tests for the
  live-data reducer, the defensive readers and components with malformed robot data. Proved the
  regression test works: putting the old unguarded battery read back makes it fail with the original
  `TypeError: battery.toFixed is not a function`. Installing the tools exposed **#18: the frontend ran on
  end-of-life Node.js 20** (last release Mar 2026; Vitest/jsdom need ≥ 22; npm crashed). Moved to
  Node 24 LTS in dev (`.nvmrc`; nvm default untouched), CI and the Docker build stage (verified
  `node -v` = v24.21.0 inside it); e2e passes. #6 now covers only real-browser tests.
- **#11 closed.** Reading the code found four problems, not two: no limit; a write error (disk full)
  logged a traceback per message and silently dropped messages; replay loaded the file twice
  (measured 90 MB peak for a 25 MB file); listing parsed every line of every file. Fixed: size limit
  with end-record `reason` and UI notice; one clean stop on write errors; streaming replay (0.03 MB
  peak); list reads first/last line; delete endpoint + button. Found on the way: the limit setting was
  not passed through Docker Compose (would have been ignored) — fixed and verified in Docker (20 KB
  limit → stopped after 8.5 s, one log line). The INCOMPLETE 13:04 session in `sessions/` is real
  evidence of the shutdown bug fixed earlier (laptop restart while recording).
- **#10 closed: not a defect (verified).** Experiment: orders got headerId 1, 2; after a backend restart the
  next got 1 again, and the validator reported **no** warning (it restarts with the backend), so the
  predicted warning cannot happen. The spec says nothing about restarts; orders are identified by
  orderId/orderUpdateId; robots also restart at 1; an observed decrease is already a `header-id`
  warning. Behaviour documented in VDA5050_NOTES instead of adding persistence.
- **#12 narrowed; real exposure fixed.** Checked: every port was published on all interfaces, and from
  the LAN address an anonymous MQTT client was **accepted** and the API answered. Ports are now
  published on 127.0.0.1 by default (D-18); verified LAN MQTT refused, LAN API unreachable, UI on
  localhost fine; e2e passes (binds only where it connects). Authentication itself stays open (#12).
- **#13 closed (issue was wrong; found a real deviation instead).** VDA 5050 2.1 section 6.2 (and 3.0)
  *requires* QoS 0 for `state`, so a lost state message is by design. Checking every publish/subscribe
  call against the spec showed the opposite problem: the backend sent **orders at QoS 1** and the
  simulator subscribed to them at QoS 1; the spec says QoS 0. Fixed with failing tests first; all unit
  and end-to-end tests pass. Spec rule recorded in VDA5050_NOTES and ARCHITECTURE.
- **#14 closed.** CI annotations showed `actions/checkout@v4`, `setup-python@v5`, `setup-node@v4` running on
  deprecated Node.js 20. Looked up each action's latest release and its `action.yml`: all at v7 on
  Node.js 24, and every input we use still exists. Upgraded (also `upload-artifact` to v7). Runner pinned
  to `ubuntu-24.04` (matches the dev machine) so the Ubuntu 26 switch on 19 Oct happens by choice.

### Sat 10 Oct 2026 (late night): battery at 0 % fixed

- Reproduced issue 4 with failing tests first. Cause: steps were not capped by the remaining battery,
  and nothing changed the status when it hit 0, so the robot stayed MOVING forever.
- Fix (D-17): new mission status FAILED with a FATAL `batteryEmpty` error; robot stops exactly where
  the battery runs out; orders rejected while empty. Validator transitions, schema enum and UI (red)
  updated; tests for each. Issue 4 closed. All Week 2 items done.

### Sat 10 Oct 2026 (late night): Week 2 started early — end-to-end tests

- `tests/e2e`: 10 tests against an isolated copy of the real Docker stack; in CI as the `e2e` job (D-16).
- Compose: health checks, configurable host ports and sessions directory, no fixed container names.
- Three test-design bugs found and fixed while making the suite trustworthy: a timing window that
  miscounted messages; a failing test that left the simulator stopped for the next tests; and a
  "robots are live" check fooled by a replay that had just ended (Docker's event log showed the
  simulator was killed in the same second it was started, before it ever connected).
- Product verified: last will arrives within seconds of a SIGKILL; backend and robots recover after a
  broker restart; recordings close on shutdown.
- MQTT on loopback ports hung from the assistant's shell too (issue 15 updated); the LAN address works.

### Sat 10 Oct 2026 (night): customer discovery kit

- Outreach messages for the plan's five segments, follow-up and thank-you
  ([discovery/OUTREACH.md](discovery/OUTREACH.md)); 15-minute interview guide built on past behaviour,
  with the new VDA 5050 version question ([discovery/INTERVIEW_GUIDE.md](discovery/INTERVIEW_GUIDE.md)).
- Private contact tracker created in `docs/company/` (git-ignored; the repository is public).
- Discovery counters added above. Sending the messages is the founders' job.

### Sat 10 Oct 2026 (night): VDA 5050 3.0 research

- Read the 3.0.0 release notes in full and compared the official 2.1.0 and 3.0.0 `state`, `order`
  and `connection` schemas field by field. Result: [research/VDA5050_3_0.md](research/VDA5050_3_0.md).
- 3.0 is breaking for everything ActuNode emits (position, battery, connection enum, order edges);
  topic layout and header are unchanged.
- Found: the official 3.0.0 `order.schema` is invalid JSON (issue 17).
- Decision D-15: support 2.x and 3.0 side by side, chosen by topic; implement in Week 5.
  Issue 9 closed; issues 7 and 8 now point at the Week 5 plan.
- Customer discovery question added: which VDA 5050 version do your robots speak?

### Sat 10 Oct 2026 (night): Python lint and format

- Added ruff (pinned 0.17.0): pycodestyle, pyflakes, import order, bugbear, pyupgrade; 120 columns
  (D-14). Formatted all Python once; new `lint` job in CI; `.flake8` so editors agree.
- Real findings fixed by hand: five `raise HTTPException` inside `except` without `from` (original
  error hidden from tracebacks); order validator's `zip` made explicitly non-strict, because a wrong
  edge count must be reported, not crash the check.
- All tests unchanged and passing after formatting. Issue 16 closed.

### Sat 10 Oct 2026 (late evening): laptop restart exposed two shutdown bugs

- The laptop restarted (13:25) while the stack ran. Containers stopped in the wrong order (broker
  first) and two exit codes were wrong.
- Found and fixed: **simulator crashed on shutdown** (exit 1) when the broker was already gone:
  publishing OFFLINE raised `RuntimeError`. Now skips/logs it; the broker's last will covers a
  dropped connection. Tests added.
- Found and fixed: **backend hung on shutdown and was killed** (exit 137) when no MQTT traffic
  flowed: the WebSocket handler only noticed a closed socket when sending. Its shutdown cleanup
  never ran, so **an open recording would have lost its end line**. The handler now also waits for
  the close; uvicorn gets a 5 s graceful-shutdown limit as a backstop. Reproduced first with a
  failing test under a real uvicorn server (FastAPI's TestClient hid the bug).
- Verified in Docker with the reboot order (broker first): simulator and backend exit 0 in ~1 s;
  recording closed with its end line. Normal stop: all robots retained OFFLINE.
- Port 8000 still hangs from the assistant's shell in a fresh session (issue 15 stays open).
- New issue 16: no Python linter/formatter configured.

### Sat 10 Oct 2026 (evening): first real Docker run

- `rupert` added to the `docker` group. `docker compose up --build`: all four services start;
  Mosquitto healthy.
- **Definition of done passed under Docker**: record → P-1042 mission → BLOCKED_PATH → clear →
  COMPLETED → stop simulator → replay at 10×; UI and live WebSocket through nginx on :8080;
  182 messages validated, 0 issues. Open issues 1 and 2 closed.
- Found and fixed: **session files were written as root** (backend container ran as root), so the
  user could not delete their own recordings. Backend and simulator images now run as a non-root
  user; Compose runs the backend as the host uid/gid (D-12).
- Found and fixed: **nginx cached the backend's IP**, so recreating the backend container broke the
  UI with 502 until nginx restarted. nginx now re-resolves through Docker's DNS; verified by forcing
  the backend from 172.18.0.4 to 172.18.0.6.
- Found, not yet understood: host loopback port 8000 hangs from the sandboxed shell (issue 15).

### Sat 10 Oct 2026 (later): Docker check

- Docker Engine 29.9.0 and Compose v5.6.0 are installed and the service is active; installed 8 Oct,
  so the Day 1 report "Docker not installed" was wrong. Blocker is permission: `rupert` is not in the
  `docker` group (open issue 1 updated).

### Sat 10 Oct 2026: weeks 4–5 items, documentation

- 10 robots: parking grid, short map labels, `--robots` 1–50 (`99a1df5`).
- Validator with JSON Schemas and sequence rules; Validation panel; VDA 5050 notes (`b97fe43`).
- Found and fixed: **the UI went blank on malformed robot data** (battery sent as a string). Robot
  data is now read defensively and every panel has an error boundary.
- Found and fixed: simulator shared one `headerId` counter across topics (spec: per topic).
- Found: CI had failed on Days 1–5 without anyone noticing (open issue 3). From now on, check CI
  after every push.
- Agreed working rule: follow the calendar, build properly, document everything. Wrote this file,
  [ARCHITECTURE.md](ARCHITECTURE.md), [DECISIONS.md](DECISIONS.md) and the [CHANGELOG](../CHANGELOG.md).

### Fri 9 Oct 2026: Days 1–7 of the first-week sprint

- Built the whole 7-day sprint in one session (`5045226` … `c28ec6c`): skeleton, simulator,
  missions, map and stream, BLOCKED_PATH, recording, replay.
- Bugs found during E2E testing and fixed: ACCEPTED was never published (accepted and moved in the
  same tick); busy-order errors stuck after completion; an order rejection wiped a `pathBlocked`
  error; replay refused after a backend restart because retained connection messages looked live.
- Not done: Docker run, demo video.

## How to update this file

At the end of each session:

1. Update **Where we are** (calendar week, last updated, status).
2. Update the **Schedule** row(s) you worked on.
3. Tick items in **This week**; add new ones if the week's work changed.
4. Update **Verification status** if something new was tested (or found untested).
5. Add, update or remove **Open issues** (reference them by number in commits).
6. Add a **Session log** entry.
7. Check CI for the pushed commits and note any failure.
