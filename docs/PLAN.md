# ActuNode build plan

The plan as written in *Company Vision & Full Execution Plan* (October 2026; kept in `docs/company/`,
not in git). This file is the reference and does not track status. **Progress is tracked in
[PROGRESS.md](PROGRESS.md).**

## First-week sprint: "What to build this week" (plan p. 15)

- **Day 1**: Git repo, Docker Compose with Mosquitto, FastAPI skeleton, React app
- **Day 2**: Robot simulator process: `robot_id`, `x`, `y`, `battery`, `mission_status`, MQTT status publishing
- **Day 3**: Mission sender endpoint + state machine `IDLE → ACCEPTED → MOVING → COMPLETED`
- **Day 4**: Robots on a web page + raw MQTT message stream
- **Day 5**: One failure: `BLOCKED_PATH`, shown in the UI and logged
- **Day 6**: Record messages to a JSONL session file
- **Day 7**: Replay the JSONL file + short demo video

**Definition of done:** a friend can clone the repo, run one command, open a local URL,
create three robots, send one mission, inject one failure, and replay the session.

## Eight-week build plan (plan p. 7)

Week 1 starts Friday 9 October 2026; each week runs Friday to Thursday.

| Week | Dates | Objective | Output |
|---|---|---|---|
| 1 | 9–15 Oct | Study VDA 5050 concepts, MQTT topics, AMR state machines | Notes + message schemas + Docker Mosquitto |
| 2 | 16–22 Oct | One fake AMR process with battery, pose and state | Robot publishes status every second |
| 3 | 23–29 Oct | Mission sender and state transitions | Move job from start to destination |
| 4 | 30 Oct – 5 Nov | Simulate 5–10 robots and a simple warehouse map | Multi-robot screen with location/state |
| 5 | 6–12 Nov | Message inspector and validation | Readable message stream + errors |
| 6 | 13–19 Nov | Failure injection | Blocked path, low battery, disconnect, invalid payload |
| 7 | 20–26 Nov | Record/replay | Session file can reproduce incident |
| 8 | 27 Nov – 3 Dec | Publish demo + README + 3-minute video | GitHub repo + pitch demo for friends/integrators |

## After the eight weeks: six-month milestones (plan p. 8)

1. **Developer credibility**: easy to run, documented message flow, sample scenarios, blog posts, failure cases.
2. **Real integrations**: connect one real AMR or open-source robot stack (ROS 2 demos, open-source simulation, a low-cost robot).
3. **Automated tests**: scenarios become test suites; `robotlab test` validates an integration.
4. **First external users**: system integrators, robotics clubs, warehouse engineers, small AMR vendors.

## Phase 2: weeks 9–16 (written 13 Oct 2026, D-44)

The eight-week plan ended with v0.1.0. Phase 2 turns the six-month milestones above into weeks, in this
order: scenario tests first (milestone 3: the product step that needs no hardware), sample scenarios on top
of them (milestone 1), then one real open-source robot stack (milestone 2); milestone 4 (first users) runs
alongside through outreach. Dates continue the calendar for reference only: a week is done when its work
and its quality gate are done (D-30). **Decision point after Week 10:** what the first user conversations
say can reorder weeks 11–16.

| Week | Dates (reference) | Objective | Output |
|---|---|---|---|
| 9 | 4–10 Dec | Scenario format and runner | A scenario file (YAML: steps such as send mission, inject failure, wait; expectations such as robot status, error, connection, validation rule) and an `actunode test` command that runs it against the stack, with readable and JUnit XML output and exit codes. The P-1042 incident passes as a scenario. |
| 10 | 11–17 Dec | Expectations and sample scenarios | "Within N s" / "never" timing semantics, expectations on messages (topic + JSON pattern), every run recorded as a session; five sample scenarios (P-1042, low battery during a mission, disconnect during a mission, invalid traffic, cancel and resume) shipped in `scenarios/`. Decision point. |
| 11 | 18–24 Dec | Testing a system under test | Scenarios that check what an external master control does when ActuNode's simulated robots misbehave (e.g. "after pathBlocked, the master sends cancelOrder or an order update within 10 s"): ActuNode simulates the robots, an external fleet manager sends the orders. Output: the plan's demo question "does the system cancel, reroute or escalate?" answered by a scenario. |
| 12 | 25–31 Dec | Scenarios in CI | A Docker-based runner (`docker compose run … actunode test scenarios/`) and a GitHub Actions example; ActuNode's own CI runs the sample scenarios. |
| 13 | 1–7 Jan | Real stack, part 1 | A ROS 2 simulated robot (Nav2, headless) behind the open-source VDA 5050 connector, as an optional Docker profile; ActuNode sends it a mission and validates its traffic. |
| 14 | 8–14 Jan | Real stack, part 2 | The sample scenarios run against the ROS 2 robot; a conformance report of what passes and fails (and upstream reports where the connector deviates from the spec); a "connect your own robot" guide. |
| 15 | 15–21 Jan | Developer credibility | Failure-case catalogue, scenario gallery, message-flow walkthroughs; drafts of two blog posts for the founder to publish. |
| 16 | 22–28 Jan | Ready for external users | Onboarding path from the README to a first passing scenario, issue triage routine, v0.2.0 release. |

Each week ends with its quality gate (independent review, tests for every fix, e2e in all CI configurations,
docs), as in Weeks 1–8.

## Demo scenario (plan p. 5)

WMS job: move pallet **P-1042** from **Receiving Door 2** to **Storage A17**.
ActuNode turns it into a robot mission, publishes it, updates robot status, shows the route,
records every event. Then: inject a blocked path and verify the system cancels, reroutes or escalates.

## Weekly cadence (plan p. 12)

- **Monday**: choose the sprint objective.
- **Wednesday**: internal demo.
- **Friday**: ship something public or record a demo.
- **Weekend**: user outreach and learning (target: 30 conversations in 60 days).

## Guardrails

- Engineering tool first (logs, messages, replay), **not** a pretty fleet dashboard.
- VDA 5050 / MQTT only at the start. One workflow, done well.
- Keep schema/version support modular (VDA 5050 3.0 is new and will evolve).
- Real robot control only with safeguards; position the MVP as testing and debugging.
