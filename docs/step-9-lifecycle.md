# Step 9: local entitlement lifecycle and operator recovery

Status (2026-10-14): the local milestone passes 563 offline tests and eight native
PostgreSQL/Temporal restart/replay workflows. Lint, dependency, Compose, readiness
and migration checks pass. The steady snapshot used approximately 483 MiB under
the combined 0.70 CPU cap. Project containers are stopped and volumes preserved.
See [verification evidence](step-9-recovery-verification.json).

This implementation remains confined to generated synthetic worlds and dedicated
application tables. There is no native Mirza, Mattermost or ServiceDesk writer.
Production activation requires the installed contracts listed in the Step 8
guide. Only `local-qwen3.8` is permitted for inference; lifecycle activities make
no inference calls.

## Ownership and expiry

Each ownership scope records the value before the first request, its last
verified value and a cooperating-writer revision. Separate approved request
claims record requested targets and explicit expiry. Permanent claims have no
invented expiry; budget requests gain no expiry field or revocation operation.

Expiry recomputes membership/model unions and maximum reasoning ceilings over
the original grants and remaining independent claims. It restores original
legacy reasoning metadata when the last temporary change ends. Unrelated models,
memberships, metadata, spend/reset fields and larger budgets remain intact.
Reasoning scopes cover the reasoning fields of one row because wildcard/legacy
grants overlap; model and membership scopes cover individual entries.

A created key retains its owner/Tool team and becomes expired at its approved
deadline. It is never deleted, moved, regenerated or given a key model list.
Supporting owner/Tool membership and newly created Tool teams are retained:
another key or administrator may depend on them. Cleanup concerns only expiry
explicitly approved in the eight jobs. There is no general offboarding,
department synchronization or new request-driven revocation job.

Changed values or writer revisions stop cleanup with an ownership conflict.
Expiry never adopts an external change as its baseline or forces a snapshot back.
Equal-value independent writes need provenance too: cooperating fixture writers
must increment `owned_scope_versions`. A row lock/fingerprint cannot detect an
uncoordinated administrator writing the same value. This simulator contract does
not establish a supported native Mirza concurrency/ownership contract.

Non-Tool membership cannot silently outlive a temporary team-model grant on which
it depends; insufficient supporting lifetime requires clarification. A key
reasoning request records its own key grant when inherited team reasoning is
temporary, without extending that team's grant on behalf of the key.

## Workflow and verified outcomes

`MirzaFixtureLifecycleWorkflow` is a new workflow type; the original Step 8 type
remains unchanged for replay. Indexed fulfillment is followed by a Temporal timer
for the next owned expiry. An activity conditionally reconciles overdue grants
and records minimal evidence. Expiry remains scheduled for completed or cancelled
fulfillment. The activity rejects finite grants from the original or an unknown
workflow type; temporary grants must use the new timer-owning workflow.

Reconciliation checks pending request terms/authority, positive downstream
receipts, active owned grants and final synthetic Resolved status. Notifications
summarize verified scope, models, reasoning/budget and explicit expiry. Raw key
delivery remains inside the private owner cipher boundary. Resolution follows
required DMs and retries its own phase without repeating work or messages.

## Authenticated operator endpoints

All endpoints require the existing operator bearer credential. Intake credentials
cannot authorize them. Base mode permits projections only. Mutation commands also
require the explicit local fixture-provisioning configuration and an unpaused
Mirza worker. API does not receive the vault key or perform provisioning itself.

| Endpoint | Behavior |
|---|---|
| `GET /v1/operations/{operation_id}` | State/revision, terms digest, approval flags, owned scopes/targets/expiry, phase receipts and audit references. |
| `GET /v1/operations/metrics` | Aggregate counters, age/latency/spend information and recovery/expiry alert flags. |
| `POST /v1/operations/{operation_id}/cancel` | Stop further fulfillment; retain grants, abandoned encrypted material and approved expiry. |
| `POST /v1/operations/{operation_id}/resume` | Persist an idempotent command and schedule validation before resumption. |
| `POST /v1/operations/{operation_id}/reconcile` | Schedule verification/expiry without provisioning a pending job. |
| `POST /v1/operations/{operation_id}/retain` | Apply an eligible local terminal retention tombstone. |

Commands carry `request_id` and `expected_revision`. Reusing a resume request after
a Temporal outage returns the same durable command. Revision conflicts require a
fresh projection. Resume/cancel commands record the configured operator identity.
Recovery revalidates original terms/reviewers, lifecycle exclusion, directory and
delivery bindings and grant read-back. Operator access cannot approve the agent's
work, clear uncertain claims, bypass terms confirmation, recover missing raw keys
or resume a terminal cancelled operation.

Cancellation is conservative compensation: it stops future effects without
undoing verified grants, deleting supporting resources, revoking delivered keys
or closing tickets. Known partial work remains visible; only its approved expiry
can clean it up. An uncertain create/post without positive evidence stays blocked.
Fixing availability or bot identity can permit recovery with the original secret.

Views include the latest reconciliation result independently of fulfillment state:
a later status or grant change remains visible after successful fulfillment.
Failed verification prevents private evidence from being purged. Approved expiry
remains scheduled after a status change. Views contain no ticket descriptions,
employee emails, keys, ciphertexts, private
DM bodies or approval notes. Existing detailed review endpoints are separately
authenticated. Alert flags are returned to operators; no external alert DM is sent.

## Metrics, retention and storage

Metrics distinguish synthetic fulfillment from native observation previews.
Verified group-correction actions, protected no-ops and review states are separate.
Approval age measures stored previews, which may be historical. Reserved model
USD is conservative reservation accounting, not verified billing. Latency uses
up to 100 recent completed records and is explicitly a sample.

The fixture retention prototype removes terminal ticket text, event/approval
payloads, encrypted key material and encrypted posts after 180 days from verified
completion. Opaque receipts, ownership claims and terms digests survive so expiry
and deduplication remain possible. Pending/uncertain/abandoned key recovery cannot
be purged. This is local fixture policy, not approved production retention.
Native ticket/model-trace/audit periods, backup expiry, database roles, vault
custody and Temporal history retention require operator decisions before activation.

Migration `0006_fixture_lifecycle` adds four isolated ownership/recovery/audit
tables. Upgrade before workers. Downgrade destroys ownership evidence and must
never clean up outstanding temporary grants. It preserves Step 8 ciphertext and
all business/review tables. The verifier neither downgrades nor deletes volumes.

## Verification

```bash
export COMPOSE_FILE=compose.yaml:compose.resource-check.yaml
export COMPOSE_PARALLEL_LIMIT=1
docker compose up -d --wait --wait-timeout 180 postgres temporal
docker compose run --rm --no-deps migrate
bash scripts/check_lifecycle.sh
```

The native verifier covers four expiry workflows, overlapping permanent
membership, abandoned key delivery and the unchanged Step 8 workflow. It restarts
this project's PostgreSQL/Temporal, resumes with overdue timers, checks preserved
access and owner-only delivery of the original key, verifies the old-workflow expiry
guard, and replays eight histories.
It checks API/worker readiness and schema parity. Cleanup stops this project's
containers and preserves volumes; failures retain private recovery state.

Offline checks cover legacy baselines, overlap, equal-value writer revisions,
cancellation, rejected resumption, authentication, retention and secret isolation.
Production lifecycle acceptance remains pending the native adapter, installed
expiry/reconciliation/resolution guarantees, retention policy and authorized pilot.
