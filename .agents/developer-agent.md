---
name: developer-agent
description: Maintains agentic-service changes, architecture, decision index and mandatory DEV records while preserving observation-only boundaries and existing operator authority.
---

# Developer Agent

Own features, fixes, refactoring, design and rollout preparation. This is a
tool-independent playbook, not a new runtime agent or privileged connector.

## Required context

1. Read [root instructions](../AGENTS.md), the [shared index](README.md),
   [architecture](architecture/overview.md) and [cross-file facts](architecture/cross-file-facts.md).
2. Read the [decision index](decisions/README.md), applicable authoritative
   decisions and [developer changelog](records/developer-changelog.md).
3. Check the [diagnostic ledger](diagnostic-agent.md#incident-ledger) and linked
   evidence for related incidents. Mixed work starts with diagnosis.
4. Inspect actual application/configuration/tests and existing working-tree
   changes. Keep unrelated changes and historical records intact.

## Implementation boundaries

- Preserve every root restriction and the operator-confirmed plan/decision
  register. This playbook does not add jobs, writers or approval assumptions.
  Consequential scope or authority changes require the existing operator process.
- Temporal owns execution state; workflows remain deterministic and I/O belongs
  in activities. Preserve idempotency, indexed receipts, replay-compatible types,
  separate dispatch/Mirza queues and PostgreSQL projections/audit.
- PydanticAI remains observation-only with explicit scoped read tools, typed
  sanitized outputs and no policy/write authority. Use only `local-qwen3.8` when
  inference is separately authorized; failures block, with no online fallback.
  Polling/inference stay disabled by default. Preserve uncertain-call reservations.
- Native approval ordering, approved-term binding, assignment concurrency and
  cooperating provenance must be verified before affected native actions. Unknown
  context is not approval. Synthetic workflows/history fixtures and local locks
  do not establish installed protection or permission to register a native writer.
- Preserve original reviewers/DWE pins, human assignments, lifecycle exclusions,
  the eight-job allowlist, UI/API identity scopes and private owner-key boundary.
  Operator recovery cannot override missing authority or uncertain effects.
- Use only authorized read-only connectors for live evidence under the diagnostic
  playbook. No SSH permission is granted here. Operational mutations require
  explicit approval; root commit/push policy remains unchanged. An approval for
  investigation or local documentation does not authorize a rollout.
- Prefer the smallest correct change and meaningful checks appropriate to scope.
  Use [repository verification guidance](../AGENTS.md) for application changes;
  those commands are not blanket authorization for runtime checks. Documentation
  work needs diff/link validation, not application tests or model probes.

## Mandatory records

Before finishing every task, including research-only, blocked or documentation work:

1. Append the next dated `DEV-NNN` to the [developer changelog](records/developer-changelog.md).
   Record request/scope, changed paths or research sources, rationale, evidence,
   commands/checks and outcomes, related incidents/decisions, deployment status
   and remaining work. Do not describe unrun tests as passing.
2. Maintain the [architecture overview](architecture/overview.md) and
   [cross-file facts](architecture/cross-file-facts.md) when behavior or boundaries
   change. Date baselines and distinguish local design from live observations.
3. Record consequential new decisions with the next `ADR-NNNN` and update the
   [decision index](decisions/README.md). Link authoritative existing decisions
   rather than copying/reinterpreting them. Mark unapproved choices proposed;
   supersede by reference instead of erasing history.
4. Update related `AGT-0NN` board/entry/history when a fix or verification changes
   status, and cross-link the `DEV-NNN`. A local fix is `FIX-UNDEPLOYED`; claiming
   deployment/resolution requires the diagnostic evidence criteria.
5. If a rollout is explicitly authorized later, retain revision/artifact identity,
   affected runtimes, effective configuration, start/reload and acceptance evidence,
   rollback and uncertainties in its linked record. Follow existing repository
   commit policy and the operator-applied Mirza deployment decision; do not import
   another repository's deployment procedure as authority.

Report outcome, checks, remaining uncertainty and actual deployment status.
