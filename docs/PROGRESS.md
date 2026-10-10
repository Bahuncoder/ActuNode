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
| **Last updated** | Sat 10 Oct 2026 (late evening) |
| **Status** | Ahead on features, catching up on verification. The Docker stack now runs the full definition-of-done scenario end to end; there are still no end-to-end tests in CI. |
| **Working rule** | Follow the calendar. Being ahead is not a reason to start the next week's features: spare time goes into hardening, verification, documentation and user conversations. |

## Schedule

Week 1 started on Friday 9 October 2026 (Day 1). Each week runs Friday to Thursday.

| Week | Dates | Plan objective | Plan output | Feature state | Quality state |
|---|---|---|---|---|---|
| **1** | 9–15 Oct | VDA 5050 concepts, MQTT topics, AMR state machines | Notes + message schemas + Docker Mosquitto | ✅ Done | ✅ Docker stack verified end to end (10 Oct) |
| 2 | 16–22 Oct | One fake AMR with battery, pose, state | Robot publishes status every second | ✅ Built early (Day 2) | 🟡 Battery-at-0 bug; no automated E2E tests |
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
- [x] **Run the Docker Compose stack end to end**: definition of done passed on 10 Oct (record → mission → block → clear → replay, UI via nginx)
- [ ] Confirm `curl localhost:8000/api/health` works from a normal terminal (open issue 15)
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
| Backend API | 66 unit/API tests (pytest), run in CI, including a shutdown test under a real uvicorn server | |
| Simulator | 34 unit tests (pytest), run in CI | |
| Frontend | Type check + lint + production build in CI; E2E by headless-Chrome screenshots | No automated UI tests |
| MQTT flow | E2E against amqtt (9 Oct) and **Mosquitto in Docker** (10 Oct) | Not automated |
| Shutdown | Reboot reproduced by stopping the broker first, then simulator and backend: both exit 0 in ~1 s, open recording closed with its end line; normal stop leaves all robots OFFLINE | Not automated in Docker |
| Docker stack | `docker compose build` in CI; `docker compose up` run by hand on 10 Oct: definition-of-done scenario passed, UI and WebSocket through nginx, 0 validation issues on 182 messages | Not automated; host access to port 8000 unconfirmed (issue 15) |
| P-1042 scenario (mission → block → clear → complete) | E2E, several times | |
| Record → replay | E2E; replay timing matched the recording within ~25 ms at 5× | |
| Validator | Real recorded messages produce 0 issues; 8 kinds of planted bad messages all flagged | Schemas not compared with official ones |
| 10 robots, 6 concurrent missions | E2E screenshot | No load test |

## Open issues and technical debt

Numbered so they can be referenced from commits. Remove an item only when it is fixed and verified; numbers are never reused (fixed: 1, 2).

| # | Issue | Impact | Plan |
|---|---|---|---|
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
| 15 | From the dev machine, `127.0.0.1:8000` (backend published port) accepts connections but never answers, while the LAN address `192.168.1.151:8000`, port 8080 on loopback, and container-to-container calls all work. Seen from the assistant's sandboxed shell; not yet checked from a normal terminal | API docs at localhost:8000/docs may be unreachable; the UI is unaffected (it uses 8080) | Run `curl -m 5 localhost:8000/api/health` in a normal terminal; if it hangs there too, investigate Docker's port forwarding |
| 16 | No linter or formatter configured for Python (no agreed line length; the IDE flags E501 against the default 79) | Inconsistent style creeps in | Add `ruff` with the project's line length to CI; Week 1/2 |

## Session log

Newest first. One entry per work session: what was done, what was learned, what is next.

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
