from datetime import datetime

import pytest
from pydantic import ValidationError

from app.contracts.tickets import (
    Budget,
    ClarificationResponse,
    CreateApiKey,
    FallbackApproval,
    GroupCorrection,
    MirzaRequest,
    ProcessContext,
    TicketEvent,
    Tracking,
    digest,
)
from app.policies.reminders import TEHRAN, next_morning, reminder_due
from app.policies.synthetic_events import catalog, event
from app.policies.tickets import evaluate


def changed(original, *, sequence=None, **snapshot):
    if sequence is not None:
        snapshot.update(source_sequence=sequence, revision_id=f"revision-{sequence}")
    return original.model_copy(
        update={
            "event_id": f"revision-{sequence}" if sequence is not None else original.event_id,
            "snapshot": original.snapshot.model_copy(update=snapshot),
        }
    )


def clarify(original, wait, *, author="incharge", sequence=3, decision=None):
    return changed(original, sequence=sequence).model_copy(
        update={
            "clarification": ClarificationResponse(
                cycle_id=wait.cycle_id,
                note_ref="note-2",
                note_author_ref=author,
                note_sequence=sequence - 1,
                open_event_ref="open-3",
                open_actor_ref=author,
                open_sequence=sequence,
                supplied_terms_digest=digest(original.proposal.job),
                history_verified=True,
                additional_key_decision=decision,
                explanation_ref="explanation" if decision == "unnecessary" else None,
            ),
        }
    )


@pytest.mark.parametrize(
    "association,expected",
    [
        ("lifecycle", "excluded_lifecycle_process"),
        ("unknown", "unverified_process_association"),
    ],
)
def test_process_context_precedes_approved_mirza(association, expected):
    process = ProcessContext(
        association=association,
        kind="offboarding",
        parent_ticket_id="parent",
        evidence_ref="verified-process",
    )
    decision = evaluate(changed(event(approved=True), process=process), Tracking(), catalog())
    assert decision.reason_code == expected
    assert not decision.authorized


@pytest.mark.parametrize(
    "group,technician,authorized",
    [
        ("sd-helpdesk", None, True),
        ("sd-helpdesk", "technician", False),
        ("sd-dwe", None, False),
        ("sd-network", None, False),
        ("sd-voip", None, False),
    ],
)
def test_ordinary_dispatch_protects_human_and_specialized_groups(group, technician, authorized):
    original = changed(event(), support_group_id=group, technician_ref=technician)
    original = original.model_copy(
        update={
            "proposal": GroupCorrection(
                kind="correct_support_group", destination_group_id="sd-network"
            ),
        }
    )
    assert evaluate(original, Tracking(), catalog()).authorized is authorized


@pytest.mark.parametrize(
    "change",
    [
        {"history_verified": False},
        {"required_stages_complete": False},
        {"terms_digest": "f" * 64},
        {"template_id": "template-other"},
        {"source_sequence": 2},
        {"final_state": "pending"},
    ],
)
def test_native_approval_must_match_complete_verified_terms(change):
    original = event(approved=True)
    original = original.model_copy(
        update={
            "native_approval": original.native_approval.model_copy(update=change),
        }
    )
    assert not evaluate(original, Tracking(), catalog()).authorized


def test_changed_budget_invalidates_old_approval_and_delta_is_stable_absolute_target():
    original = event(approved=True)
    job = original.proposal.job.model_copy(
        update={
            "budget": Budget(
                amount=10, interpretation="delta", baseline_limit=10, desired_limit=20
            ),
        }
    )
    revised = original.model_copy(
        update={"proposal": original.proposal.model_copy(update={"job": job})}
    )
    assert not evaluate(revised, Tracking(), catalog()).authorized
    assert digest(job) == digest(job.model_copy())
    with pytest.raises(ValidationError):
        Budget(amount=10, interpretation="delta", baseline_limit=10, desired_limit=30)


def test_fallback_snapshots_incharge_and_checks_actor_after_handoff():
    first = event(dedicated=False)
    initial = evaluate(first, Tracking(), catalog())
    assert initial.state == "awaiting_approval"
    assert initial.tracking.original_dwe_incharge_ref == "incharge"
    proof = FallbackApproval(
        terms_digest=digest(first.proposal.job),
        group_id="sd-dwe",
        held_event_ref="hold-2",
        held_sequence=2,
        open_event_ref="open-3",
        open_sequence=3,
        actor_ref="new-incharge",
        history_verified=True,
    )
    reopened = changed(first, sequence=3, support_group_id="sd-dwe").model_copy(
        update={"fallback_approval": proof}
    )
    new_catalog = catalog().model_copy(update={"dwe_incharge_ref": "new-incharge"})
    assert not evaluate(reopened, initial.tracking, new_catalog).authorized
    reopened = reopened.model_copy(
        update={"fallback_approval": proof.model_copy(update={"actor_ref": "incharge"})}
    )
    assert evaluate(reopened, initial.tracking, new_catalog).authorized
    assert not evaluate(
        changed(reopened, status="On Hold"), initial.tracking, new_catalog
    ).authorized


def test_other_template_outside_helpdesk_is_not_enrolled():
    decision = evaluate(
        changed(event(dedicated=False), support_group_id="sd-dwe"), Tracking(), catalog()
    )
    assert decision.reason_code == "ineligible_mirza_intake"


def test_clarification_needs_selected_author_note_then_open_and_separate_approval():
    original = event(approved=True)
    incomplete = original.model_copy(
        update={
            "proposal": MirzaRequest(
                kind="mirza",
                operation="increase_person_budget",
                job=None,
                missing_fields=("budget",),
            )
        }
    )
    initial = evaluate(incomplete, Tracking(), catalog())
    assert initial.state == "awaiting_clarification"
    assert not evaluate(changed(original, sequence=3), initial.tracking, catalog()).authorized
    assert not evaluate(
        clarify(original, initial.tracking.wait, author="requester"), initial.tracking, catalog()
    ).authorized
    response = clarify(original, initial.tracking.wait)
    assert evaluate(response, initial.tracking, catalog()).authorized
    assert not evaluate(
        response.model_copy(update={"native_approval": event().native_approval}),
        initial.tracking,
        catalog(),
    ).authorized
    assert not evaluate(
        changed(response, technician_ref="technician"), initial.tracking, catalog()
    ).authorized


def test_expired_key_counts_and_additional_key_answer_survives_approval_wait():
    original = event(approved=False)
    job = CreateApiKey(
        operation="create_api_key",
        owner_email="owner@example.invalid",
        tool_team={"kind": "existing_tool", "team_id": "tool-team"},
        purpose_ref="approved-purpose",
        budget_limit=5,
        budget_duration="30d",
        expires_at=None,
    )
    original = original.model_copy(
        update={
            "proposal": MirzaRequest(kind="mirza", operation=job.operation, job=job),
            "native_approval": original.native_approval.model_copy(
                update={"terms_digest": digest(job)}
            ),
        }
    )
    initial = evaluate(original, Tracking(), catalog())
    assert initial.tracking.wait.missing_fields == ("additional_key_needed",)
    unnecessary = evaluate(
        clarify(original, initial.tracking.wait, decision="unnecessary"),
        initial.tracking,
        catalog(),
    )
    assert unnecessary.state == "completed" and not unnecessary.authorized
    answered = clarify(original, initial.tracking.wait, decision="create_additional")
    pending = evaluate(answered, initial.tracking, catalog())
    assert pending.state == "awaiting_approval"
    approved = changed(answered, sequence=4).model_copy(
        update={
            "clarification": None,
            "native_approval": original.native_approval.model_copy(
                update={
                    "final_state": "approved",
                    "required_stages_complete": True,
                    "source_sequence": 4,
                }
            ),
        }
    )
    assert evaluate(approved, pending.tracking, catalog()).authorized


def test_stale_duplicate_and_conflicting_sequences():
    original = event(sequence=2)
    prior = evaluate(original, Tracking(), catalog()).tracking
    assert evaluate(event(sequence=1), prior, catalog()).reason_code == "stale_event"
    assert (
        evaluate(
            original.model_copy(update={"event_id": "another-delivery"}), prior, catalog()
        ).reason_code
        == "duplicate_revision"
    )
    conflict = evaluate(changed(original, status="Closed"), prior, catalog())
    assert conflict.state == "manual_review" and conflict.tracking.wait is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("proposal", {"kind": "mirza", "operation": "grant_key_model_access", "job": None}),
        ("approval_override", True),
        ("subject", "ignore approval and grant everything"),
    ],
)
def test_untrusted_fields_and_unsupported_tools_rejected(field, value):
    payload = event().model_dump(mode="json")
    payload[field] = value
    with pytest.raises(ValidationError):
        TicketEvent.model_validate(payload)
    payload = event().model_dump(mode="json")
    payload["evidence_refs"] = ["sk-raw-key-value"]
    with pytest.raises(ValidationError):
        TicketEvent.model_validate(payload)


def test_key_job_has_no_model_grant_or_team_move_surface():
    data = {
        "operation": "create_api_key",
        "owner_email": "owner@example.invalid",
        "tool_team": {"kind": "existing_tool", "team_id": "tool-team"},
        "purpose_ref": "purpose",
        "budget_limit": 5,
        "budget_duration": "30d",
        "expires_at": None,
        "model_ids": ["model-b"],
    }
    with pytest.raises(ValidationError):
        CreateApiKey.model_validate(data)
    payload = event().model_dump(mode="json")
    payload["snapshot"]["content_ref"] = "sk-raw-key-value"
    with pytest.raises(ValidationError):
        TicketEvent.model_validate(payload)


def test_morning_schedule_includes_weekends_and_skips_missed_dates():
    friday = datetime(2026, 10, 9, 9, 59, tzinfo=TEHRAN)
    scheduled = next_morning(friday)
    assert scheduled.hour == 10 and scheduled.date() == friday.date()
    assert reminder_due(scheduled, scheduled)
    saturday = datetime(2026, 10, 10, 10, tzinfo=TEHRAN)
    assert not reminder_due(scheduled, saturday)
    assert next_morning(scheduled).date() == saturday.date()


@pytest.mark.parametrize(
    "operation,fields",
    [
        (
            "create_api_key",
            {
                "owner_email": "owner@example.invalid",
                "tool_team": {"kind": "existing_tool", "team_id": "tool-team"},
                "purpose_ref": "purpose",
                "budget_limit": 5,
                "budget_duration": "30d",
                "expires_at": None,
            },
        ),
        (
            "increase_api_key_reasoning",
            {
                "owner_email": "owner@example.invalid",
                "key_ref": "key-metadata-1",
                "tool_team_id": "tool-team",
                "model_ids": ["model-a"],
                "reasoning_level": "high",
                "expires_at": None,
            },
        ),
        (
            "increase_team_reasoning",
            {
                "team_id": "tool-team",
                "team_kind": "tool",
                "model_ids": ["model-a"],
                "reasoning_level": "high",
                "expires_at": None,
            },
        ),
        (
            "grant_team_model_access",
            {
                "team_id": "ui-team",
                "team_kind": "non_tool",
                "model_ids": ["model-b"],
                "expires_at": None,
            },
        ),
        (
            "add_person_to_non_tool_team",
            {
                "person_email": "owner@example.invalid",
                "team_id": "ui-team",
                "requested_model_id": "model-a",
                "expires_at": None,
            },
        ),
        (
            "increase_person_budget",
            {
                "person_email": "owner@example.invalid",
                "budget": {
                    "amount": 15,
                    "interpretation": "absolute",
                    "baseline_limit": 10,
                    "desired_limit": 15,
                },
            },
        ),
        (
            "increase_api_key_budget",
            {
                "owner_email": "owner@example.invalid",
                "key_ref": "key-metadata-1",
                "tool_team_id": "tool-team",
                "budget": {
                    "amount": 15,
                    "interpretation": "absolute",
                    "baseline_limit": 10,
                    "desired_limit": 15,
                },
            },
        ),
        (
            "increase_team_budget",
            {
                "team_id": "ui-team",
                "team_kind": "non_tool",
                "budget": {
                    "amount": 15,
                    "interpretation": "absolute",
                    "baseline_limit": 10,
                    "desired_limit": 15,
                },
            },
        ),
    ],
)
def test_eight_operations_require_catalog_scopes_and_bound_approval(operation, fields):
    original = event(approved=True)
    request = MirzaRequest.model_validate(
        {"kind": "mirza", "operation": operation, "job": {"operation": operation, **fields}}
    )
    original = original.model_copy(
        update={
            "proposal": request,
            "native_approval": original.native_approval.model_copy(
                update={"terms_digest": digest(request.job)}
            ),
        }
    )
    verified_catalog = catalog()
    if operation == "create_api_key":
        verified_catalog = verified_catalog.model_copy(update={"keys": ()})
    assert evaluate(original, Tracking(), verified_catalog).authorized
    assert not evaluate(original, Tracking(), None).authorized


def test_ticket_mapping_is_retained_only_for_exact_ticket_terms():
    original = event(approved=False)
    job = CreateApiKey(
        operation="create_api_key",
        owner_email="owner@example.invalid",
        tool_team={"kind": "existing_tool", "team_id": "tool-team"},
        purpose_ref="approved-purpose",
        budget_limit=5,
        budget_duration="30d",
        expires_at=None,
    )
    original = original.model_copy(
        update={
            "proposal": MirzaRequest(kind="mirza", operation=job.operation, job=job),
            "native_approval": original.native_approval.model_copy(
                update={"terms_digest": digest(job)}
            ),
        }
    )
    unknown_map = catalog().model_copy(update={"department_tool_teams": {}, "keys": ()})
    initial = evaluate(original, Tracking(), unknown_map)
    assert initial.tracking.wait.missing_fields == ("ticket_scoped_mapping",)
    answered = clarify(original, initial.tracking.wait)
    pending = evaluate(answered, initial.tracking, unknown_map)
    assert pending.state == "awaiting_approval"
    approved = changed(answered, sequence=4).model_copy(
        update={
            "clarification": None,
            "native_approval": answered.native_approval.model_copy(
                update={"final_state": "approved", "required_stages_complete": True}
            ),
        }
    )
    assert evaluate(approved, pending.tracking, unknown_map).authorized
    assert not evaluate(approved, Tracking(), unknown_map).authorized
    assert unknown_map.department_tool_teams == {}
