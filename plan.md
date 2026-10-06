# Internal ICT agents implementation plan

## Objective

Build `agentic-service` as a shared platform for internal ICT automation, starting
with two jobs:

1. Correct the support group for requests currently in the Helpdesk group when
   their subject/description belongs to Network, DWE, or VOIP, regardless of
   template or whether they arrived by email or the ServiceDesk UI.
   Automatically correct only tickets with no technician: ServiceDesk clears
   the technician on a group change. Preserve assigned tickets without writes.
   Never select, assign, clear, or change a technician.
2. Fulfill only eight Mirza jobs after the appropriate ticket approval: create an API
   key; increase API-key reasoning; increase team reasoning; add model access for
   a team; add a person to a non-Tool team for model access; increase a person's
   budget; increase an API-key budget; or increase a team budget.

Mirza intake accepts `Mirza Access Request` and `Mirza API Key` templates. Other
templates start a workflow only when the request is currently in Helpdesk.
Dedicated templates use existing required approvals. Other Helpdesk templates
have no Mirza approval steps: move a supported request to DWE, set On Hold, and
notify the DWE person in charge, dynamically resolved from `incharge_group`,
through Mattermost with the ticket link. Continue
the tracked workflow in DWE and fulfill only after that authorized person changes
it from On Hold to Open. This handoff may clear an existing technician assignment;
never select or assign a technician and never change the template. Untracked
other-template tickets outside Helpdesk remain ineligible for Mirza execution.

During Mirza processing, unspecified or unclear details put the ticket On Hold.
Ask its assigned technician, or DWE's in-charge person if no technician is assigned.
That person supplies the requested details in a ticket note and sets it Open.
Read and validate the note before resuming; keep clarification and authorization
as separate checks and never invent a missing budget or other execution value.

New API keys are delivered directly to the named key owner's Mattermost DM by the
bot. Every completed Mirza ticket also sends a completion description to its
assigned technician, or the original DWE in-charge person when no technician is
assigned. Include the ticket link and verified work without disclosing the key
in staff summaries. Set Resolved after verified fulfillment and delivered required
notifications. Delivery implementation and installed status contracts are pending.

API-key model access comes from its existing Tool team's model grants. There is
no job to grant models directly to a key, change its model-access list, move it to
another team, or attach it to a non-Tool team. Key creation uses the selected Tool
team's existing grants; it does not expand them. Adding models to a team requires
the separate approved team-model job and must not be inferred from a key request.

For ordinary requests already outside Helpdesk, a template A/template B mismatch
is a no-op, including mismatches across specialized support groups. Do not change
their template, support group, technician, status, or post a correction reply.
Unsupported Mirza matters are also no-ops. Only local observation/audit is allowed
for ignored cases. Templates cannot be changed; never expose a template-write tool.

The LLM interprets requests and drafts replies. Application policies authorize
actions. Narrowly scoped connectors execute and verify them.

This document plans implementation; it does not authorize production grants,
ticket changes, deployment, commits, or pushes.

## Architecture

```text
Helpdesk webhook / polling reconciliation
                  |
             FastAPI intake
                  |
          Temporal workflow owner
             /             \
   Group corrector      Mirza job fulfiller
             \             /
          Deterministic policy checks
                  |
       Approval / clarification if needed
                  |
          Controlled connector actions
             /       |       \
        Helpdesk     AD     Mirza administration
                  |
       Verification, audit, reply, resolution
```

- Python, FastAPI, Pydantic, and HTTP clients for the service and contracts.
- Temporal with Python workers for durable execution, retries, timers, and waits.
  LLM calls and external I/O run in activities, outside deterministic workflow
  code. Completed model decisions are recorded and reused on replay.
- PostgreSQL for versioned policies, approval records, action identities, audit
  records, and operator-facing workflow projections. Temporal owns workflow
  execution state; projections do not independently drive transitions.
- Mirza/LiteLLM for inference using a dedicated, budgeted service key with only
  the required model access. Inference credentials have no administration rights.
- A separate Mirza administration connector for privileged operations. Where
  needed, expose a narrow internal API in `jam-ai-service` that reuses its existing
  grant semantics rather than duplicating them here.
- Existing n8n workflows may forward events or deliver notifications. Each
  business workflow has one execution owner in `agentic-service`.
- Start with typed model calls and explicit workflows. Add an agent framework
  only if later jobs need bounded, dynamic tool planning.

Temporal documentation: [durable AI workflows](https://docs.temporal.io/ai) and
[activity idempotency](https://docs.temporal.io/activity-definition).

Onboarding, offboarding and internal-transfer process tickets, including their
associated children, are excluded from both workflows. Preserve their process
assignments and relationships. Use authoritative process context and revalidate
before writes; unresolved association means local review without external writes.
The [service catalog](docs/service-ownership.md) records confirmed DWE services
and content-based Network/VOIP ownership; everything else stays in Helpdesk.

## Step 1 — Discover integrations and agree on policies

Status: policy baseline and planning handoff ready on 2026-10-06; Steps 2–3 implemented locally.
Repository discovery is documented. The operator confirmed
ServiceDesk Plus 15.1 Build 15100, no staging environment, Helpdesk-group intake
regardless of template/source, ordinary technician preservation, the Mirza DWE
handoff exception, and two approval paths for Mirza fulfillment. Installed API
contracts and remaining execution details still need verification. See
[integration findings](docs/step-1-discovery.md),
[decision register](docs/step-1-decisions.md), and
[synthetic review cases](tests/fixtures/step_1/discovery_tickets.json).
The synthetic cases contain proposed labels and do not replace the restricted
historical evaluation set or constitute approved access policies.

The open technical checklist below is retained rather than marked verified.
It does not block the local scaffold. Carry live contract work into Steps 3–4,
approval/execution verification into Steps 7–8, and historical evaluation into
Step 10. These remain gates for affected production actions; the original full
integration exit condition has not yet been met.

- [x] Confirm the helpdesk product and installed version: ServiceDesk Plus 15.1
      Build 15100; no staging environment is available.
- [ ] Verify API authentication, rate limits, and capabilities for requests,
      support-group updates, approvals, replies, and status transitions. Read
      existing technician assignments only for preservation and conflict checks.
- [x] Inspect the existing ServiceDesk integrations in `n8n-flows`; use them as
      integration references, without assuming the exact helpdesk product.
- [ ] Confirm webhook availability; define a polling fallback and reconciliation
      cursor that cannot miss updates with equal timestamps.
- [ ] Collect the ICT service ownership catalog, template/category metadata,
      and live support-group IDs. Technician rosters, skills, workload, and on-call lookup
      are not dependencies for the new service.
- [x] Record DWE platform/system-administration ownership and content-based
      Network/VOIP ownership in the service catalog. Everything else stays in Helpdesk.
- [x] Exclude onboarding, offboarding and internal-transfer process tickets and
      their children before either workflow; preserve their assignments/relationships.
- [ ] Verify live process/template identifiers and parent/child metadata for this
      exclusion, including uncertain association and standalone requests.
- [x] Confirm dispatcher team scope: Helpdesk, Network, DWE, and VOIP. Teams
      referenced by older exports are discovery evidence, not additional targets.
- [x] Define intake by current Helpdesk group, covering email and UI requests
      regardless of template. This replaces the earlier template/unassigned-only
      intake restriction for listening. Automatic group correction remains
      limited to unassigned tickets because a group change clears the technician.
- [x] Restrict corrections to the support-group field. Never assign, clear, or
      change technicians for ordinary dispatch; templates are never written.
- [x] Confirm server behavior: changing a support group clears the technician.
      Skip group writes for assigned tickets to preserve human assignments;
      verify null stays null and concurrency protection before activation.
- [x] Leave ordinary specialized ICT template mismatches outside Helpdesk alone
      except supported Mirza jobs submitted through an eligible Mirza intake path.
      Unsupported or ineligible Mirza requests are no-ops.
- [x] Define dedicated-template Mirza authorization: fulfill after existing
      required approvals are complete; no extra sign-off or self-approval.
- [x] Define other-Helpdesk-template approval: supported Mirza requests move to
      DWE/On Hold; notify its person in charge through Mattermost with the ticket
      link. That person's subsequent Open transition authorizes the job.
- [x] Permit this Mirza handoff to move assigned tickets and allow ServiceDesk
      to clear the technician. This exception never authorizes assigning people.
- [x] Resolve the DWE person in charge dynamically from the DWE ServiceDesk
      support group's `incharge_group` field; each support group has this field.
      Do not configure a fixed person's email.
- [x] Keep each handoff's originally resolved in-charge person for that request
      even if the group field changes; new requests resolve the current value.
- [ ] Verify the field's API exposure, value format and DWE lookup;
      resolve its value to ServiceDesk/Mattermost identities. Verify status/history/
      actor APIs and live status IDs. Missing/ambiguous values cannot authorize grants.
- [x] Define Mirza intake: the two dedicated templates, plus other templates only
      for new workflows currently in Helpdesk. Continue persisted DWE handoffs
      after the group move. Interpret subject/description content.
- [x] Confirm dedicated template names: `Mirza Access Request` and `Mirza API Key`.
      Live template IDs and structured fields remain to be inspected; template
      choice alone does not authorize a grant.
- [x] Define person as email for LibreChat UI access and personal budget; a person
      can belong to many non-Tool teams, each granting its UI models.
- [x] Define an API key as owned by a person email and associated with exactly one
      Tool team. Person membership/model grants do not substitute for key scope.
- [x] If the new-key owner already has a key in the mapped Tool team, put On Hold
      and ask the technician/original DWE in-charge using the note/Open flow.
- [x] Count expired keys too when checking existing owner/Tool-team keys.
- [x] When the contacted technician/in-charge confirms another key is unnecessary
      in the clarification note/Open response, create no key, send the explanation
      through required completion notifications, and resolve the ticket.
- [x] Wait indefinitely for approval/clarification, with Mattermost reminders every
      morning at 10:00 AM in `Asia/Tehran`, including weekends. Stop when the gate
      is satisfied or the request ends; waiting age alone never authorizes action.
- [x] Confirm credential sources for read-only discovery: LiteLLM master keys in
      `jam-ai-service` and the technician key in `n8n-flows` nodes. Load privately;
      source discovery does not verify live permissions or API contracts.
- [x] Require an explicit department-to-Tool-team map for new API-key selection.
- [x] Inspect live LiteLLM non-Tool/Tool teams through SSH to `mirza-ha1` and create
      a [reviewable map](docs/department-tool-team-map.md) with observed team IDs:
      72 catalog departments, now 30 operator-verified mappings and 42 unspecified.
- [x] Obtain operator verification of all proposed department mappings.
- [ ] Verify department values against live AD. Missing/ambiguous mappings or conflicts with
      approved terms require clarification. Existing keys retain their teams.
- [x] Confirm Tech & Product - Cloud maps to Cloud-Tool, and all Tapsi Box
      departments map to TapsiBox-Tool. TapsiBox-Manager-Tool access is manual.
- [x] Complete the explicitly requested live TapsiCloud-Tool-to-Cloud-Tool merge:
      one key/member moved, empty source removed, owner/key limits/UI memberships
      and destination policies verified. This does not enable agent key moves.
- [x] Define on-the-fly mapping through technician/original DWE in-charge notes;
      create an absent Tool team as an approved supporting key-creation step.
- [x] Apply on-the-fly mapping only to the current ticket; retain evidence in
      workflow/audit without changing the shared department map.
- [ ] Verify initial team-creation terms/API and retry correlation.
- [x] Confirm user notifications through a Mattermost bot using a template.
- [x] Approve DWE review message wording with ticket ID/link and instructions to
      change On Hold to Open; exact text is in the decision register.
- [x] Send the review notification to the originally resolved DWE in-charge
      person's Mattermost DM through the bot.
- [x] Define clarification for missing/unclear Mirza details: On Hold, ask assigned
      technician or in-charge if null, then read their ticket note and Open transition.
      Missing budget uses this flow rather than an invented default.
- [x] Use DWE's in-charge person for clarification when no technician is assigned;
      reuse the request's original DWE identity or resolve it once when first needed.
- [x] Approve the clarification message with ticket ID/link, missing details,
      ticket-note response, and On Hold-to-Open instructions; exact text is in
      the decision register.
- [ ] Verify note author/history APIs and resume event correlation.
- [x] Deliver new API keys directly to the intended user's Mattermost DM;
      an authenticated retrieval page is not required.
- [x] Send key DMs to the named key owner, including tickets submitted by another
      requester; verify the recipient account from the approved owner email.
- [x] Notify the current assigned technician of every completed Mirza ticket,
      falling back to the request's original DWE in-charge person when null.
      Include the completed ticket description/link and verified work summary.
- [x] Approve the staff completion DM wording with ticket ID/link, description
      and verified work summary; exact text is in the decision register.
- [x] Set successful Mirza tickets to Resolved after verified fulfillment and
      required notification delivery; verify the live status ID/required fields.
- [ ] Implement user-result/key-delivery rendering and verify recipient lookup,
      bot DM API and delivery reconciliation.
- [ ] Define execution contracts for the eight Mirza jobs, model aliases, reasoning
      ceilings, budget targets/amounts, approved defaults, duration, and requests
      made on behalf of someone else. Read approved terms/defaults without inventing
      budgets, duration, or additional approval requirements.
- [ ] Verify identity/delegation, operator authentication, privileged direct-DM
      key delivery and production read-only API contracts; channel is confirmed.
- [ ] Collect a restricted, representative ticket evaluation set covering Persian,
      English, conflicting templates, ambiguous subjects, and access requests.
      The operator will provide examples. Resolve remaining operator questions
      one at a time. Both approval paths and the handoff exception are answered;
      dynamic ServiceDesk in-charge resolution and per-request identity retention
      and approval message wording/DM delivery are confirmed. Missing/unclear
      details use human clarification with DWE fallback and the approved message;
      direct key DM and staff completion notifications are confirmed. DWE, Network
      and VOIP ownership and lifecycle process exclusions are confirmed. Indefinite
      waits and daily 10:00 AM Tehran reminders are confirmed. A new-key request whose
      owner already has a key in the mapped Tool team uses On Hold and clarification;
      named-owner key delivery,
      department-map verification, ticket-specific scope, completion wording and
      final Resolved status are confirmed.

Completed supporting work:

- [x] Inspect the existing ticket assignment and on-call integration in `n8n`.
- [x] Record seed ICT groups/templates and distinguish observed names from
      approved support-group correction scope. Older technician assignment logic
      remains historical evidence only.
- [x] Document a polling/reconciliation design that handles timestamp ties,
      partial scans, and changing offset-paginated results; installed API support
      remains to be verified.
- [x] Document existing Mirza grant, identity, cache, and permission-scope behavior.
- [x] Draft routing/access examples and record the decisions required to approve
      them without inventing budgets, durations, approvers, or live capabilities.
- [x] Create synthetic evaluation examples without live tickets or employee data.

**Exit condition:** Documented integration capabilities and approved routing and
access policy examples. Missing policy decisions block affected production writes,
not development with fixtures or read-only evaluation.

Validation uses local fixtures/mocks and production read-only observation. There
is no staging prerequisite. Exercise writes on scoped production tickets when
the relevant workflow is explicitly activated, without creating synthetic
production requests or test grants as part of read-only discovery.

## Step 2 — Scaffold the service and local runtime

Status: completed and locally verified on 2026-10-06. See
[runtime verification](docs/step-2-runtime.md), [startup guide](README.md), and
[runtime operations](docs/runtime-operations.md). Both modes default to observe;
only synthetic probes are registered, with no production write connectors.

- [x] Create the Python project, dependency pins, Dockerfile, Compose development
      stack, `.env.example`, README, and repository instructions.
- [x] Separate the API, dispatch worker, and access worker so credentials and
      permitted actions can differ. Start from one application image.
- [x] Add PostgreSQL migrations and separate application and Temporal database
      configuration. Do not write directly to Mirza's database tables.
- [x] Add health/readiness checks, structured logging, correlation IDs, and
      operation modes: observe, review, and automatic, independently per workflow.
      Modes are configured/reported; unimplemented write capabilities stay absent.
- [x] Document backup/restore, migrations, local startup, and worker deployment.
- [x] Verify healthy local API, workers, PostgreSQL and Temporal; recover a waiting
      synthetic workflow after restarting each worker, with idempotent audit phases.
- [x] Cap the steady local runtime at 1.25 GiB RAM/1.75 CPUs, monitor usage, and
      stop the project's containers after checks while preserving the data volume.

Suggested structure:

```text
app/
  api/             intake, authenticated approvals, operator endpoints
  contracts/       tickets, decisions, access requests, action results
  workflows/       group correction, supported Mirza jobs, owned expiry if approved
  activities/      inference, policy evaluation, connector calls
  connectors/      helpdesk, directory, Mirza inference and administration
  policies/        routing, eligibility, approval, closure rules
  storage/         models, migrations, action registry, audit, projections
tests/
  fixtures/
  unit/
  integration/
docs/
```

**Exit condition:** Local API, workers, Temporal, and PostgreSQL start successfully;
a fixture workflow survives a worker restart.

## Step 3 — Establish contracts and reliable execution

Status: completed locally on 2026-10-06. [Implementation and verification](docs/step-3-execution.md)
cover authenticated normalized input, deterministic policy gates, durable ticket
actors, audit/action receipts and reminder intents. The execution connector is
explicitly synthetic. Installed API verification, authoritative normalization of
live reads and actual status/grant/notification delivery remain Steps 4 and 6–9.
This completion does not authorize or claim production fulfillment.

- [x] Normalize helpdesk events into ticket IDs, revision/event IDs, authenticated
      requester IDs, intended recipients, content, template/category IDs, current
      assignment, authoritative process context, parent/child references, and source
      timestamps. Keep unknown process association distinct from a verified
      standalone ticket; related-ticket metadata is read-only.
- [x] Define typed group decisions and Mirza requests. Decisions include no-op,
      correct support group, supported Mirza job, or wait for approval/terms.
      Enforce the eight-operation allowlist and Mirza intake eligibility
      independently of the LLM. Outputs use
      validated catalog IDs; unknown teams, people, models, or grant types cannot
      become executable actions.
- [x] Define explicit states such as received, evaluating, awaiting clarification,
      awaiting approval, executing, verifying, completed, rejected, manual review,
      and cancelled. Ticket status is mapped separately.
- [x] Persist each clarification cycle's hold reason, workflow position, requested
      fields, selected contact, baseline source revision/sequence, note/status
      response event IDs, and response evidence.
      Both clarification and approval map to On Hold without conflating their gates.
- [x] Deduplicate deliveries and serialize workflows for the same ticket. Preserve
      new ticket revisions and meaningful changed requests.
- [x] Give every logical write a stable operation ID and durable action record.
      Check downstream state after uncertain results; do not blindly retry key
      generation or other writes without a proven recovery strategy.
- [x] Add bounded connector retries, timeout handling, the agreed human-wait policy,
      cancellation, and revalidation when identity, policy, requested scope, or
      ticket state changes. Approval/clarification waits have no age deadline.
- [x] Persist a daily 10:00 `Asia/Tehran` reminder schedule for eligible workflows
      awaiting approval/clarification. Deduplicate by ticket, recipient and local
      calendar date, correlate the active waiting cycle, and skip missed dates
      after recovery. Connector retries do not reset or expire the human wait.
- [x] Record policy version, model/prompt version, evidence, decision, approval,
      action, and verification result under one correlation ID.
- [x] Authenticate intake and operator requests. Treat ticket content and retrieved
      documents as untrusted input, never as authority to override tool policies.

**Exit condition:** Duplicate events, worker crashes, stale approvals, and changed
tickets cannot produce unauthorized or duplicate actions in integration tests.

Local exit verified: 43 unit checks; both worker restart/history replay checks;
duplicate/conflicting delivery IDs; stale approval actor/terms/source revisions;
clarification note/Open correlation; cancellation; Tehran reminder deduplication
and delayed-date suppression; one effect after simulated lost response; no write
with pending newer input or an uncertain result without a receipt; history rollover
after 102 revisions; existing runtime probes; and no Alembic schema drift.
These synthetic checks do not prove production connector idempotency or live
ServiceDesk approval/history semantics. Preserve those gates in later steps.

## Step 4 — Implement read-only connectors

Status: in progress on 2026-10-06. The read-only foundation, operator context
endpoint and local connector tests are implemented; installed Mirza and basic
ServiceDesk normalization pass. [Implementation and remaining verification](docs/step-4-read-connectors.md)
record the ServiceDesk approval-term/history-order/process gates, verified AD
identity/absence/auth-denial reads and verified Mattermost bot/DWE lookup. No external
writes or production activation are implemented. The complete-context exit
condition remains open; do not advance to Step 5 as a completed Step 4 handoff.

The operator's lifecycle examples now verify onboarding's packed child-ID field,
the reciprocal call-center/onboarding root bridge, and reverse child lookup.
Installed lifecycle root IDs identify exclusions; internal transfer has no
children. Offboarding's existing n8n nodes read relationships from PostgreSQL's
`public.offboarding_process`, rather than native ServiceDesk links. The exports
contain the query and a credential reference, without connection details or
saved results. Read-only inspection on SSH host `n8n` verifies the installed
`n8mdb` table and all three supplied offboarding children. An optional SELECT-only
reader now normalizes parent/child IDs and cross-checks parent templates against
ServiceDesk. Its runtime connection remains unconfigured; no database credential
was exported. Complete standalone membership checks remain unresolved.
The installed table has eight child-ID columns; the reader now also includes
Foundation, VOIP, Platform and Data Infrastructure relationships. The refactored
export creates children before persisting their IDs, so an absent mapping cannot
prove that a newly observed ticket is standalone. Read-only inspection of n8n's
SQLite store now observes this ordering in three active published workflow graphs,
covering 12 recognized child-creation nodes using one creation credential. No
credential was used or exported. Failed-persistence recovery and complete producer
coverage remain unverified, so unmatched tickets still cannot be processed.
The older `n8n` repository also reveals `public.onboarding_process`: installed
ID-only SELECTs match both supplied parents and all eight onboarding children.
An optional SELECT-only index now provides direct child lookup before the packed
ServiceDesk field is refreshed, preserving the existing legacy/bridge fallbacks.
Its runtime connection is unconfigured; unused `hr_id` semantics remain unresolved.

The supplied Mattermost token verifies the active `servicedesk_agent` bot and
resolves the dynamic DWE in-charge by exact email. A sampled requester has no
Mattermost account and remains ineligible for delivery; no fallback recipient is
chosen. The token remains in memory and runtime secret configuration is pending.
The operator applied the Mirza packaging, eligibility and LDAP empty-search
corrections; installed unique/eligible, absent-user and auth-denial reads pass.
The sampled real AD department resolves to an existing approved Tool destination.
Current Mirza reads also verify all 30 approved map destinations exist as Tool
teams; this does not prove coverage of every real AD department. Mirza changes
remain operator-applied; do not deploy Mirza from this task.

The context reader separately rechecks notes, history, approvals (including a
digest of template configuration) and relationships, rejecting changed observations
even when the ticket revision remains unchanged. All 188 local unit checks pass.
A new installed authority probe normalizes samples from both Mirza templates;
the initial samples were pending/missing stages. A bounded metadata scan then
finds approved examples in both templates, verifying required/current stages,
acting-user IDs and action times. History order/current-term binding remain
unverified. Native ticket creation actors/times are exposed for observation.
The operator confirms onboarding/offboarding children are n8n-created through a
dedicated ServiceDesk technician account. An optional, API-only creator-ID guard
now flags missing mappings as incomplete without treating creators as proof of
process membership or other creators as standalone. Runtime IDs remain unset.
The operator confirms that edits do not reset approvals and is unsure about
manual restart of the existing steps. Approval reads now carry observed ticket
content/revision digests; the context rejects mismatched observations without
claiming that those digests describe what the approver approved. Current-term
approval binding and the installed renewal mechanism remain unverified.
The extended read-only probe passes on approved examples from both templates,
verifying stable ticket/approval observations and matching observed digests.
These are observation checks, not authorization of edited execution terms.

- [ ] Read helpdesk tickets, revisions, support groups, templates, existing approvals,
      status transitions with actor identity and ordering for the DWE handoff,
      ticket notes with author identity and ordering for clarification,
      assignments, lifecycle process/template metadata and parent/child relationships,
      and relevant service metadata with complete pagination.
- [x] Resolve requester and recipient identity through the authoritative directory;
      verify one exact email match, enabled/unexpired account status and department
      rather than trusting a typed email. The operator confirms that no additional
      employee attribute or AD group is required. Installed positive/absent/auth-denial
      checks pass; disabled, expired and ambiguous cases have deterministic fixtures.
- [x] Read Mirza users, teams, virtual-key metadata, served models, budgets, and
      effective reasoning grants. Never return raw keys to the LLM.
- [x] Reuse or extend Mirza's AD department lookup where suitable; department lookup
      alone is not proof of employee eligibility or authenticated identity.
- [x] Resolve new-key owners through the versioned department-to-Tool-team map
      and verify the mapped team exists and is a Tool team. Stop on missing,
      ambiguous, invalid, or conflicting terms. Read existing keys' current team
      directly for key updates; mapping does not change UI memberships.
- [ ] For missing mapping/destination, gather an explicit on-the-fly mapping
      through the established human clarification flow; read enough catalog
      data to distinguish absent teams from an unavailable lookup.
- [x] Distinguish unavailable data from an empty result and fail closed for new
      permission grants when identity, approval, or policy cannot be verified.
- [ ] Build connector fixtures/local contract tests, then inspect installed API
      responses through production read-only access with secret-safe handling.

Completed local slices include paged candidate ServiceDesk reads and assignment/
note digests, the AD identity bridge and account checks, Mattermost lookup fixtures,
versioned Tool-team resolution and ticket-scoped mapping helpers.
Complete ServiceDesk authority/process evidence and runtime source configuration
remain required before the broader checklist items can be marked complete. Negative source spend and
nonstandard owner IDs are preserved for reads without relaxing execution contracts.

**Exit condition:** A ticket produces a complete, traceable context snapshot with
no external writes and no secrets in logs or inference inputs.

## Step 5 — Build ticket listening and classification in observation mode

- [ ] Exclude verified onboarding/offboarding/internal-transfer process tickets
      and associated children before routing or Mirza intake. Unknown process
      association is local review without writes; incidental keywords or any
      parent link alone are insufficient. Preserve process assignments/relationships.
- [ ] Evaluate Mirza intake: a dedicated `Mirza Access Request`/`Mirza API Key`
      template qualifies; another template qualifies only in the current Helpdesk
      group for enrollment. Persisted DWE handoff workflows remain eligible after
      leaving Helpdesk; do not adopt untracked other-template DWE tickets.
- [ ] Inspect content for the eight supported operations on eligible intake.
      Dedicated templates help extraction but are not approval proof.
- [ ] If a Mirza matter is ineligible or outside the eight jobs, emit no-op.
      Do not introduce general Mirza assistance or route it as an executable job.
- [ ] For non-Mirza requests, classify support-group corrections only when the
      current live support-group ID is Helpdesk; template and source do not filter
      intake. Include email-created requests and ServiceDesk UI requests alike.
- [ ] Ordinary template mismatches outside Helpdesk emit no-op even when the
      subject would fit another template/group. Templates cannot be changed.
- [ ] For Helpdesk-group intake, resolve ownership to Helpdesk, Network, DWE,
      or VOIP. Propose correction only when the current group differs. No-op when
      already correct. Anything outside DWE/Network/VOIP stays in Helpdesk;
      ambiguous ownership never permits a guessed destination or ticket write.
- [ ] Preserve the exact technician value, including an existing human assignment.
      Listen to assigned Helpdesk tickets, but emit no group write when a
      technician is set: the operator confirms group changes clear technicians.
      This restriction does not block an approved supported Mirza job that
      preserves the ticket's group and technician. The supported Mirza approval
      handoff is a separate path with explicitly allowed technician clearing.
- [ ] Record the proposed group/job or no-op reason locally. Evaluate Persian and
      English interpretation, correct no-ops, approved Mirza job extraction,
      support-group accuracy, latency, and cost against reviewed examples.

**Exit condition:** Observation correctly separates group correction, the eight
Mirza jobs, and no-ops; ordinary specialized-template mismatches outside Helpdesk
have no proposed writes.

## Step 6 — Enable support-group correction only

- [ ] Implement a group-only update tool with a verified destination ID. Its
      payload must exclude technician, template, category, status, and reply fields.
- [ ] Re-fetch group, content, technician, revision and process association before
      writing. Excluded or unresolved lifecycle context prevents writes. Skip if
      the current group is no longer Helpdesk, the technician is non-null, or a
      concurrent edit conflicts.
- [ ] Verify the operator-confirmed clearing behavior on the installed contract:
      null must remain null for eligible tickets, without automatic assignment.
      Never change the group of an assigned ticket or restore its technician
      through a compensating technician write.
- [ ] Verify revision/precondition support protects a human assignment made
      between read and update. A re-fetch alone is not atomic protection; keep
      automatic writes inactive where that preservation cannot be guaranteed.
- [ ] Read back the support group and confirm the technician field is unchanged.
      Record a local audit result; do not post correction notes or resolve tickets.
- [ ] Keep template repair, technician assignment, linked-ticket creation, and
      ordinary template-mismatch correction outside Helpdesk out of the tool surface.

**Exit condition:** Eligible Helpdesk-group tickets reach the correct support
group without technician/template/status/reply changes, including repeat delivery
and concurrent-edit scenarios.

## Step 7 — Build the Mirza access policy and approval workflow

- [ ] Enforce the lifecycle-process exclusion before enrollment and before every
      ticket, notification or Mirza write, including dedicated-template requests.
- [ ] Accept only `create_api_key`, `increase_api_key_reasoning`,
      `increase_team_reasoning`, `grant_team_model_access`,
      `add_person_to_non_tool_team`, `increase_person_budget`,
      `increase_api_key_budget`, and `increase_team_budget`.
      Reject executable plans containing any other requested operation.
- [ ] Resolve a person from their authoritative email; resolve user-team membership
      to a non-Tool team for UI model access. Do not write a personal model list.
- [ ] Resolve key owner email and exactly one Tool-team ID; keep that key's scope
      separate from the owner's personal budget and non-Tool team memberships.
- [ ] Emit no-op for direct key-model grants and key reassignment requests. Do not
      reinterpret them as a team-wide model grant or non-Tool user-membership job.
- [ ] Resolve team reasoning/model/budget requests to the explicitly approved
      LiteLLM team and its Tool/non-Tool kind; never infer it from an ICT group.
- [ ] Define access packages specifying target scope, team memberships, models,
      reasoning ceilings, budget/default, duration/default, recipient identity,
      and evidence from the applicable dedicated-template or DWE approval path.
- [ ] Extract a typed proposal; whenever a required detail is missing/unclear
      during processing, pause writes, set On Hold, and ask the current assigned
      technician or the original DWE in-charge person if null. Resolve and persist
      DWE's identity when first needed if absent. Preserve group/template/technician.
      Request a ticket note with the details followed by Open; do not infer defaults.
- [ ] Read the contacted person's note and Open transition, validate the supplied
      values, and resume from the persisted workflow position. Open alone or a
      Mattermost answer alone cannot resolve clarification. Re-hold and ask again
      if the response remains unclear. Verify current approval for resulting terms;
      clarification does not replace approval, and changed terms require renewed review.
- [ ] For dedicated templates, read approval state/history and required stages
      from ServiceDesk Plus. Fulfill after its required approvals are complete;
      pending, rejected, missing, or unavailable evidence cannot authorize a grant.
      An LLM recommendation or free-text approval claim is not approval evidence.
      Edits retain old approvals: verify approval of resulting terms, and pause
      materially changed requests pending renewed review. Do not invent an approval
      reset API or a substitute approver while the renewal mechanism is unverified.
- [ ] For other Helpdesk templates, persist the supported request's terms and
      handoff identity, then move the ticket to DWE and set On Hold. The group
      move may clear its technician, including an existing human assignment;
      omit technician/template fields and verify the resulting group/status.
- [ ] Read `incharge_group` from the DWE support group in ServiceDesk and resolve the DWE
      notification recipient and approval identity. Record source revision/read
      time and resolved identity at handoff. Preserve that original person for
      notifications and approvals on this request even if the field changes.
      Resolve the current field for new requests; never hardcode a global email.
- [ ] Notify the originally resolved DWE person in charge in their Mattermost DM
      through the bot using
      a review template containing the ticket link. Persist notification delivery
      and retry without repeating the handoff or re-holding an approved ticket.
- [ ] Continue tracked workflows in DWE and verify an On Hold-to-Open transition
      by that authorized person after the handoff, with unchanged recipient and
      terms. Initial Open, other actors, agent writes, and Mattermost replies are
      not approval. Missing/unverifiable history waits without granting access.
- [ ] Never let the agent approve its own work. Match both paths' approval to the
      recipient and scope/terms; material changes require renewed review through
      the applicable path. Untracked other-template tickets outside Helpdesk
      remain no-ops. This handoff is limited to the eight supported Mirza jobs.
- [ ] While an approval/clarification gate remains unresolved, wait indefinitely
      and send a Mattermost reminder at 10:00 AM Tehran time every calendar day.
      Use the original DWE approver for fallback approval, the selected contact
      for clarification, and authoritative pending approvers for dedicated
      approval stages. Render the correct native-approval or note/Open action.
      Combine actions for the same ticket/recipient/day, revalidate response and
      process context before sending, and stop when the gate is satisfied or
      the request ends. Reminders never change ticket state or run a Mirza job.
- [ ] Check existing permissions and calculate the smallest required change.
      Per-person requests must not silently broaden a shared team's grants.
- [ ] Before new key creation, reconcile any key already created by this operation,
      then inspect complete owner/key metadata for the selected Tool team. If an
      existing owner/team key is found, put On Hold and ask the current technician
      or original DWE in-charge whether an additional key is needed. Require the
      established note/Open clarification and applicable approval. Do not rotate,
      revoke, move, or disclose an existing secret. Keys in other teams do not
      trigger this check; incomplete lookup does not establish absence. Expired keys
      in the selected team count too. Replay of this operation resumes verification or
      delivery of its original generated key without another hold or generation.
- [ ] Handle a verified note/Open decision that an additional key is unnecessary
      as completion without key creation. Persist the decision and explanation;
      notify the intended user and current technician/original DWE in-charge,
      then set Resolved. Preserve all existing keys, including expired ones.
      Do not infer refusal from duplicate presence or Open alone. Retry messages
      and resolution independently without creating a key or asking again.
- [ ] Store approvals and produce dry-run plans containing proposed operations and
      expected effective access, without issuing keys or granting permissions.

**Exit condition:** Reviewed policy examples produce the expected decisions,
including unauthorized approvals and attempts to change recipients or budgets.

## Step 8 — Implement Mirza provisioning and secure delivery

- [ ] Introduce narrow internal administration operations implementing the eight
      supported jobs, read-back, and effective-access checks. Supporting membership
      changes during key creation are owner/Tool membership only; non-Tool user
      membership is exclusively the separate approved LibreChat UI membership job.
      Reuse `jam-ai-service/scripts/reasoning_access.py` semantics.
- [ ] Preserve the existing scope rules: LibreChat model access comes from non-Tool
      team memberships, allowing many non-Tool teams for one email. Each API key
      belongs to its owner email and exactly one `*-Tool` team; API reasoning
      reads the key and that team, not the person's reasoning metadata.
- [ ] Preserve unrelated metadata during updates and coordinate concurrent writers.
      A read-back verifies the requested grant but is not itself concurrency control.
- [ ] Add a person email to the approved existing non-Tool team that grants the
      requested UI model. Preserve all other memberships and do not change that
      team's models. If it does not grant the model, request clarification rather
      than silently widening its grant. Direct person-model-list writes are excluded.
- [ ] Add model access only on the approved team, preserving existing model grants.
      Helpdesk support groups and Mirza entitlement teams are separate identifiers.
- [ ] Increase reasoning only on the approved API key or team, preserving higher
      effective grants. Direct person reasoning changes are outside the eight jobs.
- [ ] Implement separate personal/UI, API-key, and team budget increases so each
      operation updates only the approved row with its before/after value.
      Preserve spend, reset schedule, other limits, and existing larger budgets.
      Reconcile a retry against the absolute desired amount so a requested delta
      is not added twice. Do not reset spend or decrease budgets.
- [ ] Implement API-key creation/reuse with deterministic request correlation,
      owner email, authoritative department, exactly one mapped existing Tool
      team, budget and expiry policy, and recovery
      after a timeout with an unknown
      outcome. If safe reconciliation is impossible, stop for manual recovery.
- [ ] When the mapping is unspecified, use On Hold/note/Open to obtain it from
      the assigned technician or original DWE in-charge. Resolve an existing
      Tool team or create the explicitly specified absent team with approved
      initial grants, budget/reset and other necessary terms. Missing terms
      require clarification. Correlate team creation so retries cannot duplicate
      teams/keys; scope the supplied mapping to this ticket and record provenance.
      This supporting step does not add general team creation to the eight jobs.
- [ ] Keep TapsiBox-Manager-Tool provisioning/access upgrades manual; automatic
      department mapping always uses TapsiBox-Tool for all Tapsi Box departments.
- [ ] Verify creation uses that Tool team's existing model grants without setting
      or expanding key-level model access. Omit key-model grant/ACL writes from the
      tool surface. Missing team model access stops for clarification; do not widen
      grants, switch teams, or add non-Tool memberships as a workaround.
- [ ] Key reasoning and budget updates must preserve key model-access fields,
      team association, and owner. Team-model updates touch only the approved team's
      grants; any effect on its keys is inherited, not a key-level update.
- [ ] Keep raw credentials in the privileged boundary/encrypted storage and the
      authorized direct key-delivery DM. Pass only opaque references through LLM
      inputs, Temporal arguments/results, audit records, and operator projections.
- [ ] Implement templated Mattermost bot notifications using verified recipient
      identity and deduplicated delivery records. Send newly created keys directly
      to the named key owner's DM, including delegated requests. Resolve the
      secret reference only inside the
      privileged connector and sanitize its result so message bodies containing
      keys never enter logs or Temporal history. Retry delivery with the same key.
- [ ] Notify the current technician for every completed Mirza ticket; if null,
      reuse its original DWE in-charge person or resolve/persist DWE's identity
      once when needed. Send a separate DM with the ticket link, sanitized ticket
      description and verified work summary. Record the selected recipient and
      delivery progress; exclude raw keys and secrets from staff summaries.
      Failed notification must not create another key or repeat a grant.
- [ ] Verify stored grants and effective access before marking fulfillment complete.
      Cover the existing personal-budget/Tool-key interaction and cache propagation
      with local fixtures and read-only production evidence, then verify outcomes
      on approved pilot fulfillment; never bypass budget limits to make a test pass.
- [ ] Implement and verify all eight supported jobs; roll out one at a time.
      Unsupported operations remain no-ops even after successful approval.

**Exit condition:** Local end-to-end simulations pass; after explicit production
activation, an approved pilot ticket completes with the correct scope, effective
permission, authorized direct key DM, staff completion notification, and no
secrets in logs/histories or duplicate keys.

## Step 9 — Add lifecycle management and operator recovery

- [ ] Reply with the actual verified outcome, summarize access and expiry, and
      set Resolved after verified fulfillment and required notifications. Verify
      installed resolution fields and read back the final status. Retry status
      updates independently without repeating work or DMs. Assignment alone
      does not resolve a helpdesk incident.
- [ ] Track which entitlement changes each request owns. Implement expiry and
      revocation explicitly for grants without native expiry, preserving unrelated
      and independently approved access.
- [ ] Reconcile pending supported jobs, abandoned key delivery, external changes,
      and expiry explicitly included in an owned approved grant. Do not introduce
      general offboarding, department maintenance, or new request-driven revocation
      jobs. Expiry included in approved terms is lifecycle cleanup, not another ticket job.
- [ ] Define safe compensation for partial fulfillment. Do not undo permissions
      created by another workflow or operator.
- [ ] Provide an authenticated operator view for workflow state, evidence,
      approvals, failures, review, cancellation, and safe resumption.
- [ ] Add metrics and alerts for group corrections, protected no-ops, local review,
      approval age, failed verification, expiry failures, latency, and model spend.
- [ ] Establish retention and access controls for ticket text, model traces,
      approvals, and audit records; verify logs and histories remain secret-free.

**Exit condition:** Operators can diagnose and recover partial work, expiry removes
only intended access, and reconciliation reports verified outcomes.

## Step 10 — Validate and roll out gradually

- [ ] Run deterministic policy tests covering Persian/English interpretation,
      Helpdesk-group correction across email/UI and arbitrary templates, ordinary
      specialized-template no-ops outside Helpdesk, the eight Mirza operations,
      fallback-template eligibility, email identities, many non-Tool memberships,
      exactly one Tool team per key, unsupported-Mirza no-ops, scopes, approvals,
      budgets, metadata preservation, and entitlement ownership.
- [ ] Verify direct key-model grant, key-to-non-Tool attachment, key team moves,
      and using user UI membership to widen key access always produce no-op plans.
      Verify key creation cannot implicitly expand model grants.
- [ ] Run integration scenarios for pagination, duplicate events, concurrent
      group changes/grants/budget increases, worker restarts, uncertain API results,
      service outages, cancelled tickets, changed requests, and expiry across downtime.
- [ ] Evaluate malicious ticket instructions and secret handling. Confirm inference
      workers cannot invoke privileged operations outside authorized workflows.
- [ ] If Mirza enforcement, policy, or scripts change, run the applicable
      `jam-ai-service` checks, use local mock validation and production read-only
      inspection, then verify outcomes during approved pilot fulfillment.
- [ ] Agree measurable acceptance targets for support-group accuracy, no-op correctness,
      fulfillment success, latency, and cost. Duplicate keys, unauthorized grants,
      secret exposure, or destructive loss of unrelated access block release.
- [ ] Roll out in order: observation, reviewed group-correction plans, automatic
      correction on requests currently in Helpdesk regardless of template, and
      the eight Mirza jobs after their applicable approval. Never enable technician
      assignment or general
      specialized-template correction.
- [ ] Prepare rollback and kill-switch procedures. Pausing new writes must retain
      the audit trail and explicitly handle in-flight work and scheduled revocation.
- [ ] Complete configuration, local fixture/mock validation, and production
      read-only observation, then obtain explicit approval for deployment and
      activation of the scoped production workflows.

**Exit condition:** Both initial jobs satisfy agreed pilot targets, operators have
recovery procedures, and only approved categories/packages run automatically.

## Dependencies and completion criteria

Implement steps 1–4 before enabling either workflow. Dispatch continues through
steps 5–6; Mirza access continues through steps 7–8. Both require steps 9–10 before
production acceptance. Planning and fixture development can proceed while specific
integration or policy questions are unresolved.

The initial release is complete when:

- Eligible requests currently in Helpdesk reach the responsible support group
  regardless of template/source when unassigned. Ordinary corrections preserve
  technicians; the supported Mirza DWE handoff may clear them. Ordinary specialized
  template mismatches outside Helpdesk produce no writes.
- The eight supported approved Mirza jobs complete through verified provisioning
  or budget updates, secure key delivery when applicable, and a correct outcome.
- Unsupported Mirza matters, ordinary template mismatches outside Helpdesk,
  and excluded lifecycle process tickets/children are no-ops. Process relationships
  and intentional cross-team assignments remain intact.
- Required approvals, expiry, revocation, audit, and recovery work across restarts
  and partial external failures.
- An operator can pause either job independently and inspect every action.

Future ICT jobs extend the same workflow, policy, identity, and connector boundaries
after defining their own contracts and acceptance criteria.
