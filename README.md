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

> Status: **early development** (week 1). See [docs/PLAN.md](docs/PLAN.md).

## Quick start (Docker)

```bash
docker compose up --build
```

| Service | URL |
|---|---|
| Lab UI | http://localhost:8080 |
| API docs | http://localhost:8000/docs |
| MQTT broker | `localhost:1883` (WebSocket `9001`) |

## Local development (without Docker)

You still need an MQTT broker on `localhost:1883`
(e.g. `docker compose up mosquitto`, or `sudo apt install mosquitto`).

```bash
# Backend
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/uvicorn app.main:app --reload --port 8000

# Frontend (second terminal; proxies /api to :8000)
cd frontend
npm install
npm run dev        # http://localhost:5173

# Simulator (third terminal, from repo root)
python3 -m venv simulator/.venv
simulator/.venv/bin/pip install -r simulator/requirements-dev.txt
simulator/.venv/bin/python -m simulator --robots 3

# Tests
cd backend && .venv/bin/pytest
simulator/.venv/bin/pytest simulator   # from repo root
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
Offline playground without MQTT: `python3 main.py`.

Watch them live: `mosquitto_sub -h localhost -t 'uagv/#' -v`

## Product modules

- **ActuNode Sim**: robot/fleet simulator
- **ActuNode Test**: integration scenarios and CI checks
- **ActuNode Replay**: record and replay robot communication sessions
