# UI/UX design brief — ActuNode Lab

Working specification · updated 17 October 2026 (v0.3.0) · [App flow](APP_FLOW.md)

## Intent and audience

Design a calm technical workspace where an integration engineer can answer: which robot is affected, what happened, what evidence supports it, and what can I do next? The central artifact is a reproducible incident. Favor precise status, readable traffic and recoverable controls over visual simulation realism.

Current baseline is the React dashboard in `frontend/src/App.tsx`. This brief preserves its panel architecture. Proposed refinements below require implementation and usability verification; this document does not claim those changes are shipped.

## Information hierarchy

| Region | Content and purpose |
|---|---|
| Header | Product name/version, independent API/MQTT/Live statuses; with login, who is logged in and their role ("alice (operator)"), "View only" for viewers, logout |
| Persistent activity | Active replay with session identity, progress and Stop |
| Warehouse | Robot positions, route and proximity warnings on the fixed map |
| Robots | Comparable identity, connection, battery, mission and action information |
| Controls | Mission sender alongside failure injection for deliberate experiments |
| Evidence | Recording controls, session list/storage, validation summary/report |
| Activity | Who changed what: the latest audit entries with time, person, action, target and result; filter by person (v0.3.0) |
| Inspector | Filterable, pausable message stream with selectable JSON details |

Desktop reference: retain the current centered 1,200 px workspace and 24/16 px outer spacing. Proposed layout checks cover 1,440×900 and 1,024×768 desktops plus a 390 px narrow viewport. At narrow widths stack panels and allow tables/code to scroll within their region rather than overflow the page. Desktop remains the primary operating environment; mobile is a review/support target.

## Visual system

Existing CSS tokens are the source of truth:

| Token | Value | Use |
|---|---|---|
| Node navy | `#0b1b2b` | Page background |
| Panel | `#10263a` | Workspace cards |
| Signal blue | `#00aeef` | Interactive emphasis |
| Machine mint | `#7cffcb` | Positive/active indicators |
| Fog white | `#eaf2f7` | Main text |
| Industrial gray | `#8aa1ad` | Secondary text |
| Border | `#1d3a52` | Panel separation |
| Danger | `#ff6b6b` | Error/destructive emphasis |

Use Inter/system sans for controls and labels, JetBrains Mono/system monospace for topics, IDs and JSON. A font fallback must work without external network requests. Proposed spacing rhythm: 4/8/12/16/24/32 px. Extend existing CSS variables rather than introducing a separate design framework.

## Interaction requirements

- A viewer sees every changing control disabled, with the reason as its title ("Viewers cannot change the lab"); errors from the server show its plain text, not a status code (v0.3.0).
- Identify a robot by version, manufacturer and serial wherever ambiguity matters. Serial alone must not silently select a different target (PR-02).
- Say “Order published” for successful publication; show observed acceptance/completion from robot telemetry separately.
- Explain failure duration and whether it ends automatically. Offer Clear only for blocked path and low battery.
- Keep recording state visible while active. Show why an automatic stop occurred and distinguish complete/incomplete recordings.
- Replay controls identify session, speed, current-time behavior and inclusion of commands. Explain the live-robot conflict and documented simulator-stop step.
- Validation results expose rule, severity, affected topic and message context. A warning is not a safety verdict.
- Show explicit units: metres, seconds and percent. Display unknown values as unknown, not zero.
- Preserve useful form values on failed requests. Make busy state visible and prevent accidental duplicate submissions.
- Session deletion needs a deliberate interaction identifying the file; confirm if the existing interaction does so, otherwise add a reviewable confirmation or reversible alternative.

## Accessibility and feedback acceptance (proposed)

Target WCAG 2.2 AA as a design objective; conformance has not been established. Verify keyboard access to every control, visible focus, programmatic labels, readable errors, sensible focus after dialogs/details, and escape/close behavior where overlays exist. Use text/icon labels as well as color for state and severity. Validate 4.5:1 normal text contrast and 3:1 non-text control/focus contrast on actual combinations.

Status updates should not flood screen readers; announce actionable failures and recording/replay transitions, not every MQTT message. Respect reduced-motion preferences. The robot table provides a text alternative to interpreting map color/position. Test keyboard-only operation, 200% zoom and at least one screen reader before claiming accessibility readiness.

## Required states and copy

| Situation | Intended message style |
|---|---|
| No robots | “No robot traffic received. Start the simulator or connect a robot.” |
| Publish accepted | “Order published: [order ID]. Waiting for robot state.” |
| Live disconnected | “Live feed disconnected. Reconnecting…” |
| Replay blocked | Identify the live robot identities and explain how to stop their publishers |
| Bad upload | “Line [N]: [reason]” with the applicable size/format guidance |
| Reduced payload | Indicate preview/truncation and how to obtain the available full session evidence |

These are proposed copy patterns; align final wording with actual server behavior.

## Deliverables and validation

Before UI changes, capture current desktop/narrow screenshots, then annotate hierarchy and failure states. Implement the smallest supported refinements using existing components. Review first-incident flow, target identity ambiguity, expired sessions, malformed telemetry, storage failures and replay conflicts. Use component/e2e checks for behavior and manual keyboard/zoom review for usability. Avoid snapshot-only tests as evidence of workflow correctness.

Success is PR-12 onboarding completion with fewer interventions, while preserving the load harness frame-rate and console-error gates. A dashboard redesign or new navigation should require evidence that the current structure blocks those tasks.
