# Compatibility: what you can rely on (v0.x)

ActuNode is pre-1.0. This page says what we keep stable between 0.x releases so that your scenarios, recordings and
CI keep working, what may change, and how a change is announced (D-54).

## Stable: changed only with a new format version and a migration note

| Interface | Version | Where defined | Promise |
|---|---|---|---|
| Scenario files | format **1** (`version: 1`, optional) | [cli/README.md](../cli/README.md), `cli/actunode/scenario.py` | Files that pass `actunode test --dry-run` today keep passing and mean the same. A runner refuses a file declaring a later format version instead of half understanding it. New optional fields may be added. |
| Session files (recordings) | `formatVersion: 1` | [ARCHITECTURE.md](ARCHITECTURE.md) "Session file format", `backend/app/recorder.py` | Recordings made by any 0.x release can be uploaded, validated and replayed by later 0.x releases. |
| `actunode test` command | | `actunode test --help` | Options keep their meaning; exit codes 0 passed, 1 failed, 2 invalid input, 3 the lab could not be used, 130 interrupted. JUnit output keeps one test case per scenario. |
| MQTT topics and logins | | README, [CONNECT_YOUR_ROBOT.md](CONNECT_YOUR_ROBOT.md) | `uagv/v2|v3/<manufacturer>/<serial>/<topic>`; robot logins `<manufacturer>.<serial>`, fleet manager logins `master@<name>` with the permissions documented there. |

## Kept compatible where possible, announced in the changelog when not

| Interface | Notes |
|---|---|
| HTTP API (`/api/...`) | Endpoints and fields used by the UI, the runner and the docs. New fields may appear in answers at any time (clients must ignore unknown fields). A removed or renamed endpoint or field is listed under **Breaking** in [CHANGELOG.md](../CHANGELOG.md) for at least one release first, as deprecated. |
| Compose services and environment variables | `docker compose` service names, `ACTUNODE_*` variables. |
| Metrics (`/api/metrics`) | Names and labels are kept; a renamed or removed metric is listed under **Breaking** in the changelog. |
| Validator rules | Rule names (`schema`, `header-id`, ...) are stable; a rule may get stricter where VDA 5050 requires it (each such change is in the changelog). |

## Not promised

- ActuNode's own extension fields in simulated robots' state (`actunode.missionStatus`, `injectedFailures`).
- The UI's layout and the WebSocket event shapes (internal to the UI).
- Simulator internals and timing beyond what the scenarios document.
- The optional ROS 2 profile's internals (pinned third-party code; the connector it wraps changes upstream).

## VDA 5050 versions

2.1 and 3.0 (robots and orders), with 2.0 robots accepted on the 2.x topics. Support for a new VDA 5050 version is
added alongside, not instead of, the existing ones.

## Reporting a break

If an update breaks a scenario, a recording or your CI, that is a bug: open an issue with the file attached
([TRIAGE.md](TRIAGE.md)).
