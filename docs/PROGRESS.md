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
| **Calendar** | Week 1 of 8 by date (Fri 9 Oct – Thu 15 Oct 2026); dates no longer gate the work (D-30) |
| **Last updated** | Mon 12 Oct 2026 |
| **Status** | **Weeks 1–3 complete** (quality gates passed 11–12 Oct, D-30). Next: Week 4, 5–10 robots and a warehouse map: the feature exists since Day 4; the load test (10/25/50 robots) is the open work. |
| **Working rule** | A week is done when its work is fully done (D-30): features, then a quality gate (independent bug and security review, scans, a test for every fix, all suites and e2e green, docs). Then the next week starts, whatever the date. |

## Schedule

Week 1 started on Friday 9 October 2026 (Day 1). Each week runs Friday to Thursday.

| Week | Dates | Plan objective | Plan output | Feature state | Quality state |
|---|---|---|---|---|---|
| **1** | 9–15 Oct | VDA 5050 concepts, MQTT topics, AMR state machines | Notes + message schemas + Docker Mosquitto | ✅ Done | ✅ Quality gate passed 11 Oct (D-30, see below) |
| 2 | 16–22 Oct | One fake AMR with battery, pose, state | Robot publishes status every second | ✅ Built early (Day 2) | ✅ Quality gate passed 11 Oct (charging, VDA 5050 state events, factsheet; timing measured at 50 robots) |
| 3 | 23–29 Oct | Mission sender + state transitions | Move job from start to destination | ✅ Built early (Day 3); completed 12 Oct (D-35) | ✅ Quality gate passed 12 Oct: VDA 5050 order handling, order updates, cancel/pause, review fixes |
| 4 | 30 Oct – 5 Nov | 5–10 robots + simple warehouse map | Multi-robot screen with location/state | ✅ Built early (Day 4, 10 Oct) | 🟡 Not load-tested beyond 10 robots. Near-collisions detected and reported, never avoided (D-22) |
| 5 | 6–12 Nov | Message inspector + validation | Readable message stream + errors | ✅ Built early (Day 4, 10 Oct) | 🟡 Official VDA 5050 2.1.0 and 3.0.0 schemas, chosen by topic (D-15, D-20). No offline validation of session files yet |
| 21 | Each robot's last state is stored whole (up to 256 KiB, D-31), so 1,000 robots could hold ~256 MB | Memory pressure only under a deliberate flood by logged-in clients | Store large states as a preview, or cap total bytes |
| 22 | Suspected UI races (found by reading, not reproduced): a message counted during "reset validation" may be counted twice in the UI; a recording started from another tab shows the previous recording's counters | Wrong numbers in the UI, not in files | Reproduce with a test first, then fix |
| 23 | Login rate limit trusts `X-Real-IP` from any peer: a local process on the direct API port 8000 (127.0.0.1 only) can rotate it | Accepted for now: the token has ~190 bits, so guessing stays infeasible; only memory growth, which is capped | Trust `X-Real-IP` only from the nginx container |
| 24 | Dependency and image scans (`pip-audit`, `npm audit`, `trivy`) run by hand, not in CI | A new CVE in a dependency is noticed late | Add a scheduled CI job |
| 7 | 20–26 Nov | Record/replay | Session file can reproduce incident | ✅ Built early (Days 6–7) | 🟡 Size limit (`ACTUNODE_MAX_SESSION_MB`, default 200) and streaming replay. No retention or upload yet |
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

## Week 3: orders, updates, instant actions; quality gate (12 Oct, D-35)

Built test-first from the official texts (rules extracted first, design written down as D-35 before
code): simulator order handling per 2.1 and 3.0 (all Week 2 review items), order updates, instant actions
(cancel, pause, state and factsheet requests), loads; backend orders that start at the robot, cancel and
extend endpoints; UI Cancel button and new statuses; 5 e2e tests (start node, cancel mid-route, cancel
without order, extend, protocol-clean traffic).

Gate: an independent review found 9 defects, each proven by a probe against the real code; every fix has
a regression test shown to fail on a snapshot of the pre-fix code (12 backend, 78 simulator).

| Severity | Finding | Fix |
|---|---|---|
| High | Malformed `actionParameters` crashed the robot halfway through applying an order; stuck until cancelled | Full validation first; atomic apply |
| High | `extend` built updates from a stale memory (rejected orders overwrote it, cancel didn't clear it, two concurrent extends diverged it for good, restart broke it) | Built from the robot's own state; one lock; 409 when unsafe |
| Medium | Update accepted while FAILED never drove | Resumes if charged; rejected if empty |
| Medium | Validator flagged legal WAITING→COMPLETED and COMPLETED→WAITING | Allowed (plus FAILED→MOVING) |
| Medium | 3.0: one instantActions message could make a state over the broker's 256 KiB limit | ≤ 50 actions per message, one error per message |
| Medium | Two internal id sets grew forever | Pruned |
| Low | Duplicate action/sequence ids accepted | Rejected |
| Low | Repeated `stateRequest` stopped publishing after 50 | Always publishes |
| Low | 3.0 error precedence after cancel | Checked first |

Also corrected before the review: a recharged robot silently dropped its order (3.0: errors never clear
an order), so it now keeps it until an update or a cancel (D-33 amended).

Verified: backend 218, simulator 269, frontend 42; e2e 22/22 (2.1), 22/22 (3.0), 25/25 (2.1 with login).

## Week 2 quality gate (11 Oct, D-30)

Scope: one fake AMR with battery, pose and state, publishing every second. Checked three ways: a semantic
review of the state and connection messages against the official 2.1 and 3.0 **texts** (they already
passed the schemas), a timing measurement on the real stack, and a look at the battery and pose model.
Each fix has a test that was shown to fail on the old code.

| Finding | Fix |
|---|---|
| Battery never recharged: every robot empty after ~500 m, then refused orders until restart | Charging in the charging area, 1 %/s; `charging` truthful; empty robot recovers (D-33) |
| Node traversals, finished actions and new errors published up to 0.9 s late (2.1 §6.10, 3.0 §6.6 make them triggers) | Event signature per tick; publish on change, ≤ 1 per tick (D-34) |
| `driving: true` and 1 m/s reported while standing still | From the distance actually moved |
| `theta` could be 3.142 (range −π…π) | Clamped |
| No `factsheet` (mandatory in both versions) | Published on connect, retained, QoS 0; validates against both official schemas |
| Our validator's `driving-consistency` demanded `driving` whenever MOVING (found by e2e after the fix above) | Flags only driving outside a route |
| Will comment claimed headerId order holds after reconnect | Corrected (spec: will header fields are always outdated) |

Timing (plan output "status every second"): see the verification table; passes at 1, 10 and 50 robots
before and after the changes.

**Moved to Week 3** (order handling, found by the same review; Week 3 is "mission sender and state
transitions"):
- `released: false` (horizon) is ignored: the robot reports horizon nodes as base and drives through
  them; it must stop at the last released node (2.1 §6.6.2).
- Edge actions are dropped (must appear in `actionStates`); unknown action types are accepted and
  reported FINISHED (2.1: reject with a warning; 3.0: `INVALID_ORDER_ACTION`).
- Error types are not version-specific: 2.1 malformed order → `validationError`; 3.0 →
  `VALIDATION_FAILURE`, `OTHER_ORDER_ACTIVE`, `OUTDATED_ORDER_UPDATE`.
- Rejection warnings are cleared when the old mission completes; they must stay until a new order is
  accepted.
- An order whose first node is far from the robot is accepted (2.1 §6.6.2 step 4; 3.0
  `START_NODE_OUT_OF_RANGE`); the backend should start orders at the robot's current node.
- `loads` not reported although pick/drop are; `instantActions` not handled at all (cancelOrder,
  stateRequest, factsheetRequest; 3.0 makes cancelOrder/startPause/stopPause mandatory).

**Moved to Week 6** (failure injection): 3.0 `errorLevel` for `pathBlocked` (WARNING vs URGENT).

## Week 1 quality gate (11 Oct, D-30)

Three independent reviews in fresh contexts (security of infra and auth; backend correctness; simulator
and frontend), plus `pip-audit`, `npm audit`, `bandit` and `trivy`. Every finding below was reproduced
(proof script or failing test) before it was fixed, and each fix has a regression test.

| Severity | Finding | Fix |
|---|---|---|
| Critical | One malformed order (missing `sequenceId`, `edges: 5`, NaN position, …) killed the whole simulator | Strict order type checks → `orderError` naming the field; one bad message can't stop the loop |
| High | A ~600-level nested JSON state broke `/api/robots`, `/api/messages`, the live feed and recording until restart | Depth limit 32, `RecursionError` caught (D-31) |
| High | No MQTT size limit: 6 MB payload → 129 MB parsed; 10 MB state → 14 s validation under the hub lock, freezing the API | Broker and backend limit 256 KiB; validation outside the lock; snapshot off the event loop |
| High | NaN/Infinity accepted, then sent as bare `NaN`: every browser lost the live feed until restart | Rejected as `non-finite-number`; client ignores unparsable frames |
| High | Wrong-shaped fields (`batteryState: "x"`, `nodes: 5`) crashed the validator and the message vanished | Type guards; `validator-error` backstop keeps the message |
| High | Any login (even read-only `tools`) could disconnect the backend or a robot by reusing its client id | Random per-process client-id suffix |
| High | Frontend image on nginx 1.27 (end of life): 43 HIGH/CRITICAL fixable CVEs; nginx ran as root | `nginx-unprivileged` 1.30 + `apk upgrade`, uid 101; 0 in trivy |
| High | Malformed but valid JSON (`null` payload, object `connectionState`) crashed the message stream / robot table | Guards and text rendering |
| Medium | Default replay republished 3.0 `zoneSet`/`responses` (commands) to robots | Treated as commands |
| Medium | Validator history, failure injection and the replay live check keyed by serial only (D-27) | Keyed by robot; failures pick the ActuNode robot |
| Medium | Command traffic created ghost robots, could evict real ones, hid the mission warning | Only `state`/`connection` touch robots |
| Medium | Near-collision pair stuck after a map change; next incident missed | Pair cleared |
| Medium | `POST /api/failures` → 500 on `actunode: null` | Guarded (409) |
| Medium | Duplicate orders re-executed, stale `orderUpdateId` accepted | Ignored / `orderUpdateError` |
| Medium | Last will carried headerId 1 and the process-start timestamp | Refreshed after each connect |
| Low | Origin check ignored scheme and port | Same-origin check (D-32) |
| Low | Open live feeds kept streaming after logout/expiry | Session re-checked every ≤5 s |
| Low | Unbounded failed-login table, validator/proximity/header-id state, client robot/failure lists | Capped |
| Low | Replay scan blocked the event loop (≈2.5 s at 200 MB); log flood via tracebacks; no log rotation | `to_thread`; rate-limited tracebacks; logs 10 MB × 3 |
| Low | Out-of-order session answers could show the lab after logout for one poll | Request sequence numbers |

Not fixed, logged with reasons: issues 21–24. Checked and found sound: shell-script quoting and name
validation, secret file permissions, session-file paths (no traversal), Host check, cookie flags,
constant-time token compare, XSS (no raw HTML anywhere), MQTT resubscribe and shutdown order.

Verified after the fixes: backend 183, simulator 64, frontend 36 tests; ruff, oxlint, tsc; e2e incl.
browser tests: 17/17 (2.1), 17/17 (3.0), 20/20 (2.1 with login + TLS); live: the broker disconnects a
client publishing 300 KB and nothing reaches the backend; nginx serves HTTP and HTTPS as uid 101.

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
- [x] Confirm `curl localhost:8000/api/health` works from a normal terminal (issue 15: host firewall, closed 11 Oct)
- [x] Confirm the Day 1–5 CI compose failures are understood (issue 3: transient runner problem, closed 11 Oct)
- [x] Read the VDA 5050 3.0 release notes and record what changes for us ([research note](research/VDA5050_3_0.md), D-15)
- [x] Python linter and formatter (ruff, 120 columns) in CI (issue 16, D-14)
- [x] Customer discovery kit: [outreach messages](discovery/OUTREACH.md), [interview guide](discovery/INTERVIEW_GUIDE.md), private tracker
- [ ] Customer discovery: first outreach messages sent (plan: 30 conversations in 60 days)
  - [x] First batch of 10 personalised drafts ready (private: `docs/company/outreach_batch_1.md`, tracker rows `to contact`); sending is the founder's

Proposed focus for the coming weeks (each week's plan objective + hardening of what was built early).
Struck-through items are already done:

| Week | Proposed engineering focus |
|---|---|
| 2 | ~~End-to-end tests in CI; fix battery-at-0; reconnect behaviour~~ (done 10 Oct, see Week 2 above) |
| 3 | ~~`instantActions` cancelOrder (the "cancel" in *cancel, reroute or escalate*); order updates (`orderUpdateId`)~~ (done 12 Oct, D-35) |
| 4 | Load test 10/25/50 robots (CPU, message rate, UI frame rate); ~~decide whether to model traffic/near-collisions~~ (D-22: detect, never avoid) |
| 5 | ~~Version-aware validation with the official 2.1.0 and 3.0.0 schemas, chosen by topic~~ (D-15, D-20); offline validation of session files |
| 6 | Remaining failures: low battery, disconnect, invalid payload, timeouts; simulator safety stops (`fieldViolation`) when a robot is in the path (D-22) |
| 7 | ~~Session size limits~~; retention; upload a session someone sent you; ~~streaming replay~~ |
| 8 | Record the demo video ([DEMO.md](DEMO.md)); polish README; publish |

## Customer discovery

Target from the plan: **30 conversations in 60 days** (by 8 Dec 2026), about 5 a week. Names and
notes stay in the private tracker `docs/company/discovery_tracker.csv` (not in git); only counts and
anonymised learnings go here.

| Week | Messages sent | Replies | Conversations | Total conversations |
|---|---|---|---|---|
| 1 (9–15 Oct) | 0 | 0 | 0 | 0 / 30 |

**Pipeline:** 10 contacts drafted (3 AMR companies, 3 VDA 5050 fleet managers, 2 open-source
maintainers, 2 developers who asked publicly for a VDA 5050 simulator or sample messages).

**Learnings so far:** none yet. After every 5 conversations, add a summary of repeated pain points
to the session log.

## Verification status

What has actually been checked, and how. "Unit" = automated tests; "E2E" = the running system
exercised by hand with a real browser and MQTT traffic.

| Area | How it was verified | Gaps |
|---|---|---|
| Backend API | 218 unit/API tests (pytest), run in CI, including a shutdown test under a real uvicorn server | |
| Simulator | 269 tests (pytest, incl. conformance against the official 2.1.0 and 3.0.0 schemas), run in CI | |
| Python style | `ruff check` + `ruff format --check` in CI (backend, simulator) | |
| Frontend | Type check, lint, 42 unit/component tests (`npm test`, incl. malformed robot data, both VDA versions, login, nothing opened before the session check) and production build, in CI; real-browser tests in the e2e suite (below) | |
| MQTT flow | Automated against Mosquitto in Docker (`tests/e2e`) | |
| Shutdown | Automated in `tests/e2e` (broker first, then backend; recording gets its end line) and `backend/tests/test_shutdown.py` | |
| Docker stack, end to end | **Automated** (`tests/e2e`, 26 tests incl. 3 in Chromium via Playwright and 5 for Week 3 orders, in CI for VDA 2.1, 3.0 and 2.1 with login): health, state every second, mission state machine, BLOCKED_PATH, near-collision warning, validation clean, record/replay, last will on kill, broker restart recovery, shutdown with open recording; in the browser: live robots, map and stream over a real WebSocket, a mission sent from the form completes, login screen refuses a wrong token, no console errors | Browser tests use the local plain-HTTP UI, not HTTPS (D-29) |
| P-1042 scenario (mission → block → clear → complete) | E2E, several times | |
| Record → replay | E2E; replay timing matched the recording within ~25 ms at 5×. Size limit stops a recording by itself (unit test); replay streams the file (unit test: 25 MB file, peak memory under 5 MB) | No retention or upload |
| Validator | Official VDA 5050 2.1.0 schemas (D-20); real and generated messages in every mission state pass them; planted bad messages flagged; e2e: all live traffic clean. 3.0.0 schemas on `v3` topics (D-15), tested with valid 3.0 messages and 2.1 messages on a `v3` topic | No offline validation of session files |
| 10 robots, 6 concurrent missions | E2E screenshot | No load test |
| State every second (Week 2) | Measured on the real stack, 75 s windows with missions: 1, 10 and 50 robots; worst interval 1.068 s, p99 ≤ 1.064 s, no headerId gaps, drift 0, at most one message per 0.1 s tick; one retained factsheet per robot | Not automated (scratch script); 50 robots is the simulator maximum |
| Dependencies and images | `pip-audit` (backend, simulator, e2e), `npm audit`, `bandit`, `trivy` images and Dockerfiles: 0 known HIGH/CRITICAL after the gate (11 Oct) | Not yet automated in CI |
| Security (D-18, D-23–D-28, D-31, D-32) | E2E: MQTT logins and ACL (spoofing refused, incl. own serial under another manufacturer; old serial-only login refused), Host/Origin checks, nothing works without a session in login mode, plain ports unreachable from the LAN, TLS refuses clients that do not trust the CA | |
| Near-collisions (D-22) | 8 unit tests (incl. 3.0 positions, offline robots, two robots sharing a serial); e2e: two robots at the same spot raise one warning | |

## Open issues and technical debt

Numbered so they can be referenced from commits. Remove an item only when it is fixed and verified; numbers are never reused (fixed: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20).

| # | Issue | Impact | Plan |
|---|---|---|---|
| 6 | No real-browser tests (component and logic tests exist since D-19, but run in jsdom, not a browser) | Browser-only issues (layout, WebSocket in a real browser) are caught by hand | Add Playwright tests against the e2e stack |

## Session log

Newest first. One entry per work session: what was done, what was learned, what is next.

### Mon 12 Oct 2026: Week 3 (D-35)

- Extracted the exact 2.1 and 3.0 rules for orders, updates, horizon, cancel, pause, loads and error names
  before designing; wrote D-35 first, including where 2.1 names no error and which name ActuNode uses.
- Built in parallel by part (simulator orders, simulator instant actions, backend, UI, e2e), each
  test-first; checked each builder's tests against the old code where they claimed red.
- Caught on the way: my brief named the 2.1 instantActions key `instantActions`; both official schemas
  require `actions` (the builder followed the schema). A builder made a recharged robot drop its order;
  the spec forbids that, changed.
- Gate review: 9 defects (table above), all fixed with regression tests proven red on a pre-fix
  snapshot. Week 3 is complete. Next: Week 4 (load test at 10/25/50 robots).

### Sun 11 Oct 2026 (night, last): Week 2 quality gate

- Battery model gap found by reading: no charging at all (D-33). Fixed test-first.
- Semantic review against the official spec texts: Week 2 items fixed (state events, truthful driving,
  theta range, factsheet; D-34); order-handling items written down as Week 3 work.
- Timing measured on the real stack at 1, 10, 50 robots, before and after the changes: passes.
- Caught on the way: one new test did not fail on the old code (it checked a tick too late), so every
  new test was re-run against the committed code in a scratch worktree; I had asked for factsheet QoS 1
  where both spec versions say QoS 0; the e2e validation check flagged our own validator rule, which
  demanded the untruthful `driving` the fix removed. The two 3.0.0 factsheet schema quirks: the boolean
  fix is already on upstream `main` (PR #609), so no duplicate report.
- Week 2 is complete. Next: Week 3 (the list above).

### Sun 11 Oct 2026 (night, later): Week 1 quality gate; new working rule (D-30)

- Founder: dates don't matter; a week is done when its work is fully done (quality, bugs, security,
  tests), then the next week starts. Recorded as D-30 (supersedes D-11) and in the working rule.
- Gate: tools first (`pip-audit`, `npm audit`, `bandit`: clean; `trivy`: frontend image 43
  HIGH/CRITICAL on end-of-life nginx 1.27, nginx as root). Then three independent reviews; every confirmed
  finding fixed with a regression test (table above), the rest logged (issues 21–24).
- nginx as uid 101 first tried ports 8080/8443 inside the container; this machine's firewall only lets
  the host reach a few container ports (issue 15), so it keeps 80/443 via the namespaced
  `ip_unprivileged_port_start` sysctl instead. Firewall untouched.
- My own same-origin change initially failed one test: TestClient WebSockets send `Host: testserver`,
  not the base URL; the tests now set Host as a browser would.
- Week 1 is complete. Next: Week 2 quality gate (the robot with battery, pose and state), then Week 3.

### Sun 11 Oct 2026 (late): first outreach batch drafted

- Found 10 contacts whose **public** work shows the pain ActuNode targets, each hook checked against
  its source: the reporter of VDA5050#660 at Navifra (the same 3.0.0 schema bug we pinned around); two
  ROS Discourse users who asked for a VDA 5050 fleet simulator and for sample messages (testing by hand
  with MQTT Explorer); Seegrid (full VDA 5050 compliance target 2026); OTTO (certified with three
  master controls in May 2026) and those three (idealworks, SYNAOS, NAiSE); InOrbit (ROS 2 connector);
  Fraunhofer IML (libVDA5050++). Drafts and names stay private (`docs/company/`).
- `OUTREACH.md` still said ActuNode speaks only 2.1: corrected to what is true today (2.1 and 3.0,
  one failure type, no real robots tested).
- Next: founder sends the batch and logs it in the tracker; follow-ups after 6 days.

### Sun 11 Oct 2026 (night): issue 6, real-browser tests (D-29)

- **#6 closed.** `tests/e2e/test_05_browser.py`: Chromium via Playwright (Python) on the e2e `stack`
  fixture, so it runs in all three CI configurations. Any console or page error fails a test, from the
  first page load on. Tests: robots, markers and live stream over a real WebSocket; a mission sent from
  the form (choosing the observed ActuNode v3 target on 3.0, as D-21 requires) reaches COMPLETED at the
  right spot; the login screen refuses a wrong token and then opens the lab with the right one. The
  browser uses the plain-HTTP UI on 127.0.0.1 (certificate checks are never switched off; TLS is covered
  by the security tests).
- **Bug found on its first login-mode run:** the lab mounted while the first session check was still
  pending (`session === null` read as "no login needed"), so the live feed and API polling started
  without a session: a 401 and a WebSocket 403 in the console. That contradicted the comment on `Lab`.
  Fixed by telling "checking" from "unreachable": nothing is shown but "Connecting to ActuNode…" until
  the first answer; an unreachable backend still opens the lab, which reports it. Three component
  tests written first (two failed on the old code).
- E2E 17 passed / 4 skipped (2.1 and 3.0), 20 passed / 1 skipped (2.1 with login; the skip is the
  LAN-only check); frontend 31. Stability rerun of the login and 3.0 configurations: identical results.
- No open issues left. Next: Week 1 customer outreach (founder); then the Week 3 hardening items
  (cancelOrder, order updates) when the calendar reaches Week 3, per the working rule.

### Sun 11 Oct 2026 (evening): issue 20, robot logins name the manufacturer

- **#20 closed (D-28).** Robot logins are `<manufacturer>.<serial>`; `mqtt-init` generates the broker ACL
  (static rules + one block per robot with manufacturer and serial in the topics; version stays `+`).
  `%u` patterns could not do this (one topic level; Mosquitto refuses `/` in substituted usernames).
  `add-robot <manufacturer> <serial>`; old serial-only files are skipped with a warning, never guessed.
- Checked the script on the real volume: missing argument and a dotted manufacturer exit 2; a real robot
  `VendorB.robot_01` next to the simulated `ActuNode.robot_01` gets its own block without `inject`;
  a planted old-style file warns and gets no login; ACL owned by mosquitto, 0400. No real robot logins
  existed on this machine, so nothing to migrate.
- Live on the broker: `VendorB.robot_01` logged in; its own state arrived, the same message published as
  `ActuNode/robot_01` was dropped; the hub showed two `robot_01` robots (issues 19 and 20 together).
  Test login removed afterwards.
- Found on the way: `docker compose up -d` does not recreate the broker when only a mounted config
  file's content changes; it kept the old ACL and the simulator (new username) could not publish until
  `--force-recreate mqtt-init mosquitto`. Written into the CHANGELOG upgrade note.
- E2E security tests: the old `robot_01` login is refused; publishing its own serial under another
  manufacturer is dropped. E2E 15/15 (+3 login-only skipped) for 2.1 and 3.0; simulator 43.

### Sun 11 Oct 2026 (later): issue 19, robots keyed by (version, manufacturer, serial)

- **#19 closed (D-27).** The live hub now keeps one robot per `(major, manufacturer, serial)` with a
  `key` like `v2/ActuNode/robot_01`; `robotId` stays the serial. Proximity pairs use keys (before, two
  robots sharing a serial could never be reported as too close: they were one entry). Serial-only
  lookups (failure injection, live check before replay, mission warning) now see every entry with that
  serial; the `identities` list is gone and the UI derives it. UI: rows, markers and map keyed by `key`;
  the table shows manufacturer and version only when serials collide; the Robot selects list each
  serial once. D-21 routing unchanged (test: a serial seen as VendorA v2 and VendorB v3 still gets its
  order on the default topic, with a warning naming both).
- Tests first for the hub: same serial under two manufacturers and two versions gives three robots;
  proximity across a shared serial. Backend 139, frontend 28. E2E 15/15 (+3 login-only skipped) for 2.1
  and 3.0; the e2e run caught that `GET /api/proximity` changed shape (now keys), so the test and the
  changelog say so.
- **New issue 20:** broker logins are still per serial (`%u` in the ACL), so colliding serials cannot
  all log in. Needs a decision on the login name scheme, not a quick patch.

### Sun 11 Oct 2026: open issues one by one (12, 17, 15, 3)

- **Issue 12 part A: MQTT logins.** Broker: no anonymous clients; logins for backend, tools (read only), healthcheck and one per robot
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
- **Stale documentation fixed** (founder's review): PROGRESS still listed as missing what the code
  has had since 10 Oct. Each claim was checked against the code and tests before rewriting: official
  2.1.0 and 3.0.0 schemas chosen by topic, near-collision detection (D-22), the recording size limit
  (`recorder.py`, unit test) and streaming replay (unit test: 25 MB file, peak memory under 5 MB).
  Updated the status line, schedule quality column, proposed focus (done items struck through),
  verification table (real test counts: backend 137, simulator 43, frontend 24, e2e 18; new rows for
  security and near-collisions) and two Week 1 checkboxes. Same sweep over the other docs: the
  `docker-compose.yml` header still said the broker was anonymous and the API had no login, and
  `VDA5050_NOTES.md` said ActuNode speaks only 2.x; both fixed. Confirmed still missing (and listed as
  such): cancelOrder and order updates, offline validation of session files, session retention and
  upload, load tests. Lesson: when a fix lands, update every row that names the gap, not just the
  issue table.
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
