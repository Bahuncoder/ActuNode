# ActuNode build tracker

Source: *Company Vision & Full Execution Plan* (docs/company, not in git).

## Week 1: "What to build this week"

- [x] **Day 1**: Git repo, Docker Compose with Mosquitto, FastAPI skeleton, React app
- [x] **Day 2**: Robot simulator process: `robot_id`, `x`, `y`, `battery`, `mission_status`, MQTT status publishing
- [x] **Day 3**: Mission sender endpoint + state machine `IDLE → ACCEPTED → MOVING → COMPLETED`
- [ ] **Day 4**: Robots on a web page + raw MQTT message stream
- [ ] **Day 5**: One failure: `BLOCKED_PATH`, shown in the UI and logged
- [ ] **Day 6**: Record messages to a JSONL session file
- [ ] **Day 7**: Replay the JSONL file + short demo video

**Definition of done:** a friend can clone the repo, run one command, open a local URL,
create three robots, send one mission, inject one failure, and replay the session.

## Eight-week plan

| Week | Objective | Output |
|---|---|---|
| 1 | VDA 5050 concepts, MQTT topics, AMR state machines | Notes + message schemas + Docker Mosquitto |
| 2 | One fake AMR with battery, pose, state | Robot publishes status every second |
| 3 | Mission sender + state transitions | Move job from start to destination |
| 4 | 5-10 robots + simple warehouse map | Multi-robot screen with location/state |
| 5 | Message inspector + validation | Readable message stream + errors |
| 6 | Failure injection | Blocked path, low battery, disconnect, invalid payload |
| 7 | Record/replay | Session file can reproduce incident |
| 8 | Demo + README + 3-minute video | GitHub repo + pitch demo |

## Demo scenario

WMS job: move pallet **P-1042** from **Receiving Door 2** to **Storage A17**.
ActuNode turns it into a robot mission, publishes it, updates robot status, shows the route,
records every event. Then: inject a blocked path and verify the system cancels, reroutes or escalates.

## Guardrails (from the plan)

- Engineering tool first (logs, messages, replay), **not** a pretty fleet dashboard.
- VDA 5050 / MQTT only at the start. One workflow, done well.
- Keep schema/version support modular (VDA 5050 3.0 is new and will evolve).
- Ship something public every Friday.
