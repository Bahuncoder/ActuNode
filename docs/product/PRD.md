# Product requirements document — ActuNode Lab

Working specification · updated 17 October 2026 (v0.3.0) · [Document index](README.md)

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

Current baseline (v0.3.0): VDA 5050 2.1.0 and 3.0.0, 1–50 simulated robots, a fixed warehouse map, mission send/cancel/extend, five failure types, validation, proximity warnings, JSONL sessions, capture import, YAML scenario runner, Docker deployment and example CI integration; an optional independent ROS 2 / Nav2 robot with a VDA 5050 2.x conformance suite and published report; per-person web logins with viewer/operator roles and an audit trail; Prometheus metrics; published amd64/arm64 images with provenance.

Next release (v0.4.0): observed onboarding and validated external pilot workflows (PR-12, PR-13), plus the release gates that need re-measuring (load, accessibility). Delivered since the 15 October baseline: PR-11 (v0.2.0) and the full audit (v0.3.0). No evidence currently establishes real-hardware compatibility or product-market fit.

Out of scope: production fleet orchestration, collision avoidance, physical safety certification, warehouse map authoring, fine-grained RBAC and enterprise SSO (roles: viewer, operator, and in the hosted service owner, D-56/D-61), autonomous dispatch and a generic WMS/ERP adapter. **Changed 19 October (D-61):** a hosted service on actunode.com (one isolated lab per workspace, GitHub/Google sign-in) is now in scope; billing follows the beta ([HOSTED_SERVICE.md](../HOSTED_SERVICE.md)). Replay is open-loop: recorded robots cannot respond dynamically to new fleet-manager commands. Schema validity does not certify full VDA conformance.

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
| PR-08 | P0 / current | CLI runs strict YAML scenarios with timing/message expectations, recordings and JUnit output. Test failure, bad input and unavailable infrastructure produce distinct exit codes. Validation checks can be scoped to one robot, so other robots in a shared lab do not decide a step (D-59). |
| PR-09 | P0 / current | External robot or fleet manager connects using scoped MQTT credentials. Site capture import produces a portable session. Documented examples demonstrate both workflows. |
| PR-10 | P0 / current | Local binding is the default; network sharing requires login and encrypted exposed listeners. Untrusted messages/files have bounded processing. |
| PR-11 | P1 / **done** (v0.2.0; D-51, D-52, D-55) | Optional independent ROS 2 / Nav2 stack receives a mission and emits traffic ActuNode can inspect. Deliver a versioned reproduction guide and candid pass/fail conformance report. Evidence: `--profile ros2`, [CONNECT_YOUR_ROBOT](../CONNECT_YOUR_ROBOT.md), [conformance report](../CONFORMANCE_ROS2_CONNECTOR.md): pinned connector 4/9 scenarios and 0/4 raw checks; with ActuNode's patches 9/9 and 4/4; both measured weekly in CI; patches proposed upstream (inorbit-ai/ros_amr_interop #82–#85, vda5050_adapter_examples #14). |
| PR-12 | P1 / **in progress** | A new user completes first mission, injected failure, saved recording and first passing scenario using public instructions, without live author assistance. Record observed completion time and failure points. Shipped: [GETTING_STARTED](../GETTING_STARTED.md), verified by following it from a fresh clone (D-54) — an author check, which does not count. Open: sessions with new users. |
| PR-13 | P1 / **open** | At least one outside integrator runs their own incident or response scenario and supplies actionable feedback; record outcome with consent. No participant yet. |
| PR-14 | P2 / discovery | Evaluate live site-broker bridging, configurable simulated manufacturer and duplicate-mission cases only after concrete user evidence. |
| PR-15 | P1 / current (v0.3.0, D-56) | A shared lab gives each person their own login; a viewer can watch but not change the lab; every change (missions, failures, recordings, uploads, deletes, replays, logins) is attributed to a person in an audit trail visible in the UI and the API. Removing a person ends their sessions without a restart. |
| PR-16 | P1 / current (v0.3.0, D-57) | An operator can monitor the lab's load (traffic, rejected messages, live feeds and drops, robots, storage, the broker's memory and dropped messages) with Prometheus, also on a shared lab. |
| PR-17 | P1 / current (v0.3.0, D-58) | A user can run a release without building it: published images for amd64 and arm64, with verifiable provenance. |

## Success and measurement

| Measure | Proposed acceptance target | How measured |
|---|---|---|
| First useful result | At least 2 of 3 new pilot participants finish PR-12 within 20 minutes after prerequisites are installed | Moderated onboarding sessions; record interventions separately |
| Independent interoperability | One pinned external robot stack completes a mission; limitations reproducible | PR-11 integration report and saved traffic |
| Incident usefulness | One outside integrator converts their incident into a failing/passing scenario | Pilot report with anonymized evidence |
| Reliability at supported scale | Existing 10/25/50-robot load thresholds pass | Repository load harness with host and workload recorded |
| Regression protection | Required unit, contract, scenario and e2e gates pass | CI artifacts for the candidate commit |

Status 17 October: *independent interoperability* met (PR-11); *regression protection* met for v0.3.0 (CI on the tagged commit); *reliability at supported scale* met again on 17 October at fa08f92 (v0.3.0 code): every threshold passed at 10/25/50 robots with the browser; 50 robots: WebSocket latency p99 130 ms of 250, 60 frames/s, 0 console errors, 0 drops, backend memory 50 MiB of 300; *first useful result* and *incident usefulness* not yet measured (they need participants).

These pilot targets are proposed decision gates. Collect feedback locally and manually; telemetry is not currently a product dependency. Interviews should ask how failures are debugged today, how often they occur, and what evidence teams can share.

## Risks and decisions

An internal simulator and an internal example fleet manager can agree while sharing the same mistake: independent-stack testing addresses this. Site captures may contain sensitive operational details: pilots should use consented, minimized samples. Limited simulation fidelity must be stated wherever results could be mistaken for motion/safety validation. If pilots cannot complete onboarding, prioritize those failures before adding broader simulation features.

Release decision: preserve P0 behavior, satisfy PR-11/12, and document PR-13 results or explicitly retain a preview designation. Feature quantity alone is not the release criterion. v0.2.0 and v0.3.0 shipped with PR-12 and PR-13 open: the project remains a preview until new-user and pilot evidence exists.
