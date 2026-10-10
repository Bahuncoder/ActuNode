# Message schemas

JSON Schemas (draft 2020-12) used by ActuNode's validator.

**These are ActuNode's own subset, written from the VDA 5050 2.x specification. They are not the
official VDA 5050 schemas.** They cover the fields ActuNode uses and enforce required fields, types
and enumerations. Extra properties are allowed, because vendors extend messages (ActuNode itself
adds an `actunode` object to `state`).

| File | Topic | Spec |
|---|---|---|
| `header.schema.json` | (shared by all) | VDA 5050 header: headerId, timestamp, version, manufacturer, serialNumber |
| `state.schema.json` | `…/state` | VDA 5050 state |
| `order.schema.json` | `…/order` | VDA 5050 order |
| `connection.schema.json` | `…/connection` | VDA 5050 connection |
| `actunode-inject.schema.json` | `actunode/v1/sim/<robot>/inject` | ActuNode failure-injection command |

Rules that need more than one message (headerId increasing, legal mission status transitions,
order sequence ids, topic/payload consistency) live in `app/validator.py`.
