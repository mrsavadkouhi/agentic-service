# ADR-0001: Shared Agent Knowledge and Records

Date: 2026-10-28
Status: Accepted by the user's local documentation request
Related: [DEV-001](../records/developer-changelog.md#dev-001-2026-10-28-shared-agent-guidance)

## Context and options

The user requested the diagnostic/developer pattern used by the reference
repository, confined to agentic-service documentation. Existing root restrictions,
operator decisions and consumer-facing operational guides must retain authority.
Tool-specific duplicate playbooks would split memory; moving all existing docs
would disturb unrelated consumers and evidence links.

## Decision

Keep canonical playbooks, architecture, incident memory, ADR index and development
records in `.agents/`, with root routing in `AGENTS.md`, `CLAUDE.md` and `README.md`.
Index existing `docs/` decisions/evidence in place. Diagnosis owns `AGT-0NN` and
updates it after every investigation; development owns `DEV-NNN` for every task,
including research and blocked work. Mixed work cross-links both records.

## Consequences

Tools share one knowledge source. The initial incident board is empty. The
original 88 root instruction lines remain verbatim; there is no additional job,
writer, approval inference, model choice or operational permission. Existing
explicit-request commit policy and operator-applied Mirza rollout policy remain.

## Validation and deployment

Documentation diff/link and root-preservation checks are recorded in DEV-001.
This is a repository baseline, not a runtime investigation. No SSH, runtime calls,
inference, commit, push or deployment is part of this request. No runtime rollout
or rollback is needed; any later documentation revision must preserve historical
records and authority boundaries.
