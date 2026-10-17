# ActuNode product specification

Working specification · updated 17 October 2026 · baseline: **v0.3.0** (roadmap weeks 1–16 complete; the full
audit closed, D-50). First written 15 October 2026 against v0.1.0 plus milestones 9–12.

These documents describe the existing product and the requirements for its next release. **Current** means supported by repository implementation or recorded verification. **Proposed** means work or validation still required; it is not a shipped capability. Targets are acceptance criteria, not measurements or customer commitments.

| Document | Purpose |
|---|---|
| [PRD](PRD.md) | Users, problems, scope, requirements and success criteria |
| [TRD](TRD.md) | Architecture, interfaces, constraints and verification |
| [App flow](APP_FLOW.md) | User journeys, decisions, recovery and state transitions |
| [UI/UX design brief](UI_UX_DESIGN_BRIEF.md) | Information hierarchy, interaction and accessibility |
| [Backend schema](BACKEND_SCHEMA.md) | Runtime entities, API contracts and persistent session format |
| [Implementation plan](IMPLEMENTATION_PLAN.md) | Sequenced deliverables, dependencies and release gates |

Read PRD → app flow → design brief for product decisions; TRD → backend schema → implementation plan for engineering work. Requirement IDs connect the documents.

## Sources and maintenance

The code defines current behavior. [Architecture](../ARCHITECTURE.md), [decisions](../DECISIONS.md), [use cases](../USE_CASES.md), [progress](../PROGRESS.md), [roadmap](../PLAN.md) and [audit](../AUDIT_2026-10-14.md) provide supporting context. Consult [CLI documentation](../../cli/README.md) for executable scenario syntax.

This package complements those documents; it does not replace the historical roadmap or progress log. Update affected requirements and contracts with behavior changes. Record significant design choices in DECISIONS.md and verification in PROGRESS.md. The founder owns product prioritization; engineering owns implementation and evidence. These are proposed roles, not claims about staffing.

Open decisions: which external pilot workflow to prioritize, and whether field users need capture import or a live broker bridge. User interviews may reorder proposed work. (Decided since: the first independent connector is InOrbit's ROS 2 VDA 5050 connector, D-51.)
