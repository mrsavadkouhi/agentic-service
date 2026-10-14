# Step 7: Mirza policy and approval review

Status (2026-10-14): local policy, durable review preparation and native recovery
checks pass. Live approval authority, ticket changes, provisioning and delivery
remain unverified/disabled; this is the Step 7 review milestone, not activation.

The operator-only review path implements local policy previews for the eight
approved jobs. Provisioning, ticket changes and Mattermost delivery remain disabled.
This path does not activate Step 6's unverified group writer or introduce a Mirza
administration credential. Existing PydanticAI extraction supplies proposals;
approval checks and change calculation are deterministic, with no new model call.

## Operator workflow

After a completed, current extraction observation for a native ticket:

```http
POST /v1/mirza-reviews/{ticket_id}
Authorization: Bearer <operator token>
Content-Type: application/json

{"observation_id": "<completed extraction receipt digest>"}
```

`MirzaPolicyReviewWorkflow` and `prepare_mirza_policy_review` run on the Mirza
queue. Temporal receives only ticket/observation references and an opaque result
receipt. The activity validates native receipt identity, extraction stage,
classification/operation agreement, policy/model/configuration versions and fresh
ticket/note/process evidence. Synthetic, unrelated, stale or classification-only
receipts never trigger native reads. No observation is adopted as approval evidence.

The activity reads fresh directory, template/group, approval and inventory context.
It rechecks inventory permission state, support groups and the ticket/process/notes
after planning. Changing usage alone does not invalidate a permission snapshot.
An incomplete or changed snapshot drops the package and any new contact pin.
Lifecycle requests are excluded before collecting an entitlement package, including
requests using dedicated Mirza templates. Assigned fallback requests remain manual;
an ordinary-template ticket already outside Helpdesk cannot enroll through this path.

`GET /v1/mirza-reviews/{ticket_id}` returns the last ten local previews under the
operator credential. Every result and every intent has `authorized: false` and
`handoff_verified: false`. Even a synthetic policy example with state `ready` is
only a preview; it is not accepted by executable intake or the action repository.
`/runtime` reports the workflow and continues to expose no external write capabilities.

## Exact scopes and minimal changes

| Job | Previewed target and change |
|---|---|
| Create API key | Verified owner email, exactly one existing approved Tool team or a ticket-approved new Tool team with explicit initial terms; existing Tool grants only. Supporting owner/Tool membership and new-team creation remain confined to this key request. |
| Increase API-key reasoning | That owned key and its existing Tool team's models; preserve higher key/team ceilings. Personal/UI reasoning is excluded. |
| Increase team reasoning | Explicit Mirza team ID/kind and existing models; preserve higher team ceilings. |
| Grant team model access | Explicit team ID/kind; union the approved models with existing models. |
| Add person to non-Tool team | Verified email and explicitly selected existing non-Tool team granting the requested model; preserve other memberships and show the resulting UI model union. Never change that team's grants. |
| Increase personal budget | Personal/UI row only, with before/after limit and existing reset duration. |
| Increase API-key budget | Owned key row only; preserve its owner, Tool team, spend and reset. |
| Increase team budget | Explicit team ID/kind only; preserve spend and reset. |

Packages retain the exact typed job, scope, owner/target identity, memberships,
models, reasoning, absolute budget target, duration and explicitly supplied expiry.
They do not invent missing defaults or requested identities. Budgets already at
or above the desired amount produce no change; an intermediate changed baseline
requires clarification rather than adding the requested delta again.
Missing/ambiguous Mirza owners, mismatched keys/teams, unavailable model grants,
unknown budgets and manual Manager-Tool scope cannot produce a grant package.

Direct key-model grants, key moves and non-Tool key memberships are outside the
job union and produce no operation. ICT group IDs never select a Mirza team.
Only a team-model request changes team model grants. Key reasoning/budget packages
retain the existing Tool-team model grants, and key creation never proposes a key ACL.

## Approval and clarification state

The policy reuses the existing normalized ticket evaluator for required native
approval stages, fallback enrollment/hold/Open proof, current technician versus
original DWE clarification contact, ticket-scoped mapping and duplicate-key decisions.
Pending stages, another actor, an initial Open state, Mattermost replies or an LLM
approval claim do not fulfill these gates. Assigned same-group approved jobs remain
eligible in normalized examples; no group-changing exception is restored.

For native approvals, a persisted `ApprovalTermsBaseline` must identify the original
reviewers and approval/configuration evidence. Current ticket content and current
approved rows cannot create that baseline. Older approvals without a terms snapshot
and changed recipient/access/reasoning/budget terms require the original reviewers'
confirmation. The review request binds exact terms, ticket, original reviewers,
configuration and cycle, and is persisted before any later delivery. Notes must use:

```text
Approved Mirza terms: <persisted review reference>
```

The Step 4 parser reads matching note summaries privately; matching visible text
does not prove order. The reconfirmation policy additionally requires verified
original identities, configuration and hold/note/Open source sequence. It retains
native required-stage/history checks after confirmation and never substitutes a
technician for an original approver. A new source event is needed to resume a
recorded decision; duplicate source revisions are not silently reevaluated.

The first native approval observation is stored separately from a verified terms
baseline. It preserves observed stage/configuration information for review and
cannot authorize execution. The installed read adapter still cannot prove sequence,
approved terms or hold/note/Open ordering; native review therefore remains blocked.
It neither manufactures a sequence from timestamps nor resets approvals.

DWE's dynamic in-charge identity is pinned when first needed for a valid review,
with its group-source digest and read time. Later group-field changes do not replace
that contact on the request. This is a review identity pin, not evidence that a real
DWE handoff or notification occurred. Clarification prefers the current technician;
if none, it uses the pinned DWE contact. Contacts require an enabled, unexpired,
uniquely resolved directory email. Incomplete identity prevents a DM draft.

Complete owner/Tool key metadata drives the duplicate check, including expired
keys. A verified note/Open decision that another key is unnecessary records the
explanation reference, clears all proposed key changes and emits only an unauthorized
completion intent for the owner and technician/original DWE contact. All existing
keys remain intact. Open alone cannot decline or authorize another key.

Hold, handoff, clarification, approval and completion intents are local descriptions.
They do not post notes, alter tickets, generate keys, send DMs or mark Resolved.
Daily reminder drafts combine pending actions for one ticket/recipient/calendar day,
become due at 10:00 Tehran time, include weekends, and stop when the gate ends.
The existing reminder clock skips missed dates. Delivery must revalidate the gate,
lifecycle context and recipient and persist send deduplication in Step 8.

## Persistence and rollout

Migration `0004_mirza_reviews` adds only `mirza_review_heads` and
`mirza_policy_reviews`. The head serializes preview revisions and preserves first
approval observations, original approval baselines and DWE identity pins. Unique
review IDs make activity retries return their original preview without repeating
reads or advancing state. PostgreSQL row locks/revision checks prevent lost local
updates; they do not supply ServiceDesk concurrency or history guarantees.

The preview tables do not write `ticket_inbox`, action/effect tables or inference
spend reservations. Downgrading to `0003_observations` removes only the two new
tables, preserving business and observation data. Rebuild the image and upgrade
the local schema before starting the API/workers. No production migration or
Mirza change was performed during this step.

Verification uses the existing reduced resource profile:

```bash
export COMPOSE_FILE=compose.yaml:compose.resource-check.yaml
export COMPOSE_PARALLEL_LIMIT=1
docker compose up -d --wait --wait-timeout 180 postgres temporal
docker compose run --rm --no-deps migrate
bash scripts/check_observations.sh
```

Activation still requires installed authoritative approval/history evidence,
supported protected ticket updates/handoffs, reviewed production classification
quality and the Step 8 provisioning/delivery boundaries. An operator token, a
preview receipt, a source hash or a mode change cannot bypass those requirements.

## Verification results

Offline cases cover all eight scopes, unknown/key-model operations, higher
reasoning ceilings, unchanged grants/memberships, absolute budget retry targets,
changed baselines, expired-key clarification/refusal, changed approval terms,
missing/wrong original reviewers, native required-stage gates, operator cancellation,
DWE contact changes, daily reminder drafts, receipt provenance, storage retries,
API authentication and migration downgrade isolation.
The full suite passed 500 cases; Ruff, Compose configuration and schema checks
passed. The closed change contract was also checked against direct key-model
grant injection.

The extended native verifier restarted PostgreSQL and Temporal, replayed the
new Mirza-queue workflow and existing observation/preflight workflows, inspected
history bytes for source-text leakage, and checked local preview concurrency and
lost-response retry behavior. Synthetic provenance was rejected without native
reads. Business inbox/action/effect counts were unchanged; all model requests were
local function fixtures, with zero external calls. Migration exited successfully,
API/workers reached readiness, and Alembic found no new upgrade operations.
See [native verification results](step-7-recovery-verification.json).

Verification retained all base RAM/PID limits and used the 0.70 CPU profile. The
steady five-service snapshot was approximately 579 MiB. Project containers were
stopped afterward; persistent volumes and unrelated services were preserved.
