# Accessibility and interaction review (19 October 2026, package I)

The checks in the [design brief](product/UI_UX_DESIGN_BRIEF.md) ("Interaction requirements", "Required states and
copy", "Accessibility and feedback acceptance"), run on the v0.3.0 UI and fixed where small. This is a review
against a design objective (WCAG 2.2 AA), **not** a conformance claim. Method: a Playwright script against the
running lab (screenshots at 1,440×900, 1,024×768, 390 px and 200% zoom; every control's accessible name; a
keyboard walk through every Tab stop with its focus style; WCAG contrast of the colour tokens), and a line-by-line
comparison of the UI code with the brief. Fixes are in commits d75b0a2 and the one that adds this file, each with
tests (`frontend/src/a11y.test.tsx`, `frontend/src/brief.test.tsx`).

## Accessibility

| Check | Result |
|---|---|
| Every control has an accessible name | Passed (0 unnamed) |
| Keyboard reaches every control, focus visible | Passed: every Tab stop shows focus |
| Text contrast ≥ 4.5:1 | Passed: lowest text pair 5.56:1 (danger on panel) |
| Form-field boundaries ≥ 3:1 | **Fixed**: fields used `--border` (1.31:1 on panel); new `--control-border` #527794 is 3.25:1 on the panel and 3.67:1 on the page (a test keeps it ≥ 3) |
| Layout at 390 px and 200% zoom | Passed: no horizontal page scroll; wide tables scroll inside their panel |
| Announcements without flooding | **Fixed**: recording start/stop, replay start/end and action results are announced (polite), errors as alerts; never message traffic or counters. Status regions stay in the page so their text is announced |
| Reduced motion | **Fixed**: `prefers-reduced-motion` turns off CSS animation and transitions (the only motion; no JavaScript animation) |
| Message stream by keyboard | **Fixed**: was one Tab stop per message (up to 200); now one, with ↑/↓/Home/End between rows; rows are disclosure buttons (`aria-expanded`) |
| Decorative images | Passed: the logo has `alt=""` |
| Headings and landmarks | Passed: one h1, an h2 per panel, header and main |

## Interaction requirements and copy

| Brief item | Before | Now |
|---|---|---|
| Publication is not acceptance | "Sent order-x → topic" | "Order published: order-x. Waiting for robot state." (topic as secondary text) |
| No robots | "No robots yet…" | "No robot traffic received. Start the simulator or connect a robot." |
| Live feed lost | Only "Live: offline" | "Live feed disconnected. Reconnecting…" once the feed had been up |
| Failure duration / ends by itself | Only blocked path and unresponsive explained | Every type: stays until cleared (blocked path; low battery, which charging does not end) or ends by itself after the set duration; invalid payload sent once |
| Identity of the failure target | Serial only | "robot_01 · ActuNode · status" |
| Units | Positions and durations without units | "Position (m)", "Duration (m:ss)" |
| Unknown is not zero | Unknown recording size shown as "0 B" | "—" |
| Busy and duplicate submissions | Replay, Stop replay and Delete could be pressed twice; several buttons only greyed out | Each shows "Starting…", "Stopping…", "Deleting…", "Sending…", "Validating…" and cannot be pressed twice |
| Validation is not a safety verdict | Not said | "Protocol checks only: a warning, or a clean result, is not a safety verdict." |
| Replay options | Explained in tooltips only | Visible help next to "Include commands" and "Current time" (labels unchanged) |
| Replay conflict | "stop the simulator" | Adds the command: `docker compose stop simulator`; other robots: stop their publishers |
| Bad upload | Line and reason (already met) | Plus a hint: the file kind and the size limit |
| Shortened payloads | Marked, but no way to the full message | "The whole message is kept in a recording: record it, then download the session" |
| Session deletion | Confirmation naming the session (already met) | Unchanged |

## Known gaps (not fixed here)

- **Screen reader pass**: not done; this environment has no screen reader. The announcements are checked as DOM
  roles and text only. To do with NVDA or VoiceOver before claiming readiness.
- **Long session lists**: each saved session adds four Tab stops (Replay, Validate, Download, Delete); a lab with
  many sessions is tedious by keyboard. Options: a skip link to the message stream, or one Tab stop per row.
- **Robot identity in the mission sender**: the robot list shows serials; the target select names the identity
  (default "ActuNode · VDA 2") and warns when the default has not been seen. Kept: changing it touches mission
  addressing (D-21).
- **Complete recordings** carry no label of their own (incomplete ones are marked INCOMPLETE).
- **Upload size hint** uses the UI's constant, not the server's configured limit.
