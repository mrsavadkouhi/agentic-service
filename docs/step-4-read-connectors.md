# Step 4: read-only integration context

Status on 2026-10-13: complete for the read-only observation handoff. The combined
installed context probe passes across ServiceDesk, directory, Mirza, Mattermost and
Tool-team mapping. `observation_complete=true` reports source collection;
`read_complete=false` and `grant_context_verified=false` preserve the approval/order
blockers. Step 5 can proceed in observation mode. No production write is enabled.

The phase boundary is clarified in `plan.md`: Step 4 finishes typed observation
collection, including explicit unknown authority; Steps 6–8 must enforce and verify
approval/order, concurrency and idempotency before production writes. The former
execution-ready-context prerequisite is not required for observation-only Step 5.
Runtime read secrets and optional process-index connections remain rollout settings;
unconfigured or incomplete sources still return explicit blockers. Operator approval,
lifecycle exclusions and the eight-job allowlist remain unchanged.

Installed directory identity/absence/auth-denial checks, eligible department-to-Tool
mapping and the Mattermost bot/dynamic DWE lookup are verified. Eligibility means
exact unique email, enabled account and unexpired account.

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
Unavailability never means an empty inventory. `observation_blockers` and
`observation_complete` distinguish missing/partial collection from observed data.
Verified `not_found` identity outcomes are complete observations, never eligible
recipients. `blockers` and `read_complete` retain stricter execution-context checks;
`grant_context_verified` is constrained to false for this implementation.

| Component | Read behavior | Remaining installed verification |
|---|---|---|
| ServiceDesk | Installed ticket/group/template/status/category readers, creation actors/times, note-detail digests/authors, native approval levels/items, structured history actors/status changes, lifecycle roots and children; optional onboarding/offboarding PostgreSQL indexes | Verified history sequence, approval-to-current-terms binding, note-edit correlation, runtime process-index connections and complete membership checks |
| Directory | Exact unique email, GUID, department and native boolean enabled/unexpired account eligibility through the Mirza adapter; installed positive/absent/auth-denial reads verified | Runtime read configuration; requester authentication/delegation belongs to later authorization |
| Mirza | Two-pass reconciliation of paged users/keys including expired Tool keys, complete team list, served models and permission/budget policy; exact identity checks for key-detail reads | Production read credential permissions and runtime configuration; observations are not an atomic snapshot |
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
the approver saw; `terms_binding_verified` remains false.

On 2026-10-12 the operator confirmed that changed terms require the original
approver(s)' explicit ticket-note confirmations before reopening. Older approvals
without a recorded approved-terms snapshot also require confirmation. Unchanged
terms with a verified approved-terms record need no reconfirmation. Native required
approval stages remain mandatory; technician clarification does not replace them.
The accepted note is `Approved Mirza terms: <review reference>`. The immutable
`ApprovalReviewRequest` binds that reference to the ticket, original review,
review cycle, exact terms, configuration and original reviewers. The bot will show
those exact terms before asking for the note; sending/persisting the review belongs
to Step 7. `confirmation_notes()` reads native note details twice, matches the exact
visible plaintext/basic HTML note, checks author/editor attribution and returns
only sanitized digests/identities. It rejects changed observations and cross-ticket
reviews. Extra terms, denials, hidden/active markup and malformed notes do not match.
No raw note text is returned; note source order remains unknown and is never fabricated.

The local `reconfirmation()` check uses typed original-review, confirmation-note
and hold/Open evidence. It requires every frozen original reviewer, the exact
current terms digest, the original approval configuration, attributable current
note content, and verified ordering after the current hold and before Open.
It rejects unrelated authors/editors, mismatched tickets/reviews/terms, stale notes,
duplicate note IDs, missing identities/order, changed configuration and future
Open events. Inputs are bounded; raw note content and keys are absent.
These checks verify only their stated evidence. They do not authorize execution,
reset approvals, enroll a workflow or perform any external write. Live collection
and executable-intake integration remain pending; source ordering and note-to-terms
binding are still unverified on the installed server. Existing authority flags
remain false until those contracts are verified.

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
  re-reads mappings and the parent ticket's identity/template. It can find children
  while the packed ServiceDesk field is still absent/stale. Roots without a
  database row retain the existing packed-field
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
  parent's offboarding template, re-reads the mapping and rechecks the parent's
  identity/template to detect changes in either source. A failed parent reread
  invalidates the relationship observation. The call-center bridge also rechecks
  the related root's identity, template, reciprocal reference and packed children.
  Unrelated description edits do not invalidate these relationship observations.
  These checks detect inconsistent reads; they do not establish atomic snapshots
  or complete lifecycle coverage.
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
intake explicitly. Mapping/root observations retain `coverage_verified=false`:
an offboarding root without a configured mapping reader has unknown children,
and no match in the two sources does not establish standalone membership.
The runtime database connection remains unconfigured. A separate, operator-confirmed
historical creator contract now supports child absence checks as described below;
empty mappings and waiting age never supply that proof. These checks do not
authorize Mirza jobs or bypass other intake gates.

Ticket content, structured UDF/resource terms and note text are represented by digests in this operator snapshot;
raw bodies are not logged or placed in workflow history. Future extraction must
use a separately bounded content path and retain its evidence correlation.
Native creation actor/time are now observed separately and included in revision
correlation. All eleven supplied children expose a creator and creation time,
with one shared creator in this sample. Creator identity alone is not process
membership. The operator has confirmed n8n-only child creation using a dedicated
ServiceDesk technician account. On 2026-10-12 the operator confirmed that all
historical children have always used this same account. The GET-only creator
probe rechecks all eleven supplied children and observes one stable native
creator/template identity. A separate ticket from another creator verifies the
non-lifecycle branch. This historical coverage is operator evidence; samples and
workflow graphs verify observations, not the whole historical roster.

An optional creator-ID guard returns `incomplete` with
`n8n_created_ticket_mapping_unconfirmed` for tickets created by a configured
dedicated producer when no parent mapping is found. Positive relationship
evidence retains precedence. Creator identity supplies a review blocker, never
positive process membership. With only IDs configured, other creators retain the
existing incomplete absence result. With explicit historical coverage enabled,
exactly one account configured, a known non-root template, no positive relationship
and a stable different native creator, the reader returns `non_lifecycle` with
`coverage_verified=true`. It rechecks ticket identity, creator and template before
returning this result. Positive roots/mappings take precedence; missing creator or
template metadata, changed observations and failed configured source reads remain
blocked. The context records this verified absence without granting approval
authority. Unmatched n8n-created tickets stay incomplete even with coverage enabled,
protecting children created before mapping persistence or left unmapped after failure.

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

The inventory reader normalizes two complete catalog passes and compares owner,
membership, team kind/models, key expiry, reasoning and budget policy. Changed
permissions or failed second reads return no partial inventory and clear cached
key handles. Ordering differences do not imply a policy change. Recorded spend
can change continuously; it is excluded from reconciliation and the second pass's
spend is retained. Budget limits, reset times and durations remain compared.
Two matching observations do not prove an atomic cross-service snapshot or rule
out a change between observations. Future writes must revalidate their targets.

Key-detail reads require the returned native identity to match the cached source
handle requested. Every present top-level `key` or nested `info.token` must agree;
missing identity, mismatches and malformed envelopes fail closed. These handles
are compared in memory, never included in the normalized result. A live read on
2026-10-12 verifies this contract for one existing key, without revealing its value.

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

All four read connectors are disabled by default. In the Step 4 configuration the API alone received
the optional `AGENTIC_{SERVICEDESK,DIRECTORY,MIRZA,MATTERMOST}_URL` and corresponding
`*_READ_TOKEN` settings. Step 5 also supplies ServiceDesk/process-index reads to
both workers and directory/Mirza reads to the extraction worker. Workers receive
no Mattermost token. See [Step 5](step-5-observation.md) for process scoping.
No production credential has been copied into this project's `.env`.

`AGENTIC_SERVICEDESK_LIFECYCLE_CREATOR_IDS` is an optional JSON list of native,
verified dedicated n8n ServiceDesk creator IDs. Step 5 passes these to the API and both workers. It
defaults to `[]`; no real actor ID was persisted here. Entries must be unique
positive numeric strings, with at most 20 IDs to bound a reviewed historical
roster. IDs alone add only an explicit blocker for unmatched producer-created
tickets. `AGENTIC_SERVICEDESK_LIFECYCLE_CREATOR_COVERAGE_CONFIRMED` defaults to
`false`; enabling it requires exactly one configured account and the operator's
all-history coverage confirmation. It allows the verified different-creator
absence branch, never an approval grant. Both settings now accompany ServiceDesk
read configuration in the API and observation workers.

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

- The 2026-10-13 combined installed context probe passes with complete observation
  collection, a verified mapped Tool destination and the dynamic DWE contact lookup.
  It preserves `transitions_unsupported`, `history_order_unverified` and
  `approval_authority_unverified`; execution authority remains false. All eleven
  child samples retain one stable creator. ServiceDesk basic/catalog reads pass.
  Mirza's fresh two-pass read has 168 users, 92 teams, 78 keys and 30 models; all
  30 approved Tool destinations and the key-detail identity read pass.
  The context uses the dynamic DWE contact as an explicit recipient lookup probe,
  not as proof of the ticket's approved beneficiary. Normalized directory/catalog
  data cross a captured encrypted SSH pipe in memory; remote master credentials
  stay remote. No raw records, key values or bot token are printed or persisted.
- 338 offline agentic unit checks pass on 2026-10-13, including transport/pagination failure
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
  Mirza regression cases detect changed owners, key teams/expiry/budget policy,
  team models/reasoning, user memberships and served models between passes; verify
  ordering/spend-only changes retain the latest spend; reject an unavailable
  second pass; and verify exact key-detail identity and secret redaction.
  History-route comparison checks distinguish matching, different, changing,
  denied and incomplete observations while retaining unverified authority and
  omitting raw history, identities and credentials from diagnostic output.
  Completion checks cover exact confirmation syntax, cycle/ticket/terms/configuration/
  reviewer binding, author/editor and changed-note rejection, bounded HTML parsing,
  source completeness versus execution gates, and private SSH result validation.
  The full suite took 1.92 seconds and peaked at 139 MiB RSS; no local Docker stack
  was started. Ruff, both Compose configuration checks and catalog JSON validation pass.
- Seven offline AD identity/packaging checks pass; the existing adapter regression suite
  passes with rendering dependencies present, without skipped renderers.
- Installed Mirza read normalization passes on 2026-10-12: 168 users, 91 teams,
  77 keys and 30 served models, reconciled over two complete passes. All 30 approved
  mappings resolve to existing Tool teams, and one key-detail identity read passes.
  The earlier 2026-10-06 observation was 165 users, 91 teams and 70 keys.
  The probe uses synthetic identities only to exercise the map against that live
  catalog; it does not establish AD department coverage or employee eligibility.
  No key or employee records were copied locally. The probe
  executes code in memory in the existing container and returns statuses/counts
  only: `scripts/probe_mirza_schema.py --ssh-host mirza-ha1 --container mirza-litellm`.
- Installed ServiceDesk reads pass again on 2026-10-12: 32 support groups, 134 templates, 7 statuses
  and 79 categories. Ticket, note, history and approval observations normalize;
  DWE has one native `$GROUP_INCHARGE$` association with an email. No employee
  values, note bodies or ticket descriptions were copied into discovery artifacts.
  [Catalog evidence](servicedesk-catalog.json) records only non-personal IDs and
  the unresolved authority flags.
  Today's basic probe auto-selected an existing ticket whose approval configuration
  is unsupported; ticket/note/history/relationship reads pass, but the probe does
  not verify grant context or supply approval authority.
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
- Further 2026-10-12 GET-only inspection finds an approved candidate in each
  dedicated template within bounded metadata samples of 25 and 23 requests.
  Both native approval-detail endpoints normalize their envelope and expose
  comments, acting user and action time. None of the inspected recognized fields
  (`approved_terms`, request snapshot/revision, content digest or sent content)
  supplies an approved request snapshot. The corresponding history samples have
  10 and 8 events, with terminal pagination metadata and IDs, actors and times,
  but no observed sequence/revision/version field. This is evidence about these
  samples, not proof that no other installed API/source exists. Approval-term
  binding and history ordering remain unverified; no authority flags were enabled.
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
- Ruff and both agentic Compose variants pass on 2026-10-12 without starting containers.
  The earlier 2026-10-06 local image packaging check passed. The jam
  Compose structure also validates with environment resolution/interpolation
  disabled; its local `.env` is absent, so this is not a runtime configuration check.
  Image verification uses one isolated container capped at 192 MiB/0.25 CPU with
  no network; that historical packaging check peaked at 55.9 MiB. The updated image
  has not been rebuilt for today's Python-only connector changes. No containers
  were started today. The local Docker socket was unavailable during the resource
  check, so current container state could not be inspected. The earlier disposable
  check container was removed after verification.

PydanticAI is selected for Step 5's classification, extraction and drafting.
Steps 1–4 retain their runtime, contracts, deterministic policies and ordinary
typed read connectors. Agent calls run in Temporal activities and receive scoped,
bounded projections rather than this full operator context or global inventory.
Unknown/incomplete/unstable reads and evidence references must survive projection.
Install and pin the minimal inference dependency with those agents in Step 5;
no agent package, inference call or additional container is introduced in Step 4.

### Installed documentation access

The operator supplied the installed
[API documentation page](https://ticket.tapsi.tech/ui/api_documentation) on
2026-10-12 and authorized reading it with the existing technician key. A GET
with the `authtoken` header returns HTTP 200 containing a browser login form,
not the API documentation. The key is accepted by the API on the same HTTPS
origin. The observed API-key request does not authenticate this UI page; the
login form does not establish that the key is invalid.
No password, browser session or alternate credential was collected.

Authenticated `GET /api/v3/requests/_metainfo` succeeds and exposes the installed
request field schema. Built-in `id` is a read-only `long`, `last_updated_time` a
read-only `datetime`, and `approval_status` a read-only lookup. `subject` is a
mandatory string; `description` is HTML, `udf_fields` is a UDF container and
`resources` has type `unknown`. The inspected built-in fields do not declare a
request revision, version, source sequence or approved request snapshot.
A numeric ID's type and read-only flag do not establish chronological ordering.
The schema does not supply approved terms or a conditional-update contract.

A bounded check of `/api/v3/api_documentation` returns HTTP 404/application code
4000. Nested `_metainfo` routes for one request's history, notes, approval levels
and approvals also return 404/code 4000; no undocumented alternative schema is
assumed. These are route observations, not proof that another documentation or
schema source is absent. Static schema projections and response codes were
inspected in memory; no credentials, raw pages or runtime records were saved.
The operator has no ServiceDesk SSH access. Continue discovery with public vendor
documentation and authorized installed API reads; SSH is not a prerequisite.
An authenticated documentation export remains an optional evidence source, rather
than a requirement to continue development. Unverified authority remains blocked.

### Online vendor references and installed comparison

Reviewed on 2026-10-12, following the operator's
[resources page](https://www.manageengine.com/products/service-desk/resources.html):

| Primary source | Useful contract information | Limits for this integration |
|---|---|---|
| [On-premises REST API guide](https://www.manageengine.com/products/service-desk/sdpop-v3-api/) and [request notes](https://www.manageengine.com/products/service-desk/sdpop-v3-api/requests/request_note.html) | Header-based technician authentication; note authors, creation/update times and updater identity | Not a Build 15100 snapshot; the reviewed on-premises navigation does not include request history or request approval pages |
| [On-premises release notes](https://www.manageengine.com/products/service-desk/on-premises/readme-new.html) | Build 15100 release dated 2025-06-18; the later Build 15300 section documents SD-140771 history route/envelope/status changes involving `/_history` | A later release's behavior is a candidate to inspect, not a guarantee for the operator-confirmed build |
| [On-premises request details guide, French edition](https://www.manageengine.com/fr/service-desk/help/adminguide/request_details_page.html) | Chronological/reverse UI history display and manual Submit for Approval action | UI ordering does not guarantee a REST source sequence or resolve equal timestamps; submitting an approval does not establish renewal of existing stages for edited terms |

The resources page also links Cloud API documentation and older PDF guides. Do
not use Cloud/MSP behavior or a PDF filename containing version 9.0 as evidence
of Build 15100's approval or history contract. The reviewed sources do not
establish an immutable approved-terms snapshot or a monotonically ordered REST
history sequence. Native actor/time observations remain useful but insufficient
for those claims; do not invent an approval reset operation.

The documented `GET /api/v3/requests/{id}/_history` route was then inspected on
the installed system. An approved example from each dedicated Mirza template
returns the same event IDs and content digests as `/history`: 10 and 8 events.
Both full paged alias reads remain stable, as do the canonical history, ticket,
note and approval observations. Native configured/current approval stages and
acting-user/action-time reads pass, with matching observed ticket digests.
Neither alias comparison verifies source ordering or approved execution terms.
The runtime connector retains `/history`; there is no automatic route fallback.

`scripts/probe_servicedesk_authority.py --compare-history-alias` provides this
opt-in comparison without changing the runtime endpoint allowlist. It bounds and
validates pagination through the existing reader, compares digests in memory,
and returns only status/count/comparison flags. It fails the diagnostic on changed,
incomplete, denied or differing alias reads; no raw records or identifiers are
printed. All execution-authority flags remain false.

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

In Steps 6–8, finish and verify authoritative status/note ordering, approval-term
proofs and write recovery before activation; unsupported sources must remain blocked.
The employment-rule, onboarding relationship, offboarding database-location,
Mattermost bot-credential and original-approver reconfirmation policy questions
are resolved. Live reconfirmation evidence and workflow integration remain pending.
Runtime process-database connectivity remains required for complete mapping reads.
Historical creator coverage is now confirmed and live sampled; the runtime account
ID and coverage setting remain unconfigured. Without that configuration, unmatched
non-producer tickets still have incomplete lifecycle context.
Installed directory identity/absence/credential-denial checks are complete.
Step 4's read-only observation exit is verified. Step 5's observation implementation
is documented separately; production
authority and write gates remain in Steps 6–8 and are not satisfied by this handoff.

Reproduce the combined read-only snapshot with an in-memory bot token:

```bash
read -rsp 'Mattermost bot read token: ' probe_mattermost_token
printf '%s\n' "$probe_mattermost_token" | \
  .venv/bin/python scripts/probe_context_snapshot.py \
    --workflow '../n8n-flows/Views/Onboadring View.json' --ssh-host mirza-ha1 \
    --child-ticket-id CHILD_1 --child-ticket-id CHILD_2 \
    --confirm-historical-creator-coverage
unset probe_mattermost_token
```

Use operator-confirmed children from onboarding and offboarding. This selects
one Mirza Access Request from at most 25 candidates and returns only status flags,
with no workflow enrollment or external writes. It never saves the snapshot or secrets.

Reproduce the historical creator observation with at least two operator-confirmed
child IDs (up to 20; pass IDs from both onboarding and offboarding):

```bash
.venv/bin/python scripts/probe_lifecycle_creator.py \
  --workflow '../n8n-flows/Views/Onboadring View.json' \
  --child-ticket-id CHILD_1 --child-ticket-id CHILD_2 \
  --confirm-historical-creator-coverage
```

The probe keeps the native creator ID in memory, rechecks sample identities and
examines at most 25 comparison candidates. It uses complete bounded relationship
reads for a selected different-creator ticket and prints only counts/statuses/flags.
The coverage flag records the operator's historical guarantee, not a sample-derived
inference. It never saves runtime IDs/credentials or performs an external write.

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
  --ticket-id TICKET_ID --compare-history-alias
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
