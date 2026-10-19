# Screen reader check (the open item of the accessibility review)

The [accessibility review](../ACCESSIBILITY_REVIEW_2026-10-19.md) checked announcements and keyboard patterns in
code and in a headless browser. This is the part only a person with a screen reader can do. About 30 minutes;
one screen reader is enough to start, two (e.g. Orca and NVDA) is better.

## Setup

| Screen reader | Where | Start / stop | Notes |
|---|---|---|---|
| **Orca** | Linux (GNOME; preinstalled on Ubuntu) | `Super+Alt+S` | Use Firefox or Chromium |
| NVDA | Windows (free, nvaccess.org) | `Ctrl+Alt+N` / `Insert+Q` | Use Firefox or Chrome |
| VoiceOver | macOS | `Cmd+F5` | Use Safari |

Start the lab (`docker compose up -d --wait`), open http://localhost:8080, keep the mouse away. Use only Tab,
Shift+Tab, arrow keys, Enter and Space (and the screen reader's own reading keys).

## Checklist

Mark each row **pass**, **fail** (what you heard instead) or **unclear**.

| # | Do | Expect to hear | Result |
|---|---|---|---|
| 1 | Load the page, press Tab once | "Skip to sessions, link" | |
| 2 | Tab again, then Enter | "Skip to message stream"; Enter moves to the Message stream panel | |
| 3 | Shift+Tab back to the top; navigate by headings (Orca/NVDA: `H`; VoiceOver: `VO+Cmd+H`) | "ActuNode Lab, heading level 1", then each panel as level 2 | |
| 4 | Tab to the Mission sender's fields | Each field's label ("Robot", "Target", "From (pick)", "To (drop)", "Load") with its value | |
| 5 | Send a mission (Robot robot_01, To STORAGE_A17, Send mission) | "Order published: order-…. Waiting for robot state." **once**, without moving focus | |
| 6 | Send a mission with an invalid target (stop the simulator first: `docker compose stop simulator`) | The error read immediately (alert) | |
| 7 | In Failure injection, choose each failure type | The type, and its explanation readable after it (e.g. "Ends by itself after the duration set here") | |
| 8 | Inject a blocked path on a moving robot | "… injected on robot_…" once | |
| 9 | Start a recording (Sessions) | "Recording started: <id>" once; **no** announcements of the running counters afterwards (wait 30 s) | |
| 10 | Stop the recording | "Recording stopped: <id> (stopped by user)" | |
| 11 | Tab into the session table | One stop: "▶ Replay, button"; Right arrow → "Validate session …", "Download, link", "Delete"; Down arrow → the same action of the next session | |
| 12 | Tab once more from the session table | Leaves the table (next is the Activity filter) | |
| 13 | Start a replay of a short session, wait for it to end | "Replay started: <id>", later "Replay finished: <id>"; no progress chatter | |
| 14 | Tab into the Message stream | One stop on the newest message; Up/Down move between messages; Enter opens the detail ("expanded") | |
| 15 | Leave the page open for 2 minutes with robots moving | **Silence**: live traffic must never be read out | |
| 16 | Restart the backend (`docker compose restart backend`) | "Live feed disconnected. Reconnecting…" once, then quiet | |
| 17 | (Shared lab with a viewer login) log in as a viewer, Tab to "Send mission" | "Send mission, button, unavailable/dimmed", with the reason "Viewers cannot change the lab" available | |

## After

Paste the filled table into an issue (label `documentation`) or send it over. Each **fail** becomes a fix with a
test, and the review's "screen reader pass" item is closed with the date, the screen reader and its version.
