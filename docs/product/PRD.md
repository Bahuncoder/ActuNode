# Product requirements document — ActuNode Lab

Working specification · 15 October 2026 · [Document index](README.md)

## Product and problem

ActuNode Lab is a local, open-source workspace for reproducing and regression-testing AMR integration failures over VDA 5050 / MQTT without requiring a physical fleet. Integration faults are expensive to reproduce on a warehouse floor, message evidence disappears, and teams struggle to establish whether a robot or fleet manager violated the expected protocol.

The product combines robot simulation, message inspection and validation, fault injection, incident recording/replay and executable scenarios. Its intended outcome is a shareable incident that another engineer can inspect and turn into a repeatable integration test.

## Users and jobs

| User | Job | Evidence of value |
|---|---|---|
| System integrator / fleet-manager developer | Check how master control reacts to blocked, disconnected or silent robots | Scenario catches an incorrect response and passes after the fix |
| AMR vendor engineer | Check the robot's VDA 5050 traffic and order handling | Invalid traffic is identified with a rule and message context |
| Warehouse integration engineer | Bring a site incident into a reproducible lab | Capture imports, validates and can be shared with another engineer |
| Student / robotics lab | Learn protocol interactions without hardware | Completes mission → failure → recovery → replay |

Primary initial segment: integrators testing fleet-manager behavior. This is a prioritization hypothesis to validate through interviews, not established customer demand. A WMS team participates through its fleet manager; ActuNode does not implement a general WMS API.

## Scope and release boundary

Current baseline: VDA 5050 2.1.0 and 3.0.0, 1–50 simulated robots, a fixed warehouse map, mission send/cancel/extend, five failure types, validation, proximity warnings, JSONL sessions, capture import, YAML scenario runner, Docker deployment and example CI integration.

Next release candidate: independently developed ROS 2 / Nav2 integration, documented conformance results, clearer onboarding and validated external pilot workflows. No evidence currently establishes real-hardware compatibility or product-market fit.

Out of scope: production fleet orchestration, collision avoidance, physical safety certification, warehouse map authoring, billing, hosted multitenancy, per-user RBAC, autonomous dispatch and a generic WMS/ERP adapter. Replay is open-loop: recorded robots cannot respond dynamically to new fleet-manager commands. Schema validity does not certify full VDA conformance.

## Functional requirements

Priority: P0 = baseline/release blocking; P1 = next-release requirement; P2 = discovery dependent.

| ID | Priority / status | Requirement and acceptance |
|---|---|---|
| PR-01 | P0 / current | A fresh Docker installation starts the lab using the documented Compose command; API, MQTT and Live connectivity become visible and three default robots appear. Verify on a clean checkout. |
| PR-02 | P0 / current | User sends a mission to an explicit version/manufacturer/serial identity; sees the order ID, publication result and observed robot state separately. Invalid targets cannot change MQTT topic structure. |
| PR-03 | P0 / current | Simulator handles order execution, cancellation, supported updates and instant actions for both protocol versions; fixtures and conformance tests cover version differences. |
| PR-04 | P0 / current | User injects blocked path, low battery, disconnect, invalid payload or unresponsive behavior into simulated robots. Bounds and clearability are enforced; no fault injection into external hardware. |
| PR-05 | P0 / current | User sees live messages, raw details and schema/history issues. Malformed traffic remains diagnosable without crashing other panels. Filtering and pausing support inspection. |
| PR-06 | P0 / current | User records, stops, downloads, uploads, validates, deletes and replays sessions. Conflicting operations are refused with a reason; incomplete recordings are distinguishable. |
| PR-07 | P0 / current | Replay preserves timing at selected speed, defaults to robot-side traffic and refuses conflicting live identities. Current-time rewriting is explicit. |
| PR-08 | P0 / current | CLI runs strict YAML scenarios with timing/message expectations, recordings and JUnit output. Test failure, bad input and unavailable infrastructure produce distinct exit codes. |
| PR-09 | P0 / current | External robot or fleet manager connects using scoped MQTT credentials. Site capture import produces a portable session. Documented examples demonstrate both workflows. |
| PR-10 | P0 / current | Local binding is the default; network sharing requires login and encrypted exposed listeners. Untrusted messages/files have bounded processing. |
| PR-11 | P1 / proposed | Optional independent ROS 2 / Nav2 stack receives a mission and emits traffic ActuNode can inspect. Deliver a versioned reproduction guide and candid pass/fail conformance report. |
| PR-12 | P1 / proposed | A new user completes first mission, injected failure, saved recording and first passing scenario using public instructions, without live author assistance. Record observed completion time and failure points. |
| PR-13 | P1 / proposed | At least one outside integrator runs their own incident or response scenario and supplies actionable feedback; record outcome with consent. |
| PR-14 | P2 / discovery | Evaluate live site-broker bridging, configurable simulated manufacturer and duplicate-mission cases only after concrete user evidence. |

## Success and measurement

| Measure | Proposed acceptance target | How measured |
|---|---|---|
| First useful result | At least 2 of 3 new pilot participants finish PR-12 within 20 minutes after prerequisites are installed | Moderated onboarding sessions; record interventions separately |
| Independent interoperability | One pinned external robot stack completes a mission; limitations reproducible | PR-11 integration report and saved traffic |
| Incident usefulness | One outside integrator converts their incident into a failing/passing scenario | Pilot report with anonymized evidence |
| Reliability at supported scale | Existing 10/25/50-robot load thresholds pass | Repository load harness with host and workload recorded |
| Regression protection | Required unit, contract, scenario and e2e gates pass | CI artifacts for the candidate commit |

These pilot targets are proposed decision gates. Collect feedback locally and manually; telemetry is not currently a product dependency. Interviews should ask how failures are debugged today, how often they occur, and what evidence teams can share.

## Risks and decisions

An internal simulator and an internal example fleet manager can agree while sharing the same mistake: independent-stack testing addresses this. Site captures may contain sensitive operational details: pilots should use consented, minimized samples. Limited simulation fidelity must be stated wherever results could be mistaken for motion/safety validation. If pilots cannot complete onboarding, prioritize those failures before adding broader simulation features.

Release decision: preserve P0 behavior, satisfy PR-11/12, and document PR-13 results or explicitly retain a preview designation. Feature quantity alone is not the release criterion.
