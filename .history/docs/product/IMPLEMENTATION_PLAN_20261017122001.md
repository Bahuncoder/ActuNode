# Implementation plan — ActuNode Lab

Working specification · 15 October 2026 · [PRD](PRD.md) · [TRD](TRD.md)

## Planning basis

The original roadmap milestones 1–12 are recorded complete; this plan continues from that baseline toward a proposed v0.2.0. It does not schedule rebuilding shipped functionality. Milestone numbers in [PLAN.md](../PLAN.md) are work packages, not elapsed calendar weeks. Estimates below are planning ranges for engineering effort, not promised dates; external feedback and connector compatibility can change them.

No production code or new dependencies are introduced by this document package. Product prioritization belongs to the founder; engineering supplies runnable deliverables and test evidence. Roles below are responsibilities to assign, not assumed team members.

## Work packages and dependencies

| Package | Effort / responsible role | Deliverables | Dependency / exit gate |
|---|---|---|---|
| A. Baseline and discovery | 1–2 days / engineering + founder | Candidate baseline checks; current screenshots; 3 pilot recruits; recorded assumptions and interview questions | Start immediately; list observed gaps separately from proposed features |
| B. Connector feasibility | 2–4 days / integration engineering | Compare available independent ROS 2/VDA connectors, compatible protocol/ROS/Nav2 versions, licenses, maintenance and headless requirements; select and pin one | A technical baseline; demonstrate clean startup before committing to full profile |
| C. Independent stack integration | 3–6 days / integration engineering | Optional Compose profile/composition, scoped login, resource/startup limits, map/location mapping, mission and cancel example | B; PR-11 mission completes, traffic captured, default simulator startup unchanged |
| D. Conformance and regression | 2–4 days / engineering | Applicable scenario subset, pass/fail report with raw evidence, expected limitations, repeatable cleanup and CI decision | C; repeatable clean runs and no suppressed protocol failures |
| E. Onboarding and UX | 2–4 days / frontend + docs | First-scenario path, explicit target/status copy, complete/incomplete evidence cues, failure recovery guidance, keyboard/zoom fixes | A baseline; C/D limitations inform connector guide; PR-12 observed with new users |
| F. External pilot | 1–2 engineering days plus participant availability / founder + engineering | Outside integrator's incident or reaction scenario, consented recording, interview notes and prioritized findings | Existing lab is sufficient to recruit/run pilots; C optional unless pilot requires it; PR-13 evidence |
| G. Release candidate | 1–2 days / engineering + founder | Full gates, changelog/docs alignment, known limits, release notes and v0.2.0 decision | C/D/E plus F outcome or explicit preview status |

B–D correspond to original weeks 13–14; E includes weeks 15–16 onboarding and educational material. Discovery and pilot recruitment can proceed alongside engineering without depending on ROS 2 delivery.

## Package details

### A — Re-establish evidence

Run documented unit/lint/build gates and required Docker configurations on the candidate commit. Record actual results in PROGRESS.md, avoiding inherited test counts as proof of a new run. Compare current docs with implementation and log blockers. Capture journey A from [app flow](APP_FLOW.md) as the usability baseline. Ask pilot recruits about their last integration incident before demonstrating the tool.

### B/C — Add independent interoperability

Evaluate connectors using primary upstream documentation when implementation begins; no connector is selected in this specification. Confirm version compatibility and upstream license before adding artifacts. Pin image/source references and record provenance. Provision a separately scoped robot login and ensure topic identity matches mission target fields. Account for ROS coordinates/map IDs and Nav2 startup readiness; do not assume the lab's fixed map matches an arbitrary robot world.

Implement the optional stack and health/readiness checks, then mission completion and cancel. Store a minimal recording and exact reproduction commands. Avoid modifying the default simulator to hide connector deviations. If connector compliance prevents completion, publish reproducible findings and decide whether to fix upstream, add an explicit compatibility mode, or choose another connector.

### D — Test what is actually supported

Select scenarios using plain VDA fields for external robots; do not require `actunode.missionStatus`. Fault injection scenarios apply only to ActuNode's simulator, so independent-stack tests should cover mission acceptance/completion, cancellation, connection and validation. Record both protocol and functional outcomes: completing a mission with invalid traffic is not a clean conformance pass.

Prefer deterministic headless CI if resource and startup measurements support it. If integration needs manual or scheduled execution, document the exact reason, runner requirements and release procedure rather than claiming full CI coverage.

### E/F — Prove a usable workflow

Use the [design brief](UI_UX_DESIGN_BRIEF.md) to address observed friction with small changes to current panels. Test new-user mission/failure/recording and CLI scenario flow, including replay conflicts and malformed files. Record completion times and interventions against PR-12. Pilot evidence should capture the user's original problem, expected response, observed result and whether the artifact helped diagnose it. An example fleet manager maintained by ActuNode does not count as an external pilot.

Create a failure-case catalogue, scenario gallery and message-flow explanation from verified examples. Publish only consented/redacted pilot details. Keep the documentation usable without private company files.

## Traceability and release gates

| Requirement | Implementation evidence | Verification |
|---|---|---|
| PR-01/10, TR-07 | Compose, broker ACL/TLS, auth and security guards | Fresh start, sharing-mode e2e, security regressions/scans |
| PR-02/03, TR-01/02 | Mission/protocol code and fixtures | Both VDA versions, identity collisions, schema/order tests |
| PR-04/05, TR-03/05 | Simulator controls, hub and UI panels | Fault behavior, malformed traffic, reconnect/slow-client checks |
| PR-06/07, TR-04 | Recorder/readers/replayer | Upload/retention/crash/replay-conflict and bounded-input checks |
| PR-08/09, TR-06 | CLI, sample scenarios and outside clients | Docker scenarios, exit codes, recording ownership and cleanup |
| PR-11, TR-08 | Independent stack and conformance report | Clean setup, mission/cancel, saved traffic and documented deviations |
| PR-12, TR-09 | Onboarding instructions and targeted UX changes | Pilot completion target, keyboard/zoom review |
| PR-13 | External incident/scenario and feedback | Outside participant outcome recorded with consent |

Before release: required lint/types/unit/contract/e2e/scenario gates pass; all existing load thresholds pass at 10/25/50 robots on a recorded host; relevant security scans are reviewed; independent-stack limits are explicit; no unresolved release-blocking regression; public quick start works from clean checkout. Fixes include meaningful regression tests where behavior warrants them; prose-only updates need link/format review.

## Risks, fallback and deferred work

| Risk | Response |
|---|---|
| Connector is incompatible or unmaintained | Time-box feasibility; preserve findings and choose another candidate or explicitly retain preview scope |
| ROS stack makes default lab heavy | Keep opt-in composition, separate measurements and documented resource prerequisites |
| Pilot recruitment takes longer than development | Recruit early; ship usable previews without describing internal tests as market validation |
| UI improvements obscure evidence | Preserve raw message access, truncation markers and existing contract fixtures |
| Scope grows into production orchestration | Keep planning/avoidance/safety and hosted multitenancy outside this release |

Deferred until evidence justifies them: live broker bridge, configurable manufacturer simulation, duplicate-mission detection, persistent indexed search, per-user audit, metrics service, published images and API/scenario versioning. Track any dependency that becomes release-critical explicitly.

Changes to optional integration should be removable without session-format migration; disable its profile to return to the default lab. Preserve failing artifacts before cleanup. The release decision records which proposed criteria were met, unmet or deliberately deferred and why.
op