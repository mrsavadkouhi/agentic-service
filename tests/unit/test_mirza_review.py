from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.contracts.context import (
    ApprovalReopenRead,
    ApprovalTermsBaseline,
    ApprovalTermsNote,
    BudgetRead,
    MirzaInventory,
    MirzaKey,
    MirzaTeam,
    MirzaUser,
    ReasoningRead,
    StatusTransition,
)
from app.contracts.mirza_review import (
    AccessPackage,
    MirzaReviewResult,
    MirzaReviewStart,
    MirzaReviewState,
    ReviewEvidence,
    ReviewIntent,
)
from app.contracts.tickets import ClarificationResponse, Job, MirzaRequest, NoOp, digest
from app.policies.mirza_review import access_package, reminder_drafts, review_mirza
from app.policies.synthetic_events import catalog, event
from app.storage.mirza_reviews import MirzaReviewRepository, ReviewConflict
from app.storage.models import Base
from app.storage.observations import InferenceBudget
from app.storage.tickets import FixtureEffect, TicketAction, TicketInbox

NOW = datetime(2026, 10, 14, tzinfo=UTC)


def inventory():
    budget = BudgetRead(limit=Decimal(10), spend=Decimal(3), duration="30d", reset_at=NOW)
    reasoning = ReasoningRead(all_models=None, models={})
    return MirzaInventory(
        users=(MirzaUser(user_id="mirza-owner", email="owner@example.invalid",
                         team_ids=("tool-team",), budget=budget, reasoning=reasoning),),
        teams=tuple(MirzaTeam(team_id=t.team_id, alias=t.alias, kind=t.kind, models=t.models,
                              budget=budget, reasoning=reasoning) for t in catalog().teams),
        keys=(MirzaKey(key_ref="key-metadata-1", owner_id="mirza-owner", team_id="tool-team",
                       expired=True, expires_at=NOW, budget=budget, reasoning=reasoning),),
        served_models=catalog().model_ids,
    )


def evidence(normalized):
    return ReviewEvidence(
        baseline=ApprovalTermsBaseline(
            ticket_id=normalized.ticket_id, approval_ref="approval-history",
            configuration_digest="c" * 64, original_approver_ids=("approver",),
            approved_terms_digest=digest(normalized.proposal.job), source_sequence=1,
            identity_verified=True, history_verified=True,
        ), configuration_digest="c" * 64, on_hold_status_id="hold", open_status_id="open",
    )


def with_job(job, **event_changes):
    normalized = event(approved=True).model_copy(update=event_changes)
    proposal = MirzaRequest(kind="mirza", operation=job.operation, job=job)
    return normalized.model_copy(update={
        "proposal": proposal,
        "native_approval": normalized.native_approval.model_copy(update={
            "terms_digest": digest(job),
        }),
    })


JOBS = [
    {"operation": "create_api_key", "owner_email": "owner@example.invalid",
     "tool_team": {"kind": "existing_tool", "team_id": "tool-team"},
     "purpose_ref": "client", "budget_limit": "5", "budget_duration": "30d", "expires_at": None},
    {"operation": "increase_api_key_reasoning", "owner_email": "owner@example.invalid",
     "key_ref": "key-metadata-1", "tool_team_id": "tool-team", "model_ids": ["model-a"],
     "reasoning_level": "high", "expires_at": None},
    {"operation": "increase_team_reasoning", "team_id": "ui-team", "team_kind": "non_tool",
     "model_ids": ["model-a"], "reasoning_level": "high", "expires_at": None},
    {"operation": "grant_team_model_access", "team_id": "tool-team", "team_kind": "tool",
     "model_ids": ["model-b"], "expires_at": None},
    {"operation": "add_person_to_non_tool_team", "person_email": "owner@example.invalid",
     "team_id": "ui-team", "requested_model_id": "model-a", "expires_at": None},
    {"operation": "increase_person_budget", "person_email": "owner@example.invalid",
     "budget": {"amount": "5", "interpretation": "delta", "baseline_limit": "10",
                "desired_limit": "15"}},
    {"operation": "increase_api_key_budget", "owner_email": "owner@example.invalid",
     "key_ref": "key-metadata-1", "tool_team_id": "tool-team",
     "budget": {"amount": "5", "interpretation": "delta", "baseline_limit": "10",
                "desired_limit": "15"}},
    {"operation": "increase_team_budget", "team_id": "ui-team", "team_kind": "non_tool",
     "budget": {"amount": "5", "interpretation": "delta", "baseline_limit": "10",
                "desired_limit": "15"}},
]


@pytest.mark.parametrize("fields", JOBS, ids=[j["operation"] for j in JOBS])
def test_eight_exact_jobs_produce_unauthorized_minimal_previews(fields):
    job = TypeAdapter(Job).validate_python(fields)
    normalized = with_job(job)
    source, current_catalog = inventory(), catalog()
    if job.operation == "create_api_key":
        source = source.model_copy(update={"keys": ()})
        current_catalog = current_catalog.model_copy(update={"keys": ()})
    result = review_mirza(normalized, MirzaReviewState(), current_catalog, source,
                          evidence(normalized))
    assert result.state == "ready" and result.package.changes == (job.operation,)
    assert result.authorized is False and result.next_state.tracking.pending_action_id is None
    assert result.package.job == job
    if job.operation == "increase_api_key_budget":
        assert result.package.scope == "api_key" and result.package.budget_after == 15
        assert source.users[0].budget.limit == 10 and source.teams[0].budget.limit == 10
    if job.operation == "add_person_to_non_tool_team":
        assert result.package.non_tool_memberships_after == ("ui-team",)
        assert result.package.models_after == ("model-a",)
        assert source.users[0].team_ids == ("tool-team",)


def test_key_reasoning_preserves_higher_team_ceiling_and_never_inherits_personal_grants():
    normalized = with_job(TypeAdapter(Job).validate_python(JOBS[1]))
    source = inventory()
    high = ReasoningRead(all_models="xhigh", models={})
    source = source.model_copy(update={"users": (source.users[0].model_copy(update={
        "reasoning": high,
    }),)})
    assert access_package(normalized, catalog(), source).reasoning_before == {"model-a": "medium"}
    source = source.model_copy(update={"teams": (source.teams[0].model_copy(update={
        "reasoning": high,
    }), source.teams[1])})
    result = review_mirza(normalized, MirzaReviewState(), catalog(), source, evidence(normalized))
    assert result.state == "no_op" and result.package.reasoning_after == {"model-a": "xhigh"}


def test_membership_and_team_grants_are_idempotent_and_preserve_existing_models():
    normalized = with_job(TypeAdapter(Job).validate_python(JOBS[4]))
    source = inventory()
    source = source.model_copy(update={"users": (source.users[0].model_copy(update={
        "team_ids": ("tool-team", "ui-team"),
    }),)})
    assert access_package(normalized, catalog(), source).changes == ()
    grant = with_job(TypeAdapter(Job).validate_python(JOBS[3]))
    assert access_package(grant, catalog(), source).models_after == ("model-a", "model-b")


@pytest.mark.parametrize("limit", ["15", "20"])
def test_budget_retry_keeps_absolute_target_and_preserves_larger_limits(limit):
    normalized = event(approved=True)
    source = inventory()
    source = source.model_copy(update={"users": (source.users[0].model_copy(update={
        "budget": source.users[0].budget.model_copy(update={"limit": Decimal(limit)}),
    }),)})
    result = review_mirza(normalized, MirzaReviewState(), catalog(), source, evidence(normalized))
    assert result.state == "no_op" and result.package.budget_after == Decimal(limit)
    assert result.package.budget_duration == "30d" and source.users[0].budget.spend == 3


@pytest.mark.parametrize("case", ["wrong_owner", "wrong_team", "budget_changed", "duplicate_owner"])
def test_stale_scope_or_budget_cannot_form_a_package(case):
    normalized = with_job(TypeAdapter(Job).validate_python(JOBS[6]))
    source = inventory()
    if case in {"wrong_owner", "wrong_team"}:
        key = source.keys[0].model_copy(update={
            "owner_id" if case == "wrong_owner" else "team_id": "ui-team",
        })
        source = source.model_copy(update={"keys": (key,)})
    elif case == "budget_changed":
        source = source.model_copy(update={"keys": (source.keys[0].model_copy(update={
            "budget": source.keys[0].budget.model_copy(update={"limit": Decimal(11)}),
        }),)})
    else:
        source = source.model_copy(update={"users": source.users + source.users})
    result = review_mirza(normalized, MirzaReviewState(), catalog(), source, evidence(normalized))
    assert result.state == "awaiting_clarification" and result.package is None


def test_expired_duplicate_key_requires_note_open_decision_instead_of_generation():
    normalized = with_job(TypeAdapter(Job).validate_python(JOBS[0]))
    result = review_mirza(normalized, MirzaReviewState(), catalog(), inventory(),
                          evidence(normalized))
    assert result.state == "awaiting_clarification"
    assert result.intents[1].missing_fields == ("additional_key_needed",)
    assert result.intents[1].contact_refs == ("incharge",)


def test_verified_duplicate_refusal_has_no_key_change_and_preserves_completion_explanation():
    normalized = with_job(TypeAdapter(Job).validate_python(JOBS[0]))
    first = review_mirza(normalized, MirzaReviewState(), catalog(), inventory(),
                         evidence(normalized))
    response = ClarificationResponse(
        cycle_id=first.next_state.tracking.wait.cycle_id, note_ref="decline-note",
        note_author_ref="incharge", note_sequence=2, open_event_ref="open-3",
        open_actor_ref="incharge", open_sequence=3,
        supplied_terms_digest=digest(normalized.proposal.job),
        history_verified=True, additional_key_decision="unnecessary", explanation_ref="explanation",
    )
    next_event = normalized.model_copy(update={"event_id": "revision-4", "clarification": response,
        "snapshot": normalized.snapshot.model_copy(update={"source_sequence": 4,
                                                           "revision_id": "revision-4"})})
    result = review_mirza(next_event, first.next_state, catalog(), inventory(),
                          evidence(normalized))
    assert result.reason_code == "additional_key_unnecessary" and result.state == "no_op"
    assert result.package.changes == () and result.completion_explanation_ref == "explanation"
    assert result.intents[0].contact_refs == ("owner", "incharge")
    # Declining creation grants nothing and does not need a historical terms approval.
    unbound = first.next_state.model_copy(update={"evidence": ReviewEvidence()})
    result = review_mirza(next_event, unbound, catalog(), inventory())
    assert result.reason_code == "additional_key_unnecessary" and result.package.changes == ()


def test_operator_cancellation_stops_renewal_and_all_message_drafts():
    normalized = event(approved=True)
    state = MirzaReviewState()
    state = state.model_copy(update={"tracking": state.tracking.model_copy(update={
        "cancelled": True,
    })})
    result = review_mirza(normalized, state, catalog(), inventory(), evidence(normalized))
    assert result.state == "no_op" and result.package is None and result.intents == ()


@pytest.mark.parametrize("case", ["lifecycle", "unknown", "assigned_fallback", "outside_helpdesk"])
def test_intake_boundaries_prevent_package_or_notification_drafts(case):
    normalized = event(dedicated=False)
    changes = {}
    if case in {"lifecycle", "unknown"}:
        changes["process"] = normalized.snapshot.process.model_copy(update={"association": case})
    elif case == "assigned_fallback":
        changes["technician_ref"] = "technician"
    else:
        changes["support_group_id"] = "sd-network"
    normalized = normalized.model_copy(update={"snapshot": normalized.snapshot.model_copy(
        update=changes
    )})
    result = review_mirza(normalized, MirzaReviewState(), catalog(), inventory())
    assert result.package is None and result.intents == ()


def test_unsupported_key_model_or_move_request_is_noop_and_job_contract_rejects_it():
    for operation in ("grant_api_key_model_access", "move_api_key", "add_key_to_non_tool_team"):
        with pytest.raises(ValidationError):
            TypeAdapter(Job).validate_python({"operation": operation})
    normalized = event().model_copy(update={
        "proposal": NoOp(kind="no_op", reason_code="unsupported"),
    })
    assert review_mirza(normalized, MirzaReviewState(), catalog(), inventory()).state == "no_op"
    package = access_package(event(), catalog(), inventory())
    with pytest.raises(ValidationError):
        AccessPackage.model_validate({
            **package.model_dump(), "changes": ["grant_api_key_model_access"],
        })


def test_changed_budget_requires_persisted_review_then_original_reviewer_note_and_open():
    normalized = event(sequence=6, approved=True)
    original = evidence(normalized)
    original = original.model_copy(update={"baseline": original.baseline.model_copy(update={
        "approved_terms_digest": "a" * 64,
    })})
    first = review_mirza(normalized, MirzaReviewState(), catalog(), inventory(), original)
    assert first.state == "awaiting_approval" and first.next_state.evidence.review is not None
    notes = (ApprovalTermsNote(
        ticket_id=normalized.ticket_id, approval_ref="approval-history", note_id="note",
        author_id="approver", content_digest="d" * 64,
        terms_digest=digest(normalized.proposal.job), source_sequence=4,
        author_verified=True, terms_verified=True, history_verified=True,
    ),)
    reopen = ApprovalReopenRead(ticket_id=normalized.ticket_id, held_sequence=2,
        history_verified=True, transition=StatusTransition(
            event_id="open-5", actor_id="technician", occurred_at=NOW, source_sequence=5,
            before_status_id="hold", after_status_id="open",
        ))
    updated = first.next_state.evidence.model_copy(update={"notes": notes, "reopen": reopen})
    # A new source event is needed; policy previews do not erase duplicate/revision fences.
    next_event = event(sequence=7, approved=True)
    result = review_mirza(next_event, first.next_state, catalog(), inventory(), updated)
    assert result.state == "ready" and result.authorized is False
    for changes in ({"author_id": "technician"}, {"terms_verified": False},
                    {"source_sequence": 2}, {"source_sequence": 5}):
        invalid = updated.model_copy(update={"notes": (notes[0].model_copy(update=changes),)})
        checked = review_mirza(next_event, first.next_state, catalog(), inventory(), invalid)
        assert checked.state != "ready"
    incomplete = next_event.model_copy(update={
        "native_approval": next_event.native_approval.model_copy(update={
            "required_stages_complete": False,
        }),
    })
    checked = review_mirza(incomplete, first.next_state, catalog(), inventory(), updated)
    assert checked.state != "ready"


@pytest.mark.parametrize("case", ["missing", "unverified", "wrong_ticket", "wrong_config"])
def test_approved_native_rows_cannot_manufacture_original_terms_authority(case):
    normalized = event(approved=True)
    original = evidence(normalized)
    if case == "missing":
        original = original.model_copy(update={"baseline": None})
    elif case == "wrong_config":
        original = original.model_copy(update={"configuration_digest": "b" * 64})
    else:
        original = original.model_copy(update={"baseline": original.baseline.model_copy(update={
            "identity_verified" if case == "unverified" else "ticket_id":
            False if case == "unverified" else "another-ticket",
        })})
    result = review_mirza(normalized, MirzaReviewState(), catalog(), inventory(), original)
    assert result.state == "blocked"


@pytest.fixture
def repository():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield MirzaReviewRepository(engine)
    engine.dispose()


def test_review_commit_is_idempotent_and_isolated_from_execution_and_spend(repository):
    request = MirzaReviewStart("servicedesk", "1", "a" * 64, "mirza")
    result = MirzaReviewResult(state="blocked", reason_code="fixture")
    first = repository.commit(request, 0, result)
    assert repository.commit(request, 0, result) == first
    assert repository.load("servicedesk", "1")[0] == 1
    changed = MirzaReviewStart("servicedesk", "1", "b" * 64, "mirza")
    with pytest.raises(ReviewConflict, match="revision"):
        repository.commit(changed, 0, result)
    repository.commit(changed, 1, result)
    with Session(repository.engine) as session:
        for table in (TicketInbox, TicketAction, FixtureEffect, InferenceBudget):
            assert session.scalar(select(func.count()).select_from(table)) == 0


def test_review_storage_freezes_original_approval_identity_and_terms_baseline(repository):
    normalized = event(approved=True)
    state = MirzaReviewState(evidence=evidence(normalized))
    result = MirzaReviewResult(state="blocked", reason_code="fixture", next_state=state)
    repository.commit(MirzaReviewStart("servicedesk", "1", "a" * 64, "mirza"), 0, result)
    changed = result.model_copy(update={"next_state": state.model_copy(update={
        "evidence": state.evidence.model_copy(update={"baseline": None}),
    })})
    with pytest.raises(ReviewConflict, match="baseline"):
        repository.commit(MirzaReviewStart("servicedesk", "1", "b" * 64, "mirza"), 1, changed)


def test_daily_reminder_drafts_combine_actions_stop_with_gate_and_use_tehran_time():
    pending = MirzaReviewResult(state="awaiting_approval", reason_code="fixture", intents=(
        ReviewIntent(kind="approval_dm", contact_refs=("incharge",),
                     template_ref="mirza-approval-v1"),
        ReviewIntent(kind="clarification_dm", contact_refs=("incharge",),
                     template_ref="mirza-clarification-v1"),
    ))
    before = datetime(2026, 10, 16, 6, 29, tzinfo=UTC)
    morning = datetime(2026, 10, 16, 6, 30, tzinfo=UTC)  # Friday at 10:00 Tehran.
    assert reminder_drafts("1", pending, before) == ()
    first = reminder_drafts("1", pending, morning)
    assert len(first) == 1 and len(first[0].action_refs) == 2 and not first[0].authorized
    assert first == reminder_drafts("1", pending, morning.replace(hour=12))
    assert first[0].draft_id != reminder_drafts("1", pending, morning.replace(day=17))[0].draft_id
    assert reminder_drafts("1", pending.model_copy(update={"state": "ready"}), morning) == ()
    with pytest.raises(ValueError, match="timezone"):
        reminder_drafts("1", pending, morning.replace(tzinfo=None))
