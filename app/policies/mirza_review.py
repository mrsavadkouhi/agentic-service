"""Resolve exact Mirza scopes and preview the smallest change; no I/O or authority."""

from datetime import datetime

from app.connectors.http import ReadFailure
from app.connectors.mirza import LEVELS, effective_reasoning
from app.contracts.context import ApprovalReviewRequest, MirzaInventory
from app.contracts.mirza_review import (
    AccessPackage,
    MirzaReminderDraft,
    MirzaReviewResult,
    MirzaReviewState,
    ReviewEvidence,
    ReviewIntent,
)
from app.contracts.tickets import (
    AddPersonToNonToolTeam,
    Catalog,
    CreateApiKey,
    MirzaRequest,
    NewToolTeam,
    TicketEvent,
    WorkflowState,
    digest,
    stable_id,
)
from app.policies.approval_reconfirmation import reconfirmation
from app.policies.reminders import TEHRAN
from app.policies.tickets import evaluate, job_issue


class PackageIssue(ValueError):
    """A fixed policy reason, never source text or a validation exception."""


def access_package(
    event: TicketEvent, catalog: Catalog, inventory: MirzaInventory
) -> AccessPackage:
    job = event.proposal.job
    email = getattr(job, "owner_email", getattr(job, "person_email", None))
    owners = [u for u in inventory.users if u.email == email or (
        u.email is None and email is not None and u.user_id.casefold() == email
    )] if email else []
    if email and len(owners) != 1:
        raise PackageIssue("mirza_owner_unverified")
    owner = owners[0] if owners else None
    teams = {t.team_id: t for t in inventory.teams}
    if len(teams) != len(inventory.teams) or len({u.user_id for u in inventory.users}) != len(
        inventory.users
    ) or len({k.key_ref for k in inventory.keys}) != len(inventory.keys):
        raise PackageIssue("mirza_inventory_ambiguous")
    if owner and any(ref not in teams for ref in owner.team_ids):
        raise PackageIssue("owner_membership_unverified")
    if not set(getattr(job, "model_ids", ())).issubset(inventory.served_models):
        raise PackageIssue("served_models")
    key = None
    target_team = None
    changes = []
    values = {"job": job, "scope": "person", "target_ref": email,
              "owner_ref": owner.user_id if owner else None,
              "expires_at": getattr(job, "expires_at", None)}
    if isinstance(job, CreateApiKey):
        values.update(scope="api_key", target_ref="new-key-for-" + stable_id(job.owner_email),
                      budget_after=job.budget_limit, budget_duration=job.budget_duration)
        if isinstance(job.tool_team, NewToolTeam):
            if not set(job.tool_team.initial_model_ids).issubset(inventory.served_models):
                raise PackageIssue("served_models")
            values.update(team_id=None, models_after=tuple(sorted(job.tool_team.initial_model_ids)))
            changes.extend(("create_tool_team", "add_owner_to_tool_team"))
        else:
            target_team = teams.get(job.tool_team.team_id)
            if not target_team or target_team.kind != "tool":
                raise PackageIssue("one_verified_tool_team")
            values.update(team_id=target_team.team_id,
                          models_before=tuple(sorted(target_team.models)),
                          models_after=tuple(sorted(target_team.models)))
            if target_team.team_id not in owner.team_ids:
                changes.append("add_owner_to_tool_team")
        changes.append("create_api_key")
    elif hasattr(job, "key_ref"):
        matches = [k for k in inventory.keys if k.key_ref == job.key_ref]
        if len(matches) != 1:
            raise PackageIssue("verified_key_owner_and_tool_team")
        key = matches[0]
        target_team = teams.get(key.team_id)
        if (key.owner_id != owner.user_id or key.team_id != job.tool_team_id
                or not target_team or target_team.kind != "tool"):
            raise PackageIssue("verified_key_owner_and_tool_team")
        values.update(scope="api_key", target_ref=key.key_ref, team_id=key.team_id,
                      models_before=tuple(sorted(target_team.models)),
                      models_after=tuple(sorted(target_team.models)))
    elif hasattr(job, "team_id"):
        target_team = teams.get(job.team_id)
        expected = "non_tool" if isinstance(job, AddPersonToNonToolTeam) else job.team_kind
        if not target_team or target_team.kind != expected:
            raise PackageIssue("verified_team_kind")
        values.update(team_id=target_team.team_id,
                      scope="tool_team" if expected == "tool" else "non_tool_team",
                      target_ref=target_team.team_id,
                      models_before=tuple(sorted(target_team.models)),
                      models_after=tuple(sorted(target_team.models)))
        if isinstance(job, AddPersonToNonToolTeam):
            if job.requested_model_id not in target_team.models:
                raise PackageIssue("existing_team_model_grants")
            before = tuple(sorted(ref for ref in owner.team_ids if teams[ref].kind == "non_tool"))
            after = tuple(sorted(set(before) | {job.team_id}))
            before_models = {m for ref in before for m in teams[ref].models}
            after_models = {m for ref in after for m in teams[ref].models}
            values.update(scope="person", target_ref=job.person_email,
                          non_tool_memberships_before=before, non_tool_memberships_after=after,
                          models_before=tuple(sorted(before_models)),
                          models_after=tuple(sorted(after_models)))
            if before != after:
                changes.append(job.operation)
        elif job.operation == "grant_team_model_access":
            after = tuple(sorted(set(target_team.models) | set(job.model_ids)))
            if after != values["models_before"]:
                changes.append(job.operation)
            values["models_after"] = after
    if target_team and target_team.alias.casefold() == "tapsibox-manager-tool":
        raise PackageIssue("manual_team")
    if hasattr(job, "reasoning_level"):
        if not set(job.model_ids).issubset(target_team.models):
            raise PackageIssue("existing_team_model_grants")
        rows = [key.reasoning, target_team.reasoning] if key else [target_team.reasoning]
        effective = effective_reasoning(rows)
        before = {m: effective.models.get(m, effective.all_models) for m in job.model_ids}
        after = {m: max((level, job.reasoning_level), key=LEVELS.index)
                 for m, level in before.items()}
        values.update(reasoning_before=before, reasoning_after=after)
        if before != after:
            changes.append(job.operation)
    if hasattr(job, "budget"):
        current = key.budget if key else target_team.budget if target_team else owner.budget
        if current.limit is None:
            raise PackageIssue("budget_baseline_changed")
        if current.limit >= job.budget.desired_limit:
            desired = current.limit
        elif current.limit != job.budget.baseline_limit:
            raise PackageIssue("budget_baseline_changed")
        else:
            desired = job.budget.desired_limit
            changes.append(job.operation)
        values.update(budget_before=current.limit, budget_after=desired,
                      budget_duration=current.duration)
    return AccessPackage(**values, changes=tuple(changes))


def review_mirza(
    event: TicketEvent, prior: MirzaReviewState, catalog: Catalog,
    inventory: MirzaInventory, evidence: ReviewEvidence | None = None,
) -> MirzaReviewResult:
    evidence = evidence or prior.evidence
    frame = prior.tracking

    def result(state, reason, **values):
        preview_frame = frame.model_copy(update={
            "pending_action_id": None, "pending_action_role": None,
        })
        return MirzaReviewResult(state=state, reason_code=reason,
                                 next_state=prior.model_copy(update={
                                     "tracking": preview_frame, "evidence": evidence,
                                 }),
                                 evidence_refs=event.evidence_refs, **values)

    # Apply exclusions before attempting identity, package or approval resolution.
    if prior.tracking.cancelled:
        return result("no_op", "operator_cancelled")
    if event.snapshot.process.association == "lifecycle":
        return result("no_op", "excluded_lifecycle_process")
    if event.snapshot.process.association == "unknown":
        return result("blocked", "unverified_process_association")
    if event.snapshot.status in {"Resolved", "Closed", "Cancelled"}:
        return result("no_op", "ticket_terminal")
    if not isinstance(event.proposal, MirzaRequest):
        return result("no_op", "unsupported_mirza_operation")
    dedicated = event.snapshot.template_id in catalog.dedicated_templates.values()
    if not dedicated and not frame.fallback_enrolled:
        if event.snapshot.support_group_id != catalog.support_groups["Helpdesk"]:
            return result("no_op", "ineligible_mirza_intake")
        if event.snapshot.technician_ref is not None:
            return result("blocked", "human_assignment_preserved")
    package = None
    issue = event.proposal.missing_fields if not event.proposal.job else ()
    if event.proposal.job:
        terms = digest(event.proposal.job)
        mapping = frame.ticket_mapping_terms_digest == terms
        if prior.tracking.wait and "ticket_scoped_mapping" in prior.tracking.wait.missing_fields:
            from app.policies.tickets import valid_clarification
            mapping = mapping or valid_clarification(event, prior.tracking, terms)
        problem = job_issue(event, catalog, mapping)
        if problem:
            issue = (problem,)
        else:
            try:
                package = access_package(event, catalog, inventory)
            except (PackageIssue, ReadFailure) as error:
                reason = error.reason if isinstance(error, ReadFailure) else str(error)
                issue = (reason,)
                event = event.model_copy(update={"proposal": MirzaRequest(
                    kind="mirza", operation=event.proposal.operation, job=None,
                    missing_fields=issue,
                )})
    decision = evaluate(event, prior.tracking, catalog)
    frame = decision.tracking
    # A native approval of current ticket content cannot create its own terms baseline.
    if (dedicated and package and event.native_approval
            and event.native_approval.final_state == "approved"
            and decision.reason_code in {
                "approved_mirza_job", "awaiting_approval", "unverified_waiting_contact",
            }):
        proof, baseline = event.native_approval, evidence.baseline
        terms = digest(event.proposal.job)
        if (not baseline or baseline.ticket_id != event.ticket_id
                or baseline.approval_ref != proof.evidence_ref
                or evidence.configuration_digest is None):
            return result("blocked", "original_approval_evidence_unverified", package=package)
        if baseline.approved_terms_digest != terms:
            if (not baseline.identity_verified or not baseline.history_verified
                    or baseline.source_sequence is None
                    or evidence.configuration_digest != baseline.configuration_digest):
                return result("blocked", "original_approval_evidence_unverified", package=package)
            request = evidence.review
            if not (request and request.ticket_id == event.ticket_id
                    and request.approval_ref == baseline.approval_ref
                    and request.terms_digest == terms
                    and set(request.original_approver_ids) == set(baseline.original_approver_ids)
                    and request.configuration_digest == baseline.configuration_digest):
                request = ApprovalReviewRequest(
                    ticket_id=event.ticket_id, approval_ref=baseline.approval_ref,
                    cycle_id=stable_id(event.workflow_id(), terms, event.snapshot.revision_id),
                    terms_digest=terms, configuration_digest=baseline.configuration_digest,
                    original_approver_ids=baseline.original_approver_ids,
                )
                evidence = evidence.model_copy(update={"review": request})
                # Existing notes cannot confirm a review which has not been persisted yet.
                return result("awaiting_approval", "original_approver_confirmation_pending",
                              package=package, intents=(
                                  ReviewIntent(kind="hold"),
                                  ReviewIntent(kind="approval_dm",
                                               contact_refs=request.original_approver_ids,
                                               template_ref="mirza-terms-reconfirmation-v1"),
                              ))
        if evidence.on_hold_status_id is None or evidence.open_status_id is None:
            return result("blocked", "approval_status_contract_unverified", package=package)
        confirmation = reconfirmation(
            baseline, terms, evidence.configuration_digest, evidence.notes, evidence.reopen,
            on_hold_status_id=evidence.on_hold_status_id,
            open_status_id=evidence.open_status_id,
            current_source_sequence=event.snapshot.source_sequence,
            current_order_verified=event.snapshot.source_order_verified,
        )
        if confirmation.state not in {"not_required", "confirmed"}:
            intents = ()
            if confirmation.state == "awaiting_confirmation":
                intents = (ReviewIntent(kind="hold"), ReviewIntent(
                    kind="approval_dm", contact_refs=confirmation.missing_approver_ids,
                    template_ref="mirza-terms-reconfirmation-v1",
                ))
            return result("awaiting_approval" if confirmation.state == "awaiting_confirmation"
                          else "blocked", confirmation.reason_code,
                          package=package, intents=intents)
        # Retain the native required-stage/history gates. Confirmation only binds
        # those approvals to revised terms; it never replaces the native approval.
        rebound = event.model_copy(update={"native_approval": proof.model_copy(update={
            "terms_digest": terms,
        })})
        decision = evaluate(rebound, prior.tracking, catalog)
        frame = decision.tracking
    if decision.state == WorkflowState.AWAITING_CLARIFICATION:
        return result("awaiting_clarification", decision.reason_code, package=package, intents=(
            ReviewIntent(kind="hold"),
            ReviewIntent(kind="clarification_dm", contact_refs=frame.wait.contact_refs,
                         missing_fields=frame.wait.missing_fields,
                         template_ref="mirza-clarification-v1"),
        ))
    if issue:
        contact = event.snapshot.technician_ref or frame.original_dwe_incharge_ref
        contact = contact or catalog.dwe_incharge_ref
        active = {person.person_id for person in catalog.people if person.active}
        intents = ()
        if contact in active:
            intents = (ReviewIntent(kind="hold"), ReviewIntent(
                kind="clarification_dm", contact_refs=(contact,), missing_fields=issue,
                template_ref="mirza-clarification-v1",
            ))
        return result("blocked", decision.reason_code, package=package, intents=intents)
    if decision.state == WorkflowState.AWAITING_APPROVAL:
        intents = [ReviewIntent(kind="approval_dm", contact_refs=frame.wait.contact_refs,
                               template_ref="mirza-native-approval-v1" if dedicated
                               else "mirza-approval-v1")]
        if not dedicated:
            intents.insert(0, ReviewIntent(kind="hold"))
            if event.snapshot.support_group_id != catalog.support_groups["DWE"]:
                intents.insert(0, ReviewIntent(kind="handoff"))
        return result("awaiting_approval", decision.reason_code, package=package,
                      intents=tuple(intents))
    if decision.state == WorkflowState.COMPLETED:
        intents, explanation = (), None
        if decision.reason_code == "additional_key_unnecessary":
            package = package.model_copy(update={"changes": ()}) if package else None
            staff = event.snapshot.technician_ref or frame.original_dwe_incharge_ref
            contacts = tuple(dict.fromkeys(ref for ref in (
                event.snapshot.intended_person_ref, staff,
            ) if ref))
            intents = (ReviewIntent(kind="completion", contact_refs=contacts),)
            explanation = event.clarification.explanation_ref
        return result("no_op", decision.reason_code, package=package, intents=intents,
                      completion_explanation_ref=explanation)
    if decision.authorized:
        return result("ready" if package and package.changes else "no_op",
                      "approved_mirza_preview" if package and package.changes
                      else "requested_access_already_present", package=package)
    return result("blocked", decision.reason_code, package=package)


def reminder_drafts(ticket_id: str, current: MirzaReviewResult, now: datetime):
    """Combine pending actions per recipient/calendar day; never send or mutate a ticket."""
    if now.tzinfo is None:
        raise ValueError("Reminder clock must be timezone-aware")
    local = now.astimezone(TEHRAN)
    if local.hour < 10 or current.state not in {"awaiting_approval", "awaiting_clarification"}:
        return ()
    actions = {}
    for intent in current.intents:
        if intent.kind not in {"approval_dm", "clarification_dm"}:
            continue
        for contact in intent.contact_refs:
            actions.setdefault(contact, set()).add(intent.template_ref)
    return tuple(MirzaReminderDraft(
        draft_id=stable_id("mirza-reminder-v1", ticket_id, contact, local.date().isoformat()),
        ticket_id=ticket_id, contact_ref=contact, day=local.date(),
        action_refs=tuple(sorted(refs)),
    ) for contact, refs in sorted(actions.items()))
