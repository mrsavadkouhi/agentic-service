# Developer Changelog

Append the next unused `DEV-NNN` after every development task, including research,
blocked and documentation work. Keep scope, rationale, evidence/checks, outcome,
related decisions/incidents, deployment status and next actions factual and dated.

## DEV-001: 2026-10-28 Shared Agent Guidance

- Request/scope: adapt the reference diagnostic/developer pattern only into
  agentic-service local documentation. Preserve the original 88 root rules,
  operator authority, observation defaults, writer restrictions and commit policy.
- Sources: reference canonical index, developer playbook, diagnostic first 230
  lines, architecture overview and ADR index; target root instructions/README,
  decision register, Step 4/9 and runtime guides, package/test configuration,
  API/worker/workflow, connector factory and PydanticAI observation code.
- Existing state: initial `git status --short` was clean. `.agents/` and `.codex/`
  were empty; no existing `CLAUDE.md` facts or native records required moving.
  Existing plans, operational docs, evidence and application code stay in place.
- Changes/rationale: add shared index, both roles, empty `AGT-0NN` ledger,
  architecture/facts, decision index and documentation-only ADR-0001; prepend root
  routing without altering original instructions, add a short `CLAUDE.md` router
  and README agent section. No tool-specific competing definitions or ignore
  changes are necessary; `.agents/` remains eligible for tracking.
- Checks: `git diff --check` passed. A local `python3 -c` documentation validator
  compared `AGENTS.md` against `git show HEAD:AGENTS.md`: all original 88 lines
  remain a byte-for-byte suffix. It validated 130 local Markdown links/anchors
  across 11 new/changed documents, new-document whitespace/final newlines, and
  `git check-ignore` confirmed all eight canonical `.agents/` files are eligible
  for tracking. No application tests needed for guidance-only changes.
- Outcome: canonical role guidance and mandatory records prepared; existing
  authoritative decision/operational knowledge linked rather than duplicated.
  No incident invented and no live behavior inferred from synthetic evidence.
- Deployment: uncommitted, not pushed, not deployed. No SSH, runtime calls,
  inference/paid probes, application or production mutations performed.
- Related: ADR-0001; no incident ID because this setup was not an investigation.
- Next actions: none for this setup. Current runtime facts, installed permissions
  and native execution authority remain unverified; this documentation request
  authorizes no follow-up runtime checks or activation.
