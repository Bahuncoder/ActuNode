# Load test: 10, 25 and 50 robots

Week 4 asks for 5 to 10 robots on a warehouse map. This test checks how much room is left above that:
it runs the real Docker stack with 10, 25 and 50 simulated robots (50 is the simulator's maximum,
`simulator/__main__.py` `MAX_ROBOTS`), keeps half of them on missions, and measures every layer from
the robot's MQTT message to the frame the browser draws. It is a script, not part of `pytest`: one
run takes about 4–5 minutes and its numbers depend on the machine.

## Running it

```bash
# once: the e2e virtualenv has everything (paho-mqtt, httpx, websockets, Playwright + Chromium)
python -m venv tests/e2e/.venv && tests/e2e/.venv/bin/pip install -r tests/e2e/requirements.txt
tests/e2e/.venv/bin/playwright install chromium

tests/e2e/.venv/bin/python tests/load/run_load.py                    # 10, 25, 50 robots, 60 s each
tests/e2e/.venv/bin/python tests/load/run_load.py --robots 50 --window 120
tests/e2e/.venv/bin/python tests/load/run_load.py --no-browser --vda 3
```

Options: `--robots` (comma-separated, run in that order; use ascending order, see below), `--window`
(seconds measured per robot count, default 60), `--warmup` (missions run this long before measuring,
default 15), `--browser-seconds` (default 20, runs inside the window), `--no-browser`, `--vda 2|3`,
`--project` (compose project name, default `actunode-load`), `--keep` (leave the stack running).

The exit code is 0 when every check passes, 1 otherwise.

### Isolation

Like the e2e tests (`tests/e2e/conftest.py`), the script starts its own copy of the stack: compose
project `actunode-load`, host ports 28080 (UI), 28000 (API), 21883 (MQTT), 29001, 28443, 28883, a
temporary sessions directory, login off, everything bound to 127.0.0.1. It runs
`docker compose -p actunode-load down -v` at the end, also after an error or Ctrl+C. A stack you are
using on the default ports is not touched, but it does share the CPU: stop it for the cleanest numbers
(the result records host CPU and load average so you can tell).

Between robot counts only the simulator is recreated (`ACTUNODE_SIM_ROBOTS=N`). The backend keeps the
robots it has seen, so robots from a larger earlier run stay listed as offline: run counts in
ascending order.

## What happens per robot count

1. The simulator restarts with N robots; the script waits until all N publish state.
2. Warm-up (15 s): a dispatcher keeps about half the robots busy with pick-and-drop missions
   (`POST /api/missions` with a random source and destination from `backend/app/warehouse.py`). It
   only sends a mission to a robot that reports `IDLE`, `COMPLETED` or `CANCELLED`, is not paused,
   carries no load and has at least 20 % battery; a robot that finishes gets a new mission. The
   robots' state comes from MQTT, so the dispatcher adds no REST load.
3. Measurement window (60 s), all at once:

| Layer | How | Metrics |
| --- | --- | --- |
| MQTT | Subscribe to `uagv/#` with the read-only `tools` login, on the host | messages/s and kB/s by topic; per-robot state cadence; robot -> MQTT latency |
| Cadence | Week 2 method: per robot, intervals between *periodic* state messages (receive time). Periodic messages are told apart from event messages (D-34) by their tick phase: the simulator publishes every robot's periodic state in the same 0.1 s tick once a second, so they share one timestamp phase modulo 1 s | cadence p50/p99/max; longest silence between any two state messages; headerId gaps |
| CPU and memory | Exact CPU time from each container's cgroup (`cpu.stat`) at the start and end of the window; `docker stats --no-stream` every 5 s for the maximum and memory | CPU % of one core (100 % = one core busy), memory |
| WebSocket | One long-lived `/api/ws` on the UI port (through nginx) with the same-origin `Origin` header a browser sends; a fresh connection every 10 s for the snapshot | events/s by type; latency from the state message's `timestamp` to WebSocket receipt (p50/p99, and split into the once-a-second burst vs state sent alone); snapshot size and time to first snapshot |
| REST | `GET /api/robots` and `GET /api/messages`, alternating every 0.6 s (about 50 each) | p50/p99/max, response size |
| Browser | Playwright Chromium (headless, 1440x900) loads the UI, waits for N robots on the map, then runs 20 s: a `requestAnimationFrame` counter, a `PerformanceObserver('longtask')`, `performance.memory`, Chrome's `Performance.getMetrics` for main-thread time, console errors | frames/s (median of 1 s buckets), frame time p50/p95/p99, long tasks, JS heap, DOM nodes, main-thread busy % |

The robot clock (simulator container) and the receiving clock (host) are the same kernel clock, so the
latencies need no clock correction.

### Measurement overhead

- `docker stats --no-stream` takes about 2 s of daemon time per call (recorded as
  `docker_stats_call_s_mean`); it is used for memory and peaks only. The CPU means come from cgroup
  counters, which cost nothing.
- During the window the backend serves two extra WebSocket clients (the script's and the browser) and
  a snapshot probe every 10 s, as a user with the lab open would.
- Headless Chromium has no GPU: painting is done in software, so main-thread busy % is pessimistic
  compared with a desktop browser. Frame rates are what headless delivers (capped at 60).

## Thresholds and why

| Check | Limit | Why |
| --- | --- | --- |
| State cadence p99 (periodic) | ≤ 1.2 s | The simulator promises state every 1 s (D-34); 20 % jitter is the most a fleet manager or our timeout logic should see. Week 2 measured ≤ 1.064 s. |
| Longest silence of a robot | ≤ 1.5 s | No robot may look stale; the e2e "live" check treats 3 s without state as offline. |
| headerId gaps | 0 | A gap means the broker or our subscriber lost a message. |
| Robot -> WebSocket latency p99 | ≤ 250 ms | Below what a person watching the map notices as lag; well below the 1 s state interval. |
| WebSocket state events / MQTT state messages | ≥ 0.98 | Every state message reaches the UI (both clients subscribe in the same window, so small edge effects remain). |
| Events dropped by the backend | 0 | `backend/app/live.py` drops events for a client whose queue (1000) is full and logs "Live client is too slow". |
| Time to first snapshot p99 | ≤ 1 s | A page load must show the fleet within a second. |
| `GET /api/robots`, `GET /api/messages` p99 | ≤ 200 ms | Interactive API; scripts and the e2e tests poll these. |
| Backend CPU mean / max | ≤ 50 % / ≤ 80 % of one core | The backend is one Python process (one core because of the GIL). Half a core at the simulator maximum leaves room for replay, recording and validation of hostile traffic. |
| Simulator CPU mean | ≤ 70 % of one core | One process ticks every robot every 0.1 s; near 100 % the ticks run late and the cadence breaks. |
| Mosquitto CPU mean | ≤ 20 % of one core | The broker is the shared component real robots also use. |
| Backend memory max | ≤ 300 MiB | Buffers are bounded (500 messages, 1000 robots); growth beyond this would mean a leak. |
| UI frames/s, median of 1 s buckets | ≥ 30 | Smooth enough for a monitoring screen; robots move 1 m/s, updates come once a second. |
| UI frame time p95 | ≤ 50 ms | Even the slow frames stay at 20 fps or better. |
| Browser console errors | 0 | As in the e2e browser tests. |
| Workload: busy robots | ≥ 0.35 | Validity, not performance: the run only counts if about half the robots really were on missions. |

## Reading the results

The script prints a table (also written to `tests/load/results/latest.md`, the one file there that is
committed) and saves everything to `tests/load/results/<UTC timestamp>.json` plus the stack's logs in
`<timestamp>-stack.log`. In the JSON, `results[i]` is one robot count with sections `mqtt`,
`websocket`, `rest`, `containers`, `missions`, `browser`, `environment` and `checks` (value, limit and
pass/FAIL for each threshold).

Things to look at beyond pass/fail:

- **WebSocket latency, burst vs alone.** State sent alone (an event) shows the pipeline's own latency;
  the once-a-second burst, where every robot publishes in the same tick, shows queueing in the backend.
  If the burst number grows with N while the "alone" number stays flat, the backend's per-message work
  is the limit, not the network.
- **Proximity events/s.** The backend sends a `proximity` event whenever the list of close pairs or
  their distances change; each one re-renders the UI.
- **UI main-thread busy %** against frames/s: frames stay at 60 until the main thread is close to 100 %.
- `environment.host_cpu_pct_all_cores` and `loadavg_1m_before`: if other work was running, compare
  runs with care.

## In CI

`.github/workflows/load.yml` ("Load test") runs this script weekly and on demand (Actions tab, Run
workflow; inputs `robots` and `window`). The job fails if any threshold fails, and `tests/load/results/`
is always uploaded as the `load-results` artifact. Hosted runners are small and shared, so compare runs
with each other, not with numbers from a workstation.
