# Shared Agent Knowledge

This is the canonical, versioned home for agent playbooks and shared engineering
memory. Read [AGENTS.md](../AGENTS.md) and the
[architecture overview](architecture/overview.md) first. These files supplement
existing instructions without changing operator-confirmed scope or authority.

## Roles and mandatory memory

| Request | Playbook | Required record |
|---|---|---|
| Symptoms, errors, logs, deployed-state questions | [Diagnostic agent](diagnostic-agent.md) | Embedded `AGT-0NN` ledger after every investigation, including repeats and inconclusive checks |
| Features, fixes, refactors, design, rollout preparation | [Developer agent](developer-agent.md) | Dated `DEV-NNN` for every task, including research-only and blocked work |
| Incident and fix | Diagnose first; hand evidence and issue ID to developer | Both records, cross-linked when status changes |

Follow these definitions directly or supply them to tool-supported subagents.
Do not assume automatic discovery or keep competing definitions under `.claude/`,
`.codex/` or `.kilo/`. Native tool state is not canonical knowledge. Preserve
existing records when consolidating; inspect and link rather than deleting them.

## Architecture and decisions

- [Architecture overview](architecture/overview.md)
- [Cross-file facts and authority boundaries](architecture/cross-file-facts.md)
- [Decision index](decisions/README.md), linking authoritative existing decisions
- [Developer changelog](records/developer-changelog.md)
- [Documentation role policy](decisions/0001-shared-agent-knowledge.md)

## Knowledge kept with its consumers

Existing scope, operational knowledge and evidence remain in place. This is an
index, not a migration of unrelated plans or a rewrite of confirmed decisions.

- [Operator-confirmed plan](../plan.md) and [decision register](../docs/step-1-decisions.md)
- [Service ownership](../docs/service-ownership.md) and [department mapping](../docs/department-tool-team-map.md)
- [Discovery](../docs/step-1-discovery.md) and [supporting discovery artifacts](../docs/discovery/)
- [Local runtime](../docs/step-2-runtime.md) and [execution foundation](../docs/step-3-execution.md)
- [Read-only connectors and authority gaps](../docs/step-4-read-connectors.md)
- [Observation agents and evaluation](../docs/step-5-observation.md)
- [Group-correction contract review](../docs/step-6-group-correction.md)
- [Mirza policy review](../docs/step-7-mirza-policy.md)
- [Synthetic provisioning and recovery](../docs/step-8-provisioning.md)
- [Synthetic lifecycle and recovery](../docs/step-9-lifecycle.md)
- [Runtime operations](../docs/runtime-operations.md)
- [Operator entry point](../README.md), [application](../app/), [migrations](../migrations/), [tests](../tests/), [verification scripts](../scripts/)

## Evidence and access boundaries

The 2026-10-28 baseline is a repository inspection, not fresh node observations.
Historical installed checks in `docs/` retain their original dates and limits.
Current running revision, deployment topology, credential scope, live permissions
and runtime health are unknown until independently verified within authorization.
The diagnostic playbook permits only authorized read-only connectors; it grants
no SSH access or blanket probing authority. Unknown approval remains unknown.
Simulation, collection completeness and local test success cannot authorize native
execution. Operational mutations require explicit operator approval; local work
follows the existing root development and commit rules.
