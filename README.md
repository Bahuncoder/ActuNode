<p align="center">
  <img src="docs/brand/actunode_logo_mark_square.png" width="120" alt="ActuNode logo" />
</p>

<h1 align="center">ActuNode</h1>
<p align="center"><strong>Infrastructure for autonomous machines.</strong><br/>
Simulate, test, debug and replay AMR integrations.</p>

---

ActuNode Lab is a local integration lab for autonomous mobile robots (AMRs) that talk
**VDA 5050 over MQTT**. Think *Postman + Wireshark + a test runner* for robot integrations:
simulate robots, send missions, inspect messages, inject failures, and record/replay incidents
without needing a physical fleet.

> Status: **early development, week 1 of 8.** Simulate robots, send missions, inject a failure,
> validate every message, record and replay. Verified end to end with Docker on 10 Oct 2026.
>
> **Where the project is:** [docs/PROGRESS.md](docs/PROGRESS.md).

## Quick start (Docker)

```bash
docker compose up --build
```

| Service | URL |
|---|---|
| Lab UI | http://localhost:8080 (or https://localhost:8443) |
| API docs | http://localhost:8080/api/docs |
| MQTT broker | `localhost:1883` (WebSocket `9001`) |

Your user needs access to Docker (`sudo usermod -aG docker $USER`, then log in again).
Recordings are written to `./sessions` as your user; if `id -u` / `id -g` are not `1000`, start with
`ACTUNODE_UID=$(id -u) ACTUNODE_GID=$(id -g) docker compose up --build`.

Stop with `docker compose down`. Replay needs the simulator stopped: `docker compose stop simulator`.

**Security:** the lab is reachable only from this computer (ports are published on `127.0.0.1`). The MQTT
broker requires a login: passwords are generated on first start and kept in a Docker volume (D-23).

```bash
docker compose run --rm mqtt-init show tools          # read-only login for MQTT tools (user: tools)
docker compose run --rm mqtt-init add-robot Acme amr_7   # login for a real robot (user = Acme.amr_7)
docker compose up -d --force-recreate mqtt-init mosquitto   # apply a new robot login
```

Each robot may publish only its own topics; only the backend may send orders. Other web pages in your
browser cannot use the API (Host and Origin checks, D-24).

### Sharing the lab on a network

Sharing needs a login (D-25); the backend refuses to start shared without one:

```bash
ACTUNODE_BIND_ADDRESS=0.0.0.0 ACTUNODE_REQUIRE_LOGIN=1 \
ACTUNODE_ALLOWED_HOSTS=localhost,127.0.0.1,::1,<this machine's name or IP> \
docker compose up --build
docker compose run --rm mqtt-init show api-token      # the token people enter in the browser
docker compose run --rm cert-init show ca > actunode-ca.crt   # the certificate authority to trust
```

Others open `https://<this machine>:8443` (import `actunode-ca.crt` in the browser to avoid the
certificate warning). Real robots connect with TLS to `<this machine>:8883`, trusting the same CA, with a
login from `mqtt-init add-robot`. Plain HTTP and MQTT ports never leave this computer (D-26).

## Local development (without Docker)

You still need an MQTT broker on `localhost:1883`. Simplest: a local broker without logins
(`sudo apt install mosquitto`); backend and simulator connect anonymously when no
`ACTUNODE_MQTT_USERNAME` / `ACTUNODE_MQTT_PASSWORD_FILE` is set. To use the Compose broker instead, copy
the backend password out of the volume and point `ACTUNODE_MQTT_PASSWORD_FILE` at it.

```bash
# Backend
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/uvicorn app.main:app --reload --port 8000

# Frontend (second terminal; proxies /api to :8000). Needs Node.js 24 (frontend/.nvmrc).
cd frontend
nvm use            # or install Node 24 another way
npm install
npm run dev        # http://localhost:5173

# Simulator (third terminal, from repo root)
python3 -m venv simulator/.venv
simulator/.venv/bin/pip install -r simulator/requirements-dev.txt
simulator/.venv/bin/python -m simulator --robots 3   # up to 50; 10 fill the charging area
# add --vda-version 3 for robots that speak VDA 5050 3.0.0 (ACTUNODE_VDA_VERSION=3 in Docker)

# Frontend unit and component tests
(cd frontend && npm test)

# Lint and format Python (ruff is in requirements-dev.txt)
backend/.venv/bin/ruff check . && backend/.venv/bin/ruff format --check .

# Tests
cd backend && .venv/bin/pytest
simulator/.venv/bin/pytest simulator   # from repo root

# End-to-end tests: start an isolated copy of the Docker stack (ports 18080/11883),
# drive it through the API and MQTT, then remove it (~2 minutes)
python3 -m venv tests/e2e/.venv && tests/e2e/.venv/bin/pip install -r tests/e2e/requirements.txt
tests/e2e/.venv/bin/pytest tests/e2e
```

## Architecture

```
React UI  ──/api──▶  FastAPI backend  ──▶  MQTT broker (Mosquitto)  ◀──▶  Robot simulators
map + message stream   missions, replay        VDA 5050 topics              Python state machines
```

| Path | What |
|---|---|
| `backend/` | FastAPI service: missions, validation, record/replay |
| `frontend/` | React + TypeScript lab UI |
| `simulator/` | Python AMR simulator |
| `mosquitto/` | Local broker config |
| `docs/` | Plan tracker and brand assets |

## VDA 5050 2.1 and 3.0

ActuNode understands both versions at once, per robot, from the topic (`uagv/v2/...` or `uagv/v3/...`):
messages are validated against the official schema of their version, and orders are sent in the
version each robot speaks. To run 3.0 robots: `ACTUNODE_VDA_VERSION=3 docker compose up --build`
(or `--vda-version 3` for the simulator). See [docs/research/VDA5050_3_0.md](docs/research/VDA5050_3_0.md).

## MQTT topics

Robots follow the VDA 5050 topic layout
`interfaceName/majorVersion/manufacturer/serialNumber/topic`:

| Topic | Publisher | Content |
|---|---|---|
| `uagv/v2/ActuNode/robot_01/state` | simulator, every 1 s | pose, battery, mission status, errors |
| `uagv/v2/ActuNode/robot_01/connection` | simulator (retained, last will) | `ONLINE` / `OFFLINE` / `CONNECTIONBROKEN` |
| `uagv/v2/ActuNode/robot_01/order` | backend (`POST /api/missions`) | VDA 5050 order: nodes, edges, pick/drop actions |
| `actunode/v1/sim/robot_01/inject` | backend (`POST /api/failures`) | ActuNode failure-injection command (not VDA 5050) |

Each robot runs a mission state machine `IDLE → ACCEPTED → MOVING → COMPLETED` (plus `BLOCKED`
under failure injection), drives at 1 m/s
and drains 0.2 % battery per meter. Orders sent while a robot is busy are rejected with an
`orderError` in its state.

### Send a mission

```bash
curl -X POST localhost:8000/api/missions -H 'content-type: application/json' \
  -d '{"robot_id":"robot_01","source":"RECEIVING_DOOR_2","destination":"STORAGE_A17","load_id":"P-1042"}'
```

Or use the mission form in the UI. Named locations: `GET /api/locations`.

### Live view

The backend subscribes to `uagv/#` and `actunode/#` and keeps the latest state per robot plus
the last 500 messages. The UI gets them over a WebSocket and shows robots on the warehouse map,
a robot table, and a raw message stream (filter, pause, click a row for the full JSON).

| Endpoint | What |
|---|---|
| `GET /api/robots` | Latest connection + state per robot |
| `GET /api/messages` | Recent MQTT messages |
| `WS /api/ws` | Snapshot on connect, then every message live |

### Failure injection

`BLOCKED_PATH` stops a robot that is on a route: it goes `MOVING → BLOCKED`, stands still and
reports a VDA 5050 `pathBlocked` error referencing the edge (or next node) it was on. Clearing
the failure resumes the mission. Every injection is logged by the backend and shown in the UI.

```bash
curl -X POST localhost:8000/api/failures -H 'content-type: application/json' -d '{"robot_id":"robot_01"}'
curl -X POST localhost:8000/api/failures -H 'content-type: application/json' -d '{"robot_id":"robot_01","action":"clear"}'
curl localhost:8000/api/failures   # failure log
```

### Validation

Every message is checked as it arrives: JSON Schemas for `state`, `order`, `connection` and
ActuNode's inject command ([backend/app/schemas](backend/app/schemas)), plus rules that need
history: `headerId` increasing per topic, order node/edge sequence, mission state machine,
`driving` consistency, topic/payload consistency. Issues are attached to each message (and saved
in recordings), counted per rule in the Validation panel, and shown inline in the message stream.

```bash
curl localhost:8000/api/validation          # counts per rule + latest example
curl -X POST localhost:8000/api/validation/reset
```

See [docs/VDA5050_NOTES.md](docs/VDA5050_NOTES.md) for the rules and the protocol notes behind them.

### Near-collisions

ActuNode does not steer robots apart (that is the fleet manager's job); it **reports** when two live
robots come closer than 1.0 m (`ACTUNODE_PROXIMITY_M`): a `proximity` warning in the stream, the
Validation panel and recordings, a red line between the robots on the map, and `GET /api/proximity`.

### Recording sessions

Recording captures every MQTT message the backend sees (orders, states, connections, failure
injections) to `sessions/<timestamp>_<name>.jsonl`, one JSON object per line:

```jsonl
{"type":"session","formatVersion":1,"sessionId":"20261009-215557_P-1042-blocked-aisle","name":"P-1042-blocked-aisle","startedAt":"..."}
{"type":"snapshot","robots":[...]}
{"type":"message","t":14.04,"receivedAt":"...","topic":"actunode/v1/sim/robot_01/inject","retained":false,"payload":{...}}
{"type":"end","endedAt":"...","messageCount":186}
```

`t` is seconds since the recording started. A message that was not valid JSON is kept verbatim in
`payloadRaw`. If the backend dies mid-recording the `end` line is missing and the session is listed
as incomplete.

```bash
curl -X POST localhost:8000/api/recording/start -H 'content-type: application/json' -d '{"name":"p1042"}'
curl -X POST localhost:8000/api/recording/stop
curl localhost:8000/api/sessions
curl -OJ localhost:8000/api/sessions/<sessionId>/download

# Timeline of one robot from a session file
jq -c 'select(.type=="message" and (.topic|endswith("robot_01/state"))) | [.t, .payload.actunode.missionStatus]' sessions/*.jsonl
```

A recording stops itself at 200 MB (about 5–6 hours with 10 robots; change with
`ACTUNODE_MAX_SESSION_MB`) or if the disk fills up; the end line records why. Delete old sessions with
`curl -X DELETE localhost:8000/api/sessions/<sessionId>` or the Delete button.

Or use the Sessions panel in the UI.

### Replaying a session

Replay republishes a session's messages to MQTT with the original timing (optionally faster), so
the UI, or any system under test listening on the broker, sees the incident happen again.

- Each robot's state at the start of the recording is published first, so robots start where they were.
- **Robot-side traffic only by default** (state, connection). Orders, instant actions and failure
  injections are skipped unless `include_commands` is set, because any robot listening would execute them.
- Replay is **refused while robots with the same ids are publishing live state**: stop the
  simulator first (`docker compose stop simulator`) so live and replayed messages never mix.
- Replayed messages are never retained, so a replay cannot overwrite the broker's stored state.

```bash
curl -X POST localhost:8000/api/sessions/<sessionId>/replay -H 'content-type: application/json' \
  -d '{"speed": 5, "include_commands": false}'
curl localhost:8000/api/replay          # progress
curl -X POST localhost:8000/api/replay/stop
```
Offline playground without MQTT: `python3 main.py`.

Watch them live: `mosquitto_sub -h localhost -t 'uagv/#' -v`

## Product modules

- **ActuNode Sim**: robot/fleet simulator
- **ActuNode Test**: integration scenarios and CI checks
- **ActuNode Replay**: record and replay robot communication sessions

## Troubleshooting

**`localhost:8000` or `localhost:1883` hangs while the UI on `localhost:8080` works.** A host firewall
that denies outgoing connections (for example ufw with `DEFAULT_OUTPUT_POLICY="DROP"`) blocks this
computer's own connections to Docker container ports; check with `journalctl -k | grep "UFW BLOCK"`.
The UI, API docs (`localhost:8080/api/docs`) and robots are unaffected. To allow it, narrowly:

```bash
sudo ufw allow out proto tcp to 172.16.0.0/12 port 1883,8000,8883,9001 comment 'ActuNode containers'
```

## Documentation

| Document | What it covers |
|---|---|
| [docs/PROGRESS.md](docs/PROGRESS.md) | Where the project is: schedule, verification status, open issues, session log |
| [docs/PLAN.md](docs/PLAN.md) | The build plan and calendar |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Components, topics, API, data formats |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Why things are built the way they are |
| [docs/VDA5050_NOTES.md](docs/VDA5050_NOTES.md) | Protocol notes and validator rules |
| [docs/research/](docs/research) | Research notes (e.g. VDA 5050 3.0 vs 2.1) |
| [docs/discovery/](docs/discovery) | Customer discovery: outreach messages and interview guide |
| [docs/DEMO.md](docs/DEMO.md) | 3-minute demo script |
| [CHANGELOG.md](CHANGELOG.md) | Changes per commit |
