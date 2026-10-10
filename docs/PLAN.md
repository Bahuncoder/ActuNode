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
