"""Deterministic boundaries, not a classifier or live authorization connector."""

from app.contracts.tickets import (
    AddPersonToNonToolTeam,
    Catalog,
    CreateApiKey,
    Evaluation,
    GroupCorrection,
    MirzaRequest,
    NewToolTeam,
    NoOp,
    TicketEvent,
    Tracking,
    WaitCycle,
    WorkflowState,
    digest,
    stable_id,
)

POLICY_VERSION = "step-1-confirmed-v1"


def valid_clarification(event: TicketEvent, tracking: Tracking, terms: str) -> bool:
    proof, wait = event.clarification, tracking.wait
    return bool(
        wait
        and wait.reason == "awaiting_clarification"
        and proof
        and proof.history_verified
        and proof.cycle_id == wait.cycle_id
        and proof.note_author_ref in wait.contact_refs
        and proof.open_actor_ref == proof.note_author_ref
        and wait.baseline_sequence
        < proof.note_sequence
        < proof.open_sequence
        <= event.snapshot.source_sequence
        and proof.supplied_terms_digest == terms
        and event.snapshot.status == "Open"
    )


def job_issue(event: TicketEvent, catalog: Catalog, ticket_mapping_supplied: bool) -> str | None:
    job = event.proposal.job
    people = {p.email: p for p in catalog.people if p.active}
    person_email = getattr(job, "owner_email", getattr(job, "person_email", None))
    if person_email:
        person = people.get(person_email)
        if not person or event.snapshot.intended_person_ref != person.person_id:
            return "verified_intended_person"
    teams = {t.team_id: t for t in catalog.teams}
    models = set(getattr(job, "model_ids", ()))
    if not models.issubset(catalog.model_ids):
        return "served_models"
    level = getattr(job, "reasoning_level", None)
    if level and level not in catalog.reasoning_levels:
        return "reasoning_level"
    if isinstance(job, CreateApiKey):
        target = job.tool_team
        if isinstance(target, NewToolTeam):
            if not set(target.initial_model_ids).issubset(catalog.model_ids):
                return "served_models"
            if target.alias.casefold() == "tapsibox-manager-tool":
                return "manual_team"
            if any(t.alias.casefold() == target.alias.casefold() for t in catalog.teams):
                return "existing_team_reference"
            return None if ticket_mapping_supplied else "ticket_scoped_mapping"
        team = teams.get(target.team_id)
        if not team or team.kind != "tool":
            return "one_verified_tool_team"
        if team.alias.casefold() == "tapsibox-manager-tool":
            return "manual_team"
        mapped = next(
            (
                v
                for k, v in catalog.department_tool_teams.items()
                if k.strip().casefold() == (person.department or "").strip().casefold()
            ),
            None,
        )
        if mapped != team.team_id and not ticket_mapping_supplied:
            return "ticket_scoped_mapping"
    elif hasattr(job, "key_ref"):
        key = next((k for k in catalog.keys if k.key_ref == job.key_ref), None)
        team = teams.get(job.tool_team_id)
        if (
            not key
            or key.owner_email != job.owner_email
            or key.tool_team_id != job.tool_team_id
            or not team
            or team.kind != "tool"
        ):
            return "verified_key_owner_and_tool_team"
        if not models.issubset(team.models):
            return "existing_team_model_grants"
    elif hasattr(job, "team_id"):
        team = teams.get(job.team_id)
        kind = "non_tool" if isinstance(job, AddPersonToNonToolTeam) else job.team_kind
        if not team or team.kind != kind:
            return "verified_team_kind"
        if isinstance(job, AddPersonToNonToolTeam) and job.requested_model_id not in team.models:
            return "existing_team_model_grants"
        if job.operation == "increase_team_reasoning" and not models.issubset(team.models):
            return "existing_team_model_grants"
        if team.alias.casefold() == "tapsibox-manager-tool":
            return "manual_team"
    return None


def evaluate(event: TicketEvent, prior: Tracking, catalog: Catalog | None) -> Evaluation:
    snapshot = event.snapshot
    sequence = snapshot.source_sequence
    frame = prior.model_copy(update={"pending_action_id": None, "pending_action_role": None})

    def result(state, reason, **kwargs):
        return Evaluation(
            state=state,
            reason_code=reason,
            tracking=frame.model_copy(update={"state": state}),
            **kwargs,
        )

    if prior.cancelled:
        return result(WorkflowState.CANCELLED, "operator_cancelled")
    if not snapshot.source_order_verified or sequence is None:
        frame = frame.model_copy(update={"wait": None})
        return result(WorkflowState.MANUAL_REVIEW, "unverified_source_order")
    if sequence < prior.latest_sequence:
        return Evaluation(state=prior.state, reason_code="stale_event", tracking=prior)
    event_digest = digest(event.model_copy(update={"event_id": "logical-revision"}))
    if sequence == prior.latest_sequence:
        if event_digest == prior.latest_event_digest:
            return Evaluation(state=prior.state, reason_code="duplicate_revision", tracking=prior)
        frame = frame.model_copy(update={"wait": None})
        return result(WorkflowState.MANUAL_REVIEW, "conflicting_source_sequence")
    frame = frame.model_copy(
        update={"latest_sequence": sequence, "latest_event_digest": event_digest}
    )
    if snapshot.process.association == "lifecycle":
        frame = frame.model_copy(update={"wait": None})
        return result(WorkflowState.COMPLETED, "excluded_lifecycle_process")
    if snapshot.process.association == "unknown":
        frame = frame.model_copy(update={"wait": None})
        return result(WorkflowState.MANUAL_REVIEW, "unverified_process_association")
    if snapshot.status in {"Resolved", "Closed", "Cancelled"}:
        frame = frame.model_copy(update={"wait": None})
        return result(WorkflowState.CANCELLED, "ticket_terminal")
    if isinstance(event.proposal, NoOp):
        frame = frame.model_copy(update={"wait": None})
        return result(WorkflowState.COMPLETED, event.proposal.reason_code)
    if (
        not catalog
        or event.catalog_version != catalog.version
        or event.policy_version != POLICY_VERSION
        or (event.data_kind == "synthetic") != (catalog.environment == "synthetic")
    ):
        frame = frame.model_copy(update={"wait": None})
        return result(WorkflowState.MANUAL_REVIEW, "unverified_catalog_or_policy")
    if snapshot.requester_ref not in {p.person_id for p in catalog.people if p.active}:
        frame = frame.model_copy(update={"wait": None})
        return result(WorkflowState.MANUAL_REVIEW, "unverified_requester")
    groups = catalog.support_groups
    proposal = event.proposal
    if isinstance(proposal, GroupCorrection):
        frame = frame.model_copy(update={"wait": None})
        if snapshot.support_group_id != groups["Helpdesk"] or snapshot.technician_ref is not None:
            return result(WorkflowState.COMPLETED, "preserve_group_or_human_assignment")
        if proposal.destination_group_id not in groups.values():
            return result(WorkflowState.MANUAL_REVIEW, "unknown_support_group")
        if proposal.destination_group_id == snapshot.support_group_id:
            return result(WorkflowState.COMPLETED, "already_correct_group")
        terms = digest(proposal)
        return result(
            WorkflowState.EXECUTING,
            "group_correction_proposed",
            authorized=True,
            terms_digest=terms,
            target_role="dispatch",
            action_id=stable_id(event.workflow_id(), terms),
        )
    assert isinstance(proposal, MirzaRequest)
    dedicated = snapshot.template_id in catalog.dedicated_templates.values()
    if not dedicated and not frame.fallback_enrolled:
        if snapshot.support_group_id != groups["Helpdesk"]:
            return result(WorkflowState.COMPLETED, "ineligible_mirza_intake")
        frame = frame.model_copy(
            update={"fallback_enrolled": True, "enrollment_sequence": sequence}
        )
    if not frame.original_dwe_incharge_ref and catalog.dwe_incharge_ref:
        frame = frame.model_copy(update={"original_dwe_incharge_ref": catalog.dwe_incharge_ref})
    terms = (
        digest(proposal.job)
        if proposal.job
        else stable_id(
            proposal.operation, snapshot.content_digest, ",".join(proposal.missing_fields)
        )
    )

    def waiting(reason, missing=(), contacts=()):
        nonlocal frame
        active_people = {p.person_id for p in catalog.people if p.active}
        if not contacts or not set(contacts).issubset(active_people):
            frame = frame.model_copy(update={"wait": None})
            return result(WorkflowState.MANUAL_REVIEW, "unverified_waiting_contact")
        old = frame.wait
        if not (
            old
            and old.reason == reason
            and old.terms_digest == terms
            and old.contact_refs == tuple(contacts)
            and old.missing_fields == tuple(missing)
        ):
            old = WaitCycle(
                cycle_id=stable_id(event.workflow_id(), reason, terms, str(sequence)),
                reason=reason,
                baseline_sequence=sequence,
                terms_digest=terms,
                contact_refs=tuple(contacts),
                missing_fields=tuple(missing),
                baseline_revision_id=snapshot.revision_id,
            )
        frame = frame.model_copy(update={"wait": old})
        return result(WorkflowState(reason), reason, terms_digest=terms)

    contact = snapshot.technician_ref or frame.original_dwe_incharge_ref
    clarification_valid = valid_clarification(event, prior, terms) and prior.wait.contact_refs == (
        contact,
    )
    if proposal.job is None:
        return waiting(
            "awaiting_clarification", proposal.missing_fields, (contact,) if contact else ()
        )
    if prior.wait and prior.wait.reason == "awaiting_clarification" and not clarification_valid:
        return waiting(
            "awaiting_clarification", prior.wait.missing_fields, (contact,) if contact else ()
        )
    mapping_supplied = bool(
        clarification_valid and prior.wait and "ticket_scoped_mapping" in prior.wait.missing_fields
    )
    if mapping_supplied:
        frame = frame.model_copy(update={"ticket_mapping_terms_digest": terms})
    mapping_supplied = mapping_supplied or frame.ticket_mapping_terms_digest == terms
    issue = job_issue(event, catalog, mapping_supplied)
    if issue:
        return waiting("awaiting_clarification", (issue,), (contact,) if contact else ())
    if frame.completed_terms_digest == terms:
        frame = frame.model_copy(update={"wait": None})
        return result(WorkflowState.COMPLETED, "already_completed_terms", terms_digest=terms)
    if isinstance(proposal.job, CreateApiKey):
        target = proposal.job.tool_team
        existing = not isinstance(target, NewToolTeam) and any(
            k.owner_email == proposal.job.owner_email and k.tool_team_id == target.team_id
            for k in catalog.keys  # Expired keys count too.
        )
        if existing and frame.additional_key_terms_digest != terms:
            response = event.clarification
            if (
                not clarification_valid
                or response.additional_key_decision is None
                or not set(prior.wait.missing_fields).intersection(
                    {"additional_key_needed", "decision_explanation"}
                )
            ):
                return waiting(
                    "awaiting_clarification",
                    ("additional_key_needed",),
                    (contact,) if contact else (),
                )
            if response.additional_key_decision == "unnecessary":
                if not response.explanation_ref:
                    return waiting(
                        "awaiting_clarification",
                        ("decision_explanation",),
                        (contact,) if contact else (),
                    )
                frame = frame.model_copy(update={"wait": None, "completed_terms_digest": terms})
                return result(
                    WorkflowState.COMPLETED, "additional_key_unnecessary", terms_digest=terms
                )
            frame = frame.model_copy(update={"additional_key_terms_digest": terms})
    if dedicated:
        proof = event.native_approval
        if (
            proof
            and proof.final_state == "rejected"
            and proof.history_verified
            and proof.template_id == snapshot.template_id
            and proof.terms_digest == terms
            and proof.source_sequence <= sequence
        ):
            frame = frame.model_copy(update={"wait": None})
            return result(WorkflowState.REJECTED, "native_approval_rejected")
        approved = bool(
            proof
            and proof.final_state == "approved"
            and proof.required_stages_complete
            and proof.history_verified
            and proof.template_id == snapshot.template_id
            and proof.terms_digest == terms
            and proof.source_sequence <= sequence
            and snapshot.status == "Open"
        )
        contacts = proof.pending_approver_refs if proof else ()
    else:
        proof = event.fallback_approval
        approved = bool(
            proof
            and proof.history_verified
            and proof.terms_digest == terms
            and proof.actor_ref == frame.original_dwe_incharge_ref
            and proof.group_id == groups["DWE"] == snapshot.support_group_id
            and frame.enrollment_sequence <= proof.held_sequence < proof.open_sequence <= sequence
            and (
                not prior.wait
                or prior.wait.reason != "awaiting_approval"
                or proof.held_sequence >= prior.wait.baseline_sequence
            )
            and snapshot.status == "Open"
        )
        contacts = (frame.original_dwe_incharge_ref,) if frame.original_dwe_incharge_ref else ()
    if not approved:
        return waiting("awaiting_approval", (), contacts)
    frame = frame.model_copy(update={"wait": None})
    return result(
        WorkflowState.EXECUTING,
        "approved_mirza_job",
        authorized=True,
        terms_digest=terms,
        target_role="mirza",
        action_id=stable_id(event.workflow_id(), terms),
    )
