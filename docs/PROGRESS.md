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
| **Last updated** | Wed 21 Oct 2026 |
| **Status** | **Phase 1 (weeks 1–8) complete; v0.1.0 released 13 Oct 2026** (D-43). Phase 2 (weeks 9–16, D-44) under way: **Weeks 9 and 10 done** (D-45, D-46: `actunode test`, timing and message expectations, every run recorded, five sample scenarios). **Decision point** (D-44): the founder's first user conversations decide the order of weeks 11–16; without new input, Week 11 is next. **Product audit 14 Oct (D-47):** outside fleet managers can now connect; security headers added. **Week 11 done (D-48):** the plan's demo question runs as a scenario against a fleet manager; `UNRESPONSIVE`; replay with current time. **Week 12 done (D-49).** **Full audit of weeks 0–12 done (D-50, docs/AUDIT_2026-10-14.md):** six reviews, ~95 findings (13 High), all fixed with tests; gate green. **Week 13 done (D-51):** a real ROS 2 stack (Nav2 + InOrbit's VDA 5050 connector) in the lab; eight deviations found. **Week 14 done (D-52):** conformance suite, the connector's report (4/9), five upstream drafts (not filed: founder's call), robot guide. **Week 15 done (D-53):** failure catalogue, scenario gallery, message flows from real recordings; two blog drafts (private, for the founder). **Week 16 done (D-54):** getting started guide, compatibility promise, triage routine; 0.2.0 built and verified (fresh clone, CI green); v0.2.0 released (tag on 6c234f2). **Phase 2 complete.** **After Phase 2 (17 Oct):** the ROS 2 robot's conformance failures fixed (D-55, five upstream PRs open), per-person logins and an audit trail (D-56), metrics (D-57), published images (D-58), robot-scoped scenario checks (D-59); the full audit has no open items. **v0.3.0 released 17 Oct** (tag on 238509e); images public on ghcr.io for amd64 and arm64, provenance verified. **Hosted service (D-61):** phase 1 built 19 Oct; **phase 2 built 20–21 Oct (D-62)**: idle labs, account deletion, abuse limits, upgrades, backups with a passing restore drill, alerts; **v0.4.0 released 24 Oct** (tag on f36e5a2; images public on ghcr.io); waiting on the founder's accounts (Hetzner, DNS, OAuth, backup storage, alert webhook). No open issues. |
| **Working rule** | A week is done when its work is fully done (D-30): features, then a quality gate (independent bug and security review, scans, a test for every fix, all suites and e2e green, docs). Then the next week starts, whatever the date. |

## Schedule

Week 1 started on Friday 9 October 2026 (Day 1). Each week runs Friday to Thursday.

| Week | Dates | Plan objective | Plan output | Feature state | Quality state |
|---|---|---|---|---|---|
| **1** | 9–15 Oct | VDA 5050 concepts, MQTT topics, AMR state machines | Notes + message schemas + Docker Mosquitto | ✅ Done | ✅ Quality gate passed 11 Oct (D-30, see below) |
| 2 | 16–22 Oct | One fake AMR with battery, pose, state | Robot publishes status every second | ✅ Built early (Day 2) | ✅ Quality gate passed 11 Oct (charging, VDA 5050 state events, factsheet; timing measured at 50 robots) |
| 3 | 23–29 Oct | Mission sender + state transitions | Move job from start to destination | ✅ Built early (Day 3); completed 12 Oct (D-35) | ✅ Quality gate passed 12 Oct: VDA 5050 order handling, order updates, cancel/pause, review fixes |
| 4 | 30 Oct – 5 Nov | 5–10 robots + simple warehouse map | Multi-robot screen with location/state | ✅ Built early (Day 4); completed 12 Oct (D-37, D-38) | ✅ Quality gate passed 12 Oct: load test 10/25/50 robots, one map, parking, live feed at scale |
| 5 | 6–12 Nov | Message inspector + validation | Readable message stream + errors | ✅ Built early (Day 4); completed 13 Oct (D-40) | ✅ Quality gate passed 13 Oct: offline validation (API, UI, CLI) matching live validation |
| 6 | 13–19 Nov | Failure injection | Blocked path, low battery, disconnect, invalid payload | ✅ Blocked path Day 5; the other three completed 13 Oct (D-42) | ✅ Quality gate passed 13 Oct: all four observed end to end; spec error levels |
| 7 | 20–26 Nov | Record/replay | Session file can reproduce incident | ✅ Built early (Days 6–7); completed 13 Oct (D-41) | ✅ Quality gate passed 13 Oct: retention, upload of a session someone sent you, hostile-file checks |
| 8 | 27 Nov – 3 Dec | Demo + README + 3-minute video | GitHub repo + pitch demo | ✅ Completed 13 Oct (D-43): Apache-2.0, README, demo recorder; voice-over by the founder | ✅ Quality gate passed 13 Oct: docs accuracy review, fresh-clone quick start; v0.1.0 |
| 9 | 4–10 Dec | Scenario format + `actunode test` runner | P-1042 passes as a scenario; JUnit output | ✅ Built 13 Oct (D-45) | ✅ Quality gate passed 13 Oct: review of the scenario input, HTTP and cleanup paths |
| 10 | 11–17 Dec | Expectations + five sample scenarios | `scenarios/`; decision point | ✅ Built 13 Oct (D-46) | ✅ Quality gate passed 13 Oct; decision point open |
| 11 | 18–24 Dec | Testing an external master control | "cancel, reroute or escalate?" as a scenario | ✅ Built 14 Oct (D-47, D-48) | ✅ Quality gate passed 14 Oct |
| 12 | 25–31 Dec | Scenarios in CI | Docker runner + GitHub Actions example | ✅ Built 14 Oct (D-49), with the site capture import | ✅ Quality gate passed 14 Oct |
| 13 | 1–7 Jan | ROS 2 robot stack, part 1 | Nav2 robot behind the VDA 5050 connector, optional profile | ✅ Built 15 Oct (D-51) | ✅ Quality gate passed 15 Oct |
| 14 | 8–14 Jan | ROS 2 robot stack, part 2 | Scenarios against it; conformance report; connect-your-robot guide | ✅ Built 15 Oct (D-52) | ✅ Quality gate passed 15 Oct |
| 15 | 15–21 Jan | Developer credibility | Failure catalogue, scenario gallery, blog drafts | ✅ Built 16 Oct (D-53) | ✅ Quality gate passed 16 Oct |
| 16 | 22–28 Jan | Ready for external users | Onboarding path, triage routine, v0.2.0 | ✅ Built 16 Oct (D-54) | ✅ Gate passed 16 Oct (fresh clone, CI green); v0.2.0 published 16 Oct |

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

## After Phase 2: fixing the ROS 2 robot's conformance failures (16 Oct, D-55)

Asked "can't we fix it" about the connector's 4/9. Located every failure in the pinned code: none is our
configuration; most are in InOrbit's *example* TurtleBot3 adapter (state fields never filled; every Nav2 goal
reported succeeded, so the connector's correct failure handling never runs), two in the connector (`theta`
mandatory; no map check). Built two optional patches (`ros2/patches/`, `ACTUNODE_ROS2_PATCHES=1`; default build
unchanged).

Then, asked to make every check pass, a third patch: the connector rejects orders on maps the robot does not have
(`known_map_ids`, opt-in), and its validation errors carry the standard type (`validationError`, was
`validationOrder`). Verified in the lab: patched 9/9 scenarios and 3/3 raw checks, repeated runs back to back, no
validator issue in the robot's state. Then the last two connector bugs (undecodable orders dropped; the refused-login
`TypeError`), a fourth raw check, and 4/4; the refused login tested live with a throwaway robot whose login does
not exist; unpatched still 4/9 and 0/3, as published. Testing found and fixed two
false results in `conformance/raw_checks.py` (an order left open made the unknown-map check pass; a pending cancel
could cancel the next order). Report, upstream drafts (now two PRs plus two issues), CHANGELOG, D-55 updated; the
ROS 2 workflow runs both variants. Filing upstream is still the founder's call.

## Week 16: ready for outside users (16 Oct, D-54)

Built: docs/GETTING_STARTED.md (clone to a first passing and a first failing scenario, Docker only),
docs/COMPATIBILITY.md (what stays stable in 0.x: scenario format 1, session formatVersion 1, the `actunode test`
command and exit codes, topics and logins), docs/TRIAGE.md (reports, labels, 3-working-day first response, reproduce
before fixing), issue templates (bug asks for a session or scenario file; new conformance template), labels
`conformance` and `needs-reproduction`. Scenario files may declare `version: 1`; a later version is refused (StrictInt,
tests). Version 0.2.0 everywhere; CHANGELOG 0.2.0; the CI template pins `ref: v0.2.0`.

Gate (16 Oct):
- Fresh clone from GitHub at 6c234f2, followed GETTING_STARTED exactly: lab healthy (`--wait`), UI 200, health
  0.2.0; step 3 `p1042_blocked_path` passed, exit 0, JUnit written as uid 1000, session recorded; step 4 failing copy
  printed `robot_01 pathBlocked is WARNING (expected FATAL)`, exit 1, cleanup cancelled the order. Clone torn down
  (`down -v`, its own project only); the lab here rebuilt on 0.2.0.
- CI on 6c234f2 green: lint, simulator, backend (595), frontend, cli (228), e2e (2,0) (2,1) (3,0), scenarios 2 and 3;
  security scans green.
- Released: the founder published v0.2.0 (tag on 6c234f2, notes from CHANGELOG 0.2.0).

## Week 15: developer credibility (16 Oct, D-53)

Built: [FAILURE_CATALOGUE.md](FAILURE_CATALOGUE.md) (robot, fleet-manager and site failures; how to reproduce or
detect each; open ones marked), [SCENARIO_GALLERY.md](SCENARIO_GALLERY.md) (16 scenarios; `cli/tests/test_gallery.py`
fails if one is missing), [MESSAGE_FLOWS.md](MESSAGE_FLOWS.md) (P-1042, cancel and resume, dropped connection:
Mermaid sequence diagrams with the timings and ids of real recordings). Two blog drafts for the founder in
`docs/company/blog-drafts/` (private): the conformance run against InOrbit's connector (publish after filing the
upstream issues), and testing a fleet manager's blocked-aisle reaction in CI.

Gate: every relative link in the repository's Markdown resolves (script); facts in the drafts checked against
the recordings and code; corrected while checking: the error count in the conformance post ("in a few minutes" →
"an afternoon"), the gallery test reading a CI workflow as a scenario.

## Week 14: conformance (15 Oct, D-52)

Built: `conformance/vda5050-2/` (nine scenarios, plain VDA 5050 only, for any 2.x robot), `conformance/raw_checks.py`
(orders the mission sender never builds, via a fleet manager login), scenario `rule:` on message checks and
`theta` on missions; [CONFORMANCE_ROS2_CONNECTOR.md](CONFORMANCE_ROS2_CONNECTOR.md) (each result cites the VDA 5050
2.1.0 text, fetched from the VDA's repository); five upstream drafts ([research/upstream/](research/upstream/));
[CONNECT_YOUR_ROBOT.md](CONNECT_YOUR_ROBOT.md). The opt-in ROS 2 e2e test runs the suite and fails if a result changes.

| Found | Fix |
|---|---|
| Scenario 07 passed in 0.5 s: the robot already stood at the destination | Destination never left by the other scenarios |
| Scenario 09 assumed a cancelled robot stops on the spot; the spec allows the next node (§6.6.3) | Checks FINISHED within the time to the next node; the report says it passes |
| The Week 13 notes called the map check a violation; it is a 2.1 rule (the connector speaks 2.0) | Informational in the report |
| A section number written from memory (§6.2 for header ids) | §6.4, checked against the text |
| The guide said missions carry no actions without a load id | With a `source` they have pick and drop |

Verified: the suite against the ROS 2 robot (4 of 9 pass), raw checks 0 of 3, ROS 2 e2e 4/4 on an isolated stack.

Then, from looking at the lab with the ROS 2 robot in it: real robots showed "Mission: UNKNOWN" (the UI read only
ActuNode's own field), the failure panel offered robots that cannot take failures, visualization messages were raw
JSON, and the connector reports 0 % battery. Fixed: a status derived from plain VDA 5050 fields (marked "VDA"),
the panel lists simulated robots only, a visualization summary; the battery is in the report. Frontend 144 tests;
checked on the running lab (the ROS 2 robot shows MOVING from its velocity, as its `driving` flag is wrong).

## Week 13: a real ROS 2 robot stack (15 Oct, D-51)

Built: the optional `ros2` profile (`ros2/`): ROS 2 Humble, Nav2 with a fake TurtleBot3 (odometry only, headless)
on a map generated from the warehouse, behind InOrbit's open-source VDA 5050 connector and TurtleBot3 Nav2 adapter
(pinned commits). It logs in as the robot `ROS2.nav2_01` over MQTT/TLS with only its own password and the public
CA certificate. ActuNode sent it a mission: it planned around the racks and reached STORAGE_A17. Missions gained
optional `theta`. Opt-in e2e test (3 tests) and a weekly CI workflow.

Found while bringing it up (the lab doing its job): the connector drops orders without node headings with no
error; it reported a node reached when Nav2 had aborted; `driving` false while moving; `operatingMode ""` in every
state (the validator's schema rule); `positionInitialized` false; its MQTT thread dies on a refused login. Eight
items in [research/ROS2_CONNECTOR.md](research/ROS2_CONNECTOR.md), input to Week 14.

| Found in our own setup | Fix |
|---|---|
| ROS's setup scripts break under `set -u` | Relaxed around them |
| TurtleBot3's fake-robot launch needs the Gazebo package | The fake node and a static base transform, no Gazebo |
| Launch arguments are shared between included files: Nav2's empty `namespace` reached the connector | Each include gets its own |
| The connector's launch prefixes parameter keys with its namespace | Per-node keys, as its example |
| The connector trusts `VDA5050_CONNECTOR_TLS_CA_CERT`, not `SSL_CERT_FILE` | Set |
| Robot passwords and the CA certificate are root-only in the secrets volume | The robot's own password file (`ros2/`) and a world-readable CA certificate (`public/`); backup/restore know both |
| ActuNode's map is `warehouse`, Nav2's `map`: goals in an unknown frame | `warehouse` is a second name for `map` in the robot's transforms |
| A retention test had a fixed date and failed once the calendar passed it | Ages from the real clock |

## Full audit of weeks 0–12 (14–15 Oct, D-50)

Six independent reviews of every line (backend web, backend data, simulator, frontend and nginx, infrastructure
and CI, runner and test quality) plus an architecture review: about 95 findings, 13 High, each reproduced or
traced. Decisions, details and results: [AUDIT_2026-10-14.md](AUDIT_2026-10-14.md). Fixed by five workers in
parallel on disjoint files, from the reviewers' findings, then merged and gated here.

Highest-impact fixes: overflowing JSON numbers could blank every browser and hide messages; a crafted session
file could exhaust memory (25×) or freeze the API during replay, or make the broker drop the backend; any
robot or fleet-manager login could exhaust the broker's memory; an outside fleet manager could freeze all
simulated robots or wedge one with a malformed order; one malformed robot message could take down UI panels;
the runner crashed with the wrong exit code on refused requests and could not address other manufacturers'
robots; the import could destroy its own input.

Gate: backend 576, simulator 465, runner 220, frontend 137 (lint, build, types); e2e 41+4 / 41+4 / 44+1 (VDA 2.1,
3.0, 2.1 with login and TLS); load test all thresholds at 10/25/50 robots; 19 black-box attacks re-run; nginx
headers, gzip and asset 404 checked on a running server. The gate found two more issues, fixed: the load
test's browser probe blocked by the new CSP, and a year-long cache header on a 404.

## Week 12: scenarios in CI, site captures (14 Oct, D-49)

Built: `cli/Dockerfile` and the `runner` service (`docker compose run --rm runner test scenarios/`): inside the
frontend's network namespace, so the lab is `http://localhost` (no new allowed host names), with only the web
login token mounted. CI job `scenarios` (2.1 and 3.0): the sample scenarios and the example fleet manager
against the blocked-path scenario; JUnit, recordings and logs as artifacts; counts in the job summary.
`examples/ci/github-actions.yml`: the same steps for a customer's repository. `actunode import`: a
`mosquitto_sub -F '%U %t %p'` capture becomes a session (built by a delegated worker from a written spec,
then reviewed and checked here on real traffic).

| Found | Fix |
|---|---|
| A runner on the Compose network would call the lab as `frontend`, refused by the host allow-list (D-24) | Shares the frontend's network namespace: reaches it as `localhost`; no security change |
| The runner image needs the token only when login is on, but the backend's secrets folder also holds its MQTT password | Only the token file is mounted (volume subpath to one file) |
| GitHub's runner is uid 1001; the lab writes as 1000 | CI sets `ACTUNODE_UID`/`ACTUNODE_GID` to the runner's ids; the runner service runs as both |
| The CI job's YAML did not parse (a `: ` in a step name) | Fixed; both workflow files are parse-checked |
| Import: offline validation of a too-large payload relies on the recorded rule name (the recorder keeps only a preview) | The import writes the same `rejected` rule as the recorder |

Verified: hands-on, the Docker runner ran the six sample scenarios and the fleet manager scenario on the local lab
(JUnit, summary table); a real 5 s capture with an injected bad message was imported (2 garbage lines skipped
and listed), uploaded, and the validator flagged it. Unit: backend 463, simulator 397, runner 148; ruff clean.
e2e (44 tests): 40 passed + 4 login-only skipped on 2.1 and on 3.0, 43 passed + 1 skipped on 2.1 with login and TLS.

## Week 11: testing a fleet manager (14 Oct, D-48)

Built: `examples/fleet_manager/` (an example fleet manager over VDA 5050/MQTT with its own `master@` login, and a
choice of reaction to a blocked path) and `blocked_path_reaction.yaml`, the plan's demo question as a test:
cancel, reroute and escalate pass, ignore fails. Folded in from the audit: the `UNRESPONSIVE` failure (online
but silent, commands ignored: the plan's "timeouts") and replay with **Current time**. Scenarios: `message`
lists mean "any of"; `never` counts messages from its own start; sixth sample scenario `unresponsive_robot.yaml`.
UNRESPONSIVE and the replay tests were built by delegated workers from a written spec, then reviewed and run here.

| Found | Fix |
|---|---|
| The blocked-path check polled the robot's status: a quick fleet manager cleared the block before the poll, failing a good fleet manager | Detect the block from the robot's state message (no message is missed) |
| `never` counted messages from the previous step: a state caused before the never began counted "during" it | `never` counts from its own start (D-48) |
| Cleanup reported "could not clear" for a block a fleet manager had already ended by cancelling | Reports "already over" |
| Example fleet manager: an order sent twice before the robot confirmed the first; order ids reused after a restart (the robot took them as updates of a cancelled order); escalation paused the robot and never resumed it; a callback error would silently stop the MQTT thread | All fixed in the example. The first three are classic fleet-manager bugs, listed in D-48 as things to test customers' systems for |
| e2e only (full suite): the ignore case started while robot_03 finished the previous fleet manager's order; the block landed as that leg ended, so no pathBlocked | The test starts from an idle robot; the scenario requires MOVING for 2 s before blocking |
| Gate run 1: one configuration could not build images (Docker Hub DNS timeout on this machine) | Re-run |

Verified (unit): backend 463, simulator 397, runner 135, frontend 99 (lint, build); ruff clean. e2e (43 tests): 39 passed + 4 login-only skipped on VDA 2.1 and on 3.0, 42 passed + 1 skipped on 2.1 with login and TLS. Live, on the
local lab: the four policies against the scenario (cancel, reroute with its detour order valid, escalate with
resume: pass; ignore: fails at the reaction step); the unresponsive scenario.

## Product audit after Week 10 (14 Oct, D-47)

The product checked against the company plan (problem, users, the demo question), hands-on on a running lab,
plus black-box attacks and every test suite and scanner. Who uses it for what: [USE_CASES.md](USE_CASES.md).

**Does it do the job?**

| Plan promise | Today |
|---|---|
| Simulate 5–50 AMRs; send missions; validate VDA 5050 2.1 and 3.0; inject blocked path, low battery, disconnect, bad message; record and replay | ✅ all, verified (Weeks 1–8) |
| "Turn scenarios into test suites; run `robotlab test`" | ✅ `actunode test`, five sample scenarios (Weeks 9–10) |
| An AMR vendor tests its robot against ActuNode | ✅ checked: own login, validated, missions received, isolated from other robots |
| **"Does the system cancel, reroute or escalate?"**: the customer's fleet manager under test | ❌ → ✅ **fixed**: no outside system could send orders (only ActuNode's backend). New `master@<name>` login; an outside client drove and cancelled a robot, e2e in all three configurations |
| Reproduce a pilot bug from a site; understand a site's downtime | ⚠️ only for traffic through ActuNode's own broker. A site's broker cannot be recorded or imported (open) |
| Failures named in the plan: duplicate missions, timeouts | ⚠️ not injectable yet (open) |
| Replay an incident against a connected fleet manager | ⚠️ possible since D-47 (replay sends only robot messages by default), untested (open) |
| "Understand the value within five minutes" | ✅ quick start, sample scenarios; the new USE_CASES.md says who does what |

**Bugs and vulnerabilities**

| Check | Result |
|---|---|
| All suites | backend 438, simulator 391, runner 128, frontend 96 (Node 24) passed; e2e 41 tests (incl. 2 new) |
| pip-audit (4 requirement sets), npm audit | no known vulnerabilities |
| bandit | 2 findings, both false positives (SafeLoader subclass; XML only written), annotated: 0 left |
| Black-box attacks on the running lab (19) | refused: cross-site POST and WebSocket, foreign Host, topic injection in ids, path traversal (served the UI page, no file), anonymous and wrong-password MQTT, a robot login reading or spoofing others or injecting failures, 2 MiB payload. All ports on 127.0.0.1 |
| Found: no security headers on the UI | Fixed: strict CSP, no framing, nosniff, no-referrer, nginx version hidden; real browser shows no CSP errors |
| Found: under Node 20 `npm test` printed "no tests" (Node 24 required) | Fixed: `engine-strict` |
| Found by the full e2e run: ActuNode's mission sender and an outside fleet manager on one robot give a header-id warning | Correct per VDA 5050 (one master per robot): documented in the README; the test accepts that warning only |
| Suspected simulator bug (robot refused an order after COMPLETED) | Not a bug: it was still busy; the probe's earlier cancel was malformed (2.x field `actions`), which the validator flagged |

## Week 10: timing, message expectations, sample scenarios (13 Oct, D-46)

Built: `expect … for: N` and a `never` step; `message` conditions (MQTT topic filter + JSON subset pattern)
read from the lab's live feed on a background thread, so no message is missed between polls; every run
recorded as a lab session (id in the console and JUnit); five sample scenarios in `scenarios/`:
P-1042 blocked path, low battery during a mission, disconnect during a mission, invalid traffic, cancel and
resume. The disconnect scenario ends with the robot ONLINE (the Week 9 open item).

Gate: review of the new trust boundary (the WebSocket feed: snapshot check, frame limit, a closed feed is
"could not run", never a pass), timing semantics against a fake clock, the feed client against a real
local WebSocket server, pip-audit (now including `websockets`), and every sample scenario on the real stack.

| Found | Fix |
|---|---|
| Two new unit tests were wrong (a vacuous `or True`; a test named for one thing that checked another) | Rewritten to assert the real window semantics and a real "no snapshot" server |
| Recording calls shifted the fake lab's call log and order ids, failing eight older tests | Lab calls (recording, feed) kept apart from robot commands in the fake |
| Known limits, documented in cli/README.md | Robot state is polled every 0.25 s (`never`/`for` can miss shorter states); payloads over 16 KiB match only as text |
| Found by CI (login + TLS) | One scenario "could not run": opening its live feed stalled for 10 s. Container logs showed the attempt reached neither nginx nor the backend (a connection stall before the proxy). CI also used websockets 17.2, outside the runner's own `<16` pin, because e2e installed its own copy | Opening the feed is retried (3 × 5 s; refusals are not retried); e2e installs the runner's pinned requirements |
| Found by CI | Two runner unit tests still described the old P-1042 (edited after the last local run) | Updated; the full suite runs before every commit |
| Noted, not changed | Clearing LOW_BATTERY restores the battery level from before the injection, so the drain during the injection is undone (simulator design, D-42) |

Verified: runner unit tests 128; e2e `test_09_scenarios.py` 2/2 (all five sample scenarios, each recorded,
plus the failing-scenario cleanup test) on VDA 2.1, 3.0 and 2.1 with login, about 3.5 min each; ruff clean;
pip-audit clean.

Decision point (D-44): the order of weeks 11–16 is open to what the first user conversations say. The
outreach messages are the founder's to send (docs/discovery/OUTREACH.md).

## Week 9: scenario tests (13 Oct, D-45)

Built (design first, tests with the code): `cli/`, the `actunode` package with `actunode test`. A YAML
scenario (steps `send_mission`, `inject`, `clear`, `cancel_mission`, `wait`, `expect`; expectations on
status, order, error and level, connection, validation rules, `within` N s) runs against a lab through its
HTTP API. Output: a readable log, `--junit` XML, exit codes 0 pass / 1 fail / 2 invalid / 3 could not run.
Cleanup clears injected failures and cancels the scenario's running orders. `scenarios/p1042_blocked_path.yaml`
is the pitch demo's incident; it passes on the real stack in about 29 s.

| Found while building | Fix |
|---|---|
| The runner matched robots by `vdaMajor` `"2"`; the API says `"v2"`, so with `--vda-version` no robot was ever online. The unit-test fake had the same wrong shape (the D-38 pattern) | Fixed; the fake follows the API; a contract test reads the backend's shared fixture |
| A step that is not a mapping was reported as `steps[0]` (pydantic's 0-based index) while every other error counts from 1 | All step errors numbered from 1; all errors in a file reported at once |
| The local dev stack (images from 11 Oct) answered 404 to cancel: stale images, not a runner bug | `docker compose up -d --build` refreshes it; the e2e stack is built fresh each run |
| One e2e run in login mode errored in stack setup straight after another run's teardown; three reruns passed | Watch in the gate |

Gate (a review of the runner's trust boundaries: scenario files, the lab's answers, cleanup), each finding
fixed with a test that fails on the old code:

| Severity | Finding | Fix |
|---|---|---|
| Medium (security) | YAML aliases let a small scenario file expand into a huge structure (validation would hang a CI job) | Anchors and aliases refused |
| Medium | Failure `params` were coerced: YAML `true` reached the backend as `1`, passing its strict check (D-42) | Kept as written (strict int/str); the backend decides |
| Low | A lab answering with a redirect (http → https) was reported as "not JSON" | Says where it redirects and to use that address |
| Low | An empty order id printed as `runs order  (expected …)` | Prints `none` |
| Open (Week 10) | A scenario that ends with a robot DISCONNECTed leaves it offline up to `duration_s`; the next scenario's 15 s online wait can fail | Week 10's disconnect scenario ends by expecting ONLINE; revisit cleanup then |

Verified: runner unit tests 82; e2e `test_09_scenarios.py` 2/2 in all three configurations (VDA 2.1, 3.0,
2.1 with login); full e2e 35 passed + 4 login-only skipped (VDA 2.1); `pip install ./cli` gives a working
`actunode`; ruff clean; pip-audit of the runner's dependencies clean.

## Week 8: publishing, quality gate (13 Oct, D-43)

Built: Apache-2.0 LICENSE (verbatim), NOTICE, SECURITY.md, CONTRIBUTING.md, issue/PR templates; README and
DEMO.md rewritten with every claim checked against the code; `tests/demo/record_demo.py` records the
3-minute demo (about 2.8 min, nine scenes with captions) and the six README screenshots from the real
product on an isolated stack.

Gate: an independent accuracy review of the public docs (every link, number, default, command and
decision reference checked; LICENSE byte-identical to apache.org; no secrets or private material in git)
and a fresh clone followed by the README as written (working lab in about 20 s on a warm Docker cache;
every command worked).

| Found | Fix |
|---|---|
| Retention (and trusted-proxy) settings documented but never passed to the backend under Docker | Added to docker-compose.yml |
| `POST /api/recording/stop` answered `recording: true` | Fixed; test fails on the old code |
| README load figures predated Weeks 4–7 | Load test re-run on the release code: 18/18 at 10/25/50 robots |
| Missing tour commands (clear, record, parameters), CLI setup, mosquitto_sub prerequisites, 3.0 last-will name, replay speeds, a broken CONTRIBUTING anchor, stale test-README wording | Docs fixed |
| Doc drift in ARCHITECTURE, VDA5050_NOTES, D-34, NOTICE (found while rewriting) | Fixed |

## Week 6: failure injection, quality gate (13 Oct, D-42)

Built (design first, test-first): LOW_BATTERY, DISCONNECT (abrupt → broker last will, or clean OFFLINE),
INVALID_PAYLOAD (four kinds) next to BLOCKED_PATH; 3.0 error levels from the spec's own definitions
(`batteryLow` URGENT, `pathBlocked` CRITICAL); UI panel with parameters. E2E observes each failure on the
real stack, including the broker publishing the last will.

Gate review findings, all fixed with regression tests:

| Severity | Finding | Fix |
|---|---|---|
| Important | Every abrupt disconnect produced a false header-id warning (the will's headerId is outdated by design) | Validator skips and does not remember it |
| Important | One robot's DISCONNECT froze the whole simulator (every robot) for up to 1 s | Disconnect and reconnect on a helper thread |
| Important | Clearing low battery left FATAL "Battery empty" next to a full battery | Restoring charge clears it |
| Important | The shared fixture test could not catch parameter drift | Exact result per command; unknown params rejected |
| Suggestions | Unbounded malformed-message queue; loose types; wrong 422 locations; schema allowed params on clear; no state right after reconnect; reconnect handshake built on paho's thread; silent second disconnect; LOW_BATTERY clear with nothing injected | All fixed; robots report `injectedFailures` |
| Found on the way | The UI's robot update slowed down with many robots (a test needed 4.5 s) | Plain copy loop: 0.3 s |
| Found on the way | Since 11 Oct this table had no Week 6 row and closed issue 6 still showed as open (my close-issue script removed the wrong `\| 6 \|` row) | Restored |

Verified: backend 438, simulator 391, frontend 96; e2e 33/33 (2.1), 33/33 (3.0), 36/36 (2.1 with login).

## Weeks 5 and 7: features finished, quality gate (13 Oct, D-40, D-41)

Built (design first, test-first): offline validation of a saved session (API, Validate button, CLI for a
customer's CI); session retention by age and total size; uploading a session file someone sent you.

Gate: a security review and a correctness review (which recorded real traffic in-process and fed it back
through the new code — the first tests never did that).

| Severity | Finding | Fix |
|---|---|---|
| P1 | Upload rejected legitimate recordings (large snapshots, non-ASCII text, recorded invalid payloads) | Per-record line bounds; round-trip tests with real recordings |
| P1 / Medium | Retention deleted a just-uploaded file (500) or just-stopped recording, and an upload could evict colleagues' sessions | Uploads never delete (507 when full); just-stopped session protected |
| Medium (security) | A crafted upload crashed the UI for every user (wrongly typed fields) | Types checked on upload, sanitised in listing, UI defensive |
| Medium (security) | Validation had no CPU/concurrency bound (could starve live-feed connections) | One at a time on its own worker; cached |
| Medium (security) | UTF-16 file passed upload, broke validate and replay | Strict UTF-8 everywhere |
| P2 | Offline validation disagreed with live for invalid payloads | Recorder stores the rejection rule |
| P2 | Crash-cut and size-limit-stopped recordings refused on upload | Torn last line accepted; end-record reserve |
| Low (security) | Uploads could stall forever and use 2× disk; nginx's 1 MB default broke every UI upload over 1 MB | Timeout, one at a time, disk check, single copy; nginx 201 MB on the upload path |
| P2 | UI/backend field type mismatch (`t`), the D-38 pattern again | Shared contract fixtures for all session responses |
| Quality | Four copies of the session-file parser; private imports | One record reader; `jsonsafe.py` |

Verified: backend 389, simulator 337, frontend 82 (incl. contract fixtures); e2e 26/26 (2.1), 26/26 (3.0),
29/29 (2.1 with login).

## Week 4: load test and quality gate (12 Oct, D-37, D-38)

A repeatable load test (`tests/load/run_load.py`, isolated stack, missions keeping half the robots busy)
plus a code review of the multi-robot surface.

Review findings fixed: robots 11–50 parked in RECEIVING and STORAGE RACKS, some on racks, and could not
charge there (new PARKING zone; layout tested for all 50, D-37); a slow WebSocket client was never resynced
and could show wrong near-collisions for good (now closed with 1013, reconnects for a snapshot); the map
existed in two copies (now one, served at `GET /api/map`); off-map robots were invisible; UI and backend
read 3.0 positions differently. Expected, not fixed: straight-line driving at 50 robots produces frequent
near-collision warnings (D-22).

Load test at 50 robots, before → after the fixes (same script, same machine):

| | Before | After |
|---|---|---|
| Live feed | 133 kB/s, 66 events/s | 76 kB/s, 60 events/s |
| Proximity events | 12.5/s | 5.9/s |
| UI | 55 fps, frame p95 33.3 ms, main thread 58 % busy | 59 fps, frame p95 16.8 ms, 48 % busy |
| Robot → browser latency p99 | 72 ms | 75 ms (unchanged) |

Caught on the way: the backend put the new `stateFromMessage` flag inside the robot, the UI builder read it
from the event; each side's unit tests used its own idea of the shape, so only the real-browser e2e tests
failed (robots showed UNKNOWN). Fixed, and a shared contract fixture now ties both sides
(`contracts/live_message_event.json`). An intermediate load run that looked like a big UI win (13 % busy)
was the broken build rendering nothing; the numbers above are from the fixed build.

Verified: backend 282, simulator 337, frontend 59; e2e 22/22 (2.1), 22/22 (3.0), 25/25 (2.1 with login);
load test 18/18 at 10, 25 and 50 robots. Load test runs weekly in CI (`load.yml`, D-39).

## Week 3 second review (12 Oct, D-36)

At the founder's request, after Week 3 was committed: three fresh reviews (code quality, security,
correctness of the first review's fixes) plus bandit and radon.

| Severity | Finding | Fix |
|---|---|---|
| High | `extend` refused forever after one rejected or lost update ("retry in a moment" never helped) | Next id from the robot's state; "in flight" lasts 5 s |
| Medium (security) | A robot's own map name copied into node 0 could make the backend publish an order over the broker limit → backend disconnected | Robot values validated before reuse; every publish size-checked (422 / skip) |
| Medium (security) | Crafted session file passed the replay live check and could fake a live robot's state | Live key from the published topic; ids validated; injection topics checked |
| Medium | Long ids could still push a robot's state over the broker limit | Ids ≤ 128; final size guard |
| Medium (quality) | `simulator/robot.py` 1,131 lines, maintainability C (0.00), 10 complex functions | Split into 6 modules with a version profile; all A, 3 functions at CC 11 |
| Low | Robot-reported sequence ids not type-checked (500 / wrong stitch); order memory unbounded, could evict the running order; simulator parsed without D-31 limits; huge ints crashed validation; unlocked header counter; lone surrogate could break a publish | Fixed, each with a test |
| Low (UI) | Paused robot looked stuck; one cancel's state overwrote another's | PAUSED badge; per-robot state |
| Found on the way | `python3 main.py` (README) spun forever since the Week 3 start-node rule | Fixed; smoke test |

Order caps: a valid order with 1,000 nodes would give a 425 KB state, so the simulator caps nodes, edges
and actions at 300 each (largest state < 200 KiB). Every new test failed on the code before its fix.
Verified: backend 269, simulator 333, frontend 46; ruff, oxlint, tsc, build; e2e 22/22 (2.1), 22/22 (3.0),
25/25 (2.1 with login).

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
  - [x] First batch of 10 personalised drafts ready (private: the private company folder (not in git), tracker rows `to contact`); sending is the founder's

Proposed focus for the coming weeks (each week's plan objective + hardening of what was built early).
Struck-through items are already done:

| Week | Proposed engineering focus |
|---|---|
| 2 | ~~End-to-end tests in CI; fix battery-at-0; reconnect behaviour~~ (done 10 Oct, see Week 2 above) |
| 3 | ~~`instantActions` cancelOrder (the "cancel" in *cancel, reroute or escalate*); order updates (`orderUpdateId`)~~ (done 12 Oct, D-35) |
| 4 | ~~Load test 10/25/50 robots (CPU, message rate, UI frame rate)~~ (done 12 Oct, D-38); ~~decide whether to model traffic/near-collisions~~ (D-22: detect, never avoid) |
| 5 | ~~Version-aware validation with the official 2.1.0 and 3.0.0 schemas, chosen by topic~~ (D-15, D-20); ~~offline validation of session files~~ (done 13 Oct, D-40) |
| 6 | ~~Remaining failures: low battery, disconnect, invalid payload~~ (done 13 Oct, D-42); timeouts and safety stops (`fieldViolation`) left out (not in the plan's list) |
| 7 | ~~Session size limits~~; ~~retention; upload a session someone sent you~~ (done 13 Oct, D-41); ~~streaming replay~~ |
| 8 | ~~Record the demo video ([DEMO.md](DEMO.md)); polish README; publish~~ (done 13 Oct, D-43; voice-over by the founder) |

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
| Backend API | 438 unit/API tests (pytest), run in CI, including a shutdown test under a real uvicorn server | |
| Simulator | 391 tests (pytest, incl. conformance against the official 2.1.0 and 3.0.0 schemas), run in CI | |
| Python style | `ruff check` + `ruff format --check` in CI (backend, simulator) | |
| Frontend | Type check, lint, 96 unit/component tests (incl. the shared backend contract fixtures) (`npm test`, incl. malformed robot data, both VDA versions, login, nothing opened before the session check) and production build, in CI; real-browser tests in the e2e suite (below) | |
| MQTT flow | Automated against Mosquitto in Docker (`tests/e2e`) | |
| Shutdown | Automated in `tests/e2e` (broker first, then backend; recording gets its end line) and `backend/tests/test_shutdown.py` | |
| Docker stack, end to end | **Automated** (`tests/e2e`, 37 tests incl. 3 in Chromium via Playwright, 5 for Week 3 orders, 4 for session validation and upload and 7 for failure injection, in CI for VDA 2.1, 3.0 and 2.1 with login): health, state every second, mission state machine, BLOCKED_PATH, near-collision warning, validation clean, record/replay, last will on kill, broker restart recovery, shutdown with open recording; in the browser: live robots, map and stream over a real WebSocket, a mission sent from the form completes, login screen refuses a wrong token, no console errors | Browser tests use the local plain-HTTP UI, not HTTPS (D-29) |
| P-1042 scenario (mission → block → clear → complete) | E2E, several times | |
| Record → replay | E2E; replay timing matched the recording within ~25 ms at 5×. Size limit stops a recording by itself (unit test); replay streams the file (unit test: 25 MB file, peak memory under 5 MB). Retention and upload (D-41): unit tests incl. round trips of recordings made from real traffic; e2e: download → upload → validate, replay of an uploaded file refused while robots are live (D-36), bad uploads refused, 1.7 MB upload through nginx | |
| Validator | Official VDA 5050 2.1.0 schemas (D-20); real and generated messages in every mission state pass them; planted bad messages flagged; e2e: all live traffic clean. 3.0.0 schemas on `v3` topics (D-15), tested with valid 3.0 messages and 2.1 messages on a `v3` topic. Offline validation (D-40): unit tests show message-by-message parity with the live hub; e2e: a recorded session validates with no errors | Near-collision warnings and pre-recording header history are not part of offline validation (by design) |
| 10/25/50 robots with missions | Load test (`tests/load`, D-38): all 18 thresholds met at every size; at 50 robots cadence p99 1.03 s, robot→browser p99 75 ms, backend CPU 10 %, UI 59 fps (p95 frame 16.8 ms), nothing dropped | Weekly in CI (`load.yml`, D-39); 50 robots is the simulator maximum |
| State every second (Week 2) | Measured on the real stack, 75 s windows with missions: 1, 10 and 50 robots; worst interval 1.068 s, p99 ≤ 1.064 s, no headerId gaps, drift 0, at most one message per 0.1 s tick; one retained factsheet per robot | Not automated (scratch script); 50 robots is the simulator maximum |
| Dependencies and images | `pip-audit` (backend, simulator, e2e), `npm audit`, `trivy` images and Dockerfiles: 0 known HIGH/CRITICAL; automated weekly and on dependency changes (`security.yml`, D-39) | `bandit` still by hand |
| Security (D-18, D-23–D-28, D-31, D-32) | E2E: MQTT logins and ACL (spoofing refused, incl. own serial under another manufacturer; old serial-only login refused), Host/Origin checks, nothing works without a session in login mode, plain ports unreachable from the LAN, TLS refuses clients that do not trust the CA | |
| Near-collisions (D-22) | 8 unit tests (incl. 3.0 positions, offline robots, two robots sharing a serial); e2e: two robots at the same spot raise one warning | |

## Open issues and technical debt

Open from the full audit (D-50): none. Per-user identity and an audit trail (A3): done 17 Oct, D-56;
metrics (A6): done 17 Oct, D-57;
published images (A7): done 17 Oct, D-58. (A5, versioned scenario format and a compatibility promise:
done, D-54. The session-id generators merged and the simulator's unreachable edge-action code removed: done 17 Oct.)

Open from the product audit (D-47), checked 14 Oct, with the recommended order:
(Items 1 and 2 done in Week 11, D-48.)
1. **Replay against a fleet manager**: checked, it works (simulator stopped, as replay requires; a
   `master@` client received all 105 robot messages of the recorded P-1042 incident, pathBlocked included, no
   commands). Two limits: timestamps are the original ones (a fleet manager checking freshness may drop them),
   and it is open-loop (robots in a replay cannot react to the fleet manager). Recommended for Week 11: a
   replay option that stamps messages with the current time.
2. **Timeouts**: not injectable. Recommended for Week 11: an `UNRESPONSIVE` failure (stays ONLINE, stops
   publishing state, ignores commands for N s); the simulator's publisher already gates state per robot.
3. **Site traffic**: done in Week 12 (D-49), `actunode import`; recommended first a capture import (offline, read-only, a customer can send a file):
   `mosquitto_sub -h <site> -t 'uagv/#' -F '%U %t %p' > capture.txt` → `actunode import` → a session file to
   upload, validate and replay. A live broker bridge (mosquitto 2.1 supports it, `in` direction only, so
   ActuNode could never command site robots) only when a user asks for it.
4. **Duplicate missions**: no detection today. Recommended after asking users how duplicates show up: a
   validator warning when two robots run orders that pick the same `loadId`.

Numbered so they can be referenced from commits. Remove an item only when it is fixed and verified; numbers are never reused (fixed: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24).

| # | Issue | Impact | Plan |
|---|---|---|---|
| — | No open issues (21–24 closed 12 Oct, D-39) | | |

## Session log

Newest first. One entry per work session: what was done, what was learned, what is next.

### Sat 24 Oct 2026: v0.4.0 released
The release the hosted service deploys (Terraform's default `release`, `prod-up.sh`'s `ACTUNODE_RELEASE`). Version
0.4.0 in the backend, CLI, frontend, the CI template (`ref: v0.4.0`), the provisioner's and the deploy compose
file's default lab version, and the README's published-images example; changelog with upgrade notes (pull or
rebuild; nothing else changes for a self-hosted lab). Gate on the release commit's parent: backend 671, simulator
465, CLI 232, cloud 105, frontend 176 tests passing, typecheck and lint clean, CI green. Still a preview (PR-12,
PR-13 open). The founder tagged it (f36e5a2) and published the release; all four images pull anonymously from ghcr.io at
0.4.0. On the tag one e2e cell timed out waiting for robots after a simulator restart and passed on rerun (the
same commit was green on main). The security scan then failed on three undici advisories published that day
(test-only, through jsdom; not in any image): updated on main (29f0415). Frontend tests flaked on this host under
a load average of 21 (Testing Library's 1 s wait); the wait is now 5 s (899f702), 4 of 4 runs green under the
same load.

### Wed 21 Oct 2026 (later): what is missing before outside users, checked
Asked what we are missing before users or engineers use the hosted service. Verified, not guessed: **CI could not
reach a hosted lab**: every lab has an API token the runner accepts, but no page showed it; built a "Run scenario
tests from CI" section (owners and operators: show the token on demand, rotate it with confirmation; the rotation
restarts the lab's backend), provisioner routes, tests, and a local check that runs `actunode test` through the
edge with the token. Verified a publishing robot keeps a lab awake (65 s against a 30 s limit) and silence puts it
to sleep. Capacity estimate written down (about 12 labs at their caps on a 16 GB server; measure before more than
ten workspaces). Still needing the founder: real GitHub/Google sign-in, a first real deployment and restore on a
server, terms and privacy text. Not blocking a closed beta: no invitation email, no screen reader pass on the
control plane pages, an upgrade ends lab sessions.

### Wed 21 Oct 2026: the hosted pages and the lab's reporting, checked in a browser
Asked to check the sign-in and the other pages and make the reporting better. Screenshots of every control plane
page (headless Chromium; the Chrome extension cannot attach to the local self-signed site) and of the lab itself.
**Found: the hosted lab had no live feed at all** ("Live: offline", no robots): the frontend's nginx forwarded its
own scheme (http) and Traefik names a WebSocket upgrade's protocol `wss`, so the backend's cross-site check refused
every WebSocket from a hosted lab; the check script never saw it because curl sends no Origin. Fixed in nginx (map
https/wss/http/ws) and normalised in the backend, with tests; the local check now does the handshake and a
browser-origin POST through the edge. Also fixed: a redirect loop for a few seconds after a lab wakes (the control
plane reached it before the edge routed to it): a "Connecting you" page instead. Control plane pages: state badges
(Running, Asleep, Waking up, Could not start) instead of database words, "0 minutes" (30 s rounded down) now "30
seconds", a spinner on waiting pages, an error box, 44 px controls on phones, aligned footer and copy rows. The
lab's Activity panel: plain-words actions and OK/Refused/Error badges instead of red HTTP codes on every row (176
frontend tests). Self-hosted e2e (security, users, browser) green on the new nginx.

### Wed 21 Oct 2026 (early): phase 2 built: upgrades, backups and a restore drill, alerts (D-62)
Upgrades of all workspace labs (provisioner `upgrade`, run by the deploy scripts; verified: the running labs were
recreated, the sleeping ones re-rendered). Backups (`backup.sh`: online SQLite copy, every lab's secrets volume,
workspace folders, secrets; daily timer; optional off-site copy by rclone), `restore.sh`, and `restore-drill.sh`,
which **passed 11 of 11** on the local stack: back up, destroy everything (control database and lab secrets volumes
gone), restore, start, the database and alpha back, the robot connects with its old password, recordings back.
`healthcheck.sh` every 5 minutes with webhook alerts (8 of 8 locally). Found by the drill and fixed: a freshly
restored database volume was root-owned (the control plane could not write its journal); a restored database says
"ready" for labs whose containers are gone, and Open lab bounced between the lab's address and the wake page (now it
wakes an unreachable ready lab); a fourth review finding (a member removed at the same instant as deleting their
account could take the workspace with them) fixed with a test. Scripts hardened: tolerant polling through the
few seconds between a recreated lab and the edge seeing it; the check wakes the labs before the robot steps.
A fifth review finding: the off-site copy was plaintext; archives are now age-encrypted to a public key kept off the
server (tested: encrypt, decrypt and list, wrong key refused, plaintext off-site copy refused). The standard local
check passed 29 of 29 after the drill. **Phase 2 of D-61 is built**; what remains needs the founder: an off-site backup target, the alert webhook, an
outside uptime monitor, terms and privacy text, then the first invited users. Cloud 89 and backend 669 tests; the
deep review for the phase 2 gate was done inline (no open finding). CI green on every push of this session.

### Tue 20 Oct 2026 (night): phase 2 continued: account deletion, abuse limits, two review findings
Account page and deletion (D-61 phase 2, customer data): sole-owned workspaces go with the account, shared ones are
left, identities and sessions deleted, a failed lab deletion keeps the account. Abuse limits at the edge (rate
limits per address for the app and the labs, a 64 KB form cap, 100 MQTT connections per address) and 50 logins per
workspace in the provisioner. Review findings fixed with tests: the public health answer revealed whether a lab was
in use (now a signed single-use status token per poll); leaving a shared workspace was check-then-remove (now one
statement, also for "Remove"); deleted handles are retired so a later holder of the login is told apart in the
labs' audit trails. Local check extended (account page, flood slowed, big form refused). CI: the e2e flake on
b7f86c3 passed on rerun; 262c310 green.

### Tue 20 Oct 2026 (later): hosted service phase 2, idle labs stop and wake
Phase 2 of D-61 started with the items that need no founder accounts. Built: a hosted lab reports `idleSeconds`
(backend: signed-in requests, the live feed, external robot or fleet manager messages and commands count; the lab's
own simulator does not); the control plane stops labs idle for 30 min (settings `ACTUNODE_IDLE_STOP_S`,
`ACTUNODE_IDLE_SWEEP_S`), **Open lab** wakes a stopped lab (an atomic state change, so two people wake it once), a
stopped lab's own address falls back to the wake page at the edge, a wake lost in a restart is settled by the sweep.
Found by the local run: **the edge and the control plane lost every workspace's front network when recreated**
(an upgrade): labs unreachable, revocation failing. Fixed: the provisioner re-attaches them on request, at control
plane start and before every sweep. Local check 26 of 26 with `ACTUNODE_IDLE_STOP_S=30` (asleep, fallback, no robot
connections while asleep, wake, robot back). Cloud 74 and backend 659 tests, lint clean. CI on b7f86c3: one e2e cell
failed in a fleet manager scenario (green for the previous eleven runs; the cloud change cannot reach it); rerun
requested. Next: account deletion, abuse limits, upgrades of all workspaces, backups and a restore drill.

### Tue 20 Oct 2026: hosted service, security review round 6
Two findings in the new login pages, fixed with tests: **cross-workspace path traversal** (a login name such as
`x/../../globex` in the remove form became `DELETE /workspaces/globex` at the provisioner; now checked by kind before
any call, and the client percent-encodes every path segment) and **credential disclosure** (adding an existing login
returned its current password, because mqtt-init keeps and prints it; the provisioner now answers 409 and the page says
to remove it first). Known and accepted: two operators of the same workspace adding the same name at the same instant
can still get past the exists check (one extra listing per add; no cross-workspace effect). Cloud suite 62 passing,
lint clean. Still waiting on the founder's Hetzner/DNS/OAuth accounts and the v0.4.0 release.

### Mon 19 Oct 2026 (night): hosted service phase 1 (D-61)
The founder chose a shared online service on actunode.com (Hetzner EU, GitHub/Google sign-in, billing after the
beta). Built: lab SSO, control plane, provisioner, Traefik edge, local stack, Terraform. Five rounds of security
review findings fixed with tests (login CSRF, identity confusion, cookie injection, content injection, stale
identities). Local end-to-end check: 16 of 16 (two people, two isolated workspaces, SSO, a robot over TLS by SNI,
cross-workspace attempts refused). Waiting on: the founder's Hetzner/DNS/OAuth accounts and the v0.4.0 release.

### Mon 19 Oct 2026 (evening): the founder used the lab as a user
Login on (`.env`, now ignored by git), personal accounts `rupert` (operator) and `guest` (viewer) made with
`mqtt-init add-user`; tokens kept in docs/company/ (private). The founder logged in through the browser and went
through mission, blocked path and clear, recording, the Activity panel, the viewer's read-only view and removing a
user: everything behaved as described. An author's own run: it does not count for PR-12 (a newcomer, unassisted).

### Mon 19 Oct 2026 (later): kits for the work that needs people
docs/research/SCREEN_READER_CHECK.md (17 checks for Orca, NVDA or VoiceOver), ONBOARDING_STUDY.md (package J:
participants, script, observation sheet, consent, target) and PILOT_GUIDE.md (package K: agreement, steps, report).
Invitation drafts for both are in docs/company/ (private, not in git).

### Mon 19 Oct 2026: package I, accessibility and interaction review
The design brief's checks run on the v0.3.0 UI (Playwright: screenshots at four sizes, accessible names, a keyboard
walk, token contrast; and a line-by-line comparison with the brief). Fixed with tests: field contrast (3:1),
announcements, reduced motion, message-stream keyboard, and fourteen brief items (copy, units, unknown values, busy
states). Written up in docs/ACCESSIBILITY_REVIEW_2026-10-19.md; open: a screen reader pass, long session lists. The
builder agents hit their usage limit midway; the second batch was done in the main session.
Then D-60 (skip links; the session actions one Tab stop: 25 stops for the whole page on a lab with 100+ sessions).
CI was red on d75b0a2, 1fa786c and 567f3dd: the browser e2e test looked for the stream as an ordered list and for
the old "Sent" wording, which the unit tests do not see. Fixed in d6524ad (the stream is an `ol` again; the test
expects "Order published"); the full e2e suite passed locally first and CI is green. Rule kept: a change to UI
structure or copy runs the browser e2e locally before it is pushed.

### Sat 17 Oct 2026 (night): product specification brought up to date; load re-measured
The founder's product documents (docs/product/, written 15 Oct) updated to v0.3.0: requirement status (PR-11 done,
PR-12 in progress, PR-13 open), PR-15..17 and TR-10..12 added, the implementation plan now runs toward v0.4.0
(packages H–M). ARCHITECTURE.md brought up to D-59. Package H done: load test on 17 October at fa08f92 (v0.3.0 code): every threshold passed at 10/25/50 robots with the browser; 50 robots: WebSocket latency p99 130 ms of 250, 60 frames/s, 0 console errors, 0 drops, backend memory 50 MiB of 300.

### Sat 17 Oct 2026 (evening): v0.3.0 released
Per-person logins and audit trail (D-56), metrics (D-57), published images (D-58), robot-scoped scenario checks
(D-59). Gate on 238509e: CI, ROS 2 workflow, image build, security scans all green. The founder tagged and published;
the tag built and pushed the four images (amd64, arm64), made public; `gh attestation verify` confirms they were built
by images.yml from v0.3.0 at 238509e, and the published backend reports 0.3.0.

### Fri 16 Oct 2026 (evening): ROS 2 robot fixes (D-55)
Patches for the example adapter and the connector; 9/9 with them; raw checks script corrected; upstream drafts
reworked into PRs; then the map check (3/3); then the last two bugs (4/4) and five upstream PRs.

### Sat 17 Oct 2026: upstream pull requests opened; v0.2.0 published
The founder opened [ros_amr_interop #82](https://github.com/inorbit-ai/ros_amr_interop/pull/82), [#83](https://github.com/inorbit-ai/ros_amr_interop/pull/83), [#84](https://github.com/inorbit-ai/ros_amr_interop/pull/84), [#85](https://github.com/inorbit-ai/ros_amr_interop/pull/85) and [vda5050_adapter_examples #14](https://github.com/inorbit-ai/vda5050_adapter_examples/pull/14) (awaiting review; first-time contributor, so upstream CI waits for a maintainer). Release v0.2.0 published, tag on the verified commit 6c234f2.

### Fri 16 Oct 2026 (later): Week 16 and the 0.2.0 release candidate (D-54)
Getting started, compatibility promise, triage routine, scenario format version, version 0.2.0 (6c234f2). Gate passed:
fresh clone followed the guide (pass and fail both as documented), CI green in every configuration. Tag and release
left for the founder.

### Fri 16 Oct 2026: Week 15 (D-53)
- Failure catalogue, scenario gallery, message flows from recordings; two private blog drafts.

### Thu 15 Oct 2026 (later): Week 14 (D-52)
- Conformance suite and raw checks; the connector's report with spec citations; upstream drafts (not filed);
  connect-your-robot guide. ROS 2 e2e 4/4.

### Thu 15 Oct 2026: Week 13 (D-51)
- Researched ROS 2 VDA 5050 connectors (InOrbit's maintained; TUM's 1.1/ROS 1). Built the `ros2` profile; ActuNode
  drives the Nav2 robot; eight connector deviations recorded for Week 14. e2e 3/3 on an isolated stack.

### Wed 14 – Thu 15 Oct 2026: full audit of weeks 0–12 (D-50)
- Six parallel reviews, an architecture review, five parallel fix workers, full gate. All suites, e2e in three
  configurations, the load test and the attack probes green on the final code.

### Wed 14 Oct 2026 (evening): Week 12 (D-49)
- Docker scenario runner, CI job `scenarios`, GitHub Actions template, `actunode import`. Gate green in all
  three e2e configurations.

### Wed 14 Oct 2026 (later): Week 11 (D-48)
- Example fleet manager and the blocked-path reaction scenario; `UNRESPONSIVE`; replay with current time;
  any-of message checks; `never` window. Four policies checked live; races found and fixed (see Week 11).

### Wed 14 Oct 2026: product audit (D-47)
- Checked the product against the company plan, hands-on: AMR-vendor path works; an outside fleet manager could
  not connect at all. Added `master@<name>` logins (`add-master`), e2e in three configurations.
- Black-box attacks (19), all suites, pip-audit, npm audit, bandit. Fixed: security headers, npm engine check.
- docs/USE_CASES.md: each user's path and what works today. Three gaps recorded for the decision point.

### Tue 13 Oct 2026 (later still): Week 10 (D-46)
- `for`, `never`, message expectations from the live feed, every run recorded; five sample scenarios passing on
  the real stack. Decision point reached; Week 11 next unless user conversations reorder.

### Tue 13 Oct 2026 (late night): Week 9 built (D-45)
- `actunode test` and the scenario format (`cli/`); P-1042 as `scenarios/p1042_blocked_path.yaml`, passing on
  the real stack in all three CI configurations; CI job for the runner; pip-audit covers it.
- Quality gate: four findings fixed with tests (YAML aliases, coerced failure params, redirects, empty
  order id); scenario e2e re-run on VDA 2.1 and 3.0 after the fixes. Week 9 done. Next: Week 10.

### Tue 13 Oct 2026 (night): release published; Phase 2 planned (D-44)

- GitHub Release v0.1.0 published on the founder's behalf (gh CLI, device login authorized by the founder);
  private vulnerability reporting enabled (SECURITY.md relies on it).
- Phase 2 written into PLAN.md (weeks 9–16) from the plan's six-month milestones; decision point after Week 10.

### Tue 13 Oct 2026 (evening): Week 8 and v0.1.0 (D-43)

- Founder chose Apache-2.0 and approved tagging v0.1.0 after verification.
- The demo video is recorded by a script from the real UI; the founder adds the voice-over.
- Two bugs found by checking the docs against reality (Docker env pass-through; stale stop response).
- All 8 weeks complete.

### Tue 13 Oct 2026 (later): Week 6 finished (D-42)

- The spec settled the open error-level question: 3.0 names low battery as its URGENT example and defines
  CRITICAL as "cannot continue its order but can take new ones" (a blocked path).
- E2E confirmed on the real broker that an abrupt disconnect publishes the last will; review fixes made
  the disconnect stop freezing every simulated robot.
- A builder dropped out on a network error mid-task; resumed with its context, its half-written tests
  were the red phase.
- My own doc bug from 11 Oct (Week 6 row deleted instead of issue 6) found and fixed.
- Weeks 1–7 complete. Next: Week 8 (demo video, README, publish).

### Tue 13 Oct 2026: Weeks 5 and 7 finished (D-40, D-41)

- Designed first, built test-first (backend, UI), then a security review and a correctness review in
  parallel; every confirmed finding fixed with a regression test (table above).
- Lesson: tests must round-trip real data. Recordings made from real traffic exposed four upload and parity
  bugs that tests with hand-written files missed.
- My retention design was wrong for uploads (an upload could evict other people's sessions); uploads now
  never delete anything.
- Also corrected: the backend test count in the verification table was stale (282, should have read 291
  after D-39); now 389.
- Next: Week 6 (low battery, disconnect, invalid payload failures), then Week 8.

### Mon 12 Oct 2026 (night): code-quality backlog closed (D-39)

- Issues 21–24 fixed in parallel (backend, UI, CI), test-first; the shared contract fixture now also carries
  `validationEpoch`. Security scans and the load test run in CI on a schedule.
- Next: Week 5 and Week 7 quality gates.

### Mon 12 Oct 2026 (evening): Week 4 (D-37, D-38)

- Load test built and run; code review in parallel; fixes in three parts (backend, simulator, UI).
- Lesson 1: a contract between two codebases needs a shared fixture, not two sets of unit tests.
- Lesson 2: a performance number from a broken build is not a result; re-measure after every fix.
- Week 4 complete. Next: code-quality backlog (issues 21–24, load test in CI), then Weeks 5 and 7 gates.

### Mon 12 Oct 2026 (later): Week 3 second review (D-36)

- Three fresh reviews and the scanners found the items in the table above; fixed in two phases (bugs and
  security first, then the behaviour-preserving split of the simulator), test-first, each red claim
  checked against the committed code.
- Lesson: the Week 3 start-node rule broke the README's offline demo and no test covered it; it does now.
- Week 4 starts when the founder says so.

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
