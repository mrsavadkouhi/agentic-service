# Step 4: read-only integration context

Status on 2026-10-06: connector foundation implemented and locally checked;
installed Mirza and basic ServiceDesk normalization verified. Step 4 remains in progress because
ServiceDesk approval-term/history-order/process contracts and complete process
membership remain pending. Installed directory identity, absence and credential
denial checks pass, including real department-to-Tool-team resolution. The Mattermost
bot identity and dynamic DWE recipient lookup are verified. The AD
eligibility policy is confirmed: unique email, enabled account, unexpired account.

## Implemented surface

`GET /v1/contexts/{ticket_id}` requires the operator credential, distinct from
the intake credential. It reads context without enrolling a workflow, signaling
Temporal, or writing to any external system. Optional `recipient_email` selects
the intended person for an on-behalf request; it is a lookup input, not delegation
or approval evidence. Optional `key_ref` accepts only a generated
`litellm-key-<sha256>` reference, never a raw key.

Each component returns a typed result, observation time, evidence digest,
contract provenance and completeness flag. Missing, ambiguous, unsupported,
unavailable, partial and concurrently changed reads have distinct outcomes.
Unavailability never means an empty inventory. `blockers` explains incomplete
context; `grant_context_verified` remains false for this entire implementation.

| Component | Read behavior | Remaining installed verification |
|---|---|---|
| ServiceDesk | Installed ticket/group/template/status/category readers, creation actors/times, note-detail digests/authors, native approval levels/items, structured history actors/status changes, lifecycle roots and children; optional onboarding/offboarding PostgreSQL indexes | Verified history sequence, approval-to-current-terms binding, note-edit correlation, runtime process-index connections and complete membership checks |
| Directory | Exact unique email, GUID, department and native boolean enabled/unexpired account eligibility through the Mirza adapter; installed positive/absent/auth-denial reads verified | Runtime read configuration; requester authentication/delegation belongs to later authorization |
| Mirza | Paged users/keys including expired Tool keys, complete team list, served model IDs, budget limit/spend/reset/duration, reasoning metadata | Concurrent catalog reconciliation and production read credential permissions |
| Mattermost | Verified active `servicedesk_agent` bot, dynamic DWE recipient by exact email; reject deleted accounts and bots, distinguish missing users | Runtime secret configuration and further intended-recipient checks; notification delivery is a later step |
| Mapping | Versioned operator-approved department map; all 30 approved destinations verified against the current live Tool-team catalog | Check real AD department values; authoritative ticket-note mapping evidence belongs to the clarification workflow |

ServiceDesk history observations preserve event ID, actor, time and structured
status differences. They do not turn timestamps or numeric IDs into a verified
source sequence. Prose-valued history field names are hashed, preserving only
machine field names and structured status changes. The authoritative transition method remains unsupported until
ordering is established. Approval observations preserve native required levels,
aggregation rules, approvers, acting users and deletion/current flags; template
configuration can be matched without claiming approval of the current terms.
Deleted or absent required levels cannot satisfy that match. The context cannot
authorize a grant or dispatch update while these authority contracts remain unknown.

The operator confirms that editing an approved Mirza request leaves its approvals
in place; whether a technician can restart them manually remains unverified.
Each approval read now includes the content/revision digests of the ticket it
observed. The context rejects an approval read correlated with a different ticket
snapshot, even when the initial and final ticket reads agree. Missing correlation
also blocks complete context. These hashes detect changing observations, not what
the approver saw; `terms_binding_verified` remains false. Materially changed terms
still require renewed review through the existing approval path. No approval reset,
restart, self-approval or alternate approval path is implemented.

### Lifecycle relationship observations

The supplied examples and existing n8n views establish separate sources:

- Lifecycle root exclusions use installed template IDs: onboarding `3601`,
  call-center onboarding `7501`, offboarding `2701`, internal transfer `6601`
  and call-center internal transfer `7802`. The operator confirms that internal
  transfer has no children.
- The operator confirms that onboarding/offboarding children are created by
  n8n, rather than manually created or linked by technicians. This identifies
  the producer; it does not make an empty process index proof of absence.
- Onboarding parents store pipe-separated `key:value` pairs in
  `udf_fields.udf_sline_4217`. Child IDs are `office_id`, `ex_id`, `helpdesk_id`
  and `viop_id`; the parser also accepts the existing view's `voip_id` alias.
  Duplicate/conflicting IDs, malformed fields and missing required IDs fail closed.
- Call-center onboarding points to its ordinary onboarding root through
  `udf_sline_6601`; the reverse reference is `udf_sline_10449`. Both roots must
  be onboarding templates and reference each other before the reader uses the
  other root's children. This explains the differing call-center link text/target.
- A bounded, projected onboarding-root scan identifies child tickets even when
  their own template is the default template. It checks each returned template,
  retains all matched parents and re-reads matched roots to detect changes.
- The older `n8n` repository contains onboarding's producers. The v2 callbacks
  write `public.onboarding_process` in the same installed `n8mdb` database.
  Read-only schema/ID inspection verifies `automation_id` plus `office_id`,
  `ex_id`, `helpdesk_id` and `voip_id`, all bigint columns. Both supplied parent
  records and all eight supplied child references match. The observed table has
  120 processes; 17 have no VOIP reference yet. There are no invalid/zero observed
  ticket references. `hr_id` is null in all observed rows and its relation
  semantics remain unverified; it is not silently treated as a ticket link.
- The optional onboarding index casts only confirmed ID columns to text in its
  fixed SELECT, retains optional/shared children, verifies parent templates and
  re-reads mappings. It can find children while the packed ServiceDesk field is
  still absent/stale. Roots without a database row retain the existing packed-field
  fallback, and call-center roots retain their reciprocal bridge. Conflicting
  onboarding/offboarding observations return `ambiguous` rather than choosing one.
- Offboarding's `Fetch Child Tickets` node reads `automation_id` and child
  columns `helpdesk_id`, `sysadmin_id`, `network_id`, `devflow_id` from
  `public.offboarding_process`. Its export contains a `Postgres account`
  credential reference, without connection values or saved results. Read-only
  inspection on SSH host `n8n` confirms the table in database `n8mdb` inside
  `n8n-postgres-1`. All three supplied children match their parent. The observed
  table contains 489 processes; its parent and nonempty child references are
  numeric. The supplied process has no sysadmin child. No database credential
  was extracted or exported.
- Further installed schema inspection verifies four additional child columns:
  `foundation_id`, `voip_id`, `platform_id` and `di_id`. They must be included in
  both the SELECT projection and reverse-lookup predicate. Observed nonempty
  counts are 214, 0, 216 and 470 respectively. All eight child columns and the
  parent column contain numeric nonempty references. The reader now includes
  every observed column, including historical Platform/VOIP relationships.
- The optional PostgreSQL reader uses a fixed, parameterized SELECT for one
  ticket's parent/child matches, limited to 101 rows to detect the 100-row bound.
  It uses fresh connections, read-only transactions and connection/statement
  timeouts, rejecting malformed references, duplicate parents and self-links.
  Shared children preserve all parents. The ServiceDesk reader checks each
  parent's offboarding template and re-reads the mapping to detect changes.
- The refactored offboarding export upserts a parent, creates child requests,
  collects their responses, then persists their IDs. A child can therefore exist
  before its mapping is visible; two empty lookup results do not establish
  standalone status. Read-only inspection of n8n's SQLite workflow store now
  confirms paths from child creation to later child-ID persistence in the active
  published definitions: three workflows contain 12 recognized HTTP creation
  nodes. All use one literal creation credential, which was compared in memory
  and never used, printed or saved. All 36 active workflows have a published
  definition; their observed graphs match their editable definitions. The graph
  inspection covers recognized HTTP request nodes, not hidden/custom producers
  or historical credentials. A complete exclusion contract must address
  this window and any failed persistence; no arbitrary waiting deadline is assumed.

Native `linked_to_request`, `has_linked_requests`, `has_dependency` and `lifecycle`
do not expose these business-process relationships in the examples. Arbitrary
links or keywords remain insufficient. A positive lifecycle observation blocks
intake explicitly. `coverage_verified` remains false: an offboarding root without
a configured mapping reader has unknown children, and no match in the two
sources cannot establish that a ticket is standalone. Complete absence semantics
and creation/update ordering remain unresolved. The runtime database connection
is still unconfigured, so default offboarding child reads remain incomplete.
These are exclusion observations, never permission to process a ticket.

Ticket content, structured UDF/resource terms and note text are represented by digests in this operator snapshot;
raw bodies are not logged or placed in workflow history. Future extraction must
use a separately bounded content path and retain its evidence correlation.
Native creation actor/time are now observed separately and included in revision
correlation. All eleven supplied children expose a creator and creation time,
with one shared creator in this sample. Creator identity alone is not process
membership. The operator has confirmed n8n-only child creation using a dedicated
ServiceDesk technician account. Neither sampled creators nor one credential in
active graphs establishes a
complete historical producer roster. Unmatched tickets therefore remain
incomplete, including children awaiting or missing mapping persistence.

An optional creator-ID guard returns `incomplete` with
`n8n_created_ticket_mapping_unconfirmed` for tickets created by a configured
dedicated producer when no parent mapping is found. Positive relationship
evidence retains precedence. Creator identity supplies a review blocker, never
positive process membership or permission to process other creators' tickets.
Unconfigured producers, other creators and missing creator metadata retain the
existing fail-closed absence behavior; no waiting deadline makes them eligible.

The reader fetches the ticket again after its dependent reads. A changed revision
invalidates that ticket result. It separately rechecks successful notes, history,
approvals and process relationships, rejecting changed or unavailable observations
even when the exposed ticket revision stays unchanged. Approval observations also
hash the template's configured stages, detecting changes independently of the
ticket or approval rows. That hash records observed configuration, not approved
execution terms. Changed history invalidates derived transitions. These reads
remain observations and do not enroll a workflow. Pagination rejects duplicate IDs, missing terminal
metadata, count mismatches and excessive page/response sizes. These safeguards
detect several changing-read cases; they do not make a cross-service transaction
or prove an atomic snapshot. Revalidation remains necessary before future writes.

## Mirza scope and secret handling

Key metadata keeps an opaque reference, owner ID, existing team, expiry, budget
and reasoning. Upstream key handles stay in an in-process `SecretStr` map for the
restricted key-info read; no token, raw key, unrestricted metadata or key-bearing
nested configuration is returned. Unknown owners remain unknown. Source owner IDs
are preserved even when they do not match executable catalog-ID syntax; the
action contracts retain their stricter validation and identity policy.

Installed LiteLLM source inspection confirms that omitting the key-list `status`
and `expires` filters applies no expiry restriction. Its separate session-token
filter excludes the internal UI-session team, not expired Tool-team keys. The
connector omits both filters and preserves expiry flags; fixtures explicitly
cover expired keys. Do not add an active-only filter to duplicate-key detection.

Budget reads preserve signed, finite recorded spend because the installed ledger
contains negative values. They do not infer a new allowance, reset, duration or
permission to change a budget. Reasoning combines the deployed legacy
`reasoning_levels` and wildcard/per-model `reasoning_models` ceilings. UI context
uses the person plus non-Tool memberships; key context uses only that key and its
existing Tool team. The owner’s UI grants never become key grants. Model lists
are observed catalog data, not a new effective model authorization decision.

Mapped destinations must exist and have the Tool suffix. Missing mappings require
clarification; TapsiBox-Manager-Tool remains manual. An explicitly verified
ticket-note destination can be used for that ticket only; this read helper never
updates the shared map or creates a team. The approved map remains unchanged.

## Configuration and boundaries

All four read connectors are disabled by default. The API process alone receives
the optional `AGENTIC_{SERVICEDESK,DIRECTORY,MIRZA,MATTERMOST}_URL` and corresponding
`*_READ_TOKEN` settings. Workers do not receive these credentials from Compose.
No production credential has been copied into this project's `.env`.

`AGENTIC_SERVICEDESK_LIFECYCLE_CREATOR_IDS` is an optional JSON list of native,
verified dedicated n8n ServiceDesk creator IDs, passed only to the API. It
defaults to `[]`; no real actor ID was persisted here. Entries must be unique
positive numeric strings, with at most 20 IDs to bound a reviewed historical
roster. This setting only adds an explicit blocker for unmatched producer-created
tickets; it never supplies standalone absence proof or grants approval authority.

`AGENTIC_MATTERMOST_BOT_USERNAME` defaults to the operator-confirmed
`servicedesk_agent`. The reader verifies `GET /api/v4/users/me` is that active
bot before composing a recipient lookup. It returns only bot ID/username and
eligibility flags. A missing email returns `not_found`, while unsupported routes
and denied reads remain distinct. The supplied token verified the bot and the
dynamic DWE in-charge against `https://mattermost.tapsi.tech`; a sampled requester's
email has no matching account. Missing recipients cannot qualify for delivery.
The token was entered through an echo-disabled prompt and remains unpersisted.

`AGENTIC_OFFBOARDING_DATABASE_URL` optionally configures the separate mapping
reader with a native `postgresql://` DSN for the verified n8n database. Use an
account limited to SELECT on `public.offboarding_process`; the application's
own PostgreSQL database is a different source. This secret goes only to the API
process, never workers or inference. Session defaults and each transaction are
read-only; database errors never expose connection strings or row content.
This change adds no credential provisioning or PostgreSQL writes.

`AGENTIC_ONBOARDING_DATABASE_URL` optionally configures SELECT-only access to
`public.onboarding_process`. It is separate from the application's database and
is passed only to the API. An account may be permitted to SELECT both process
tables, but configuring one reader does not silently enable the other. The same
fresh-connection/read-only/timeout/bounded-query rules apply. Both runtime URLs
remain blank; no database credential was extracted, provisioned or persisted.
The existing database probe accepts `--process onboarding` to check this index
once the operator supplies its runtime setting.

Origins must be fixed HTTP(S) origins without embedded credentials or paths.
HTTPS certificate verification stays enabled. Non-local HTTP requires explicit
`AGENTIC_CONNECTOR_ALLOW_HTTP=true`; retain false when TLS is available. The
transport exposes allowlisted GET paths, never follows redirects, ignores ambient
proxy configuration, bounds retries/timeouts/response bytes and omits upstream
response bodies from failures. HTTPX URL logging is suppressed because the
upstream key-info contract uses a sensitive query parameter.

`AGENTIC_DEPARTMENT_MAP_FILE` can select another reviewed map; the default approved
JSON and the observed ServiceDesk exclusion catalog are packaged in the image.
The latter supplies only lifecycle exclusions, never approval authority.
`AGENTIC_MIRZA_REASONING_DEFAULT` must be a known
level and agree with the deployed service; the installed value observed here is
`medium`. Read credentials still need their actual permissions verified before
runtime configuration. No write methods or production activation are introduced.

The supporting `jam-ai-service` bridge exposes authenticated
`GET /internal/identity`, reusing AD configuration and master-key authentication.
It does not change `/internal/department` behavior. AD reads are exact, escaped,
read-only and bounded; account expiry preserves AD's never-expiring sentinels.
The operator confirmed on 2026-10-06 that every unique-email AD account that is
enabled and unexpired is eligible. No extra employee-status attribute or group
is required; the connector derives the displayed eligibility from the verified
account flags. Flags must be native booleans; strings or integers cannot establish
eligibility. Ambiguous email, missing account facts, disabled or expired accounts
cannot qualify. The bridge has been checked locally and has not been deployed by this
work. It does not authenticate the requester as that employee or prove delegation.

## Verification and pending work

- 188 offline agentic unit checks pass, including transport/pagination failure
  cases, key sanitization, expired-key fixtures, signed spend, reasoning scope,
  concurrent ticket/structured-term revision detection, native in-charge roles,
  deleted approval observations, unverified history ordering, history prose redaction,
  reciprocal lifecycle roots, shared-parent/partial/changed onboarding lookups,
  exclusion blockers, bounded/parameterized/read-only PostgreSQL reads, optional
  and shared offboarding children, mapping changes and parent-template mismatches,
  database failure redaction, active/expected bot identity, missing/denied/unsupported
  Mattermost accounts, rejection of coerced directory account flags, independent
  note/history/approval/configuration/process change detection and operator/intake
  separation. SQLite regression checks execute the actual reverse-query predicates
  for all four additional installed child columns; PostgreSQL connection behavior
  remains covered separately with fixtures. Onboarding checks cover all four
  native bigint child columns, optional/shared relationships, missing packed
  fields, wrong/changed parent evidence, denied reads and conflicting process kinds.
- Seven offline AD identity/packaging checks pass; the existing adapter regression suite
  passes with rendering dependencies present, without skipped renderers.
- Installed Mirza read normalization passes: 165 users, 91 teams, 70 keys and
  30 served models. All 30 approved mappings resolve to existing Tool teams.
  The probe uses synthetic identities only to exercise the map against that live
  catalog; it does not establish AD department coverage or employee eligibility.
  No key or employee records were copied locally. The probe
  executes code in memory in the existing container and returns statuses/counts
  only: `scripts/probe_mirza_schema.py --ssh-host mirza-ha1 --container mirza-litellm`.
- Installed ServiceDesk reads pass: 32 support groups, 134 templates, 7 statuses
  and 79 categories. Ticket, note, history and approval observations normalize;
  DWE has one native `$GROUP_INCHARGE$` association with an email. No employee
  values, note bodies or ticket descriptions were copied into discovery artifacts.
  [Catalog evidence](servicedesk-catalog.json) records only non-personal IDs and
  the unresolved authority flags.
- A dedicated approval/history probe inspects actor/time completeness, status
  differences, current approval stages and required configuration. Read-only
  initial samples from both installed Mirza templates normalize successfully.
  A bounded metadata scan of 25 API-key and 20 access requests then finds approved
  candidates. One approved example per template verifies one configured/current
  approved stage and one approved item with its acting-user ID/action time.
  Notes/history/approval observations and ticket revisions stay stable on repeated
  reads. Basic stage/actor verification no longer needs a supplied ticket link.
  No source sequence or binding to current execution terms is inferred.
- The extended approval probe passes on one existing approved example from each
  Mirza template: initial/final ticket, note, history and approval reads remain
  stable, and the approval reader's observed ticket digests match the ticket
  snapshot. This verifies read correlation only. It does not prove that the
  currently observed terms were present when approval was granted. Editing a
  request does not automatically reset approvals, per the operator; manual
  restart capability remains unverified. No approval action was taken.
- Installed relationship checks match both supplied onboarding child sets,
  including the reciprocal call-center root pair. Reverse lookups recognize
  sampled default-template and VOIP children. History reads pass for the sampled
  roots and children after hashing prose field names. Installed PostgreSQL SELECTs
  in explicit read-only transactions verify the supplied offboarding parent and
  all three children. No installed driver connection has been configured for the
  API; both optional database readers are verified locally with fixtures, while
  installed schema and ID-only SQL verify their backing sources. Real tickets
  and employee data are not used in committed fixtures or discovery artifacts.
- Installed Mattermost GETs verify the supplied bot account and DWE contact.
  No message was sent and no credential was copied into repository files.
- The operator applied the Mirza packaging/eligibility and LDAP empty-search
  corrections. The adapter is healthy. Installed reads now verify the unique DWE
  contact's enabled/unexpired identity and department, return `not_found` for an
  absent address and deny an incorrect master credential. Resolving that real
  department against the approved map and current Mirza inventory verifies an
  existing Tool destination. This is one real department check, not revalidation
  of the whole AD department catalog. Mirza changes are applied personally by the
  operator; no Mirza deployment or external writes were made by this work.
- Local image packaging, Ruff and both agentic Compose variants pass. The jam
  Compose structure also validates with environment resolution/interpolation
  disabled; its local `.env` is absent, so this is not a runtime configuration check.
  Image verification uses one isolated container capped at 192 MiB/0.25 CPU with
  no network; the latest read-connector packaging check peaked at 55.9 MiB. The full runtime
  stack remains stopped and the disposable check container is removed.

The initial automatic approval rejection for the embedded ServiceDesk credential
was resolved by explicit operator approval on 2026-10-06. The authorized source
is the `Count All` node of `n8n-flows/Views/Onboadring View.json`, and the destination
is that node's configured ServiceDesk origin. This authorizes memory-only GET
discovery of ticket, group, template, note, approval, history and process schemas;
it does not authorize writes or credential persistence. The rejected attempts
did not execute. Subsequent permitted probes leave the credential in memory.

Reproduce the permitted basic read probe from the repository root:

```bash
.venv/bin/python scripts/probe_servicedesk_schema.py \
  --workflow '../n8n-flows/Views/Onboadring View.json' --allow-http
```

It returns only statuses/counts and authority flags, chooses one existing request
when no ticket ID is supplied, and never enrolls or changes that request.

Finish the authoritative history-order, approval-term and process normalizers.
The employment-rule, onboarding relationship, offboarding database-location and
Mattermost bot-credential questions are resolved.
Runtime process-database connectivity and complete membership checks remain gates.
Installed directory identity/absence/credential-denial checks are complete.
Step 4's complete-context exit condition has not yet been met; Step 5 has not begun.

Reproduce the verified directory check:

```bash
.venv/bin/python scripts/probe_directory_schema.py \
  --workflow '../n8n-flows/Views/Onboadring View.json' --allow-http \
  --ssh-host mirza-ha1
```

The ServiceDesk credential stays local and is used only against its configured
origin. Only the dynamic contact's email crosses SSH in memory; the directory
master credential stays remote. Output contains statuses and verification flags,
never employee records or credentials.

Inspect an approved Mirza example:

```bash
.venv/bin/python scripts/probe_servicedesk_authority.py \
  --workflow '../n8n-flows/Views/Onboadring View.json' --allow-http \
  --ticket-id TICKET_ID
```

This probe emits only counts, read-stability and authority flags. It does not print
ticket IDs/text, note text, actors' identifiers, employee records or credentials.

Primary API references: [ServiceDesk on-premises v3](https://www.manageengine.com/products/service-desk/sdpop-v3-api/),
[request reads](https://www.manageengine.com/products/service-desk/sdpop-v3-api/requests/request.html),
[request notes](https://www.manageengine.com/products/service-desk/sdpop-v3-api/requests/request_note.html),
[LiteLLM virtual keys](https://docs.litellm.ai/docs/proxy/virtual_keys),
[Mattermost user-by-email](https://docs.mattermost.com/api/reference/get-user-by-email),
and [Mattermost User JSON](https://github.com/mattermost/mattermost/blob/master/server/public/model/user.go).
Generic documentation is a candidate contract until checked against the installed
ServiceDesk 15.1 Build 15100 or the deployed service.
