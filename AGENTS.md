# Repository instructions

This repository implements internal ICT workflows. `plan.md` and
`docs/step-1-decisions.md` define the operator-confirmed scope. Preserve those
decisions; do not add new jobs or reinterpret approval authority without asking.

- Never commit or push without an explicit request.
- Never commit `.env`, credentials, raw API keys, real tickets or employee data.
- Default both workflows to observation. Steps 2–3 implement runtime probes and
  durable ticket contracts with an opt-in synthetic connector. There are no
  ServiceDesk, Mattermost or Mirza write connectors.
- Step 4 adds optional operator-only read connectors. Its installed authority
  gaps are tracked in `docs/step-4-read-connectors.md`. Keep incomplete context
  distinct from verified approval and never feed it into executable intake as proof.
- Temporal owns workflow state. Keep I/O in activities, and make activities
  idempotent before adding privileged actions. PostgreSQL stores projections/audit.
- PydanticAI is the selected agent framework. Add its minimal pinned inference
  dependency with Step 5's agents; reuse Pydantic contracts and run agents in
  Temporal activities. Give agents only explicit scoped read tools and bounded
  sanitized results. Policy checks and privileged writes remain outside agents.
- Keep dispatch and Mirza workers on separate task queues. Do not write to Mirza
  database tables directly. Use least-privilege credentials per process later.
- Do not change ticket templates or assign technicians. Lifecycle process tickets
  and their children remain excluded. Follow the eight-job Mirza allowlist.
- The operator confirms all historical lifecycle children used one dedicated
  n8n account. A verified configured creator plus the explicit coverage setting
  can rule out children from other creators; positive mappings take precedence.
  Unmatched n8n-created tickets and unknown creator metadata remain blocked.
- Missing execution terms require the agreed clarification flow, not invented
  defaults. Approval and clarification remain separate gates.
- Changed Mirza terms and older approvals without a recorded terms snapshot
  require the original approver(s)' verified note confirmations before reopening.
  Preserve native required approvals and original reviewer identities; current
  ticket hashes or technician clarification cannot substitute for terms approval.
- Use Python 3.12, four-space indentation, type hints at service boundaries,
  snake_case names, and explicit dependency pins. Shell uses strict Bash and
  quoted expansions.
- Local verification: `.venv/bin/python -m pytest`, `.venv/bin/ruff check app
  migrations scripts tests/unit`, `docker compose config --quiet`, and, for a
  running local stack, `bash scripts/check_runtime.sh`.
- Local resources are limited. Keep Compose caps, build/check sequentially,
  monitor this project's CPU/RAM, and stop its containers after verification.
  Never stop unrelated containers or delete persistent volumes as cleanup.
