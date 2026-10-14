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
  The Step 4 observation handoff is complete; `observation_complete` measures
  collection only. Enforce unresolved approval/order/write gates in Steps 6–8;
  Step 5 classification remains observation-only.
- Step 6 currently adds operator-only group-correction preflight and review
  payloads. Keep its results unauthorized and outside executable intake/actions.
  No native writer exists until installed atomic revision/technician protection
  is verified; two reads or a local lock do not establish that contract.
  Native preflight recovery and v1-to-v2 history upgrade checks now pass. Frozen
  sources under `scripts/history_fixtures` are synthetic verification only; never
  import them into application activities or use them as a live policy choice.
- Step 7 adds operator-only Mirza policy previews, exact-scope packages and pinned
  review records. These remain unauthorized and outside executable intake/action
  tables. The first approval observation is not a verified approved-terms baseline.
  Preserve original reviewers and DWE identity pins; native source sequence and
  approved-term authority remain unverified. Do not infer them from a note match.
  Native provisioning, ticket updates and notification delivery remain disabled.
- Step 8 implements only the network-free fulfillment simulator. Its dedicated
  fixture tables, generated tenant prefix and `.invalid` identities cannot serve
  as native execution authority. Keep raw generated keys in the private cipher/
  owner-delivery boundary, indexed activity receipts stable, and uncertain effects
  blocked without positive downstream evidence. Do not expose fixture seeding as
  an API or register a native writer based on a simulation pass. Temporary non-key
  grants remain blocked until safe ownership/expiry handling exists in Step 9.
- Temporal owns workflow state. Keep I/O in activities, and make activities
  idempotent before adding privileged actions. PostgreSQL stores projections/audit.
- PydanticAI is the selected agent framework. Step 5 pins the minimal OpenAI
  inference package and implements observation agents; reuse Pydantic contracts and run agents in
  Temporal activities. Give agents only explicit scoped read tools and bounded
  sanitized results. Policy checks and privileged writes remain outside agents.
- Agent inference must use `local-qwen3.8` exclusively. Do not evaluate or fall
  back to online-provider models. Local-model failures remain blocked.
- Keep observation polling and inference disabled by default. Observation receipts
  must not enter executable intake or action staging. Durable cache claims prevent
  retries from repeating uncertain model calls; never erase spend reservations to retry.
  Runtime model accuracy needs reviewed live examples before activating Step 6.
- Keep dispatch and Mirza workers on separate task queues. Do not write to Mirza
  database tables directly. Use least-privilege credentials per process later.
- Do not change ticket templates or assign technicians. Lifecycle process tickets
  and their children remain excluded. Follow the eight-job Mirza allowlist.
- Preserve human assignments for every group change, including the Mirza DWE
  handoff. The earlier handoff clearing exception was revoked on 2026-10-14.
  Unknown assignment origin is treated as human; assigned fallback requests
  require manual handling. Approved same-group Mirza jobs remain eligible.
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
  Use `Approved Mirza terms: <review reference>` bound to the persisted exact
  terms/cycle/reviewers; matching text alone does not verify ordering or authorize a job.
- Use Python 3.12, four-space indentation, type hints at service boundaries,
  snake_case names, and explicit dependency pins. Shell uses strict Bash and
  quoted expansions.
- Local verification: `.venv/bin/python -m pytest`, `.venv/bin/ruff check app
  migrations scripts tests/unit`, `docker compose config --quiet`, and, for a
  running local stack, `bash scripts/check_runtime.sh`.
- Local resources are limited. Keep Compose caps, build/check sequentially,
  monitor this project's CPU/RAM, and stop its containers after verification.
  Never stop unrelated containers or delete persistent volumes as cleanup.
  Retain explicit Temporal SQL pool limits: default pools exhausted the local
  database's 57 application slots. `compose.resource-check.yaml` provides the
  lower CPU verification profile; see the Step 6 guide for measurements.
