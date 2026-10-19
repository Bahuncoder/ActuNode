# External pilot guide (package K, requirement PR-13)

**Goal:** one outside integrator turns one of **their own** incidents, or their fleet manager's reaction to a
failure, into a scenario that fails before a fix and passes after it, and tells us whether that was worth it.
An example maintained by ActuNode does not count.

## Who

A team that integrates VDA 5050 robots or builds a fleet manager, with a recent incident they can describe and
some evidence of it (broker logs, a capture, notes). One team is enough; a second is a bonus.

## Agreement before starting (written, short)

- What they share: only what they choose; site captures are **minimized and redacted** first (robot names, site
  identifiers, positions if sensitive). They can run everything on their own machine and share only conclusions.
- What we publish: nothing without their written OK; an anonymized summary is the default.
- Time: about half a day of their time over one to two weeks, with an engineer available.

## Steps

1. **Incident interview (30 min):** what happened, what the fleet manager and robot should have done, what
   evidence exists. Write down the expected behaviour as one sentence ("when X, the fleet manager must Y within Z s").
2. **Bring it into the lab:** either import their capture (`actunode import`, then upload and validate), or rebuild
   the situation with the simulator and failure injection. Their fleet manager connects with its own login
   (`mqtt-init add-master`); a real robot with `add-robot` (docs/CONNECT_YOUR_ROBOT.md).
3. **Write the scenario together:** the expected sentence becomes `expect`/`never` steps (cli/README.md, the
   gallery); run it against their current version: it should **fail** the way the incident did.
4. **Their fix, then rerun:** the scenario passes; optionally add it to their CI (examples/ci/).
5. **Debrief (30 min):** did the scenario reproduce the incident? What took longest? Would they keep it in CI?
   What is missing for their next incident?

## Report (one page)

| | |
|---|---|
| Participant | Role, company type (anonymized unless agreed) |
| Incident | One paragraph; the expected-behaviour sentence |
| Evidence used | Capture / logs / reconstruction |
| Scenario | Steps (or the file, if they agree), fail before / pass after |
| Effort | Hours on their side, on ours |
| Outcome | Kept in CI? Would recommend? What blocked? |
| Findings | Each one an issue, linked |

File it in PROGRESS.md and the PRD's PR-13 row. Without a pilot by the release, the release keeps its preview
designation (implementation plan, release gates).
