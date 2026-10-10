# VDA 5050 notes

Working notes on the parts of VDA 5050 that ActuNode uses. Written from the 2.x specification;
check the official text before relying on details.

**VDA 5050 3.0 (March 2026) is a breaking release**: same topic layout and header, but renamed
fields (`agvPosition` → `mobileRobotPosition`, `batteryState` → `powerSupply`), new enums
(`CONNECTION_BROKEN`, error levels URGENT/CRITICAL) and edges without `startNodeId`/`endNodeId`.
Everything below describes **2.x**, which ActuNode speaks today. See
[research/VDA5050_3_0.md](research/VDA5050_3_0.md) for the full comparison and the plan (D-15).

## What it is

A communication interface between a central **master control** (fleet manager) and **AGVs/AMRs**,
carried over **MQTT** with **JSON** payloads. It lets one fleet manager drive robots from different
manufacturers.

## Topics

```
interfaceName/majorVersion/manufacturer/serialNumber/topic
uagv/v2/ActuNode/robot_01/state
```

| Topic | Direction | Purpose | In ActuNode |
|---|---|---|---|
| `order` | master → robot | Route (nodes + edges) and actions to perform | ✅ backend sends, simulator executes |
| `instantActions` | master → robot | Actions to run now (cancelOrder, pause, …) | ⬜ planned (cancel a blocked mission) |
| `state` | robot → master | Position, order progress, battery, errors, actions | ✅ every 1 s and on change |
| `visualization` | robot → master | High-rate position for displays | ⬜ |
| `connection` | robot → master | ONLINE / OFFLINE / CONNECTIONBROKEN, retained, last will | ✅ |
| `factsheet` | robot → master | Robot capabilities | ⬜ |

**QoS (section 6.2, same in 3.0):** QoS 0 (best effort) for `order`, `instantActions`, `state`,
`factsheet`, `visualization` (3.0 adds `zoneSet`, `responses`); QoS 1 (at least once) for `connection`.
So a `state` message may be lost by design: robots repeat state periodically and on every change, and a
fleet manager must cope with gaps. ActuNode follows this exactly (an integration tool must not hide
problems by being more reliable than the standard).

## Header (every message)

`headerId` (counts up **per topic**, starting at 1), `timestamp` (ISO 8601 UTC), `version`
(e.g. `2.1.0`), `manufacturer`, `serialNumber`.

**headerId across restarts.** The spec only says it is per topic and incremented by 1 per sent message;
it says nothing about restarts. ActuNode (backend and simulated robots) starts again at 1 after a
restart, like most implementations. Orders are identified by `orderId` + `orderUpdateId`, not
`headerId`. The validator reports a decrease it observes as a `header-id` *warning* ("sender restarted,
duplicate, or replay?"), not an error.

## Orders

- An order is a graph: **nodes** (positions, with actions) and **edges** (connections, with actions).
- Sequence ids alternate: nodes **even**, edges **odd**: node 0, edge 1, node 2, edge 3, node 4.
  Each edge connects the nodes right before and after it.
- `released: true` nodes/edges are the **base** (robot may drive there); unreleased ones are the
  **horizon** (planned, not yet authorised). ActuNode currently releases everything.
- Orders are updated with the same `orderId` and a higher `orderUpdateId`. Not used yet.
- Actions (`pick`, `drop`, …) have `blockingType` NONE / SOFT / HARD.

## State

- Reports `orderId`, `lastNodeId`, `lastNodeSequenceId`, and the **remaining** `nodeStates` and
  `edgeStates`: the robot removes nodes and edges as it passes them.
- `actionStates` move WAITING → INITIALIZING → RUNNING → FINISHED / FAILED.
- `errors` have `errorType`, `errorLevel` (WARNING / FATAL) and `errorReferences` pointing at the
  order, node, edge or action involved.
- `driving`, `operatingMode`, `batteryState`, `safetyState` (eStop, fieldViolation), optional
  `agvPosition` and `velocity`.

## Connection and last will

The robot sets an MQTT **last will** on its `connection` topic with `CONNECTIONBROKEN` (retained),
publishes `ONLINE` when connected and `OFFLINE` before a clean disconnect. The broker publishes the
last will if the robot vanishes.

## ActuNode extensions (not VDA 5050)

- `state.actunode.missionStatus`: the simulator's mission state machine
  `IDLE → ACCEPTED → MOVING → COMPLETED`, plus `BLOCKED` under failure injection and `FAILED`
  when the battery runs empty.
- `actunode/v1/sim/<robot>/inject`: failure-injection commands, kept off VDA 5050 topics.
- Error types: `pathBlocked` (BLOCKED_PATH failure, WARNING), `batteryEmpty` (FATAL), `orderError`
  (order rejected, WARNING).

## What the validator checks

Schemas: the **official VDA 5050 2.1.0 schemas** (vendored unchanged, see `backend/app/schemas/README.md`)
plus ActuNode's own schemas for its extension and inject command. Rules: `backend/app/validator.py`.

| Rule | Severity | Check |
|---|---|---|
| `invalid-json` | error | Payload parses as JSON |
| `schema` | error | Official VDA 5050 schema of the topic (all six topics), plus ActuNode's extension and inject schemas |
| `topic-mismatch` | error | `serialNumber` / `manufacturer` match the topic |
| `version-mismatch` | error | `version` major matches the topic's major version |
| `timestamp` | error | ISO 8601 with a time zone |
| `order-sequence` | error | Even node / odd edge ids, one edge between each pair of nodes, edges connect neighbours |
| `header-id` | warning | Increases per topic (retained messages exempt) |
| `mission-transition` | warning | ActuNode mission state machine is followed |
| `driving-consistency` | warning | `driving` is true exactly when MOVING |
| `last-node-regression` | warning | `lastNodeSequenceId` never goes backwards within an order |
| `value-range` | warning | Plausibility the official schema does not check: `batteryCharge` within 0–100 % |
| `proximity` | warning | Two live robots on the same map closer than `ACTUNODE_PROXIMITY_M` (1.0 m); once per incident (D-22) |

## Open questions to research

- ~~What changed in 3.0~~ → [research/VDA5050_3_0.md](research/VDA5050_3_0.md). Supporting 2.x and 3.0 side by side is planned for Week 5 (D-15).
- ~~Validate against the official JSON schemas~~ done for 2.1.0; 3.0 per D-15.
- `instantActions` cancelOrder as the response to a blocked path (plan: "cancel, reroute or escalate").
