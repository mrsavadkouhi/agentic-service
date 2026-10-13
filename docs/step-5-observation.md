# Step 5: ticket observation agents

Implementation and offline verification are complete on 2026-10-13. Polling and
inference remain disabled. Live model quality, the Docker image and native
PostgreSQL/Temporal recovery still need verification before rollout. No production
ticket, Mirza or Mattermost write capability was added.

## Execution and data boundaries

The dispatch queue owns `ObservationListenerWorkflow` and
`ObservationTicketWorkflow`. Classification runs in a dispatch activity; eligible
Mirza extraction runs in a Mirza activity. Workflow history contains only ticket
IDs, queue names, opaque observation receipts and reason codes. Raw ticket text,
notes, inventory and SDK messages stay in activity memory. Typed proposals,
sanitized evidence hashes and versions are stored in the local application
database, separately from executable intake/actions. Normalized proposals can
contain intended owner emails; restrict access to application storage/backups.

The implementation uses `pydantic-ai-slim[openai]==2.55.0`, with separate agents
and existing Pydantic job contracts. This matches the documented
[minimal provider installation](https://pydantic.dev/docs/ai/overview/install/) and
[OpenAI-compatible provider configuration](https://pydantic.dev/docs/ai/models/compatible-apis/).
The locked OpenAI SDK uses `httpx2`; the existing read connectors retain their
`httpx==0.28.1` transport. Existing dependency pins and container caps are retained.

The classifier's only tool returns fixed ownership rules. The extractor's only
tool returns a ticket-scoped catalog: up to three exact eligible emails, their
mapped/current or explicitly referenced teams, opaque key references including
expired keys, served models and budget baselines. Limits are 20 teams/20 keys and
8 KiB of projection. Neither agent can issue HTTP, SQL, SSH or privileged writes.
HTML scripts/styles and credential patterns are removed from request content;
oversized/incomplete reads produce local review rather than partial interpretation.
Text and notes remain untrusted input. SDK tracing/content logging is disabled.

All results have `authorized: false`. Proposals are checked with the existing
policy engine, using unverified source ordering and no approval authority. A
policy reason such as `unverified_source_order` is expected. Classification never
creates an enrollment, action receipt, ticket note, status transition or message.

## Intake behavior

The listener scans current Helpdesk tickets regardless of template or email/UI
source, plus the two verified dedicated Mirza template IDs (`11702`, `11401`). It
verifies returned filter scope, deduplicates IDs and rotates a bounded batch.
Verified native persisted DWE handoffs remain observable with the original DWE
in-charge identity. Synthetic records cannot enroll native tickets; untracked
other-template DWE requests are no-ops.

Verified lifecycle roots/children are excluded before reading text. Unknown
process membership requires local review. Ordinary requests propose group
correction only for unassigned current Helpdesk tickets. Existing technicians,
correct Helpdesk ownership and ordinary requests outside Helpdesk produce no-ops.
No template changes or technician assignment are proposed.

Only the eight confirmed Mirza operations are extracted. Direct key model grants,
key reassignment, key membership in non-Tool teams and other unsupported Mirza
assistance are no-ops. Missing fields, duplicate keys including expired ones,
unverified identities/mappings and manual manager teams produce a typed request
with missing-field identifiers. Clarification drafts use the accepted template
and technician or DWE contact; they remain local. Raw API keys in input are
redacted and require an unambiguous opaque key reference rather than guessing.

## Configuration and first observation

Apply migration `0003_observations` before deploying the new API/workers. Compose
runs it before startup; use the migration procedure in
[runtime operations](runtime-operations.md) for an existing stack. Downgrade
deletes observation proposals and spend reservations, so take a backup first.

Configure `.env` locally using the blank fields in `.env.example`. Do not copy
production credentials into examples or workflow arguments. The dispatch worker
receives ServiceDesk/process-index read settings and a dedicated inference token.
The Mirza worker also receives directory/Mirza read settings. The API retains its
Step 4 operator readers and receives only the inference-enabled reporting flag,
without the inference token. Neither worker receives a Mattermost token.

Both workflow modes must stay `observe` for automatic polling. Inference needs a
fixed HTTPS LiteLLM-compatible URL, a dedicated inference credential, a model
alias, and declared upper-bound input/output USD rates per million tokens. The
credential must differ from read/administrator/intake/operator credentials. The
agent service does not provision or modify that Mirza credential/model.

| Setting | Default |
|---|---:|
| `AGENTIC_OBSERVATION_LISTENER_ENABLED` | `false` |
| `AGENTIC_OBSERVATION_POLL_SECONDS` | 60 |
| `AGENTIC_OBSERVATION_BATCH_SIZE` | 4 |
| `AGENTIC_INFERENCE_ENABLED` | `false` |
| `AGENTIC_INFERENCE_TIMEOUT_SECONDS` | 30 |
| `AGENTIC_INFERENCE_REQUEST_LIMIT` | 3 per stage |
| `AGENTIC_INFERENCE_TOOL_LIMIT` | 2 per stage |
| `AGENTIC_INFERENCE_INPUT_TOKEN_LIMIT` | 20,000 per stage |
| `AGENTIC_INFERENCE_OUTPUT_TOKEN_LIMIT` | 2,000 per stage |
| `AGENTIC_INFERENCE_MAX_COST_USD` | 0.25 per stage |
| `AGENTIC_INFERENCE_DAILY_BUDGET_USD` | 2 shared across both workers |

An extraction can consume a second stage reservation after classification.
Provider retries are disabled; SDK validation/request/tool limits and an overall
timeout bound each run. One inference runs per worker at a time. Spend is reserved
atomically before a call, rounded upward, with a shared Tehran-date daily cap.
Estimates use declared rates, not a provider invoice. Conservative preflight can
reject a costly alias before calling it. Unknown/lost responses keep their full
reservation; an activity retry returns the existing receipt without calling the
model again. A daily-budget rejection can retry on a later Tehran day. Changed
ticket evidence, scoped catalog, prompt/configuration or model creates a new claim.

For a first observation, keep polling off and enable only configured inference.
Recreate affected services to load environment changes. With the existing
operator authentication, `POST /v1/observations/{numeric_ticket_id}` starts or
wakes one observation workflow. `GET /v1/observations/{numeric_ticket_id}` returns
up to ten local stage results. The intake token cannot access these endpoints.
Inference disabled produces an explicit unavailable outcome and no model call.

Enable polling only after reviewing single-ticket outcomes. Setting the listener
flag false and recreating API/workers makes existing listener polls skip source
reads; existing workflows remain durable. Manual operator observations still
work. Disabling inference prevents further model calls. A listener retains its
initial poll interval/batch size in history; changing those values for an already
running listener requires replacing that listener workflow, with its abandoned
ticket children preserved. Worker pause controls continue to stop queue polling.
`/runtime` reports configured inference/polling switches, not provider readiness.

## Verification and quality review

Offline tests use the documented
[FunctionModel testing approach](https://pydantic.dev/docs/ai/guides/testing/).
Fixtures cover English/Persian routing, all eight typed jobs, scoped catalogs,
assignment/process guards, unsupported requests, invalid tools/outputs, timeouts,
caps, cache/retry uncertainty, revisions and API isolation. These are contract
tests with labeled model responses, not evidence of a real model's language accuracy.

Use a private reviewer label file outside Git after observing real examples:

```json
[
  {"ticket_id": "123", "expected_kind": "correct_support_group", "expected_group_id": "456"},
  {"ticket_id": "124", "expected_kind": "mirza", "expected_operation": "increase_team_budget"},
  {"ticket_id": "125", "expected_kind": "no_op"}
]
```

```bash
.venv/bin/python scripts/evaluate_observations.py --labels /private/reviewed-labels.json
```

The script reads local observations only; it emits aggregate accuracy, missing
cases, inference latency and cost estimates, with no ticket/employee identities.
Labels must be unique per ticket, bounded to 2,000 cases; `manual_review` is also
an accepted expected kind. It selects extraction only when evidence matches the
latest classification. Include English/Persian, all groups, all jobs, human
assignments, wrong templates, unsupported key operations and lifecycle exclusions.
Human review of extracted terms remains necessary beyond kind/operation accuracy.

The local checks pass: 399 pytest cases, Ruff, both quiet Compose configurations, dependency
compatibility, SQLite migration/metadata parity and Temporal workflow sandbox
imports. The full suite took four seconds, averaging 94% of one CPU and peaking
at 180 MiB RSS with no swapping. Worker imports, both agent instances, actual
client initialization and one offline classification peaked at 138 MiB RSS;
192 MiB worker caps remain. Docker was unavailable, so image build/native PostgreSQL locking and
Temporal replay/restart are pending. No live inference or external write was
performed. Step 6 must verify recovery/resource behavior and reviewed live model
quality before enabling any support-group correction.
