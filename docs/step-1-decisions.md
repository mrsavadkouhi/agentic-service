# Step 1 — Policy and integration decisions

Status: ticket scope, group-only correction, and the Mirza job allowlist are
confirmed by the operator. Live IDs/contracts and execution terms remain pending.
This register does not introduce another approval process for development.

## Confirmed decisions

| ID | Operator decision | Implementation consequence |
|---|---|---|
| INT-01 | ServiceDesk Plus 15.1 Build 15100 | Verify installed contracts through read-only inspection |
| INT-02 | No staging environment | Local fixtures/mocks, production observation, then scoped activation |
| GROUP-SCOPE | Helpdesk, Network, DWE, VOIP | Support-group destinations use verified live IDs |
| GROUP-OWNERSHIP | DWE owns the named platforms and system administration; Network and VOIP use their related subjects/descriptions | Use the [service catalog](service-ownership.md); everything else stays in Helpdesk; live IDs remain pending |
| PROCESS-EXCLUSION | Leave onboarding, offboarding and internal-transfer process tickets and their child tickets alone | Exclude before routing or Mirza enrollment; preserve assignments, relationships and ticket state |
| GROUP-INTAKE | Any request currently in Helpdesk, from email or UI, regardless of template | Listen regardless of assignment; apply a separate unassigned-only group-write gate |
| GROUP-PRESERVE | Preserve technician assignments for ordinary group correction | Keep the exact technician value; assigned ordinary tickets receive no group write |
| GROUP-SIDE-EFFECT | Changing the support group clears the technician | Ordinary correction is unassigned-only; the approved Mirza DWE handoff is an exception |
| NO-TECHNICIANS | Do not assign tickets to technicians | No technician selection or writes; allow server-side clearing only during the approved Mirza DWE handoff |
| INNER-TEMPLATES | Ordinary template A/template B mismatch outside Helpdesk | Do nothing, including mismatches across specialized support groups |
| NO-TEMPLATE-WRITES | Template changes are not possible | Always preserve the submitted template; no template-write capability |
| MIR-APPROVAL | Dedicated Mirza templates use their existing required ServiceDesk approvals | Fulfill after final required approval; no extra sign-off or self-approval |
| MIR-FALLBACK-APPROVAL | Other Helpdesk templates have no Mirza approval steps; move supported requests to DWE, put On Hold, notify the DWE person in charge with the ticket link | Fulfill only after that authorized person changes the held ticket to Open; preserve the original template |
| MIR-INCHARGE | Each ServiceDesk support group has `incharge_group`; resolve the DWE person in charge dynamically from that group's value | Read the DWE support-group field for notification recipient and approval actor; do not hardcode a person's email |
| MIR-INCHARGE-SNAPSHOT | Keep the originally resolved person for that request even if `incharge_group` later changes | Persist the approver at handoff; notification retries and approval checks use that identity; new requests resolve the current field |
| MIR-HANDOFF-TECHNICIAN | Move fallback Mirza requests to DWE even when a technician is assigned; allow the assignment to be cleared | Explicit exception to preservation for this handoff only; no technician assignment, selection, or restoration |
| MIR-TEMPLATES | Mirza Access Request; Mirza API Key; other templates from Helpdesk may be used | Dedicated templates qualify; start fallback workflows only in Helpdesk, then continue their tracked DWE approval handoff |
| MIR-JOBS | Create API key; increase reasoning for API key; increase reasoning for team; add model access for team; add user to a team for model access; increase person budget; increase API-key budget; increase team budget | Explicit eight-operation allowlist; all other requested Mirza matters are no-ops |
| MIR-PERSON | Person means email for LibreChat UI access and budget | Access through additive membership in one or many non-Tool teams |
| MIR-KEY | API key is owned by a person email and has exactly one Tool team | Verify owner and one Tool-team ID; do not inherit UI/non-Tool access |
| MIR-EXISTING-KEY | If a create-key request's owner already has a key in the mapped Tool team, including an expired key, put On Hold and ask | Use the established technician/original DWE in-charge clarification flow; do not automatically create another key |
| MIR-NO-ADDITIONAL-KEY | If that technician/in-charge confirms another key is unnecessary, resolve the ticket with the explanation | Verify the clarification note/Open response, create no key, send required user/staff completion notifications, then set Resolved |
| MIR-KEY-MODELS | No model grants on an API key and no key attachment to non-Tool teams | Model access comes from the key's existing Tool team; no key ACL writes or team moves |
| INT-CREDENTIALS | Use LiteLLM master keys in jam-ai-service and the technician key in n8n-flows nodes for discovery | Existing sources located without disclosing values; read-only inspection authorized, live permissions/contracts still unverified |
| MIR-DEPARTMENT-MAP | Maintain a user department-to-Tool-team map for agent decisions; investigate live Mirza teams through SSH and request operator verification | Resolve the new key owner's authoritative department to one configured existing Tool team; concrete live-derived proposals await verification |
| MIR-CLOUD-MAP | Merge TapsiCloud-Tool into Cloud-Tool; Tech & Product - Cloud maps to Cloud-Tool | Explicitly requested live administrative merge completed; this department mapping is approved |
| MIR-BOX-MAP | All Tapsi Box departments map to TapsiBox-Tool | Includes Executive Management; do not infer manager-team eligibility from a department name |
| MIR-BOX-MANUAL | TapsiBox-Manager-Tool access upgrades are manual work | Exclude that team from automated mapping, access upgrades and key provisioning; do not use it as a fallback |
| MIR-ON-FLY-MAP | If mapping is unspecified, ask the technician or DWE in-charge to supply it; if the destination Tool team does not exist, create it and use the supplied mapping | Use On Hold/note/Open with explicit validated team-creation terms and appropriate approval; mapping applies only to that ticket |
| MIR-NOTIFICATION | Notify the user through a Mattermost bot using a template | Resolve the recipient and render verified results; implement user-result/key-delivery rendering |
| MIR-KEY-DELIVERY | Sending the newly created API key directly to the user's Mattermost DM is sufficient | Deliver through the privileged bot connector to the verified intended user; no retrieval-page requirement |
| MIR-KEY-RECIPIENT | For a request on behalf of another person, send the key to the named key owner | Resolve Mattermost identity from the approved owner email; requester identity alone does not select the key recipient |
| MIR-COMPLETION-NOTIFY | Every completed Mirza ticket must notify its assigned technician, or DWE's in-charge person if technician is null, with descriptions of the completed ticket | Send a Mattermost completion DM with ticket link, sanitized ticket description and verified work/result; retain original DWE identity when already recorded |
| MIR-COMPLETION-TEMPLATE | Use the approved completion message below | Render verified ticket ID/link, sanitized description and work summary for the selected technician/in-charge DM |
| MIR-FINAL-STATUS | Set successful Mirza tickets to Resolved after verified fulfillment and delivered notifications | Verify live status ID and required resolution fields; retry final status without repeating provisioning or messages |
| MIR-REVIEW-TEMPLATE | Use the approved DWE review message below | Substitute the authoritative ticket ID/link and send through the Mattermost bot |
| MIR-REVIEW-DESTINATION | Send the approval notification to the original DWE person in charge's Mattermost DM | Resolve that person's Mattermost user ID and direct-message conversation; persist delivery for retries |
| MIR-CLARIFICATION | If anything during Mirza processing is unspecified or unclear, set On Hold and ask the assigned technician, or the in-charge person when technician is null | Human adds the requested details in a ticket note and sets Open; read and validate the note before resuming, without inventing missing values |
| MIR-CLARIFICATION-CONTACT | With no technician, always use DWE's in-charge person | Reuse the request's original DWE in-charge snapshot when present; otherwise resolve DWE `incharge_group` and record that original identity |
| MIR-CLARIFICATION-TEMPLATE | Use the approved clarification message below | Render ticket ID/link and requested missing details; instruct the selected contact to add a ticket note and set Open |
| MIR-WAIT | Wait indefinitely for approval or clarification; notify every morning | No automatic expiry, resolution, rejection or escalation based solely on waiting age; reminders do not authorize execution |
| MIR-REMINDER-TIME | Send morning reminders at 10:00 AM Tehran time | Daily schedule in `Asia/Tehran`, including weekends; deduplicate delivery and revalidate the pending response before sending |
| EVAL-SOURCE | Operator will provide representative ticket examples | Keep historical evaluation collection pending until examples arrive |

## Listening and action precedence

0. Exclude onboarding, offboarding and internal-transfer process tickets and
   their associated children before either workflow. Use authoritative process
   context; uncertain association means local review without external writes.
   See the [service catalog](service-ownership.md). Revalidate before writes.
1. Apply Mirza intake eligibility: `Mirza Access Request` or `Mirza API Key`
   qualifies; another template starts a workflow only in the current Helpdesk group.
   Identify supported intent from the subject/description of eligible tickets.
   Other-template tickets outside Helpdesk are no-ops unless already enrolled in
   this agent's persisted DWE approval handoff. Do not adopt unrelated DWE tickets.
2. For a supported Mirza job in a dedicated template, resolve terms and verify
   its existing required approvals. For a supported job in another Helpdesk
   template, resolve terms and start the DWE/On Hold handoff described below.
   Fulfill only after the appropriate approval evidence is verified.
3. For unsupported Mirza matters, do nothing. An approval does not expand the
   allowlist. Do not turn these into general Mirza support or automatic routing.
4. For non-Mirza requests currently in the Helpdesk group, infer the responsible
   support group from content regardless of template or email/UI origin. Correct
   a mismatched group only when no technician is assigned and ownership/update
   semantics are established. A group change clears the technician, so assigned
   tickets receive no group write. Already-correct groups are no-ops. This group
   write gate does not block approved Mirza jobs that preserve ticket assignment.
5. For ordinary requests outside Helpdesk, do nothing about template A/template B
   mismatches even if another specialized support group would be more suitable.
6. Uncertain ordinary ownership/intent is a local review outcome, with no external
   ticket changes. Missing/unclear information during eligible Mirza processing
   follows the On Hold/note/Open clarification flow below. Unsupported or ignored
   tickets receive no correction replies, notes,
   status changes, template changes, linked tickets, or technician changes.

Local audit/observation of no-op decisions is permitted. For supported Mirza jobs,
clarification of unresolved approved terms and result delivery/closure follow the
configured fulfillment flow. These are not general-purpose responder actions.
Mixed requests cannot execute an unsupported operation; execute supported parts
only if their exact approved terms can be separated without ambiguity.

## DWE approval handoff for other Helpdesk templates

These templates have no existing Mirza approval steps. For an eligible supported
job, persist the ticket ID, original Helpdesk intake, original template, request
terms/fingerprint, and handoff state. Move its support group to DWE and set its
status to On Hold, then verify both values. Notify the configured DWE person in
charge through the Mattermost bot with the ticket link and a configured review
template. Do not select a technician or change the ticket template.

The operator explicitly allows this supported Mirza handoff even when a
technician is assigned: the DWE group move may clear that assignment. Record
the before/after technician values and this exception in the audit. Do not
select, assign, restore, or write a technician. Check concurrent changes to
group, content, and approval terms before moving; this exception applies only
to this handoff, not ordinary group correction or other Mirza ticket writes.

Continue monitoring the persisted workflow after the ticket moves out of Helpdesk.
Resolve the DWE person in charge dynamically from the DWE support group's
`incharge_group` field in ServiceDesk. The operator confirms each support group
has this field; its API exposure, value format, and lookup contract remain
unverified. Resolve the value to an
authoritative ServiceDesk identity and Mattermost recipient. Record the source
revision/read time and resolved identity at handoff for notification and approval
evidence. Keep this original identity for that request even if the group field
later changes; retries and approval checks use the persisted identity. New
requests resolve the current field rather than sharing a fixed global approver.
Missing, unavailable, or ambiguous values leave the job waiting without grants.

Approval means an observed On Hold-to-Open transition made by the originally
resolved DWE person in charge after this handoff. Verify the actor, transition ordering,
current DWE group, and unchanged recipient/operation/terms from authoritative
ServiceDesk history. Initial Open status, a transition by another person or the
agent, a Mattermost reply, and an untracked DWE ticket do not authorize execution.
If actor/history cannot be verified, wait for review rather than granting access.
Material term changes invalidate the approval and require renewed review.

Persist handoff and notification progress so retries/crash recovery reconcile
the same ticket and message without re-holding an already approved ticket or
repeating a grant. Only group/status writes needed for this supported Mirza
handoff are permitted; ordinary dispatch still writes the support group only.

Approved DWE approval notification template:

> Mirza request #{ticket_id} awaits your approval: {ticket_link}. Review the request and change its status from On Hold to Open to approve.

Render the placeholders from the authoritative ticket ID and configured
ServiceDesk ticket URL. The recipient remains this handoff's originally resolved
DWE in-charge person. Send it to that person's Mattermost DM through the bot.
This is the review message; clarification and staff-completion templates are
also approved below. User-result/key-delivery rendering remains to be implemented.
Direct key delivery through the user's DM is confirmed.

## Clarification during Mirza processing

Whenever needed information is unspecified or unclear, pause affected Mirza
execution, persist the missing questions and workflow position, and set the
ticket On Hold. This includes an omitted budget on a new-key request: do not
invent a default. Read the current assignment and ask the assigned technician;
if it is null, use DWE's in-charge person, regardless of the ticket's current
support group. Reuse the request's original DWE in-charge identity if recorded;
otherwise resolve DWE's ServiceDesk `incharge_group` and persist that identity
when first needed. Preserve group, template, and technician during this
clarification; only the separately authorized DWE approval handoff may move the
group and clear its technician. Ask through the Mattermost bot with the ticket
link and specific missing details using the approved message below.

> Mirza request #{ticket_id} needs clarification: {ticket_link}. Required details: {missing_details}. Add these details in a ticket note and change its status from On Hold to Open so processing can continue.

The contacted technician/in-charge person must add the requested details in a
ticket note and set the ticket back to Open. Read notes with author identity and
event ordering, associate the response with this clarification cycle, and verify
the matching Open transition. An Open status alone, a Mattermost reply alone,
or unrelated/agent-written notes do not resolve the question. Re-extract and
validate the supplied details; if they remain missing or ambiguous, hold and
ask again. Persist the selected contact, notes, transitions, and notification
progress so retries resume the same cycle without duplicate provisioning.

Record the reason for each hold: `awaiting_clarification` and `awaiting_approval`
are distinct workflow states even though both use On Hold in ServiceDesk. A
technician's clarification note/Open transition supplies information; it does
not replace dedicated-template approvals or the original DWE handoff approver.
The same Open event can satisfy both checks only if the actor is also that
authorized approver and the exact resulting terms have valid approval evidence.
Materially changed terms require renewed review through the applicable path.
Existing eight-job boundaries, identity verification, and no-op rules for clearly
unsupported/ineligible requests still apply.

## Indefinite waiting and morning reminders

The operator confirmed indefinite waiting for required Mirza approvals and
clarification, with a reminder every morning at **10:00 AM in `Asia/Tehran`**.
Use a calendar-day schedule, including weekends, rather than a fixed UTC offset
or a 24-hour timer started when the ticket enters On Hold. Waiting age alone
must not expire, resolve, reject, escalate or authorize a ticket. Connector
timeouts and bounded delivery retries remain separate from human waiting.

Send reminders through the Mattermost bot to the person whose response is needed:
the original DWE in-charge for fallback approval, the selected technician or
original DWE in-charge for clarification, and the authoritative pending approvers
for dedicated-template approval. Resolve dedicated approval recipients from the
current required approval stage; exact live API/identity contracts remain pending.
Do not change the fallback approver snapshot because `incharge_group` changes.

Include the ticket link and the outstanding action. Reuse the appropriate
approved fallback-review or clarification wording; dedicated-template approval
reminders must describe the native approval action, not the fallback Open
transition. Clarification reminders include sanitized missing details and the
note/Open instruction. No reminder may contain an API key or other secret.

Only persisted eligible workflows with unresolved approval/clarification gates
qualify. Re-read authoritative ticket, process context and response evidence
before sending; stop reminders once that gate is satisfied, or the request is
completed, cancelled, rejected or excluded. An arbitrary On Hold ticket is not
enrollment, and an unverified Open transition does not satisfy a waiting gate.
When both gates are pending for the same recipient, combine the required actions
into one reminder rather than sending duplicates.

Persist reminder state and the waiting-cycle identity. Deduplicate by ticket,
recipient and Tehran calendar date; retries and multiple workers must not create
multiple logical reminders. Skip obsolete waiting cycles. Schedule the next
eligible morning after recovery without replaying reminders for missed dates.
Sending or retrying a reminder does not change the ticket status, restart its
handoff, or repeat provisioning.

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

Before generating a new key, inspect the owner's keys in the selected Tool team
using a complete metadata lookup. An existing key for that owner/team requires
On Hold and clarification from the current technician, or the original DWE
in-charge when technician is null. Ask for an explicit decision on whether an
additional key is needed, in a ticket note followed by Open. This is not a
permanent one-key-per-person limit. Preserve existing keys; do not rotate, revoke,
move, or deliver an existing secret as a substitute for the requested new key.
Staff clarification includes only sanitized metadata or opaque references.

First reconcile this workflow's durable operation record: a key already created
by this same operation is a retry/recovery result, not a fresh duplicate requiring
another hold. Keys in other Tool teams do not trigger the same-team check.
Unverified/incomplete lookup must not be interpreted as no existing keys. Human
clarification still follows the applicable approval path and binds to the actual
additional-key decision; Open alone does not bypass approval. Expired keys count
in this check too; do not treat expiry as absence.

If the contacted technician/in-charge confirms in the correlated ticket note
that another key is unnecessary and sets Open, complete the request without
creating a key. Persist that verified decision and its explanation, notify the
intended user and the current technician/original DWE in-charge through the
completion flow, then set Resolved. The completion summary must explicitly say
no new key was created and explain the human decision. Do not claim an expired
existing key is usable, expose an existing secret, or re-enable it. The agent
must not infer this decision from the mere presence of an existing key, Open
alone, a Mattermost reply, or a note by an unrelated actor. No new provisioning
approval is needed to honor this verified decision not to create a key; creating
an additional key still requires the applicable approval evidence. Retries resume
notification/resolution without generating a key or reopening clarification.

For new API keys, resolve the owner's email to an authoritative department and
look up an explicit, versioned department-to-Tool-team map. Each configured
department resolves to one Tool-team ID; several departments may share a team.
Tech & Product - Cloud uses Cloud-Tool. All Tapsi Box departments, including
Executive Management, use TapsiBox-Tool. TapsiBox-Manager-Tool access upgrades
and provisioning are manual; never infer them from a department or use the
manager team as an automatic fallback.

Missing, ambiguous, invalid, or conflicting mappings/approved terms require
the established On Hold clarification: ask the assigned technician, or original
DWE in-charge if null, to specify the department and destination Tool team in
a ticket note, then set Open. Verify the department from authoritative identity
and resolve exactly one Tool team. If the specified destination does not exist,
create it as an approved supporting step of `create_api_key`, then record its ID
and the supplied mapping. This is not a ninth general team-administration job.
Require explicit name, Tool kind, initial team-model grants, budget/reset and
other needed terms; unspecified values use another clarification cycle, never
guessed grants or budgets. Preserve applicable approval for the resulting terms.
Do not create teams to work around unsupported direct-key model requests, or
silently widen existing team grants. A supplied mapping applies only to the
current ticket: preserve its provenance in workflow/audit, do not add it to the
department-wide map, and do not automatically reuse it for later requests.

Record the department, mapping origin/version, note author/event, resolved team
and approved terms. Non-Tool UI memberships are unaffected. Existing-key
reasoning/budget updates use that key's current team; mapping changes never move
an existing key. The separately authorized one-off Cloud merge moved one key and
one member through native LiteLLM APIs and removed the empty source team. Its
[verified report](discovery/cloud-team-merge.json) records preserved key fields,
UI memberships and destination policies; this operator action does not enable
ticket agents to merge teams or move existing keys.

Supported-job notifications use a Mattermost bot and a configured template.
Resolve the intended recipient from authoritative identity, record delivery
status, and retry without repeating provisioning. The operator confirmed direct
delivery of a newly created API key to the intended user's Mattermost DM; an
authenticated retrieval page is not required. Resolve the DM recipient from the
approved key-owner email, including when the requester is another person. Verify
that owner's identity and Mattermost account; broader requester/delegation
authorization still follows the ticket's applicable approval evidence.
Keep the key in privileged encrypted storage and pass only opaque references
through the LLM, Temporal and audit. Resolve the key reference only inside the
privileged notification connector when sending the authorized user DM; sanitize
connector results so message bodies containing keys do not enter histories/logs.
Delivery retries reuse the same key and tracked message, never creating a new key.

For every completed supported Mirza ticket, read the current technician and
notify that person; if null, use the request's originally recorded DWE in-charge
person, resolving DWE `incharge_group` once when absent. Send a bot DM describing
the completed ticket and verified work, including its link and sanitized ticket
description. Select and record this completion recipient when preparing the
notification; retries use that record. Completion messages contain no raw API
keys, secret-bearing descriptions, or misleading claims about unverified work.
Track user-key delivery and staff completion notification separately so a failed
message can be retried without repeating provisioning or sending another key.
Approved staff completion notification template:

> Mirza request #{ticket_id} completed: {ticket_link}. Request: {ticket_description}. Work done: {completion_summary}.

The verified no-additional-key outcome uses the same completion notification and
Resolved-status sequence, with no key-delivery message or Mirza write.
Key-delivery/user-result wording remains an implementation detail. After verified work and
required notifications are delivered, set the ticket to Resolved and read back
the result. Verify live status ID and required resolution fields. Reconcile final
status independently on retry so a failed status write does not repeat work or DMs.

There is no direct API-key model-access job. The key agent must not set/add model
grants on a key, move a key to a different Tool team, or attach it to a non-Tool
team. New keys use the selected Tool team's existing model grants; creation does
not change those grants. Do not add the owner to a non-Tool team to widen API access.
Adding a model to an approved Tool team remains the separate team-model job,
with inherited effects on that team's keys. A direct key request does not authorize
that broader team change and must not be automatically converted into it.

Team reasoning/model/budget jobs name the precise Mirza team and whether it is
Tool or non-Tool. They apply to that team's relevant UI or API scope. There is
no direct person-reasoning ticket job. ICT support-group IDs and Mirza entitlement
team IDs are distinct, even when their display names happen to match.

## Remaining integration and execution details

| ID | Needed fact | Blocks |
|---|---|---|
| INT-03 | Verify permissions/rate limits of the authorized existing repository credential sources | Live contract inspection; source locations are confirmed |
| INT-04 | Webhooks, update ordering, pagination, and revision semantics | Reliable production intake |
| GROUP-01 | Canonical live Helpdesk group ID | Intake eligibility is current group only; no Helpdesk template allowlist needed |
| GROUP-02 | Live support-group IDs; all four ownership rules are confirmed in the service catalog | Correct destination |
| GROUP-04 | Live lifecycle process/template IDs and parent/child relationship metadata | Exclude onboarding/offboarding/internal-transfer process tickets and children |
| GROUP-03 | Verify null remains null, automatic assignment is absent, and concurrent assignments are protected | Clearing behavior is operator-confirmed; group-only writes restricted to unassigned tickets |
| MIR-01 | Resolve authoritative emails, key owner/one Tool team, and precise Mirza team IDs/kinds | Enforce confirmed UI/API/team scope; support groups remain separate |
| MIR-02 | Fields/defaults for models, reasoning level, budget target, absolute/delta amount, duration | Executable approved operation |
| MIR-03 | Dedicated-template final approval/history; fallback On Hold-to-Open history with authenticated actor, status IDs, and material-change handling | Valid approval evidence for both paths |
| MIR-04 | Live IDs/fields for Mirza Access Request and Mirza API Key | Structured extraction hints only |
| MIR-05 | Verify live AD values and Tool-team creation contracts | All 30 mapped entries are operator-verified; 42 unspecified entries use ticket-scoped clarification and explicit team creation when absent |
| ID-01 | Requester identity/delegation and operator authentication | Privileged execution |
| SEC-01 | Verify encrypted key storage and intended-recipient identity for direct Mattermost DM | Direct key delivery confirmed; secrets confined to privileged connector/storage and authorized user DM |
| MSG-01 | Mattermost bot identity/configuration, recipient lookup and DM API, user-result/key-delivery rendering and reconciliation | Review, clarification and staff-completion templates, direct user key DM, and completion contact priority confirmed |
| MIR-06 | Verify API exposure/format of ServiceDesk support-group `incharge_group`, DWE lookup, and ServiceDesk/Mattermost identity resolution | Resolve dynamically for each new handoff, preserve its original approver; source and change policy confirmed |
| MIR-CLARIFY-01 | Verify note author/history APIs and resume event correlation | Supported Mirza On Hold/note/Open clarification; contact selection and message wording confirmed |
| OPS-01 | Durable reminder scheduling/deduplication and live dedicated-approval recipient lookup; indefinite waiting and daily 10:00 Asia/Tehran reminders are confirmed | Durable handling of held requests |
| EVAL-01 | Operator-provided restricted historical samples, reviewers, and acceptance targets | Production quality assessment; operator will provide examples |

Technician rosters, workload, skills, leave, and on-call lookup are not dependencies
for this scope. There is no automatic fallback assignment for uncertain requests.
The group-only rule must be enforced by payload shape and installed behavior,
not just a prompt telling the LLM to avoid assigning people.

## Supported Mirza execution contracts

| Operation | Required approved terms | Execution boundary |
|---|---|---|
| create_api_key | Owner email, authoritative department, approved mapped Tool team or explicit new-team terms, purpose/client, budget, duration, verified user DM recipient | Resolve/create exactly one approved Tool team; use its initial/existing model grants without key ACL writes; deliver key through user Mattermost DM |
| increase_api_key_reasoning | Owned key reference, its Tool team, model scope, higher ceiling, duration/default | Change key reasoning metadata; preserve higher effective grants; never change the owner row |
| increase_team_reasoning | Explicit Mirza team ID/kind, model scope, higher ceiling, duration/default | Change only the approved team's reasoning metadata |
| grant_team_model_access | Explicit Mirza team ID/kind, model aliases, duration/default | Add models to that team and preserve current model grants |
| add_person_to_non_tool_team | Person email, approved existing non-Tool team, requested model | Add membership while preserving other memberships; team must already grant the model |
| increase_person_budget | Person email, approved amount, absolute/delta meaning, existing reset/default | Increase personal LibreChat budget only; preserve spend/reset |
| increase_api_key_budget | Owned key reference, owner email, one Tool team, approved amount/meaning | Increase only this key's budget; preserve spend/reset |
| increase_team_budget | Explicit Mirza team ID/kind, approved amount/meaning, existing reset/default | Increase only this team's budget; preserve spend/reset |

Budget retries reconcile an absolute recorded desired limit, so a delta is not
added twice. Already larger limits are preserved. Grant-team-model access and
add-person membership are distinct jobs; never silently widen a shared team's
models to fulfill an individual membership request.

All eight jobs require approval through the applicable intake path. Dedicated
templates use their configured final approval semantics rather than requiring
every individual approver regardless of stage configuration. Other Helpdesk
templates use the tracked DWE handoff and authorized On Hold-to-Open transition.
Pending, rejected, missing, unavailable, or materially stale evidence cannot
authorize execution. The agent must never approve its own job.

No direct API-key model grants/ACL changes, API-key team moves/non-Tool attachment,
user-membership workarounds for API access, direct person-reasoning or
personal-model-list updates, ticket-driven
revocation, key rotation/deletion, reasoning downgrade, budget
reduction/spend reset, arbitrary admin/page access, general Q&A, or other Mirza
job is supported. Necessary verification, secure delivery, retry recovery, and
expiry explicitly included in owned approved terms do not add new ticket jobs.

## Completion record

- Product/build, no staging, group-only scope, and preserved technician assignments:
  confirmed.
- Helpdesk-group intake across email/UI regardless of template: confirmed;
  replaces template-based listening restrictions. Technician clearing on group
  changes is confirmed; ordinary group writes require unassigned tickets.
- Specialized-template no-op rule and eight Mirza jobs: confirmed.
- Dedicated Mirza templates plus Helpdesk-only fallback templates: confirmed.
- Other Helpdesk templates lack Mirza approval steps: confirmed. Their supported
  requests use DWE/On Hold, a Mattermost ticket-link notification to the person in
  charge, and that person's Open transition as approval. Actor identity/API
  evidence remain pending. The handoff may move assigned tickets and allow
  ServiceDesk to clear their technician; that exception is confirmed.
- Dynamic DWE in-charge resolution from each ServiceDesk support group's
  `incharge_group` field: confirmed. API exposure, value format, and identity
  resolution remain pending; a secret-safe
  repository scan found no occurrences of this exact variable in the inspected
  `jam-ai-service`, `n8n`, or `n8n-flows` source files. This does not establish its
  availability in live systems.
- Original in-charge person remains the recipient/approver for an enrolled
  request after the group's field changes: confirmed. New requests resolve the
  current field; retries do not transfer a waiting request to a new person.
- DWE approval notification template with ticket ID/link and On Hold-to-Open
  instructions and direct-message delivery to the original DWE in-charge person:
  confirmed. Bot/API configuration and remaining message wording remain pending.
- Unspecified/unclear Mirza processing details use On Hold, assigned technician
  (or in-charge if null), a ticket note, and Open to resume: confirmed. No new-key
  budget is invented when omitted; the response is obtained through clarification.
- Clarification without a technician always goes to DWE's in-charge person:
  confirmed; reuse the request's original DWE contact when already recorded.
- Clarification message with ticket ID/link, missing details, ticket-note and
  On Hold-to-Open instructions: confirmed.
- Newly created API keys are sent directly to the user's Mattermost DM: confirmed;
  the previously proposed retrieval page is not required.
- API-key delivery recipient is the named owner, including requests submitted
  by someone else: confirmed. Staff completion remains a separate notification.
- Every completed Mirza ticket notifies the assigned technician or original DWE
  in-charge if null, describing the completed ticket and verified work: confirmed.
- Staff completion message with ticket ID/link, ticket description and verified
  work summary: confirmed.
- Person-email identity, many non-Tool memberships, and one Tool team per key:
  confirmed; approval is required through the appropriate intake path.
- Historical repository inspection and synthetic examples: completed.
- Existing credential sources, department-to-Tool-team mapping requirement, and
  templated Mattermost bot notification channel: confirmed. Live AD verification and
  notification/delivery details remain pending.
- Live read-only LiteLLM team discovery through SSH to `mirza-ha1`: completed.
  [Reviewable map](department-tool-team-map.md) and
  [machine-readable draft](department-tool-team-map.json) contain live IDs with
  30 approved entries and 42 unmapped
  department entries. Agent execution remains inactive. Unspecified mapping now
  uses human ticket-note clarification and, when explicitly specified, creation
  of the absent Tool team under the supported key-creation workflow.
- On-the-fly mappings apply only to their current ticket, never future department
  requests: confirmed. Created Tool teams persist, but the mapping remains local
  to its request's workflow/audit evidence.
- Requested live Cloud merge: completed and verified. One existing key and one
  source-only member moved to Cloud-Tool, whose budget remains 220/1d; key fields
  and non-Tool memberships were preserved. The empty TapsiCloud-Tool was deleted.
- TapsiBox-Manager-Tool remains manual; all Tapsi Box departments use TapsiBox-Tool.
- Final successful Mirza status is Resolved after verified work and delivered
  required notifications: confirmed.
- Live template/group/status IDs, API behavior, approved execution terms/defaults,
  delivery implementation and historical evaluation data: pending.

The Step 1 policy baseline is ready for implementation. Full live-contract
verification remains open in the register above; those checks continue in the
relevant later steps and gate affected production actions. Step 2's local scaffold
is implemented and verified; see [runtime verification](step-2-runtime.md).
Only synthetic runtime probes exist, with observation defaults and no live
ServiceDesk/Mirza/Mattermost write connectors.

Resolve operator questions one at a time. Technician behavior is answered:
support-group changes clear the technician. Other Helpdesk templates use the
confirmed DWE handoff, including permission to clear an existing assignment.
The source is answered: each ServiceDesk support group has `incharge_group`.
In-charge changes, review message wording, direct-message delivery, and handling
unspecified details, DWE clarification fallback, direct key DM, completion
notification rules, completion wording and final Resolved status are answered.
All 30 entries in the [map](department-tool-team-map.md) are now operator-verified.
The named key owner receives delegated-request key DMs: confirmed. DWE services
and content-based Network/VOIP ownership are recorded in the
[service catalog](service-ownership.md). Lifecycle process tickets and children
are excluded. Everything outside DWE/Network/VOIP stays in Helpdesk. Approval and
clarification waits are indefinite, with daily 10:00 AM Tehran reminders. Both
active and expired same-owner/same-team keys trigger On
Hold and clarification. If the contacted human says another key is unnecessary,
resolve with the explanation after required notifications, without key creation.
No reminder-time question remains pending. Continue live contract discovery and
ask remaining operator policy questions one at a time when needed.
