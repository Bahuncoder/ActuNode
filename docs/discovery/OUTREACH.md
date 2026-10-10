# Outreach messages

For the plan's customer discovery: **30 conversations in 60 days**, research not pitching. Each
message asks for 15 minutes to learn how robot integrations go wrong. Nothing is for sale.

Rules for every message:

- Say who you are and that you are not selling anything. Both must be true.
- Ask about *their* experience, not about ActuNode. Mention the project only as context.
- One clear ask: 15 minutes, their choice of time. Make it easy to say no.
- Personalise the first line (their post, product, talk, repo). A generic message gets ignored.
- Never overstate what ActuNode does. Today it is an open-source lab: simulated robots, VDA 5050
  2.1 messages, failure injection, validation, record and replay. No real robots yet.

Replace `[...]` before sending. Log every message in the private tracker
(`docs/company/discovery_tracker.csv`, not in git).

## LinkedIn connection note (keep under 200 characters)

> Hi [Name], I'm a computer engineering student researching how AMR integrations fail during
> deployment. Your work on [specific thing] stood out. Could I ask you a few questions?

## Main message, by segment

### System integrators

> Hi [Name],
>
> I'm a computer engineering student building an open-source tool for testing and debugging AMR
> integrations (VDA 5050 over MQTT). I'm not selling anything; I'm trying to learn what actually goes
> wrong when robots meet a customer's WMS, PLCs and network.
>
> I saw [their project / post / company work] and you clearly know this better than most. Could I ask
> you 15 minutes of questions about your last AMR deployment: what broke, what was hard to test before
> go-live, and how you debugged it?
>
> Any time that suits you next week works for me. If now is a bad time, no problem at all.
>
> [Your name]
> [GitHub: https://github.com/Bahuncoder/ActuNode]

### AMR startups

> Hi [Name],
>
> I'm a computer engineering student working on an open-source integration lab for AMRs: simulated
> robots, VDA 5050 message validation, failure injection and record/replay. Not a product pitch;
> I want to understand how robot companies test customer integrations.
>
> How do you test that your robots behave with a customer's fleet manager before you're on site?
> Do you support VDA 5050, and which version? I'd be grateful for 15 minutes of your time,
> whenever suits you.
>
> [Your name]
> [GitHub link]

### Warehouse and 3PL engineers

> Hi [Name],
>
> I'm a computer engineering student researching how automated warehouses deal with robot downtime
> and exceptions. I'm not selling anything.
>
> I'd love to hear how robot problems show up in your operation: what causes the most downtime, and
> how support gets handed between you and the robot vendor. Would you have 15 minutes for a few
> questions?
>
> [Your name]

### University robotics labs and clubs

> Hi [Name],
>
> I'm a computer engineering student building an open-source lab for learning and testing robot
> fleet integration (simulated AMRs, VDA 5050 over MQTT, failure injection, replay). It runs on a
> laptop with Docker, no robots needed.
>
> Could it be useful for teaching or for your students' projects? I'd value 15 minutes of feedback on
> what would make it worth using, or why it wouldn't be.
>
> [Your name]
> [GitHub link]

### Open-source maintainers (ROS 2, Open-RMF, VDA 5050 libraries)

> Hi [Name],
>
> Thank you for [project]; I've learned a lot from it. I'm a computer engineering student working on
> an open-source tool for testing and replaying VDA 5050 robot communication, and I want to make sure
> I'm filling a real gap rather than duplicating existing work.
>
> Which integration and debugging problems do you see people struggle with that existing tools don't
> cover? 15 minutes of your view would help a lot, at any time that suits you.
>
> [Your name]
> [GitHub link]

## Follow-up (once, 5–7 days later, only if no reply)

> Hi [Name], just bringing this to the top of your inbox in case it got buried. If you're busy, no
> worries; even a one-line answer to "what broke in your last AMR deployment?" would help.

## After a conversation (same day)

> Thank you for your time today, [Name]. [One specific thing you learned] was especially useful.
> If anything else comes to mind, or if you know someone else I should talk to, I'd be grateful.
> I'll share what I build from this.

Always ask at the end of a call: *who else should I talk to?* That is how 5 conversations become 30.
