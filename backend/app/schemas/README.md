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
upstream (checked with `diff`; lines: factsheet 173, 178, 183, 188; order 314; visualization 54, 115).
Already reported upstream as [VDA5050/VDA5050#660](https://github.com/VDA5050/VDA5050/issues/660) and
fixed on their main branch, but not in a release yet (latest tag 3.0.0, checked 11 Oct 2026). When a
fixed release (e.g. 3.0.1) is tagged, vendor it unchanged and drop this local fix.

The validator picks the set by the topic's major version: `v2` → 2.1.0, `v3` → 3.0.0.

## ActuNode's own schemas

| File | Checks |
|---|---|
| `actunode-state.schema.json` | ActuNode's `actunode` extension of `state` (mission status values), in addition to the official schema |
| `actunode-inject.schema.json` | ActuNode's failure-injection command on `actunode/v1/sim/<robot>/inject` (not VDA 5050) |

Rules a schema cannot express (headerId per topic, order sequence, state machine, topic consistency)
and plausibility checks the official schema does not make (e.g. `batteryCharge` within 0–100 %, which
the 2.1.0 schema leaves unbounded) are in `app/validator.py`.

## Known quirks in the 3.0.0 factsheet schema (worked around in the simulator, D-34)

- `protocolFeatures` … `pauseAllowed` and `cancelAllowed` are typed `string` in the schema but described
  as boolean in the specification text. The simulator sends `"false"` so the official schema validates.
- `required` lists `mobileRobotKinematic` while `properties` defines `mobileRobotKinematics`. The
  simulator sends both keys.

Upstream status (checked 11 Oct 2026): the boolean type for `pauseAllowed`/`cancelAllowed` is already
fixed on `main` (VDA5050/VDA5050 PR #609, merged 17 Jun 2026) but not in a release; a 3.0.1 bug-fix PR
(#632) is open. Whether the `mobileRobotKinematic(s)` mismatch is covered there was not verified; check
#632 before filing a report.
