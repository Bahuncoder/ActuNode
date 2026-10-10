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
point `OFFICIAL_SCHEMA_DIR` in `validator.py` at it (VDA 5050 3.0 support is planned per D-15).

## ActuNode's own schemas

| File | Checks |
|---|---|
| `actunode-state.schema.json` | ActuNode's `actunode` extension of `state` (mission status values), in addition to the official schema |
| `actunode-inject.schema.json` | ActuNode's failure-injection command on `actunode/v1/sim/<robot>/inject` (not VDA 5050) |

Rules a schema cannot express (headerId per topic, order sequence, state machine, topic consistency)
and plausibility checks the official schema does not make (e.g. `batteryCharge` within 0–100 %, which
the 2.1.0 schema leaves unbounded) are in `app/validator.py`.
