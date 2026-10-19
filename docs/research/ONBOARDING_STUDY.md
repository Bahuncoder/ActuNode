# Onboarding study (package J, requirement PR-12)

**Question:** can a new user get from the public instructions to a first passing scenario without help?
**Target (PRD):** at least 2 of 3 participants finish within 20 minutes after the prerequisites are installed,
without the moderator's help. An author's own run does not count.

## Participants

Three people who have **not** used ActuNode, each from one of: a fleet manager or integration developer, an AMR
vendor engineer, a robotics student. They need Docker installed (that is a prerequisite, not part of the 20
minutes) and a screen share or a seat next to the moderator. No payment is assumed; offer to share the findings.

## Before the session (moderator)

- A clean machine or a fresh folder; no ActuNode images built yet (`docker image ls | grep actunode` shows
  nothing), or decide in advance to test the **published images** path instead and say which in the notes.
- Open nothing for them. Have the observation sheet (below) ready; a timer.
- Consent (read out, note the answer): "We want to see where our instructions are unclear. We will note what you do
  and say, not record your screen unless you agree. Your name will not be published; quotes only with your OK. You
  can stop at any time."

## The session (40 minutes)

1. **Before showing anything (5 min):** "Tell me about the last time an integration between robots and a fleet
   manager went wrong. How did you find out what happened? What evidence did you have?" (From the PRD: how failures
   are debugged today, how often, what can be shared.)
2. **Task (up to 25 min):** give only this: "Here is the repository: https://github.com/Bahuncoder/ActuNode. Get
   the lab running, send a robot on a mission, block its path, and record it. Then run the sample scenario so it
   passes. Think aloud." Start the timer when they open the README.
   - Do not help. If they are stuck for 3 minutes, ask "what are you looking for?"; if still stuck after 5 minutes,
     give the smallest hint and log it as an **intervention**.
3. **After (10 min):** "What was hardest? What did you expect to find and did not? Would this help with the
   incident you described? What would you need to use it on your project?"

## Observation sheet (one per participant)

| Milestone | Time (mm:ss) | Errors / confusion | Interventions |
|---|---|---|---|
| Found the getting-started path | | | |
| Lab running (UI shows robots) | | | |
| Mission sent, robot moving | | | |
| Blocked path injected and seen | | | |
| Recording saved | | | |
| Sample scenario passed (exit code 0) | | | |
| Stopped (if not finished) and why | | | |

Also note: operating system, Docker version, build vs published images, anything they read aloud twice.

## After all three

- Result against the target: how many finished within 20 minutes without interventions.
- Findings ranked by how many participants hit them; each becomes an issue (`documentation` or `bug`) with the
  sheet's evidence. Fix, then re-test the failing step with a new participant if possible.
- Record the outcome in [PROGRESS.md](../PROGRESS.md) and the PRD's PR-12 row; publish only consented quotes.
