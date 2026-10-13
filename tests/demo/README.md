# Automated demo recording

`record_demo.py` plays the pitch story (pallet P-1042, blocked aisle, replay) in the real UI with Playwright and
records it as a video plus the README screenshots. The founder adds the voice-over afterwards.

```bash
tests/e2e/.venv/bin/python tests/demo/record_demo.py
```

It needs Docker and the e2e virtualenv (Playwright + Chromium, see `tests/e2e/requirements.txt`). It takes about
4 to 6 minutes including the image build, and produces:

- `tests/demo/output/actunode-demo.webm` (git-ignored), 1440x900, about 3 minutes, with an on-screen caption per scene.
- `docs/images/` screenshots (committed, used by the README): `lab-overview.png`, `mission.png`,
  `blocked-path.png`, `validation.png`, `sessions.png`, `failures.png`.

The stack runs in its own compose project (`actunode-demo`) on its own host ports (38080 UI, 38000 API, 31883
MQTT, ...) with login off, six simulated robots and a temporary sessions folder. It never touches a stack you
are using and is removed at the end, also on failure or Ctrl+C.

## Scenes

| # | Caption | What happens |
|---|---|---|
| 1 | Six simulated AMRs speaking VDA 5050 over MQTT | Robots parked on the map, robot table, live message stream. Screenshot `lab-overview.png`. |
| 2 | Record everything | Type a session name, Start recording in the Sessions panel. |
| 3 | Send a VDA 5050 order | Mission P-1042, Receiving door 2 to Storage A17, sent to robot_01; it drives. Screenshot `mission.png`. |
| 4 | Inject a failure: blocked path | Failure panel, Blocked path on robot_01: it shows BLOCKED and the error. Screenshot `blocked-path.png`. |
| 5 | Clear it: the robot completes the mission | Clear; robot_01 reaches COMPLETED. |
| 6 | The validator flags bad messages | Invalid payload (kind schema, 3 messages) on robot_02; the Validation panel counts the issues. Screenshot `validation.png`. |
| 7 | Disconnects and the last will | Disconnect (broken, 5 s) on robot_03: CONNECTIONBROKEN, then ONLINE. Screenshot `failures.png` (panel with parameters). |
| 8 | Validate a recorded session offline | Stop recording, Validate the session. Screenshot `sessions.png`. |
| 9 | Replay the incident | The simulator is stopped (`docker compose stop simulator`) so the live-robot safety check allows it; replay at 5x. |

## Voice-over

Play the video and record yourself reading the script in `docs/DEMO.md` (the captions mark each scene). Any
free editor works: Kdenlive or Shotcut (Linux/Windows/macOS), OpenShot, DaVinci Resolve (free tier). Import
the `.webm`, add an audio track, trim pauses to fit, export MP4 (H.264/AAC). Audacity helps to clean the audio.

Convert to MP4 without an editor:

```bash
ffmpeg -i tests/demo/output/actunode-demo.webm -c:v libx264 -pix_fmt yuv420p -crf 20 tests/demo/output/actunode-demo.mp4
```

## Why it never goes stale

It records the real product: real clicks in the real UI against the real backend, broker and simulator. If a
label or flow changes, the script fails loudly (Playwright waits for each expected result) instead of
producing an out-of-date video. Re-run it after UI changes to refresh the video and screenshots.
