# Step 8: provisioning and delivery simulation

Status (2026-10-14): the local fulfillment milestone is implemented and verified.
All eight jobs and ticket-scoped new Tool-team creation complete in the persistent,
network-free simulator. No native Mirza administrator, Mattermost sender or
ServiceDesk writer is registered. Live fulfillment and production activation remain
incomplete; existing approval/history and concurrent-update gates still apply.

Step 9 now supplies conditional fixture ownership/expiry and a separate timer-owning
workflow. Its guide supersedes this milestone's temporary non-key expiry blocker;
native expiry remains disabled. See [lifecycle and recovery](step-9-lifecycle.md).

## Boundaries

PydanticAI supplies the Step 5 typed proposal; the Step 7 policy calculates scope
and approval requirements. Privileged fulfillment runs in a separate Temporal
activity on the Mirza queue, with opaque operation references and indexed commands.
It makes no model call. Only `local-qwen3.8` remains permitted for agent inference.

`MirzaFixtureFulfillmentWorkflow` calls `advance_fixture_mirza_fulfillment`, which
requires an explicit local fixture configuration, automatic Mirza mode, the Mirza
worker role, an unpaused worker, and a private vault key file. Ordinary mode changes,
read/master credentials and preview receipts cannot activate it. The dispatch
worker never constructs the private cipher. Base Compose does not forward enabling
fixture-provisioning settings or mount a vault key.

Seeding is available only to the local verifier/internal fixture helper, not an API
endpoint. It accepts synthetic catalogs, generated `fulfillment-fixture-*` tenants,
synthetic events and `.invalid` directory identities. Native events and real employee
emails are rejected before storage. Step 7 previews remain unauthorized and cannot
be converted into execution authority. Existing `TicketWorkflow` histories and its
earlier synthetic connector are unchanged.

The simulator writes dedicated application fixture tables. It never connects to a
Mirza database, invokes an admin HTTP endpoint, sends a real DM or updates a real
ticket. The fixture world provides a server-side transaction/row-lock contract for
all simulated writers. An agent-local lock cannot establish the same guarantee for
actual LiteLLM/Mirza administrators; a native adapter needs a verified equivalent.

## Narrow administration operations

| Job | Mutation and verification |
|---|---|
| Create API key | Resolve the verified owner and one Tool team; add only supporting owner/Tool membership if needed. Create no key model/ACL field. Bind owner, team, budget, reset duration, explicit expiry and operation correlation. |
| Increase API-key reasoning | Update only requested model ceilings in the owned key's metadata. Evaluate existing key/Tool ceilings and avoid redundant or lower grants. Preserve owner, team, model fields and unrelated metadata. |
| Increase team reasoning | Update only the approved team's requested model ceilings; preserve higher ceilings and other metadata. |
| Grant team model access | Union approved models into the explicitly selected team; preserve concurrent additions. |
| Add person to non-Tool team | Add membership while retaining other memberships and the personal model field. The team must already grant the requested model; the operation never widens its model grants. |
| Increase personal budget | Set an increasing absolute target on the personal/UI row only. |
| Increase API-key budget | Set an increasing absolute target on that owned key only. |
| Increase team budget | Set an increasing absolute target on the explicitly selected team only. |

Budget mutations preserve spend, credits, reset schedule, duration and unrelated
metadata. Already larger limits remain larger. A changed intermediate baseline
requires clarification; retry does not add the delta again. Reasoning merges use
`reasoning_models`, fold the legacy broad `reasoning_levels` into `*`, preserve
unrelated grants and apply the maximum ceiling. These semantics follow the inspected
`jam-ai-service/scripts/reasoning_access.py`; that script was read, never executed.

Key reasoning reads the key and its Tool team, excluding personal/UI reasoning.
The simulator's Tool-key effective budget checks use key/team limits and do not
spend or increase the owner's personal budget to make a test pass. Native proxy
scope, key ACL behavior and multi-node cache propagation still require installed
verification; these simulations do not establish those production contracts.

Creation of an absent Tool team is a supporting step of `create_api_key`, requiring
the ticket-approved mapping and explicit initial models, budget and duration. Its
correlated resource is verified and the mapping is not written into global
department policy. Alias conflicts cannot silently choose another team. Manager-Tool
scope remains manual. Direct key-model grants, key moves, non-Tool key membership,
personal model-list writes and personal reasoning updates have no mutation branch.

Before every simulated side effect, the activity revalidates current ticket terms,
native/fallback approval, source order, original reviewers, lifecycle association,
directory eligibility, owner/team bindings and delivery identities. A service
principal cannot approve or clarify its own operation. Temporary non-key grants
are blocked with `managed_expiry_unavailable` until Step 9 supplies safe ownership
and expiry handling. Expired selected keys and elapsed requested key expiry also
block fulfillment; the agent never silently extends them.

## Claims, reconciliation and secrets

Each phase has a durable claim before its downstream effect. A stable command
index is carried by Temporal and the result is stored with the effect. A lost
response returns that same command receipt, rather than advancing or repeating
the operation. Active claims are busy; an expired/uncertain claim without positive
downstream evidence stops for manual recovery. A matching free-text operation tag
alone cannot hide an existing key from the duplicate check.

Creation receipts correlate this operation's resource and typed terms. Only those
positively proven resources are excluded from the pre-creation duplicate/absent-team
checks during recovery. Existing same-owner/Tool keys, including expired keys, still
require the agreed clarification. Missing/ambiguous creation evidence, missing key
material or a changed owner/team never triggers regeneration, disclosure of an
existing secret, key reassignment or compensating permission writes.

New key material and private simulated posts are encrypted with the pinned PyCA
[Fernet implementation](https://cryptography.io/en/stable/fernet/). Encrypted envelopes
bind their payload to the secret/post reference. Raw key material is resolved only
inside the private owner-DM phase and checked against its owner, team and fixture
key identity. It is absent from workflow arguments/results, public projections,
ordinary JSON rows and staff summaries. The private key file requires restrictive
permissions; the verifier creates it with mode 0600 and keeps it across restarts.

These are fixture credentials, not production keys. The simulator commits its
world receipt, encrypted vault value and private post in one database transaction.
That provides a useful recovery test but does not prove atomicity across a real
Mirza API and an external vault. The native boundary must positively reconcile its
own creation/delivery outcome, or stop when the original secret cannot be recovered.
Production vault isolation, retention, rotation and backup remain rollout work.

## Delivery and resolution

The owner/target person's verified Mattermost identity receives the completion DM;
for a new key, the body includes the raw key inside that private phase. Delegated
key requests use the named owner's DM, never the requester's as a fallback. Team
jobs notify the requester. Inactive, ambiguous or redirected accounts and an
unverified `servicedesk_agent` bot block delivery.

Staff completion uses the current technician, or the originally pinned DWE in-charge
person when null, with the confirmed template:

```text
Mirza request #{ticket_id} completed: {ticket_link}. Request: {ticket_description}. Work done: {completion_summary}.
```

Descriptions are sanitized before fixture persistence/delivery. Staff messages
exclude raw keys. Delivery IDs and downstream receipts prevent duplicate posts
after lost responses. Notification failure does not create another key or repeat
a grant. If the assigned technician changes after a staff DM, the simulator
notifies the new current contact before resolution without resending the owner DM.
An in-charge field change does not replace this request's original person.

Stored grants and effective limits are checked before messages and resolution.
The final simulated status is Resolved, with group, technician and template
preserved. Lifecycle/context changes or missing effective grants stop subsequent
effects. A fulfilled entitlement may therefore remain in manual recovery without
notification/resolution; the agent does not silently broaden or roll it back.

## Verification and storage

Migration `0005_provisioning_fixtures` adds five isolated fixture tables for worlds,
fulfillment records, claims, encrypted secrets and encrypted messages. It leaves
business inbox/actions and Step 7 review tables intact. Downgrade to
`0004_mirza_reviews` destroys these fixture records/ciphertexts and must be intentional;
no downgrade or volume deletion was used in native verification.

After building the current image, repeat the capped local verification with:

```bash
export COMPOSE_FILE=compose.yaml:compose.resource-check.yaml
export COMPOSE_PARALLEL_LIMIT=1
docker compose up -d --wait --wait-timeout 180 postgres temporal
docker compose run --rm --no-deps migrate
bash scripts/check_provisioning.sh
```

The script uses one private worker and function/fixture data, runs all eight jobs
plus new Tool-team creation, loses each mutation response, pauses before delivery,
then restarts PostgreSQL/Temporal. It resumes with the same private vault key,
verifies owner-only secret delivery, checks histories for keys/email leakage and
replays all nine histories. A native PostgreSQL race verifies concurrent model
additions survive with unrelated metadata intact. API/workers reach readiness
after migration and Alembic checks schema parity. Cleanup stops only this project
and preserves volumes; failed checks retain their private state for investigation.

The full offline suite passes 536 cases. Lint, Compose, migration and dependency
checks pass. The installed native recovery run passed with zero external business
or model calls and no business inbox/actions created. See
[verification evidence](step-8-recovery-verification.json).

The steady API/worker/PostgreSQL/Temporal snapshot used approximately 560 MiB
under the resource override's combined 0.70 CPU limit. All project containers
are stopped after verification; persistent volumes remain intact.

## Remaining production gates

Do not activate a native adapter until installed evidence establishes approved
terms and hold/note/Open ordering, protected ServiceDesk handoff/status updates,
coordinated Mirza permission updates, creation correlation/recovery, Mattermost
identity and uncertain-post reconciliation, effective proxy/cache behavior and
least-privilege secret custody. Then validate an explicitly approved pilot through
the real path. A local fixture pass, observation receipt, HTTP 200, matching tag or
mode change cannot substitute for those guarantees. No live Mirza change or DM
was performed during this step.
