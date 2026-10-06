# Step 3: ticket contracts and durable execution

Implemented for local verification on 2026-10-06. This step establishes the
execution boundary. ServiceDesk reading/classification, actual group/status
updates, Mirza provisioning, key delivery and Mattermost messages remain later
steps. A local `completed` state means a no-op or a verified synthetic receipt;
it does not claim that a real ticket was fulfilled or resolved.

## Contracts and authority

`app/contracts/tickets.py` defines a closed normalized event contract, separate
support-group and Mirza team identities, and the eight operation variants. Unknown
fields and operations are rejected. API-key creation takes one Tool-team target
and has no key-model grant, key-team move or non-Tool membership fields. Personal,
key and team budgets have separate targets. A delta carries its original baseline
and absolute desired limit so retries cannot add it twice. These contracts do not
prove the installed Mirza update semantics; that verification remains Step 8.

Every event carries a source revision and verified ordering sequence, requester
and intended-person references, current assignment/status/template/category,
authoritative process context, read-only parent/child references, content reference
and digest, and policy/catalog/model/prompt versions. Raw ticket text stays behind
the content reference for the future restricted connector. Raw keys are outside
this contract; recognizable `sk-` values are rejected, including references inside
collections. This validation supplements, rather than replaces, the privileged
secret boundary required before implementing key generation/delivery.

The authenticated intake principal is a **trusted normalization connector**, not
the LLM, a ticket requester or a browser. It must obtain identity, history, order,
process and approval evidence from authoritative ServiceDesk reads. Boolean
`history_verified` and `source_order_verified` assertions are only useful under
that boundary. The classifier may propose a decision but must never manufacture
those assertions or possess the intake credential. Step 4 must verify the actual
ServiceDesk 15.1 Build 15100 APIs before producing production events.

Catalogs are server-owned and immutable by version; intake cannot supply catalog
contents. Unknown versions, identities, ordering or process association stop
automatic actions. The built-in catalog contains only invented `example.invalid`
identities. A production catalog cannot be used with the synthetic execution
switch. No production catalog or administrator credentials were loaded here.

## Policy and waiting

`app/policies/tickets.py` applies the confirmed rules independently of inference:

- Exclude verified onboarding/offboarding/transfer processes and their children
  before evaluating either job. Unknown association requires local review.
- Ordinary correction applies only to current Helpdesk tickets with no technician.
  Specialized-group requests and human assignments are preserved. The proposed
  write surface contains only the destination support group.
- Dedicated Mirza templates require complete verified approval for the exact job
  digest. Other-template intake must start in Helpdesk; enrollment persists after
  the DWE handoff. Its original DWE in-charge identity is retained.
- Fallback authorization requires that original person, DWE, the exact terms and
  a verified Hold/Open transition after enrollment/current approval cycle.
- Missing terms select the current technician or original DWE in-charge. A
  clarification cycle records reason, fields, contact, terms, baseline revision
  and sequence. Resume needs that contact's later note followed by their Open
  transition, correlated to the cycle and supplied terms. Clarification does not
  replace approval. Native execution also requires normalized Open status;
  live status mapping remains to be verified.
- An expired key still triggers the additional-key question. Confirmed additional
  creation and ticket-specific mappings survive a later approval wait only for
  the same terms. An unnecessary-key answer records a completion decision with
  no key action; later completion notification/resolution work is still required.
- Unknown models, key ownership, team kind, existing grants and unmapped
  departments cannot yield executable actions. Manager-Tool access remains manual.

Ticket status and workflow state are separate. Waiting currently persists the
intent to put the ticket On Hold; this foundation does not perform that status
change or send a DM. Production handoff and clarification activities must confirm
the status write and original contact before accepting their response evidence.

## Execution and recovery

`TicketWorkflow` is the sole serial execution owner for a stable tenant/ticket ID.
PostgreSQL stores an inbox, immutable catalogs, projections, action records,
reminder intents and audit receipts. Intake commits before returning 202. A
transactional outbox uses Temporal Signal-With-Start and acknowledges delivery
only after the server accepts it. A duplicate event ID with the same payload
returns the same owner; different data under that ID returns 409. Lower source
sequences do not regress state; conflicting equal sequences require review.

An action ID is a hash of workflow identity and canonical operation terms. The
workflow drains pending input before executing an action on its designated
dispatch/Mirza queue. Storage locks and fresh sequence/pending-input checks guard
both intent and the synthetic side effect. New revisions supersede old plans.
Replayed transition commits return the original canonical receipt instead of
re-evaluating policy against a later projection.

The synthetic connector writes only `fixture_effects` in this application's local
database. Its fault injection commits a receipt, loses the response and lets the
next activity attempt reconcile that receipt. An uncertain/in-flight operation
without a provable receipt stops for manual recovery; it never generates another
effect blindly. A late verified receipt cannot mark a newer request completed.
This does not establish a production recovery strategy: each future connector
needs downstream correlation/read-back, fresh authoritative preconditions and
its own reconciliation before enabling writes.

Activity attempts have 15-second execution and 120-second overall batch timeouts,
with at most five attempts. Infrastructure failures in storage preserve the actor
and retry after a durable 30-second delay. Unrecoverable contract conflicts require
operator investigation. Failed action batches go to manual review. Human waits
have no deadline. Cancellation is authenticated, revision-checked, idempotent,
audited with the server-owned operator identity, and latched against later input.
It cancels future work; it does not undo a committed effect. General repair and
resumption belong to Step 9.

Idle ticket actors remain available for meaningful later revisions. They continue
as new after 100 transitions or Temporal's history-size suggestion, carrying the
tracking state while keeping the workflow ID stable. The initial worker queue
owns coordination; privileged action activities use the relevant role queue.
Pausing that initial coordinator suspends the whole ticket actor, including a
later domain change. Review queue handoff if production needs independent
coordination pauses for tickets that change between dispatch and Mirza.

## Reminders and audit

Temporal persists a timer for the next 10:00 in `Asia/Tehran`, including weekends.
Recovery skips previous dates. The reservation activity also checks the current
local date so an already queued activity delayed across midnight cannot create a
missed reminder. PostgreSQL deduplicates by workflow, recipient and local date.
Each reservation is bound to the active waiting cycle; new input, cancellation,
terminal/excluded state and changed cycles suppress or supersede pending intents.
Mattermost delivery/reconciliation is not implemented yet.

The tenant/ticket's original correlation UUID follows inbox, action and audit
records. Audits include policy/model/prompt versions, evidence references, exact
approval/clarification evidence, decisions and sanitized verification results.
HTTP logs and activity errors omit request bodies, SQL parameters and credentials.

## Authenticated local API

| Endpoint | Principal | Behavior |
|---|---|---|
| `POST /v1/events` | intake | Validate a normalized event, persist, return 202 |
| `GET /v1/workflows/{workflow_id}` | operator | Read current projection/action status |
| `POST /v1/workflows/{workflow_id}/cancel` | operator | `request_id` plus `expected_sequence` |

Use separate `AGENTIC_INTAKE_TOKEN` and `AGENTIC_OPERATOR_TOKEN` Bearer credentials
of at least 32 characters. Without a credential setting its endpoints return 503;
the other principal's token returns 401. There is no approve/grant endpoint.
Cancellation uses configured `AGENTIC_OPERATOR_PRINCIPAL`; a body cannot impersonate
another actor. Request-validation errors omit input, and event bodies are capped
at 64 KiB. The local generator adds missing tokens privately without replacing
existing database/API credentials. Production principal mapping, TLS, secret
distribution and restricted network access remain deployment gates.

## Local verification

```bash
python3 scripts/init_local_env.py
COMPOSE_PARALLEL_LIMIT=1 docker compose build api
COMPOSE_PARALLEL_LIMIT=1 docker compose -f compose.yaml -f compose.verify.yaml up -d --wait --wait-timeout 180
bash scripts/check_tickets.sh
docker compose stop
```

The explicit override enables only the synthetic connector, automatic fixture
execution and response-loss injection. Resource caps are unchanged. Base Compose
and `.env` remain in observation with fixture execution off. Omit the override
for normal local use; recreate containers when switching settings. Verification
records persist locally for inspection. No real tickets, teams, credentials or
Mattermost messages are used.

Verified locally: 43 unit checks, Ruff, both Compose configurations and Alembic
schema consistency passed. The integration runner passed authenticated role
separation, duplicate/conflicting event IDs, both worker restarts and history
replays, stale approvals/revisions, clarification author/note/Open correlation,
cancellation, weekend reminder reservation/deduplication, delayed-date suppression,
response-loss reconciliation with one effect, pending-new-input protection, and
manual recovery for an uncertain result without a receipt. A 102-revision scenario
continued as new with state intact and replayed successfully. The existing Step 2
runtime restart/audit probes also passed.

This is not a substitute for historical Persian/English classification evaluation
or installed API verification. Containers were kept under the existing CPU/RAM
caps; sampled stack RAM was about 475–545 MiB and no container reported an OOM.
Containers were stopped after checks; the local database volume was retained.

Implementation references: Temporal's [message passing and Signal-With-Start](https://docs.temporal.io/develop/python/workflows/message-passing),
[Python error handling](https://docs.temporal.io/develop/python/best-practices/error-handling),
and SQLAlchemy's [PostgreSQL conflict handling](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#insert-on-conflict-upsert).
