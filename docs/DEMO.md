# ActuNode Lab: 3-minute demo

A pitch demo of one integration incident, start to finish: six simulated robots, a WMS mission for pallet
**P-1042**, a blocked aisle, a bad message, a dropped connection, and the whole incident recorded,
validated and replayed.

There are two ways to run it, with the same nine scenes:

- **Automated video**: [`tests/demo/record_demo.py`](../tests/demo/record_demo.py) drives the real UI with
  Playwright, adds a caption per scene, records the video and refreshes the README screenshots. See
  [Producing the video](#producing-the-video).
- **Live**: you click through the scenes below and speak the voice-over.

## Setup checklist (live demo)

1. Start the stack with six robots and confirm it is healthy:

   ```bash
   git clone https://github.com/Bahuncoder/ActuNode.git && cd ActuNode
   ACTUNODE_SIM_ROBOTS=6 docker compose up --build -d
   ```

2. Open http://localhost:8080. The header shows **API**, **MQTT** and **Live** in green; six robots
   (`robot_01` … `robot_06`) are `ONLINE` in the robot table and on the map.
3. Start from a clean slate: in **Validation**, click **Reset counters**. Delete old sessions in
   **Sessions** if you do not want them on screen.
4. Browser window about 1440 × 900, zoom 100 %. Close other tabs and notifications.
5. Have a terminal open in the repo for scene 9 (`docker compose stop simulator`).
6. Do one dry run. Afterwards restore the robots: `docker compose start simulator`, wait until all six are
   `ONLINE`, then reset the counters again.
7. Have the recorded video ready to play in case something goes wrong live (see [Fallback](#fallback-plan)).

## Script (3:00)

The automated recorder uses the same robots and values: mission on `robot_01`, invalid payload on
`robot_02`, disconnect on `robot_03`.

### 1. The lab (0:00–0:20)

- **Click:** nothing. Then scroll to **Message stream** and back to the top.
- **Audience sees:** six robots in the charging area of the warehouse map, the robot table, state messages
  arriving every second.
- **Say:** "Integration incidents between a fleet manager and robots are hard to reproduce. This is
  ActuNode Lab: six simulated robots speaking VDA 5050 over MQTT, and every message they send is visible
  and checked."

### 2. Start recording (0:20–0:35)

- **Click:** **Sessions** → Session name `p1042-blocked-aisle` → **● Start recording**.
- **Audience sees:** the button turns into **■ Stop recording**; the session id, elapsed time, message
  count and size start counting.
- **Say:** "First, record everything that happens next, so the incident is not lost."

### 3. Send mission P-1042 (0:35–0:55)

- **Click:** **Mission sender** (prefilled: `robot_01`, From `RECEIVING_DOOR_2`, To `STORAGE_A17`, Load
  `P-1042`) → **Send mission**. Scroll back to the map.
- **Audience sees:** "Sent …" confirmation; `robot_01` goes `ACCEPTED` → `MOVING` and drives towards
  Receiving door 2.
- **Say:** "A WMS job: move pallet P-1042 from receiving door 2 to storage A17. ActuNode sends it as a
  standard VDA 5050 order, starting where the robot stands."

### 4. Inject a blocked path (0:55–1:20)

- **Click:** **Failure injection** → Robot `robot_01` → Failure type **Blocked path** → **Inject**
  (enabled only while the robot is `ACCEPTED` or `MOVING`). Scroll to the map, then the message stream.
- **Audience sees:** `robot_01` stops and shows `BLOCKED`; its error reads `Path blocked on edge …`; the
  injection appears in the failure log and the stream.
- **Say:** "Now something blocks the aisle. The robot stops and reports a `pathBlocked` error naming the
  edge it was on. This is the exception your fleet manager or WMS integration has to handle."

### 5. Clear it; the mission completes (1:20–1:45)

- **Click:** **Failure injection** → **Clear**. Back to the map.
- **Audience sees:** `robot_01` resumes, drives to Storage A17 and turns `COMPLETED`.
- **Say:** "Clear it and the robot carries on from where it stopped, and the mission completes."

### 6. Inject an invalid payload (1:45–2:00)

- **Click:** **Failure injection** → Robot `robot_02` → **Invalid payload** → Kind `schema`, Count `3` →
  **Inject**. Scroll to **Validation**.
- **Audience sees:** the count of messages with issues turns red; the `schema` rule counts the bad
  messages; they are flagged inline in the stream.
- **Say:** "Now a robot sends messages that break the official VDA 5050 schema. Every message is checked
  as it arrives, so you see exactly which rule broke, and when."

### 7. Inject an abrupt disconnect (2:00–2:20)

- **Click:** **Failure injection** → Robot `robot_03` → **Disconnect** → Duration `5`, Mode `broken` →
  **Inject**. Back to the robot table.
- **Audience sees:** `robot_03`'s connection shows `CONNECTIONBROKEN`, then `ONLINE` again after about five
  seconds.
- **Say:** "The robot drops off the network without saying goodbye. The broker publishes its last will,
  CONNECTIONBROKEN, and a few seconds later it reconnects."

### 8. Stop recording, validate offline (2:20–2:35)

- **Click:** **Sessions** → **■ Stop recording** → **Validate** on the new session row.
- **Audience sees:** the session row with duration, message count and size; below it the validation
  result: messages checked and the rules triggered, including the schema errors from scene 6.
- **Say:** "Stop, and the incident is a plain JSONL file. ActuNode validates it offline with the same
  validator; the same check runs as a command line tool in CI."

### 9. Replay the incident (2:35–3:00)

- **Click:** terminal: `docker compose stop simulator`. Wait about five seconds. **Sessions** → Speed
  **5×** → **▶ Replay** on the session row. Scroll to the top.
- **Audience sees:** the **REPLAYING** banner; the robots move again as recorded, `robot_01` blocks again,
  then **REPLAY FINISHED**.
- **Say:** "To replay, stop the live robots so recorded and live traffic never mix. Replay republishes
  what the robots said with the original timing, so any system listening sees the incident again. ActuNode
  is open source; feedback from people who integrate robots is very welcome."

## Producing the video

`tests/demo/record_demo.py` runs the nine scenes above against the real stack, unattended. Details:
[tests/demo/README.md](../tests/demo/README.md).

```bash
# once: the e2e virtualenv has Playwright, Chromium and httpx
python3 -m venv tests/e2e/.venv && tests/e2e/.venv/bin/pip install -r tests/e2e/requirements.txt
tests/e2e/.venv/bin/python -m playwright install chromium

tests/e2e/.venv/bin/python tests/demo/record_demo.py
```

- It starts its own copy of the stack (compose project `actunode-demo`, six robots, UI on port 38080,
  temporary sessions folder, login off) and removes it at the end, also after a failure. A stack you are
  running on the default ports is not touched.
- It records a 1440 × 900 video with a caption per scene to `tests/demo/output/actunode-demo.webm` and
  overwrites the README screenshots in `docs/images/` (`lab-overview.png`, `mission.png`,
  `blocked-path.png`, `validation.png`, `failures.png`, `sessions.png`).
- It waits for each expected result (for example `MOVING`, `BLOCKED`, `CONNECTIONBROKEN` then `ONLINE`,
  **REPLAY FINISHED**), so a run that finishes means every scene really happened. It exits 1 if a scene
  did not, and lists any browser console errors seen.
- The video has no sound. Record the voice-over lines above separately and combine them in a video
  editor; trim waits if the result runs longer than three minutes.

## Fallback plan

| If | Do |
|---|---|
| **Inject** for Blocked path is disabled | The robot is not on a route (mission finished or not started). Send the mission again (for example `STORAGE_A17` → `RECEIVING_DOOR_2`) and inject while it is `MOVING`. |
| The mission is rejected | The robot still has a load or its last order was not idle. Use another robot from the Robot select; say "the robot rejected the order, and the reason is in its state", and show the `orderError`. |
| Validation is already red before scene 6 | Near-collision (`proximity`) warnings appear when robots pass close to each other; that is a feature (ActuNode detects, it does not steer). Click **Reset counters**, then inject. |
| `CONNECTIONBROKEN` is not visible | It lasts only the disconnect duration. Inject again with Duration `10`. |
| Replay is refused | Live robots with the same ids were seen in the last few seconds. Check `docker compose stop simulator` finished, wait five seconds, try again. |
| A header pill turns red, or the page stops updating | Reload the page. If **MQTT** stays red: `docker compose restart backend` (the recording closes cleanly and the session is kept). |
| Anything else | Switch to the recorded video (`tests/demo/output/actunode-demo.webm`) and narrate it with the same lines. |

After the demo, `docker compose start simulator` brings the live robots back.
