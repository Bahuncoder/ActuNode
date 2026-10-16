---
name: Bug report
about: Something does not work as documented
labels: bug
---

<!-- Security problems: do not open an issue, see SECURITY.md. How issues are handled: docs/TRIAGE.md -->

**What happened**

**What you expected** (link the doc, or the VDA 5050 section, that says so)

**A file that reproduces it** (the most useful part)
- A session file (UI: Sessions → Download) or a converted site capture (`actunode import`): remove anything
  confidential first, recordings contain every message.
- Or the scenario file and the `actunode test` command and output.

**Steps to reproduce** (if there is no file)

**Versions**: ActuNode (UI header or `GET /api/health`) · VDA 5050 (2.1 / 3.0) · robots (simulated / your own) · OS and Docker

**Logs** (`docker compose logs --tail 200 <service>`, browser console)
