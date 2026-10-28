# Decision Index

Existing policy decisions remain authoritative where their consumers use them.
This index does not renumber, duplicate or rewrite their approvals. Historical
checks remain dated evidence rather than new acceptance or deployed-state claims.

| Source | Authority / purpose |
|---|---|
| [plan.md](../../plan.md) | Operator-confirmed scope and staged implementation boundaries |
| [Step 1 decision register](../../docs/step-1-decisions.md) | Existing named decisions, approval policy, eight jobs and unresolved live contracts |
| [Service ownership](../../docs/service-ownership.md) | Group destinations and exclusions |
| [Department mapping](../../docs/department-tool-team-map.md) | Operator-verified mapping and unresolved entries |
| [Step 4](../../docs/step-4-read-connectors.md) | Observation/authority separation and installed read gaps |
| [Step 5](../../docs/step-5-observation.md) | Observation-only PydanticAI and local-model restrictions |
| [Step 6](../../docs/step-6-group-correction.md) | Unauthorized preflight and installed atomic-write blocker |
| [Step 7](../../docs/step-7-mirza-policy.md) | Exact-scope reviews and original reviewer/identity pins |
| [Step 8](../../docs/step-8-provisioning.md) | Synthetic fulfillment and private delivery boundary |
| [Step 9](../../docs/step-9-lifecycle.md) | Synthetic ownership, expiry and recovery limitations |

## New ADRs

| ID | Decision | Status |
|---|---|---|
| [ADR-0001](0001-shared-agent-knowledge.md) | Canonical agent playbooks and mandatory work records | Accepted by documentation request, 2026-10-28; no runtime policy change |

The developer maintains this index. Use the next unused `ADR-NNNN` for a
consequential new design choice. Include date, status (`Proposed`, `Accepted`,
`Rejected`, or `Superseded by ADR-NNNN`), related `DEV-NNN`/`AGT-0NN`, context and
evidence/unknowns, options, decision and actual approval evidence, consequences,
validation, deployment status and applicable rollout/rollback. Proposed choices
must not be represented as operator-confirmed. Link existing decisions; retain
rejected/superseded reasoning and link replacements. Update architecture when an
implemented decision changes behavior. ADR status never supplies ticket authority.
