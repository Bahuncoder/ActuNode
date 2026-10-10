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
| **Last updated** | Sat 10 Oct 2026 |
| **Status** | Ahead on features, behind on verification. Most of the 8-week feature list exists as a first version; Docker has never been run end to end and there are no end-to-end tests in CI. |
| **Working rule** | Follow the calendar. Being ahead is not a reason to start the next week's features: spare time goes into hardening, verification, documentation and user conversations. |

## Schedule

Week 1 started on Friday 9 October 2026 (Day 1). Each week runs Friday to Thursday.

| Week | Dates | Plan objective | Plan output | Feature state | Quality state |
|---|---|---|---|---|---|
| **1** | 9–15 Oct | VDA 5050 concepts, MQTT topics, AMR state machines | Notes + message schemas + Docker Mosquitto | ✅ Done | 🟡 Docker stack never run end to end |
| 2 | 16–22 Oct | One fake AMR with battery, pose, state | Robot publishes status every second | ✅ Built early (Day 2) | 🟡 Battery-at-0 bug; only tested against amqtt, not Mosquitto |
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

## This week (Week 1, 9–15 Oct)

Plan objective is done. Remaining work for this week is verification and documentation, not features.

- [x] VDA 5050 notes ([VDA5050_NOTES.md](VDA5050_NOTES.md))
- [x] Message schemas ([backend/app/schemas](../backend/app/schemas))
- [x] Mosquitto in Docker Compose (config written)
- [x] Project documentation: progress, architecture, decisions, changelog
- [ ] **Run the Docker Compose stack end to end** on a real machine (needs Docker installed; see open issue 1)
- [ ] Confirm the Day 1–5 CI compose failures are understood (open issue 3)
- [ ] Read the VDA 5050 3.0 release notes and record what changes for us (open issue 9)
- [ ] Customer discovery: first outreach messages sent (plan: 30 conversations in 60 days)

Proposed focus for the coming weeks (each week's plan objective + hardening of what was built early):

| Week | Proposed engineering focus |
|---|---|
| 2 | End-to-end tests against real Mosquitto in CI (broker as a service container); fix battery-at-0; reconnect behaviour |
| 3 | `instantActions` cancelOrder (the "cancel" in *cancel, reroute or escalate*); order updates (`orderUpdateId`) |
| 4 | Load test 10/25/50 robots (CPU, message rate, UI frame rate); decide whether to model traffic/near-collisions |
| 5 | Compare our schemas with the official VDA 5050 JSON schemas; offline validation of session files |
| 6 | Remaining failures: low battery, disconnect, invalid payload, timeouts |
| 7 | Session size limits and retention; upload a session someone sent you; streaming replay |
| 8 | Record the demo video ([DEMO.md](DEMO.md)); polish README; publish |

## Verification status

What has actually been checked, and how. "Unit" = automated tests; "E2E" = the running system
exercised by hand with a real browser and MQTT traffic.

| Area | How it was verified | Gaps |
|---|---|---|
| Backend API | 65 unit/API tests (pytest), run in CI | |
| Simulator | 32 unit tests (pytest), run in CI | |
| Frontend | Type check + lint + production build in CI; E2E by headless-Chrome screenshots | No automated UI tests |
| MQTT flow | E2E against **amqtt** (Python broker) | Never run against **Mosquitto** |
| Docker images | `docker compose build` passes in CI since Day 6 | `docker compose up` never run |
| P-1042 scenario (mission → block → clear → complete) | E2E, several times | |
| Record → replay | E2E; replay timing matched the recording within ~25 ms at 5× | |
| Validator | Real recorded messages produce 0 issues; 8 kinds of planted bad messages all flagged | Schemas not compared with official ones |
| 10 robots, 6 concurrent missions | E2E screenshot | No load test |

## Open issues and technical debt

Numbered so they can be referenced from commits. Remove an item only when it is fixed and verified.

| # | Issue | Impact | Plan |
|---|---|---|---|
| 1 | Docker Compose stack never run end to end (Docker not installed on the dev machine) | The "one command" promise is unverified | Install Docker; run the [DEMO.md](DEMO.md) script; Week 1 |
| 2 | All E2E testing used amqtt, not Mosquitto | Broker-specific behaviour (retained messages, last will timing) unverified | Mosquitto in CI E2E tests; Week 2 |
| 3 | CI `compose` job failed on Days 1–5, passes since Day 6. No build-relevant file changed in between; logs need a GitHub login | Probably transient (base image pulls), but unconfirmed | Check the job logs on GitHub Actions |
| 4 | A robot whose battery reaches 0 % mid-mission stops but keeps reporting `MOVING` and `driving: true` | Wrong state; would also trip the validator's driving rule | Fix with the low-battery failure; Week 2/6 |
| 5 | No collision avoidance or traffic management; robots drive through each other | Unrealistic with many robots | Decide in Week 4 whether to model it |
| 6 | No automated frontend tests; no end-to-end tests in CI | Regressions in UI or MQTT flow are caught by hand only | Week 2 |
| 7 | Schemas are a hand-written subset of VDA 5050 2.x | May accept messages the official schemas reject, or the reverse | Compare with official schemas; Week 5 |
| 8 | Topics and messages use VDA 5050 v2 (`uagv/v2`, `2.1.0`) | 3.0 (Apr 2026) not supported | Research 3.0 first (issue 9), then decide |
| 9 | VDA 5050 3.0 not yet researched | Notes may be outdated | Week 1 |
| 10 | Backend keeps `headerId` counters in memory; after a restart its order `headerId`s start at 1 again | Validator warns `header-id` on the next order per robot | Low; persist counters or accept |
| 11 | Session files have no size limit or retention; replay loads the whole file into memory | Large sessions could exhaust memory | Week 7 |
| 12 | No authentication anywhere; Mosquitto allows anonymous clients | Fine for a laptop lab only; must not be exposed on a network | Documented; revisit before any shared deployment |
| 13 | Robot `state` is published with QoS 0, so it can be dropped; recordings capture only what the backend receives | Rare gaps in recordings | Accept for now; document |
| 14 | CI warnings: `actions/checkout@v4` uses Node 20 (deprecated); `ubuntu-latest` moves to Ubuntu 26 from 19 Oct 2026 | CI may break after the migration | Update actions; watch the first run after 19 Oct |

## Session log

Newest first. One entry per work session: what was done, what was learned, what is next.

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
