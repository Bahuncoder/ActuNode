# ActuNode scenarios in CI

Run your scenario files against the lab on every push, with the result as a pass/fail check, a JUnit report
and a recording of every run (D-49).

## Locally, the way CI runs it

```bash
docker compose up -d --build --wait
mkdir -p test-results
docker compose run --rm runner test scenarios/ --junit test-results/junit.xml    # the sample scenarios
ACTUNODE_SCENARIOS=/path/to/your/scenarios docker compose run --rm runner test scenarios/
```

The `runner` service is the `actunode test` command in a container (`cli/Dockerfile`). It is not started by
`docker compose up`. It reaches the lab from inside (no ports, no extra host names) and receives only the
web login token, used when the lab requires login. Exit codes as `actunode test`: 0 passed, 1 failed,
2 invalid scenario, 3 the lab could not be used.

| Variable | Default | Meaning |
|---|---|---|
| `ACTUNODE_SCENARIOS` | `./scenarios` | Folder mounted as `scenarios/` in the runner |
| `ACTUNODE_RESULTS` | `./test-results` | Folder for `--junit` reports (create it first) |
| `ACTUNODE_UID` / `ACTUNODE_GID` | 1000 | User the lab and the runner write files as; in CI, the runner's own (`id -u`) |

## On GitHub Actions

Copy [github-actions.yml](github-actions.yml) to `.github/workflows/` in your repository and replace the two
marked steps: how your fleet manager starts, and where your scenario files are. ActuNode's own CI runs the
same steps with the example fleet manager ([.github/workflows/ci.yml](../../.github/workflows/ci.yml), job
`scenarios`), so the template is tested on every change.

Each run is recorded in the lab; the workflow keeps the recordings (`sessions/*.jsonl`) with the JUnit
report. To see what happened in a failed run, download the artifact and upload the session in the lab
(Sessions → Upload), then validate or replay it.

Other CI systems need the same five steps: start the lab, add a login, start your system, `docker compose
run --rm runner test …`, keep `test-results/` and `sessions/`.
