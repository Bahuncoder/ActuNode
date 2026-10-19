# Implementation plan — ActuNode Lab

Working specification · updated 17 October 2026 (v0.3.0) · [PRD](PRD.md) · [TRD](TRD.md)

## Planning basis

Roadmap weeks 1–16 ([PLAN.md](../PLAN.md)) are complete and released: v0.1.0 (13 Oct), v0.2.0 (16 Oct), v0.3.0
(17 Oct, the full audit closed). Weeks are work packages, not calendar weeks (D-30). This plan records the outcome
of the packages written on 15 October (A–G) and sequences the work toward **v0.4.0** (H–M). Estimates are planning
ranges, not promised dates; user evidence can reorder them.

Product prioritization belongs to the founder; engineering supplies runnable deliverables and test evidence.

## Outcome of packages A–G (15 → 17 October)

| Package | Status | Evidence |
|---|---|---|
| A. Baseline and discovery | Engineering part done; discovery open | Gates re-run per release (CI on each tagged commit); fresh-clone check of the quick start (D-54); pilot recruits and interviews not yet done |
| B. Connector feasibility | Done | InOrbit `ros_amr_interop` + `vda5050_adapter_examples`, pinned commits, licence and maintenance checked (D-51) |
| C. Independent stack integration | Done | Compose profile `ros2`, scoped TLS login, map alias, mission and cancel (D-51) |
| D. Conformance and regression | Done | Nine scenarios plus raw checks, report with spec citations (D-52); patches 9/9 and 4/4, unpatched 4/9 and 0/4, both weekly in CI (D-55); five upstream PRs open |
| E. Onboarding and UX | Partly done | GETTING_STARTED, CONNECT_YOUR_ROBOT, failure catalogue, scenario gallery, message flows (D-53/D-54); UI for real robots (D-52); viewer mode and Activity panel (D-56). Open: observed new-user sessions; keyboard/zoom/screen-reader review |
| F. External pilot | Not started | Needs a participant |
| G. Release candidate | Done | v0.2.0 and v0.3.0, each gated on its tagged commit; PR-12/13 open, so released as a preview |

Also delivered beyond A–G, from the full audit (D-50): per-person logins and audit trail (D-56), metrics (D-57),
published images (D-58), scenario format version and compatibility promise (D-54), robot-scoped scenario checks
(D-59).

## Work toward v0.4.0

| Package | Effort / responsible role | Deliverables | Exit gate |
|---|---|---|---|
| H. Re-measure load — **done 17 Oct** | 0.5–1 day / engineering | 10/25/50-robot load harness on the current code (last run 15 Oct at bb7ec88, before the audit trail and metrics counters); results in tests/load/results and PROGRESS; fixes for any threshold missed | Every TRD performance threshold passes on a recorded host. **Met:** 17 October at fa08f92 (v0.3.0 code): every threshold passed at 10/25/50 robots with the browser; 50 robots: WebSocket latency p99 130 ms of 250, 60 frames/s, 0 console errors, 0 drops, backend memory 50 MiB of 300 (tests/load/results/latest.md) |
| I. Accessibility and interaction review — **done 19 Oct** (screen reader pass open) | 2–3 days / engineering | The design brief's checks on the current UI: keyboard-only operation of every control, visible focus, labels, 200% zoom, 390 px width, contrast of the token pairs, one screen reader pass, reduced motion; the interaction requirements (units, unknown-not-zero, deletion confirmation, busy states, copy patterns) checked one by one; fixes with tests | A written review with each item passed, fixed, or recorded as a known gap. **Met:** [ACCESSIBILITY_REVIEW_2026-10-19.md](../ACCESSIBILITY_REVIEW_2026-10-19.md) |
| J. Observed onboarding (PR-12) | Founder: 3 participants; engineering: fixes, 1–3 days | Sessions with GETTING_STARTED only; time, errors, interventions; prioritized fixes | ≥2 of 3 finish within 20 minutes without help, or the gaps are fixed and re-tested |
| K. External pilot (PR-13) | Founder plus 1–2 engineering days | One outside integrator's incident or reaction scenario, consented and redacted | Outcome recorded, or the release keeps the preview designation |
| L. Upstream follow-through | Engineering, as reviews arrive | Answer InOrbit's reviews on PRs #82–#85 and #14; when one merges, move the pin in `ros2/Dockerfile` and delete its patch | No patch kept for a merged fix |
| M. Discovery-gated (PR-14) | Only with user evidence | Live site-broker bridge, configurable simulated manufacturer, duplicate-mission detection | A user need recorded in PROGRESS first |

H and I need no outside people and come first. J and K run whenever participants are available; L whenever
InOrbit answers.

## Package details

### H — Load

Run `tests/load/run_load.py` at 10, 25 and 50 robots with missions and browser monitoring, on an isolated stack.
Compare with the 15 October run (tests/load/results/latest.md) and D-38. Watch the costs added since: the audit middleware (state-changing requests only), metrics
counters on every message (a lock per increment), robot-scoped validation (runner side only). Use `/api/metrics`
during the run as a second view of drops and backlogs.

### I — Accessibility and interaction

Work from the [design brief](UI_UX_DESIGN_BRIEF.md): first capture the current screens (desktop 1,440×900 and
1,024×768, 390 px), then check each item and record the result. Small fixes go in with component tests; anything
larger is listed with its reason. Do not claim WCAG conformance from this review; it is a design objective.

### J/K — Evidence from people

Unchanged from the 15 October plan: participants get only the public README and sample scenario; record time,
errors and interventions; an ActuNode example does not count as an external pilot; publish only consented,
redacted details.

## Traceability and release gates

| Requirement | Implementation evidence | Verification |
|---|---|---|
| PR-01/10/15, TR-07/10 | Compose, broker ACL/TLS, per-person logins, roles, audit trail | Fresh start, sharing-mode e2e (users, viewer refusals, removal), security regressions/scans |
| PR-02/03, TR-01/02 | Mission/protocol code and fixtures | Both VDA versions, identity collisions, schema/order tests |
| PR-04/05, TR-03/05 | Simulator controls, hub and UI panels | Fault behavior, malformed traffic, reconnect/slow-client checks |
| PR-06/07, TR-04 | Recorder/readers/replayer | Upload/retention/crash/replay-conflict and bounded-input checks |
| PR-08/09, TR-06 | CLI, sample scenarios and outside clients | Docker scenarios, exit codes, recording ownership, cleanup, robot-scoped checks |
| PR-11, TR-08 | Independent stack, conformance report, patches | Weekly ROS 2 workflow, unpatched and patched |
| PR-12, TR-09 | Onboarding instructions and UX fixes | Package J sessions; package I review |
| PR-13 | External incident/scenario and feedback | Package K |
| PR-16, TR-11 | `/api/metrics` | Unit tests; e2e scrape in both modes |
| PR-17, TR-12 | Image workflow | Build of both architectures; attestation verified on the release |

Before v0.4.0: required lint/types/unit/contract/e2e/scenario gates pass on the candidate; the ROS 2 workflow and
image build pass; **all load thresholds pass at 10/25/50 robots on a recorded host (H)**; the accessibility review
is written (I); PR-12/13 outcomes recorded or the preview designation kept; public quick start works from a clean
checkout.

## Risks, fallback and deferred work

| Risk | Response |
|---|---|
| Added per-message work costs throughput | H measures it; counters can be batched if a threshold is missed |
| Pilot recruitment takes longer than development | Ship previews; never describe internal tests as market validation |
| Upstream does not merge the patches | Keep them optional and reproducible; the unpatched measurement stays the default |
| UI fixes obscure evidence | Preserve raw message access, truncation markers and contract fixtures |
| Scope grows into production orchestration | Keep planning/avoidance/safety and hosted multitenancy out |

Deferred until evidence justifies them: live broker bridge, configurable manufacturer simulation, duplicate-mission
detection, persistent indexed search, SSO and finer roles. (Done since 15 October and no longer deferred: per-user
audit, metrics, published images, scenario/API versioning.)

The release decision records which criteria were met, unmet or deliberately deferred and why.
