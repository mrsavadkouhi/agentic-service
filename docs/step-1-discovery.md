# Step 1 — Integration discovery

Date: 2026-10-06 (Asia/Tehran).

Status: repository discovery complete; deployment capabilities and business-policy
details remain pending. Operator confirmations below settle the product/build,
environment, assignment scope, and Mirza approval gate. Live LiteLLM team
discovery on `mirza-ha1` used read-only GET calls on 2026-10-06; no production
ServiceDesk systems were modified. The explicitly requested Cloud-team merge
was subsequently applied and verified in LiteLLM; see its report below. ServiceDesk
live contracts remain unverified. Workflow
exports show configured behavior, not proof that those workflows are running.

## Evidence and confidence

- **Observed:** present in local code or workflow exports.
- **Operator-confirmed:** supplied by the user; does not imply a live API check.
- **Documented:** described by vendor documentation; installed-build verification
  is still required.
- **Proposed:** a design or policy for review, not an approved entitlement.
- **Unknown:** cannot be established from the available repositories.

Source paths below are relative to `agentic-service`; they are read-only references.
No credentials, production addresses, personnel rosters, or real tickets are
copied into these artifacts.

## Helpdesk integration

The operator confirmed **ServiceDesk Plus 15.1 Build 15100**. The exports use
an on-premises-style `/api/v3` API; API v3 is not the product version. Edition,
license-dependent capabilities, authentication permissions, and live response
contracts still require inspection. The operator confirmed there is **no staging
environment**; validation must use local simulations and production read-only
observation before scoped live activation. Approval reads must be verified on this
build; Cloud approval endpoints are not evidence of an on-premises contract.

| Capability | Evidence | Remaining verification |
|---|---|---|
| List requests | Existing GET `/api/v3/requests` nodes | Account scope, rate limits, complete pagination |
| Read a request | GET `/api/v3/requests/{id}` | Authoritative requester identity, updates and revision fields |
| Historical technician assignment | PUT request with `request.technician.email_id` exists in older flows | Outside new scope; never expose a technician-write tool |
| Correct support group | Group is present in POST request bodies; operator confirms group changes clear technician | Verify group-only PUT for unassigned tickets, null preservation, and concurrent-assignment protection |
| Historical related work | POST requests for offboarding teams | Outside new scope; no linked-ticket creation |
| Change status | PUT with `request.status.name` | Allowed transitions, required fields, closure rules |
| Resolve with outcome | Offboarding status-update export | User-visible notification and requester acknowledgement behavior |
| User lookup | GET `/api/v3/users`, matching `email_id` | Identity trust, disabled employees, ambiguous matches |
| Templates and groups | Names in filters and request bodies | Full catalogs, immutable IDs, site restrictions |
| Current technician field | Available in request data | Read for preservation/conflict checks only; roster/on-call not needed |
| Notes and customer replies | No matching HTTP nodes found in inspected exports | Notes are vendor-documented; customer reply contract remains unverified |
| Approvals | Dedicated Mirza templates have approval steps; other Helpdesk templates use the operator-defined DWE/On Hold-to-Open handoff | Verify dedicated approval semantics plus fallback transition actor/history and live status IDs on Build 15100 |
| Webhooks | Not established by these exports | Build/license support, delivery authentication, retries and ordering |

The inspected exports pass a technician key in the URL query. The vendor documents
an `authtoken` request header; prefer header-based authentication after checking
it on the installed build. The operator authorized the existing technician key
in `n8n-flows` nodes for read-only discovery. A secret-safe local scan located
configured keys; their live permissions and validity remain unverified. Load
values privately from their existing sources, without copying them into these
artifacts or logs. Separate read/write runtime credentials remain a deployment
design option, not a prerequisite for the authorized discovery reads.

Vendor references, used only for candidate contracts:

- [API introduction](https://www.manageengine.com/products/service-desk/sdpop-v3-api/)
  documents technician-token authentication including the `authtoken` header.
- [Request API](https://www.manageengine.com/products/service-desk/sdpop-v3-api/requests/request.html)
  documents request reads/updates and includes `last_updated_time` and approval
  status in examples. It does not establish atomic revision checks on this system.
- [Request notes](https://www.manageengine.com/products/service-desk/sdpop-v3-api/requests/request_note.html)
  documents a notes API; a note must not be treated as a customer reply without
  checking its visibility and notification behavior.
- [On-premises automation overview](https://www.manageengine.com/products/service-desk/on-premises/low-code-no-code-automation.html)
  describes webhook automation. Configuration on the installed system is unknown.

## Existing automation to reuse and coordinate

### Ticket assignment

Source: `../n8n/flows/ticketing-system/assign-tickets.json`.

- Export configured with a 30-minute schedule and `active: true`; live activation
  has not been checked.
- Lists Open, unassigned tickets in `Data infrastructure` and `Dev Flow`.
- Requests 100 rows, sorts by subject, and has no observed pagination loop.
- Excludes `Default Request`; Dev Flow also excludes `offboarding-AccessRemoval`.
- Reads `/webhook/whois-oncall-today` and consumes `DI` and `Devflow` values.
- Chooses technicians by exact template mapping, then performs PUT assignment.
- Sends Mattermost notifications through existing nodes.
- Does not inspect subject meaning or model workload, availability, or confidence.

The implementation of `whois-oncall-today` was not found among the available
workflow exports. It is historical evidence only: the group-only agent has no
dependency on this lookup, technician rosters, skills, or workload.

The older technician assigner is not a feature to port. During rollout, coordinate
concurrent assignment/group writers so a correction cannot override human work
or indirectly invoke technician assignment. This step changes neither workflow.

### Offboarding and HR views

Sources:

- `../n8n-flows/Offboarding/refactored/get-approved-automation-tickets[Scheduled].json`
- `../n8n-flows/Offboarding/refactored/update-ticket-status[Scheduled].json`
- `../n8n-flows/HR View/Onboarding View (HR).json`, particularly `Plan Pages`
- `../n8n-flows/HR View/HR View.json`, particularly authentication/session nodes

The refactored offboarding export filters Open DWE Offboarding tickets and creates
child requests for several teams. Despite its filename, inspection found no
approval-status gate or approval-history read. Do not use that name as evidence
of authorization. This describes those exports, not the presence of approvals
in ServiceDesk: the operator confirms dedicated Mirza templates have existing
approval steps. Other Helpdesk templates lack those steps and use the separately
confirmed DWE handoff described below.
The workflow also contains destructive operations outside the
scope of these new agents; only its request schemas and integration patterns are
references.

HR views provide count/page/detail reads and PostgreSQL-backed sessions and access
grants. They are pagination references, not a verified change-feed implementation.
Their authentication normalization contains an email fallback derived from a
username; this is not sufficient evidence of authoritative employee identity for
new grants.

## Confirmed ICT catalog and historical references

The operator confirmed the dispatcher team scope:

| Confirmed team | Remaining integration details |
|---|---|
| Helpdesk | Live group ID; default ownership outside DWE/Network/VOIP confirmed |
| Network | Live group ID; network subject/description ownership confirmed |
| DWE | Live group ID; named platforms and system administration confirmed |
| VOIP | Live group ID; VOIP subject/description ownership confirmed |

Only these teams are dispatcher destinations in the current scope. `HelpDesk`
appears in historical exports; resolve the live record/ID for operator-named
`Helpdesk` rather than assuming display-name spelling establishes identity.
This team list does not choose a Mirza entitlement team. Operator-confirmed
ownership is recorded in the [service catalog](service-ownership.md). DWE covers
the named platforms and system administration; Network and VOIP use related
subject/description evidence rather than a fixed service list. Anything outside
DWE/Network/VOIP stays in Helpdesk; uncertain group correction leaves the ticket
untouched rather than guessing a destination.

Onboarding, offboarding and internal-transfer process tickets and their children
are excluded before routing or Mirza enrollment. Existing process assignments
and relationships must remain intact, including intentionally cross-team child
tickets. Inspect live process/template and parent/child fields before activation;
do not infer this exclusion from every parent link or incidental keyword.

The following table records historical integration evidence. It does not expand
the four-team scope or establish a remapping from old teams to current teams.
Resolve live group IDs and site restrictions before implementation. Do not merge
similar names without an operator-confirmed mapping.

| Observed group | Evidence |
|---|---|
| Data infrastructure | Existing assignment, reminders, offboarding |
| Dev Flow | Existing assignment and reminders |
| HelpDesk | Reminders and offboarding child request |
| DCNM | Reminders and offboarding child request |
| Network | Reminder destination |
| Foundation | Reminders and conditional offboarding child request |
| Platform OPS | Reminder destination |
| Automation | Reminder destination |
| VOIP | Reminder destination |
| System Administrator | Reminder destination |
| DevSecOps | Offboarding child request; relationship to Dev Flow unknown |
| DWE | Offboarding parent-request filter; now confirmed in dispatcher scope |

Historical assignment template mappings, not current dispatcher policy:

| Template | Observed target |
|---|---|
| Small DI Passport Pipeline | Data infrastructure; technician from `DI` |
| Decrypt Data Request (Small, less than 10K) | Data infrastructure; technician from `DI` |
| offboarding-AccessRemoval | Data infrastructure only within the existing DI branch |
| Access Management | Dev Flow; technician from `Devflow` |
| Upload Static Files | Dev Flow; technician from `Devflow` |
| Report Issue on CI-CD | Dev Flow; technician from `Devflow` |
| Security Issue (Dev Flow) | Dev Flow; technician from `Devflow` |

`Access Management` is broad: it must not automatically imply a Mirza grant or
Dev Flow ownership when description evidence conflicts. Ordinary specialized ICT
templates outside Helpdesk remain untouched except eligible approved supported
Mirza requests using one of the two dedicated templates. Lifecycle process tickets
and their children remain excluded regardless of group or Mirza wording. The live
Helpdesk group ID, process metadata and Mirza execution targets
remain to be verified.
Legacy Data infrastructure/Dev Flow assignments remain references for connector
behavior. They cannot be executed by the new four-team dispatcher or silently
translated to DWE without a service-ownership decision.

## Confirmed listening and action rules

| Ticket content / template | Action |
|---|---|
| Onboarding/offboarding/internal-transfer process ticket or associated child | No external action; preserve process assignment and relationships before either workflow |
| Current group is Helpdesk; no technician; ordinary request clearly belongs to Network, DWE, or VOIP | Correct support group only regardless of template or email/UI source |
| Current group is Helpdesk; technician assigned; ordinary request belongs elsewhere | No group write; preserve human assignment because a group change clears the technician |
| Current group is Helpdesk; request belongs to Helpdesk | No-op |
| Ordinary template A/template B mismatch outside Helpdesk | No-op, including mismatches across specialized support groups |
| Supported Mirza job under Mirza Access Request or Mirza API Key | Verify existing required approval and approved terms, then fulfill |
| Supported Mirza job under another template, currently in Helpdesk | Move to DWE/On Hold, notify DWE person in charge by Mattermost with ticket link, wait for that person's Open transition |
| Persisted fallback Mirza workflow now in DWE | Continue monitoring; verify the authorized On Hold-to-Open transition and unchanged terms before fulfillment |
| Mirza text under another template outside Helpdesk, without an enrolled handoff | No-op; outside Mirza fallback intake |
| Unsupported Mirza matter under any template | No-op even if approved |
| Uncertain Helpdesk ownership | Local review; no external writes |

The operator clarified that the current Helpdesk support group defines intake,
not a template allowlist. Include email-created and ServiceDesk UI-created tickets
under any template. Resolve the canonical Helpdesk group ID; no Helpdesk template
names are needed to enable intake. Templates cannot be changed. Ordinary template
mismatches outside Helpdesk do not enable general group repair.

Ordinary correction changes only `request.group`. Never select, assign, clear, or change a
technician; repair a template/category; post a correction note/reply; change status;
or create related tickets. Listening covers all Helpdesk tickets regardless of
assignment or template. The operator confirms that changing a support group
clears the technician. Therefore automatic group writes are restricted to
unassigned tickets; assigned tickets receive no group write. Verify null remains
null and server automation does not assign a technician. Re-fetch before writing
and verify atomic revision/precondition protection for assignments made between
read and write; a re-fetch alone cannot guarantee preservation. Do not restore
technicians through compensating writes. Dedicated-template Mirza fulfillment
may run on assigned tickets while preserving group and technician. The other-
Helpdesk-template Mirza approval handoff has an explicit exception: the move to
DWE may clear an existing assignment; no technician selection/writes are allowed.

Mirza intake accepts `Mirza Access Request` and `Mirza API Key`; other templates
start workflows only while the request is in Helpdesk. Continue persisted DWE
handoffs after the group move; untracked other-template tickets outside Helpdesk
do not qualify. Verify live IDs and workflow eligibility again before writes.
Templates help extraction but do not prove approval.
Recognize only these eight jobs from eligible content:

1. `create_api_key` — create a key owned by a person email in exactly one Tool team.
2. `increase_api_key_reasoning` — increase reasoning for an API key.
3. `increase_team_reasoning` — increase reasoning for a Mirza team.
4. `grant_team_model_access` — add model access for an approved Mirza team.
5. `add_person_to_non_tool_team` — add a person email to an existing non-Tool
   team that already grants the requested UI model, preserving other memberships.
6. `increase_person_budget` — increase the person's LibreChat UI budget.
7. `increase_api_key_budget` — increase one API key's budget.
8. `increase_team_budget` — increase one Mirza team's budget.

Unsupported Mirza matters and ordinary template mismatches outside Helpdesk receive
no replies, notes, status changes, or other external actions. Local audit is allowed.
Clarification/result delivery for supported Mirza jobs stays within those jobs.

Dedicated templates use existing required ServiceDesk approval stages, with no
second sign-off or self-approval. Verify installed all/any/stage semantics.

Other Helpdesk templates have no Mirza approvals. For supported requests, persist
the handoff and terms, move to DWE, set On Hold, verify group/status, and notify
the DWE person in charge through Mattermost with the ticket link. Resolve this
person dynamically from the DWE ServiceDesk support group's `incharge_group`,
not a fixed email. The operator confirms each support group has this field.
Its API exposure, value format, and DWE lookup remain unverified. Record resolution evidence
at handoff and keep that original person as this request's recipient/approver,
even if the field later changes. New requests resolve the current field;
missing/ambiguous values cannot authorize grants.
A secret-safe scan found no exact `incharge_group` occurrences in inspected
`jam-ai-service`, `n8n`, or `n8n-flows` source files; live availability remains
unverified. The operator
allows this move even for assigned tickets and permits the resulting technician
clearing. Continue the enrolled workflow in DWE and require an authoritative
On Hold-to-Open transition by that person after handoff. An initial Open ticket,
an unrelated/agent actor, a Mattermost reply, or an untracked DWE ticket is not
approval. Actor identity and installed history APIs remain unverified. Persist
progress so retries do not reset an already approved ticket to On Hold or repeat
provisioning. This group/status/notification flow applies only to supported Mirza
requests and does not change ordinary group-only correction.

Pending/rejected/missing/unverifiable evidence does not authorize fulfillment.
Re-check current recipient/terms immediately before grants. Material changes
invalidate approval and require renewed review through the applicable path.
Resolve models, ceilings, budgets and duration from approved terms/defaults.

The operator confirmed that anything unspecified or unclear during Mirza
processing puts the ticket On Hold. Ask the currently assigned technician, or
DWE's in-charge person when no technician is assigned, regardless of the current
support group. Reuse this request's original DWE identity when recorded; otherwise
resolve DWE `incharge_group` once when needed and record that identity. The contact
must add the
requested details in a ticket note and set Open. Read note authors/content and
the corresponding status history, validate completeness, and resume the persisted
workflow; do not invent an omitted budget. Clarification preserves group/template/
technician and is separate from the supported DWE approval handoff. The operator
approved this clarification message:

> Mirza request #{ticket_id} needs clarification: {ticket_link}. Required details: {missing_details}. Add these details in a ticket note and change its status from On Hold to Open so processing can continue.

A clarification
Open event does not bypass existing approval requirements; material term changes
need renewed review. Unsupported/ineligible Mirza requests remain no-ops.

Preserve already higher reasoning/budget values. Budget increases use a captured
before value and absolute desired limit so retries do not apply a delta twice or
reset spend. Person access is an additive non-Tool membership, not a personal
model-list write or shared-team grant change. Team model access changes only the
approved Mirza team. ICT groups and Mirza entitlement teams are separate namespaces.

## Proposed intake and polling contract

Use authenticated webhooks when verified, with periodic polling reconciliation.
Read enough template/group/content data to identify eligible Mirza intake: the two
dedicated templates, or any other template while currently in Helpdesk. Persist
fallback enrollment before moving to DWE and reconcile those tracked ticket IDs
independently of the Helpdesk intake filter. Include status history/actor identity
in their relevant-state fingerprint. Resolve the eight jobs only on eligible
new intake or enrolled handoffs. Restrict ordinary group correction to requests currently
in Helpdesk regardless of template or email/UI source. Listening does not
authorize general template repair or other actions. No production cadence is
assumed from the old 30-minute assignment schedule.

1. Establish support for updated-time filtering and stable ordering. Use a fixed
   scan upper bound and an inclusive lower bound with an overlap window.
2. If the API supports compound ordering, paginate by `(updated_time, ticket_id)`.
   Timestamp ties must not be skipped by advancing a timestamp-only watermark.
3. If compound ordering is unavailable, enumerate the entire overlap window with
   a verified pagination strategy and deduplicate by ticket ID plus revision or
   canonical relevant-field fingerprint. Null updated times need a creation-time
   fallback and periodic full reconciliation.
4. Offset pagination over changing results is not a reliable snapshot. Re-scan
   overlapping windows and periodically reconcile the full permitted scope. If
   the API cannot provide a complete enumeration, leave ingestion guarantees
   unresolved and do not claim a lossless change feed.
5. Persist intake and deduplication records before moving the completed-scan
   watermark. Partial scans do not advance it. Resume failed scans safely.
6. Re-fetch a ticket before decisions and writes. Detect new human assignments,
   cancellation, and changed recipient/access requirements.
7. Distinguish a business-relevant update from an agent-generated note so replies
   and assignments do not create endless workflow loops.

Exact timestamp field, filter operators, sort semantics, pagination limit, rate
limit/backoff, and revision support are production read-only verification items.

## Identity and permission scopes

| Target | Identity / relationship | Effective scope |
|---|---|---|
| Person | Authoritative email address, normalized and resolved to one employee | LibreChat UI access and personal budget |
| Non-Tool team | Mirza/LiteLLM team without the configured Tool suffix | Grants UI models to its members; one person can hold many memberships |
| API key | Owned by a person email; exactly one Tool-team association per key | API access and key budget, together with that one team's grants/budget |
| Tool team | Mirza/LiteLLM team with the configured Tool suffix | API model grants and team reasoning/budget for keys associated with it |

Adding a person to a non-Tool team is additive: preserve all existing non-Tool
memberships. Do not set a personal model list or create a new team as a substitute.
Select the approved existing team that already grants the requested model; otherwise
clarify the mismatch. Adding a model to a team is a separate approved operation.

Key creation records both the owner email and one Tool-team ID. Other keys owned
by that email may have their own team associations; do not impose one Tool team
across all keys or derive a key's model permissions from the owner's UI memberships.
Do not move an existing key between teams under a create-key request. Person, key,
and team budget increases update distinct rows; changing one is not changing all.

The operator confirmed that an existing owner/key in the selected Tool team puts
a new create-key request On Hold for technician/original DWE in-charge
clarification. Inspect complete metadata, preserve existing keys, and ask whether
an additional key is needed through the ticket-note/Open flow. Reconcile the
current operation first so its own generated key resumes recovery rather than
triggering another hold. Expired keys count too; expiry is not absence.
If the contacted technician/in-charge answers in the clarification note and sets
Open that another key is unnecessary, the agent sends the explanation through
required completion notifications and resolves without creating a key. Preserve
existing keys and avoid claiming an expired key is usable; retry completion
without repeating clarification or provisioning.

API-key model access is inherited from the key's current Tool team. Direct key
model grants, key-model ACL updates, moving keys between teams, and attaching keys
to non-Tool teams are outside the eight jobs. Adding the owner to a non-Tool team
cannot be used as an API-access workaround. Key creation preserves existing team
grants. Only the distinct approved team-model job can expand a team's models;
never infer that job from a request to change a key's model access.

Team reasoning/model/budget jobs name the precise Mirza team and whether it is
Tool or non-Tool. They apply to that team's relevant UI or API scope. There is
no direct person-reasoning ticket job. ICT support-group IDs and Mirza entitlement
team IDs are distinct, even when their display names happen to match.

## Mirza capabilities and boundaries

Backend capability is not ticket-job authorization. Existing revoke/page-access
functions remain outside the eight-job action surface. Lifecycle expiry applies
only when explicitly included in an owned approved grant, not arbitrary revocation
requests or general offboarding.

Sources: `../jam-ai-service/scripts/reasoning_access.py`,
`../jam-ai-service/scripts/reasoning_ui.py`,
`../jam-ai-service/litellm/routing_hook.py`, and
`../jam-ai-service/adapter/ad_lookup.py`.

Observed behavior:

- Reasoning grants are stored as `reasoning_models` metadata on users, teams, or
  keys, optionally scoped to model aliases. Grant/revoke code preserves other
  metadata and reads the record back after writes.
- The ceiling ladder is `none < minimal < low < medium < high < xhigh`; the code
  default is medium, subject to deployment overrides. A lower explicit grant is
  not a reliable cap when another effective grant is higher.
- `_user_limits` in the current routing code explicitly supports many non-Tool
  teams for one email and collects their granted UI models, subject to budgets.
  Personal model lists are deliberately ignored. API traffic uses exactly its
  authenticating key's `*-Tool` team; API reasoning reads that team/key metadata.
  Some older prose in `CLAUDE.md` still says one non-Tool team; the current code
  and operator-confirmed policy support many, so do not copy that old constraint.
- User/team/key information and metadata updates use LiteLLM administration APIs.
  Current listing code pages user and key lists at 100 rows per page.
- The reasoning UI has LDAP and token authentication modes. Compose selects LDAP;
  page access is gated by bootstrap administrators or `reasoning_ui_access`.
  The new service needs its own roles; page access is not a grant-approval policy.
- Existing reasoning UI routes include `/api/state`, `/api/describe`, and
  `/api/change`; these are broad human-administration routes, not an established
  least-privilege agent service API.
- Existing user and team cache defaults are 20 and 120 seconds. Verification must
  allow measured propagation and check key caching on the installed proxy.
- Department lookup resolves an escaped mail filter to exactly one AD entry, but
  reads only the department. It does not prove active employment or authenticate
  a ticket requester.
- Department membership is provisioned once; directory department changes do not
  automatically remove stale Mirza memberships.
- The documented personal-budget/Tool-key interaction requires local fixture
  coverage and read-only production evidence; verify actual behavior during
  approved pilot fulfillment before relying on UI/API budget isolation.

Still unknown: deployed LiteLLM build, native key-generation retry/recovery
semantics, effective key expiry, live model grants and provisioning roles,
employee eligibility, package budgets/defaults, approval API details, and
direct-DM credential delivery implementation. Dedicated-template approval comes from existing ServiceDesk
steps; fallback approval comes from the DWE person resolved from `incharge_group` changing
On Hold to Open after handoff. The agent must not invent approvers or self-approve.
Reasoning metadata has no observed native expiry field; temporary grants require
ownership-aware lifecycle handling in the new service.

Use live `/v1/models` and approved packages at fulfillment time. A configured
alias is neither evidence of an employee's entitlement nor a default allowed list.
Do not select one employee's access by broadening a shared department or Tool team.

The operator requires an explicit user department-to-Tool-team map for new-key
selection. Resolve the owner's authoritative email and directory department to
one configured existing Tool-team ID. Department names alone do not authorize
guessing a team. Missing/ambiguous entries or conflicts with approved terms stop
creation for clarification. Live team aliases/IDs have now been inspected through
SSH to `mirza-ha1`: initially 92 teams, including 12 Tool and 80 non-Tool teams. All 72
department strings in the deployed catalog match live non-Tool aliases. The
[map](department-tool-team-map.md) now contains 9 explicitly approved Cloud/Tapsi
Box entries plus 21 additional mappings, all operator-verified (30 total), and
42 unspecified entries, and lists 8
uncataloged non-Tool teams separately. The requested Cloud merge moved one key
and one source-only member to Cloud-Tool, then deleted the empty TapsiCloud-Tool;
the [verified report](discovery/cloud-team-merge.json) records preserved key fields,
UI memberships and Cloud's existing 220/1d budget. The refreshed catalog has
91 teams (11 Tool, 80 non-Tool). This operator-directed merge is not an automated
ticket job; ticket agents still cannot move existing keys. No map is active. Record
the mapping version with the resolved terms; never use this map to move an
existing key or change non-Tool UI memberships. All Tapsi Box departments map to
TapsiBox-Tool; TapsiBox-Manager-Tool access upgrades/provisioning are manual.

For an unspecified mapping, the operator requires On Hold/note/Open clarification
from the technician or original DWE in-charge if null. The supplied mapping is
used only for that ticket; do not add it to the shared department map. Resolve
the specified Tool team or create it if absent using explicit approved initial
model grants, budget/reset and all other necessary terms. Missing terms trigger
clarification again. Persist team-creation correlation and provenance so retries
cannot duplicate teams/keys. The created team persists, while its department
mapping stays ticket-specific. This is supporting provisioning within the
allowed key-creation job, not general team administration or a direct-key model
grant workaround.

## Identity, delivery, and production validation

AD is an observed directory source. Mirza also references Keycloak/OpenID for UI
SSO, but new operator roles/client configuration are not established. Confirm
immutable employee identity, active status, authenticated requester linkage,
recipient delegation, and authorized approvers separately.

The operator confirmed user notifications through a Mattermost bot with a
template. Existing notification patterns are integration references. Bot
configuration, recipient lookup and DM API, user-result/key-delivery rendering
and delivery reconciliation remain pending. The operator
approved the DWE review template:

> Mirza request #{ticket_id} awaits your approval: {ticket_link}. Review the request and change its status from On Hold to Open to approve.

The operator confirmed direct-message delivery to the originally resolved DWE
person in charge through the bot. Resolve that person's Mattermost user ID and
DM conversation; persist notification delivery so retries do not duplicate work.

The operator confirmed sending newly created API keys directly to the named
key owner's Mattermost DM, even when someone else submitted the ticket. Resolve
the recipient from the approved owner email. A retrieval page is not required.
Resolve secrets only
inside the privileged bot connector, keep opaque references in LLM/Temporal/audit,
and sanitize message-send results so key-bearing bodies are not logged. Retries
deliver the original key without repeating provisioning.

For every completed Mirza ticket, notify the current assigned technician in a
bot DM with the ticket link, sanitized ticket description and verified work.
If technician is null, use the request's original DWE in-charge identity, resolving
DWE `incharge_group` once when absent. Staff descriptions exclude raw keys and
other secrets. Track this notification separately from user key delivery.
The operator confirmed setting the ticket to Resolved after verified work and
required notification delivery. Verify live status ID/required resolution fields
and read back the final status; retry it independently without repeating DMs/grants.
Mattermost messages are not approval evidence. ServiceDesk's required dedicated-
template approvals and the verified fallback DWE status transition are authoritative.

The operator confirmed no staging environment exists. A sandbox/test instance is
not a prerequisite. The operator authorized read-only discovery using LiteLLM
master keys from `jam-ai-service` and the technician key in `n8n-flows` nodes.
A local secret-safe scan found master-key configuration fields in Mirza's
environment examples and technician-key references in workflow nodes. No live
ServiceDesk requests have yet been made. On `mirza-ha1`, read-only LiteLLM
`GET /team/list` and `GET /openapi.json` succeeded using credentials privately
inside the running container. Only aliases, team IDs, kinds and deployed catalog
department names were retained in the [sanitized inventory](discovery/litellm-team-inventory.json).
Other credentials, permissions, and contracts remain unverified. Do not print
values or copy them into new tracked files.

Validation sequence:

1. Exercise parsing, approval transitions, wrong-template detection, conflicts,
   and failure/retry recovery locally using fixtures and mock connectors.
2. Inspect existing production tickets, catalogs, approval data, and Mirza metadata
   through read-only API operations with redacted output and limited scope/rate.
3. Run observation mode: propose actions without assignments, grants, replies,
   status changes, template changes, or other external writes.
4. After explicit workflow activation, fulfill existing approved pilot requests
   and verify actual writes. Do not create fake production tickets or test grants
   to satisfy a nonexistent staging requirement.

## Evaluation data and next actions

`../tests/fixtures/step_1/discovery_tickets.json` contains synthetic cases with
proposed outcomes. It has no real employees or tickets and is not a benchmark
claim or an executable authorization policy.

A historical evaluation set remains outstanding. Obtain a restricted sample,
remove secrets and identifiers, label service owner and acceptable actions with
ICT reviewers, include Persian/English and wrong-template cases, and separate
calibration and held-out sets. Keep originals and any re-identification mapping
outside Git. Sample size and accuracy targets require agreement.

Complete the decisions in [step-1-decisions.md](step-1-decisions.md), then verify
installed API contracts through production read-only inspection. The Step 1
policy baseline is ready for implementation, and Step 2's local scaffold has
been [verified](step-2-runtime.md) with synthetic probes. Carry the remaining live
contract checks into Steps 3–4/7–8 and real-ticket evaluation into Step 10;
Step 1's full exit condition is not met until capabilities and policy examples
are confirmed by their owners.

The operator will provide historical examples. Collect remaining answers one
question at a time. Technician clearing, both Mirza approval paths, and permission
to clear an assignment during the fallback DWE handoff are confirmed. Dynamic
in-charge lookup through each ServiceDesk support group's `incharge_group` is
also confirmed. Each request keeps its originally resolved in-charge person even
if the group field changes. DWE approval message wording and delivery to that
person's DM are confirmed. Missing/unclear processing details use the confirmed
On Hold/note/Open clarification flow, always using DWE when no technician is
assigned. Clarification message wording is confirmed. New-key
delivery directly to the user's Mattermost DM, completion descriptions to the
assigned technician or original DWE in-charge if null, and final Resolved status
are confirmed. The operator also approved the staff completion template:

> Mirza request #{ticket_id} completed: {ticket_link}. Request: {ticket_description}. Work done: {completion_summary}.

All 30 mapped entries in the [concrete map](department-tool-team-map.md) and
ticket-specific on-the-fly mapping/team-creation handling are confirmed;
unspecified departments use human clarification. Named-owner delivery for
delegated requests is confirmed. DWE services and content-based Network/VOIP
ownership are confirmed in the [service catalog](service-ownership.md), along
with the lifecycle process/child exclusion. Everything outside DWE/Network/VOIP
stays in Helpdesk. New create-key requests whose owner already has a key in the
mapped Tool team use On Hold and the established technician/original DWE in-charge
clarification flow; no automatic additional key. Reconcile this operation's own
generated key before checking duplicates so recovery does not create a fresh hold.
Keys in other teams do not trigger this same-team check. Complete lookup and
sanitized metadata are required; do not disclose an existing secret. Approval and
clarification waits are indefinite, with a Mattermost reminder every calendar day
at 10:00 AM `Asia/Tehran`, including weekends. Remind the outstanding response's
contact, preserve the original fallback approver, and read native pending-stage
approvers for dedicated approvals. Reminder scheduling/deduplication and native
approval-recipient API contracts remain to be implemented/verified. Revalidate
the waiting gate before sending, stop on satisfaction or terminal/excluded
requests, and never change ticket state or provision because of a reminder.
Expired keys count too when checking existing keys in the selected Tool team.
The confirmed human decision that another key is unnecessary completes through
notifications and Resolved status, with no key creation.
