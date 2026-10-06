# Repository instructions

This repository implements internal ICT workflows. `plan.md` and
`docs/step-1-decisions.md` define the operator-confirmed scope. Preserve those
decisions; do not add new jobs or reinterpret approval authority without asking.

- Never commit or push without an explicit request.
- Never commit `.env`, credentials, raw API keys, real tickets or employee data.
- Default both workflows to observation. Step 2 implements synthetic runtime
  probes only; it has no ServiceDesk, Mattermost or Mirza write connectors.
- Temporal owns workflow state. Keep I/O in activities, and make activities
  idempotent before adding privileged actions. PostgreSQL stores projections/audit.
- Keep dispatch and Mirza workers on separate task queues. Do not write to Mirza
  database tables directly. Use least-privilege credentials per process later.
- Do not change ticket templates or assign technicians. Lifecycle process tickets
  and their children remain excluded. Follow the eight-job Mirza allowlist.
- Missing execution terms require the agreed clarification flow, not invented
  defaults. Approval and clarification remain separate gates.
- Use Python 3.12, four-space indentation, type hints at service boundaries,
  snake_case names, and explicit dependency pins. Shell uses strict Bash and
  quoted expansions.
- Local verification: `.venv/bin/python -m pytest`, `.venv/bin/ruff check app
  migrations scripts tests/unit`, `docker compose config --quiet`, and, for a
  running local stack, `bash scripts/check_runtime.sh`.
- Local resources are limited. Keep Compose caps, build/check sequentially,
  monitor this project's CPU/RAM, and stop its containers after verification.
  Never stop unrelated containers or delete persistent volumes as cleanup.

