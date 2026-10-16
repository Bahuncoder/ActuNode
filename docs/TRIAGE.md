# Triage: how issues are handled

For maintainers, and for anyone reporting a problem: what helps, what happens to an issue, and how fast (D-54).

## What a good report contains

The single most useful thing is **a file that reproduces it**:

| Problem | Attach |
|---|---|
| A robot or fleet manager misbehaves, or the validator is wrong about a message | The **session file** (UI: Sessions → Download; or a site capture converted with `actunode import`). Remove anything confidential first: recordings contain every message, including your robots' names and positions. |
| A scenario fails or the runner misbehaves | The **scenario file**, the command, and the runner's output (or the JUnit file) |
| The lab does not start | `docker compose ps`, `docker compose logs --tail 200 <service>`, OS and Docker version |
| The UI | Browser and version, the console (F12) output, a screenshot |

Plus: ActuNode version (`GET /api/health` or the UI's header), VDA 5050 version, how many robots.

**Security problems are never reported in an issue**: see [SECURITY.md](../SECURITY.md) (private report).

## Labels

| Label | Meaning |
|---|---|
| `bug` | Something does not work as documented |
| `enhancement` | A new capability or a change in behaviour |
| `conformance` | ActuNode's VDA 5050 interpretation (validator, simulator, conformance suite) is wrong or incomplete; cite the spec section |
| `needs-reproduction` | Waiting for a file or steps that reproduce it |
| `documentation` | The docs are wrong, missing or unclear |
| `good first issue`, `help wanted` | Suitable for new contributors |
| `duplicate`, `invalid`, `wontfix`, `question` | As GitHub defines them |
| `dependencies`, `docker`, `python`, `javascript` | Dependabot's update pull requests |

## The routine

1. **Within 3 working days** a maintainer reads every new issue and either labels it (`bug`, `enhancement`,
   `conformance`, `documentation`, `question`) or asks for what is missing (`needs-reproduction`).
2. **Reproduce first.** A bug is confirmed when it is reproduced, preferably as a failing test or scenario: upload
   the session and validate it, run the scenario, or replay the recording. If it cannot be reproduced after the
   reporter's answer and one more try, it is closed with an explanation (it can always be reopened).
3. **Fix with a test.** Every bug fix includes a test that fails before the fix (CONTRIBUTING.md). The pull request
   names the issue; the changelog entry names the behaviour change.
4. **`needs-reproduction` closes after 14 days** without an answer, with a note saying how to reopen.
5. **Conformance questions** are decided against the VDA 5050 text: the answer quotes the section. Where the spec is
   silent, the decision goes into docs/DECISIONS.md.
6. **Weekly:** merge or close Dependabot pull requests (CI must be green), look at issues older than 2 weeks
   without a decision.

## Priorities

Security (private) > data loss or a broken lab for everyone > wrong verdicts (the validator or a scenario says the
opposite of the spec) > a broken documented feature > everything else.
