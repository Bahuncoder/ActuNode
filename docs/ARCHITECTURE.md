# ActuNode architecture

How the lab is put together, as built. For *why* it is built this way see [DECISIONS.md](DECISIONS.md).
Keep this file in step with the code: when a component, topic or endpoint changes, update it here in the
same commit.

## Overview

```
                        ┌──────────────────────────────────────────────┐
  Browser               │ Backend (FastAPI, Python)                    │
 ┌──────────────┐  HTTP │                                              │
 │ React UI     │──────▶│ missions · failures · sessions · validation  │
 │ map, table,  │       │        │                                     │
 │ stream, ...  │◀──────│ LiveHub ◀── Validator    SessionRecorder     │
 └──────────────┘  WS   │    ▲            ▲              ▲  Replayer   │
                /api/ws │    └──── MqttBridge ───────────┘     │       │
                        └──────────────┬──────────────────────┼───────┘
                                       │ subscribe uagv/#,    │ publish
                                       │ actunode/#           │
                               ┌───────▼──────────────────────▼───┐
                               │ MQTT broker (Mosquitto)          │
                               └───────▲──────────────────────────┘
                                       │ one client per robot
                               ┌───────┴──────────────────────────┐
                               │ Simulator (Python)               │
                               │ Robot state machines, 10 Hz tick │
                               └──────────────────────────────────┘
```

Four processes, each its own Docker Compose service:

| Service | Code | Port | Role |
|---|---|---|---|
| `mosquitto` | [mosquitto/config](../mosquitto/config/mosquitto.conf) | 1883 (MQTT), 9001 (WebSocket) | Message broker |
| `simulator` | [simulator/](../simulator) | none | Simulated AMRs speaking VDA 5050 |
| `backend` | [backend/app](../backend/app) | 8000 | REST + WebSocket API, validation, recording, replay |
| `frontend` | [frontend/src](../frontend/src) | 8080 (nginx) / 5173 (dev) | Lab UI; nginx proxies `/api` to the backend |

Backend and simulator run as an unprivileged user; Compose runs the backend as the host user so
session files in `./sessions` belong to them (D-12). nginx re-resolves the backend's name per
request, so the backend can be restarted on its own (D-13).

## MQTT topics

VDA 5050 layout: `interfaceName/majorVersion/manufacturer/serialNumber/topic`, e.g.
`uagv/v2/ActuNode/<robot>/<topic>`. Both `v2` (2.1.0) and `v3` (3.0.0) are understood (D-15): the
validator picks the official schema set by the topic, and orders/replay address each robot with the
version and manufacturer it last used. Robots never seen get `ACTUNODE_VDA_MAJOR_VERSION` (default `v2`).

| Topic | Publisher | Subscriber | QoS | Retained | Content |
|---|---|---|---|---|---|
| `uagv/v2/ActuNode/<robot>/order` | backend | that robot | 0 | no | VDA 5050 order |
| `uagv/v2/ActuNode/<robot>/state` | robot | backend | 0 | no | VDA 5050 state + `actunode.missionStatus`; every 1 s and on every status change |
| `uagv/v2/ActuNode/<robot>/connection` | robot (and broker, as last will) | backend | 1 | yes | `ONLINE` / `OFFLINE` / `CONNECTIONBROKEN` |
| `actunode/v1/sim/<robot>/inject` | backend | that robot | 1 | no | Failure-injection command (ActuNode, not VDA 5050) |

QoS follows VDA 5050 section 6.2: QoS 0 for `order`, `instantActions`, `state`, `factsheet`,
`visualization`; QoS 1 for `connection`. The backend subscribes with QoS 1 (a ceiling, needed to receive
`connection` at QoS 1). The ActuNode inject topic is not VDA 5050 and uses QoS 1 so test commands arrive.

The backend subscribes to `uagv/#` and `actunode/#`, so it also sees its own orders and commands,
which is what puts them in the message stream and in recordings.

## Simulator

| File | Responsibility |
|---|---|
| [robot.py](../simulator/robot.py) | `Robot`: pose, battery, mission state machine, order handling, failure injection, VDA 5050 message building. No I/O. |
| [publisher.py](../simulator/publisher.py) | `RobotConnection`: one paho MQTT client per robot (own last will); queues incoming orders/commands |
| [\_\_main\_\_.py](../simulator/__main__.py) | Main loop: 10 Hz physics tick; applies queued messages; publishes state every second and on change |
| [topics.py](../simulator/topics.py) | Topic names |

**Mission state machine** (`state.actunode.missionStatus`):

```
IDLE ──order──▶ ACCEPTED ──next tick──▶ MOVING ──last node──▶ COMPLETED ──order──▶ ACCEPTED …
                    │                    │  ▲  │
                    └──BLOCKED_PATH──▶ BLOCKED ─clear─┘
                                         │
                                  battery 0 % ──▶ FAILED ──order (battery > 0)──▶ ACCEPTED …
```

- Orders arriving while ACCEPTED / MOVING / BLOCKED are rejected with an `orderError`.
- Motion: 1 m/s straight lines between nodes; battery −0.2 % per metre; pick/drop actions finish
  instantly on arrival.
- At 0 % battery the robot stops where it ran out and the mission is FAILED (`batteryEmpty`, FATAL);
  orders are rejected until it can drive again (D-17). Charging is not simulated yet.
- Threading: paho network threads only put messages on a queue; the robot object is touched only by
  the main loop.

## Backend

| File | Responsibility |
|---|---|
| [main.py](../backend/app/main.py) | App, lifespan (start/stop MQTT; close recording; stop replay), health, robots, messages, validation, WebSocket |
| [mqtt.py](../backend/app/mqtt.py), [mqtt_state.py](../backend/app/mqtt_state.py) | `MqttBridge`: one shared paho client, auto-reconnect, subscriptions, message callback |
| [live.py](../backend/app/live.py) | `LiveHub`: latest state per robot, last 500 messages, failure log, validation counters; hands events from the MQTT thread to WebSocket clients on the asyncio loop |
| [validator.py](../backend/app/validator.py) + [schemas/](../backend/app/schemas) | JSON Schema checks + sequence rules; attaches `issues` to every message |
| [vda5050.py](../backend/app/vda5050.py) | Topic names, headers, order building |
| [missions.py](../backend/app/missions.py) | `POST /api/missions` → VDA 5050 order |
| [failures.py](../backend/app/failures.py) | `POST /api/failures` → inject command; failure log |
| [recorder.py](../backend/app/recorder.py) | `SessionRecorder`: JSONL session files |
| [replay.py](../backend/app/replay.py) | `Replayer`: republishes a session with original timing (asyncio task) |
| [sessions.py](../backend/app/sessions.py) | Recording and replay endpoints; live-robot check before replay |
| [warehouse.py](../backend/app/warehouse.py) | Named locations (metres) |
| [config.py](../backend/app/config.py) | Settings from environment variables |

**Message path:** paho thread → `MqttBridge._on_message` → `LiveHub.handle_mqtt` (under a lock:
validate, store, update robot) → listeners (recorder) → `loop.call_soon_threadsafe` → each
WebSocket client's queue → `send_json`.

### HTTP API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Version and MQTT connection |
| GET | `/api/locations` | Named warehouse locations |
| POST | `/api/missions` | Send a mission (robot, source, destination, load) |
| GET | `/api/robots` | Latest connection + state per robot |
| GET | `/api/messages` | Recent MQTT messages with validation issues |
| GET / POST | `/api/failures` | Failure log / inject or clear `BLOCKED_PATH` |
| GET | `/api/validation` | Validation counters per rule |
| POST | `/api/validation/reset` | Reset counters |
| GET | `/api/recording` | Current recording |
| POST | `/api/recording/start`, `/api/recording/stop` | Start / stop recording |
| GET | `/api/sessions` | Recorded sessions |
| GET | `/api/sessions/{id}/download` | Session file (JSONL) |
| DELETE | `/api/sessions/{id}` | Delete a session (refused while it is recorded or replayed) |
| POST | `/api/sessions/{id}/replay` | Replay a session (`speed`, `include_commands`) |
| GET | `/api/replay` | Replay progress |
| POST | `/api/replay/stop` | Stop replay |
| WS | `/api/ws` | Snapshot, then live events |

Interactive docs: http://localhost:8000/docs.

### WebSocket events

| `type` | When | Payload |
|---|---|---|
| `snapshot` | On connect | `robots`, `messages`, `failures`, `validation`, `recording`, `replay` |
| `message` | Every MQTT message | `message` (with `issues`), `robot` (updated robot, if any) |
| `failure` | Failure injected/cleared | `failure` |
| `recording` | Recording started/stopped | `recording` or null |
| `replay` | Replay progress (≈2/s) and end | `replay` |
| `validation` | Counters reset | `validation` |

### Session file format (v1)

Recording stops by itself at `ACTUNODE_MAX_SESSION_MB` or on a write error, writing an end record with
the reason and telling the UI. Listing sessions reads only each file's first and last line. Replay
streams the file (one pass to count, one to publish), so memory does not grow with session size.


One JSON object per line; see [recorder.py](../backend/app/recorder.py).

```
{"type":"session","formatVersion":1,"sessionId","name","startedAt"}
{"type":"snapshot","robots":[...]}
{"type":"message","t","receivedAt","topic","retained","payload" | "payloadRaw","issues"?}   × N
{"type":"end","endedAt","messageCount","reason"}    reason: stopped | sizeLimit | writeError: …
                                                         (line missing after a crash)
```

## Frontend

| File | Responsibility |
|---|---|
| [live.ts](../frontend/src/live.ts) | `useLiveFeed`: WebSocket with reconnect, reducer for all live events; defensive readers for robot data |
| [api.ts](../frontend/src/api.ts) | REST calls |
| [App.tsx](../frontend/src/App.tsx) | Layout; health polling; each panel wrapped in `PanelBoundary` |
| `WarehouseMap`, `RobotTable`, `MissionSender`, `FailurePanel`, `RecorderPanel`, `ReplayBanner`, `ValidationPanel`, `MessageStream` | One panel each |

Robot data is **untrusted** (any MQTT client can publish anything), so components read it through
helpers in `live.ts` rather than trusting the TypeScript types.

## Shutdown

Stopping must never lose data, in whatever order Docker stops the services (on a reboot the broker
can go first).

- **Backend:** the lifespan shutdown stops a running replay, closes an open recording with its `end`
  line, and disconnects from MQTT. WebSocket handlers watch for the close separately, so an idle feed
  cannot block shutdown. uvicorn's `--timeout-graceful-shutdown 5` keeps the whole sequence inside
  Docker's 10 s stop timeout. Covered by `tests/test_shutdown.py` (real uvicorn server).
- **Simulator:** each robot publishes `OFFLINE` if still connected; if the broker is gone it logs and
  carries on. A connection that drops without a goodbye is reported by the broker's last will
  (`CONNECTIONBROKEN`).

## Configuration

| Variable | Used by | Default |
|---|---|---|
| `ACTUNODE_MQTT_HOST`, `ACTUNODE_MQTT_PORT` | backend, simulator | `localhost`, `1883` |
| `ACTUNODE_MQTT_CLIENT_ID` | backend | `actunode-backend` |
| `ACTUNODE_SESSIONS_DIR` | backend | `<repo>/sessions` |
| `ACTUNODE_MAX_SESSION_MB` | backend (recording stops itself at this size; fractions allowed) | `200` |
| `ACTUNODE_SIM_ROBOTS` | simulator | `3` (1–50) |
| `ACTUNODE_VDA_INTERFACE` | backend, simulator | `uagv` |
| `ACTUNODE_VDA_MAJOR_VERSION` | backend (topic version of orders it sends) | `v2` |
| `ACTUNODE_VDA_VERSION` | simulator (`--vda-version`): robots speak VDA 5050 2.1.0 (`2`) or 3.0.0 (`3`) | `2` |
| `ACTUNODE_API_URL` | frontend dev server | `http://localhost:8000` |
| `ACTUNODE_UID`, `ACTUNODE_GID` | Docker Compose (backend user) | `1000`, `1000` |
| `ACTUNODE_BIND_ADDRESS` | Docker Compose (interface the ports are published on, D-18) | `127.0.0.1` |
| `ACTUNODE_UI_HOST_PORT`, `ACTUNODE_API_HOST_PORT` | Docker Compose (host ports) | `8080`, `8000` |
| `ACTUNODE_MQTT_HOST_PORT`, `ACTUNODE_MQTT_WS_HOST_PORT` | Docker Compose (host ports) | `1883`, `9001` |
| `ACTUNODE_SESSIONS_HOST_DIR` | Docker Compose (recordings on the host) | `./sessions` |
| `ACTUNODE_E2E_HOST` | end-to-end tests | `localhost` |

## Tests and CI

| Suite | Command | In CI |
|---|---|---|
| Python lint/format | `ruff check . && ruff format --check .` (repo root) | ✅ |
| Backend | `cd backend && .venv/bin/pytest` | ✅ |
| Simulator | `simulator/.venv/bin/pytest simulator` | ✅ |
| Frontend | `cd frontend && nvm use && npm run lint && npm test && npm run build` (Node 24, D-19) | ✅ |
| End to end | `pytest tests/e2e` (needs Docker; starts its own isolated stack, D-16) | ✅ |
