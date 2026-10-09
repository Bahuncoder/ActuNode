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

# Tests
cd backend && .venv/bin/pytest
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

## Product modules

- **ActuNode Sim**: robot/fleet simulator
- **ActuNode Test**: integration scenarios and CI checks
- **ActuNode Replay**: record and replay robot communication sessions
