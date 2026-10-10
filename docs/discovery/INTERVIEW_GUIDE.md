# Discovery interview guide (15 minutes)

Goal: learn **what actually goes wrong** in robot integrations and **what it costs**, so ActuNode
solves a real problem. Not goal: getting a compliment for the idea.

## Ground rules

- **Ask about the past, not the future.** "Tell me about the last time…" gives facts.
  "Would you use a tool that…?" gives polite guesses. Avoid it.
- **Talk less than 20 % of the time.** Follow up with "why?", "what happened next?", "how did you fix it?".
- **Don't pitch.** If they ask what you're building, answer in two sentences at the end.
- **Look for cost:** hours lost, site visits, delayed go-live, penalties. Pain without cost is not a business.
- **Write notes within the hour.** Use the template below.

## Script

**Opening (1 min)**
"Thanks for your time. I'm researching how robot integrations go wrong, not selling anything.
Can I take notes? Nothing you say will be shared with your name attached."

**Context (2 min)**
- What's your role, and how are robots involved in it?
- Which robots and fleet manager do you work with? **Which VDA 5050 version, if any?**
  (2.0, 2.1, 3.0, or vendor protocols.)

**The last deployment (6 min)**
- Tell me about the last AMR deployment or integration you worked on.
- What broke or took longer than planned?
- When did you find out: in the office, during testing, at go-live, in production?
- How did you figure out what was wrong? What did you look at (logs, MQTT traffic, vendor tools)?
- How long did it take, and what did it cost (people, site visits, delay)?

**Testing before go-live (3 min)**
- How do you test an integration before you're on site?
- What can't you test until the real robots are there?
- Have you ever tried to reproduce a problem from the field afterwards? How?

**Close (2 min)**
- If you could fix one thing about how integrations are tested or debugged, what would it be?
- Who else should I talk to about this?
- Can I follow up if I build something relevant?

## What to listen for

| Signal | Why it matters for ActuNode |
|---|---|
| Bugs found only at go-live or in production | Simulation and failure injection could move them earlier |
| "We couldn't reproduce it" | Record and replay |
| Malformed or unexpected messages between vendors | Validator |
| Mixed vendors or mixed VDA 5050 versions | Version support (D-15) |
| Time spent reading raw logs or MQTT traffic | Message inspector |
| They already built an internal tool for this | Strong signal the pain is real; ask to see it |

## Notes template

Copy into the private tracker or a private notes file; never commit names.

```
Date:
Segment: integrator / AMR startup / warehouse / university / open source
Role and company size:
Robots / fleet manager / VDA 5050 version:
Last deployment, what broke:
How they found and debugged it:
Cost (time, money, delay):
How they test before go-live:
Quotes (exact words):
Surprises (what contradicted my assumptions):
Referrals:
Follow-up agreed:
```

After every 5 interviews: write a short summary of repeated pain points in
[PROGRESS.md](../PROGRESS.md) under the session log, and note what changes in the plan, if anything.
