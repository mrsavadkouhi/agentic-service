# Step 6: support-group correction contract review

Status (2026-10-14): read-only preflight implemented; external writes remain disabled.
Step 5 now has native recovery evidence and bounded real local-Qwen evaluation.
Production observation review and installed conditional-update guarantees remain
activation prerequisites. Observation receipts still cannot enter executable intake.

The operator reiterated human-assignment preservation on 2026-10-14, superseding
the earlier Mirza DWE handoff clearing exception. All group moves require an
unassigned ticket; unclear assignment provenance is treated as human. Assigned
fallback Mirza requests need manual handling. Approved Mirza work that preserves
the current group and technician remains eligible. Policy `step-1-confirmed-v2`
invalidates earlier policy receipts; no assignment-override setting exists.
`TicketWorkflow` uses per-event Temporal patch markers to reconstruct recorded v1
commands during replay while applying the revised policy to new events. The v1
evaluator is replay-only and cannot authorize a live request. Offline checks cover
this fence; native historical replay remains part of the Docker verification gate.

## Implemented review path

Operator-only `POST /v1/group-corrections/{ticket_id}/preflight` accepts only:

```json
{"observation_id": "<completed_classification_receipt_digest>"}
```

`GroupCorrectionPreflightWorkflow` runs on the dispatch queue. Its activity requires
a completed ordinary group-correction observation for the same native ticket and
current policy/model configuration. It rejects unrelated, synthetic, missing and
non-classification receipts. It collects fresh source context and checks the
verified destination, current Helpdesk group, exact null technician, terminal
status, lifecycle coverage, ticket/note evidence and final read stability.
Missing/malformed technician metadata is an incomplete read, never a null assignment.

Changed/assigned/excluded tickets produce no proposed payload. Otherwise the
result remains `blocked` with `native_atomic_group_update_unverified`, retaining
only a group-only review proposal. Its payload builder allows only verified native
Network/DWE/VOIP IDs. No template, technician, status, category, note or reply is
present. Every result has `authorized: false`.

The activity makes no inference call or spend reservation. Its receipt/proposal is
stored as a `group_preflight` observation, without executable intake/actions or a
schema migration. Workflow history contains only identifiers and an opaque
receipt. `GET /v1/observations/{ticket_id}` returns the local result for review.
Runtime reporting explicitly says the atomic write contract is unverified. No
setting or operator request activates a writer; none exists in the connector factory.

Offline checks cover idempotency, provenance isolation, policy/evidence changes,
human assignments, group moves, lifecycle exclusions, final-read conflicts,
payload field isolation and unchanged business action/spend tables. The workflow
passes Temporal sandbox preparation. The extended native restart/replay verifier
now checks its synthetic-provenance rejection too; that new native check is pending
because the Docker daemon is inactive on 2026-10-14. The earlier Step 5 native
recovery run passed. Docker's service was not started or reconfigured.
The current full suite passes 449 cases; Ruff and both Compose configurations pass.

## Candidate API contract

ManageEngine's [on-premises request API](https://www.manageengine.com/products/service-desk/sdpop-v3-api/requests/request.html#edit-request)
documents `PUT /api/v3/requests/{request_id}`, form-encoded `input_data`, and a
support-group field. A future group-only payload would contain:

```json
{"request": {"group": {"id": "<verified_destination_id>"}}}
```

This is a candidate payload, not a tested installed write contract. No PUT was
issued. Do not send technician, template, category, status, resolution, note or
reply fields. The only destinations are the verified Network, DWE and VOIP group
IDs; ordinary requests staying in Helpdesk require no change.

The reviewed public edit documentation does not describe `If-Match`, ETags,
revision predicates or an atomic technician-null condition. That observation
does not prove the installed build lacks them. `last_updated_time` appears in
responses, but no conditional-update semantics were verified for that value.
Client hashes and two matching GETs detect observed changes; they do not lock a
request while a technician assigns it.

## Required installed guarantee

The operator confirms changing a group clears the technician. Therefore a human
assignment made after the last GET must make the group update fail atomically.
A second GET or the agent's PostgreSQL lock cannot protect against ServiceDesk UI,
n8n or another integration assigning the ticket in that interval. Writing the
technician back afterward would violate the confirmed policy.

Before implementing an active connector, obtain and verify a supported installed
mechanism that checks the expected revision, current Helpdesk group and null
technician in the same transaction as the group-only update. Verify stale updates
fail without side effects and successful updates retain a null technician without
automatic assignment. Resolve incomplete/changed lifecycle context before writing.

Concrete vendor/administrator question:

> On ServiceDesk Plus 15.1 Build 15100, which supported API or server-side operation
> atomically changes only a request's support group if its expected revision still
> matches, its current group is Helpdesk, and its technician is null? What is the
> documented conflict response, and are automatic technician assignments suppressed?

Until that contract is established, retain proposals and local review. Do not
invent an `If-Match` header, issue a production PUT to test whether it is ignored,
add a database writer, or treat a conditional client read as an atomic update.

Once verified, implement the connector in a Temporal activity with durable action
claims, conflict handling, read-back verification and local audit. If a response is
lost, reconcile observed state before retrying; never overwrite a new human
assignment or use an observation receipt as execution authority.
