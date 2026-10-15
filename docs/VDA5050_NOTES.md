# VDA 5050 notes

Working notes on the parts of VDA 5050 that ActuNode uses. Written from the 2.x specification;
check the official text before relying on details.

**VDA 5050 3.0 (March 2026) is a breaking release**: same topic layout and header, but renamed
fields (`agvPosition` → `mobileRobotPosition`, `batteryState` → `powerSupply`), new enums
(`CONNECTION_BROKEN`, error levels URGENT/CRITICAL) and edges without `startNodeId`/`endNodeId`.
ActuNode speaks **both**, chosen per message by the topic's major version (`v2` / `v3`, D-15). The
notes below describe **2.x** field names; [research/VDA5050_3_0.md](research/VDA5050_3_0.md) has the full
comparison with 3.0.

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
| `instantActions` | master → robot | Actions to run now (cancelOrder, pause, …) | ✅ implemented (D-35: cancelOrder, startPause/stopPause, stateRequest, factsheetRequest; 3.0 clearInstantActions) |
| `state` | robot → master | Position, order progress, battery, errors, actions | ✅ every 1 s and on every state event |
| `visualization` | robot → master | High-rate position for displays | ⬜ |
| `connection` | robot → master | ONLINE / OFFLINE / CONNECTIONBROKEN, retained, last will | ✅ |
| `factsheet` | robot → master | Robot capabilities | ✅ simulator publishes it (retained) on every connect |

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
  **horizon** (planned, not yet authorised). The simulator never drives into the horizon: it stops at
  the last released node (the decision point) and waits (D-35). ActuNode's own missions release
  everything.
- Orders are updated with the same `orderId` and a higher `orderUpdateId`; the update's first node must
  be the decision point (stitching). ActuNode's `extend` endpoint sends such updates (D-35).
- The first node of an order must be where the robot already is (within `allowedDeviationXY`), so
  ActuNode's orders start with a node at the robot's reported position.
- Actions (`pick`, `drop`, …) have `blockingType` NONE / SOFT / HARD (3.0 adds SINGLE).
- `instantActions` act immediately: `cancelOrder`, `startPause`/`stopPause`, `stateRequest`,
  `factsheetRequest` (3.0 also `clearInstantActions`). 3.0 makes cancel and pause mandatory.
- The simulator validates the graph and rejects a bad order (2.1 `validationError`, 3.0 `VALIDATION_FAILURE`): nodes at
  even sequenceIds in steps of 2 (from 0 for a new order, from the decision point for an update), exactly one edge at
  the odd id between neighbours (2.1: `startNodeId`/`endNodeId` name them), `released` present on every node and edge,
  released items before unreleased ones, the first node of a new order released, an `actionId` not reused by an
  update, header `version` major and `manufacturer` matching the robot, a known `mapId` (`warehouse`). `pick`/`drop`
  on an edge is an invalid order action (the factsheet lists `actionScopes` NODE only).
- Limits advertised in the factsheet (`maxArrayLens` 2.1 / `maximumArrayLengths` 3.0) and enforced: 300 nodes, 300
  edges, 50 instant actions per message. The **300 actions cap covers the whole order** (finished actions stay in
  `actionStates` until a new order), so a very long-running order eventually refuses further updates.
- Load control: a robot's inbox holds 100 orders and 100 instant actions/commands (more are dropped and counted);
  each tick applies at most 5 messages or 20 ms, instant actions first. A malformed action in an `instantActions`
  message is skipped on its own (neither version names an error for it) so a valid `cancelOrder` beside it still runs.
- Known limits of the simulator: `blockingType` has no effect (its actions are instant), no retriable
  actions, no corridors, zones or maps management.

## State

- Reports `orderId`, `lastNodeId`, `lastNodeSequenceId`, and the **remaining** `nodeStates` and
  `edgeStates`: the robot removes nodes and edges as it passes them.
- `actionStates` move WAITING → INITIALIZING → RUNNING → FINISHED / FAILED.
- `errors` have `errorType`, `errorLevel` (2.1: WARNING / FATAL; 3.0: WARNING / URGENT / CRITICAL /
  FATAL) and `errorReferences` pointing at the order, node, edge or action involved. 2.1 names only a
  few types in prose (`validationError`, `orderError`, `orderUpdateError`, `noOrderToCancel`); 3.0 has
  a table (`VALIDATION_FAILURE`, `OTHER_ORDER_ACTIVE`, `OUTDATED_ORDER_UPDATE`, …). Order errors stay
  until a new order is accepted. An error never clears the robot's order.
- `loads`: omitted if the robot cannot tell; `[]` means unloaded.
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
- Error types: `pathBlocked` (BLOCKED_PATH failure, WARNING in 2.1, CRITICAL in 3.0, D-42), `batteryEmpty` (FATAL), `batteryLow` (WARNING in 2.1, URGENT in 3.0), `orderError`
  (order rejected, WARNING).

## What the validator checks

Schemas: the **official VDA 5050 2.1.0 and 3.0.0 schemas**, chosen by the topic's major version (D-15, D-20); vendored unchanged, see `backend/app/schemas/README.md`)
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

- ~~What changed in 3.0~~ → [research/VDA5050_3_0.md](research/VDA5050_3_0.md). 2.x and 3.0 are supported side by side since 10 Oct (D-15, issue 8).
- ~~Validate against the official JSON schemas~~ done for 2.1.0 and 3.0.0 (D-20).
- ~~`instantActions` cancelOrder as the response to a blocked path~~ answered: implemented (D-35).
