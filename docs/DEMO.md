# ActuNode Lab: 3-minute demo

The week-1 demo from the plan: **clone → one command → three robots → send a mission →
inject a failure → replay the incident.** Use this as the script for the demo video.

## Before recording

```bash
git clone git@github.com:Bahuncoder/ActuNode.git && cd ActuNode
docker compose up --build        # broker, backend, 3 simulated robots, UI
```

Open http://localhost:8080 and check the header: **API**, **MQTT** and **Live** are all green,
and three robots sit in the charging area. Make the browser window ~1280 px wide.

## Script (≈ 3 minutes)

| Time | Show | Say |
|---|---|---|
| 0:00–0:20 | The full page | "Robots are easy to buy and hard to integrate. ActuNode is a lab for testing AMR integrations before they fail in a real warehouse: VDA 5050 over MQTT, simulated robots, failure injection, record and replay." |
| 0:20–0:40 | Robot table + message stream | "Three simulated robots are publishing standard VDA 5050 state messages every second. Every MQTT message is visible here: no black box." Click one state row to expand the JSON. |
| 0:40–0:55 | Sessions panel → name `p1042-blocked-aisle` → **Start recording** | "First, record everything that happens next." |
| 0:55–1:20 | Mission sender (prefilled: robot_01, RECEIVING_DOOR_2 → STORAGE_A17, P-1042) → **Send mission** | "A WMS job: move pallet P-1042 from receiving door 2 to storage A17. ActuNode turns it into a VDA 5050 order." Point at ACCEPTED → MOVING and the dashed route on the map. |
| 1:20–1:45 | Wait until robot_01 has passed Receiving Door 2 → Failure injection → **Inject BLOCKED_PATH** | "Now something blocks the aisle." Robot turns red, stops, the table shows *Path blocked on edge RECEIVING_DOOR_2->STORAGE_A17*. "This is exactly the kind of exception a fleet manager or WMS integration has to handle." |
| 1:45–2:05 | **Clear** → robot resumes → COMPLETED (mint) → **Stop recording** | "Clear it, the mission completes, and the whole incident is now a session file." Point at message count and size. |
| 2:05–2:20 | Terminal: `docker compose stop simulator` | "To replay, stop the live robots so recorded and live traffic never mix. ActuNode refuses to replay otherwise." |
| 2:20–2:50 | Session row → speed **5×** → **▶ Replay** | "Replay republishes what the robots said, with the original timing. Any system listening sees the incident again: same position, same error, same edge." Point at the REPLAYING banner and robot_01 turning red again. |
| 2:50–3:00 | Download link, GitHub repo | "The session is a plain JSONL file you can attach to a bug report. Open source, built in public. Feedback from people who deploy robots is very welcome." |

## Notes

- Replay only republishes robot-side messages by default. Tick **Include commands** to
  re-send orders and failure injections too (any robot listening would execute them).
- Without Docker: run broker, backend, simulator and `npm run dev` as in the README; the UI is
  then at http://localhost:5173 and you stop the simulator with Ctrl+C before replaying.
- Recording ideas: OBS or the GNOME screen recorder (Ctrl+Shift+Alt+R); 1080p, browser zoom 100 %.
