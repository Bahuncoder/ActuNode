# Message schemas

Used by the validator (`app/validator.py`), JSON Schema draft 2020-12.

## Official VDA 5050 2.1.0 schemas (`vda5050-2.1.0/`)

Vendored **unchanged** from the official repository:

- Source: <https://github.com/VDA5050/VDA5050/tree/2.1.0/json_schemas>
- Tag `2.1.0`, commit `511d01d71587e8a3dc5e71d4f41dc52466f4284c`
- License: MIT, copyright Verband der Automobilindustrie; see `vda5050-2.1.0/LICENSE.txt`

Files: `connection`, `factsheet`, `instantActions`, `order`, `state`, `visualization`. Every message
on a VDA 5050 topic is checked against the schema of its topic. None of them sets
`additionalProperties`, so vendor extensions (like ActuNode's `actunode` object) are allowed.

The repository notes that where it differs from the PDF published by the VDA, the PDF is authoritative.

To update: download the files from a newer tag into a new folder, record the tag and commit here, and
add it to `OFFICIAL_SCHEMA_DIRS` in `validator.py`.

## Official VDA 5050 3.0.0 schemas (`vda5050-3.0.0/`)

From the official repository, tag `3.0.0`, commit `e9ba560b0e2d3f66526550ad5d61b8a2ad936172`, MIT (see
`vda5050-3.0.0/LICENSE.txt`). Files: `connection`, `factsheet`, `instantActions`, `order`, `responses`,
`state`, `visualization`, `zoneSet`.

**One local change:** three upstream files are not valid JSON (trailing commas): `factsheet.schema` (4),
`order.schema` (1), `visualization.schema` (2). Those 7 commas were removed; nothing else differs from
upstream (checked with `diff`). Reported as PROGRESS issue 17. Re-check when updating to a newer tag.

The validator picks the set by the topic's major version: `v2` → 2.1.0, `v3` → 3.0.0.

## ActuNode's own schemas

| File | Checks |
|---|---|
| `actunode-state.schema.json` | ActuNode's `actunode` extension of `state` (mission status values), in addition to the official schema |
| `actunode-inject.schema.json` | ActuNode's failure-injection command on `actunode/v1/sim/<robot>/inject` (not VDA 5050) |

Rules a schema cannot express (headerId per topic, order sequence, state machine, topic consistency)
and plausibility checks the official schema does not make (e.g. `batteryCharge` within 0–100 %, which
the 2.1.0 schema leaves unbounded) are in `app/validator.py`.
