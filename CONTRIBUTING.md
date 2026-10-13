# Contributing to ActuNode

Thank you for helping. By submitting a contribution you agree that it is licensed under the project
license, Apache License 2.0 (inbound = outbound). See [LICENSE](LICENSE).

## Development setup

Details: [README.md](README.md#development) ("Development") and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
("Tests and CI"). You need an MQTT broker on `localhost:1883` (for example `sudo apt install mosquitto`).

```bash
# Backend
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt

# Simulator (from repo root)
python3 -m venv simulator/.venv && simulator/.venv/bin/pip install -r simulator/requirements-dev.txt

# Frontend (Node 24, see frontend/.nvmrc)
cd frontend && nvm use && npm install
```

## Tests

Write the test first, watch it fail, then make it pass. Every bug fix gets a test.

| Suite | Command |
|---|---|
| Python lint/format (repo root) | `backend/.venv/bin/ruff check . && backend/.venv/bin/ruff format --check .` |
| Backend | `cd backend && .venv/bin/pytest` |
| Simulator | `simulator/.venv/bin/pytest simulator` |
| Frontend | `cd frontend && npm run lint && npm test && npm run build` |
| End to end (needs Docker) | `tests/e2e/.venv/bin/pytest tests/e2e` (Playwright: `tests/e2e/.venv/bin/python -m playwright install chromium` once) |
| Load (needs Docker, about 4–5 minutes, by hand) | `tests/e2e/.venv/bin/python tests/load/run_load.py` |

All suites must pass before you open a pull request.

## Style

Python: ruff, 120 columns. Frontend: oxlint (`npm run lint`).

## Contract fixtures

`contracts/` holds JSON fixtures shared by backend and frontend tests, so both sides test against the
same message shapes and a change on one side cannot silently break the other. After a deliberate shape
change, regenerate them with `ACTUNODE_UPDATE_CONTRACTS=1 .venv/bin/pytest` (in `backend/`), review the
diff, and commit it.

## Documentation

Update with every change (see the header of [docs/PROGRESS.md](docs/PROGRESS.md)):

- `docs/PROGRESS.md`: status, session log, open issues
- `docs/DECISIONS.md`: why, for any non-obvious design choice
- `CHANGELOG.md`: what changed
- `docs/ARCHITECTURE.md`: if the structure, topics, or APIs changed

## Commits

Short plain imperative summaries, for example "Fix order update on a cancelled mission" or
"Docs: Week 6 complete". One logical change per commit. No AI attribution lines.
