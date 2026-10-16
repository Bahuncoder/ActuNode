# Getting started: from clone to a first passing scenario

About 10 minutes, most of it the first image build. You need Docker with Compose v2 (Docker Desktop on macOS and
Windows, Docker Engine on Linux) and a few GB of disk. No Python, no Node.

## 1. Start the lab

```bash
git clone https://github.com/Bahuncoder/ActuNode && cd ActuNode
docker compose up -d --build --wait
```

`--wait` returns once everything is healthy (first build: a few minutes). Open **http://localhost:8080**: three
simulated robots in a small warehouse, the message stream filling up, the validator counting.

Nothing is reachable from your network: every port is on `127.0.0.1` (sharing the lab is a separate step, README
"Sharing the lab").

## 2. Watch one mission

In the UI: **Mission sender** → robot `robot_01`, from `RECEIVING_DOOR_2` to `STORAGE_A17`, load `P-1042` →
**Send mission**. The robot goes ACCEPTED → MOVING; the message stream shows the order and each state. Then
**Failure injection** → `robot_01`, Blocked path → **Inject**: it stops and reports `pathBlocked`. **Clear**, and it
finishes the job.

## 3. Run your first scenario

The same story as a test, in a container (nothing to install):

```bash
mkdir -p test-results
docker compose run --rm runner test scenarios/p1042_blocked_path.yaml --junit test-results/junit.xml
```

(Linux with a user id other than 1000: `export ACTUNODE_UID=$(id -u) ACTUNODE_GID=$(id -g)` before
`docker compose up`, so the lab and the runner write files as you.)

About a minute. Each step prints `ok`, and the last line says `1 scenario(s): 1 passed`. The exit code is 0
(1 failed, 2 invalid file, 3 the lab could not be used); the JUnit report is in `test-results/`.

The run was recorded: in the UI, **Sessions** → the newest `p1042_blocked_path` session → **Replay** to watch it
again, or **Validate** to check every message against VDA 5050.

## 4. Make one fail

Copy the scenario and change what it expects, e.g. `error: pathBlocked` to `error: {type: pathBlocked, level: FATAL}`:

```bash
cp scenarios/p1042_blocked_path.yaml scenarios/my_first.yaml
# edit scenarios/my_first.yaml
docker compose run --rm runner test scenarios/my_first.yaml
```

The failing step says what the robot reported instead (`pathBlocked is WARNING (expected FATAL)`) and the exit
code is 1. The scenario format: [cli/README.md](../cli/README.md); every shipped scenario:
[SCENARIO_GALLERY.md](SCENARIO_GALLERY.md).

## 5. Next, depending on what you are testing

| You are | Next |
|---|---|
| Building or integrating a **robot** | [CONNECT_YOUR_ROBOT.md](CONNECT_YOUR_ROBOT.md): a login, then the conformance suite |
| Building or testing a **fleet manager** | [examples/fleet_manager/](../examples/fleet_manager/README.md): connect it, block an aisle, check its reaction |
| Running tests **in CI** | [examples/ci/](../examples/ci/README.md): the GitHub Actions template |
| Investigating a **site incident** | `actunode import` a broker capture ([cli/README.md](../cli/README.md)), upload, replay |
| Learning **VDA 5050** | [MESSAGE_FLOWS.md](MESSAGE_FLOWS.md), [FAILURE_CATALOGUE.md](FAILURE_CATALOGUE.md), [VDA5050_NOTES.md](VDA5050_NOTES.md) |

## Stop, reset

```bash
docker compose down           # stop (logins, certificates and recordings are kept)
docker compose down -v        # also delete the generated logins and certificates (new ones on next start)
```

Something wrong? README "Troubleshooting", then an issue with the session file attached
([TRIAGE.md](TRIAGE.md) says what helps).
