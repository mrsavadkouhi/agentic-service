from datetime import UTC, datetime

import pytest

from app.contracts.context import (
    ApprovalReopenRead,
    ApprovalTermsBaseline,
    ApprovalTermsNote,
    StatusTransition,
)
from app.policies.approval_reconfirmation import reconfirmation


def evidence():
    baseline = ApprovalTermsBaseline(
        ticket_id="ticket-1", approval_ref="original-review",
        configuration_digest="c" * 64, original_approver_ids=("approver-1", "approver-2"),
        approved_terms_digest="a" * 64, source_sequence=1,
        identity_verified=True, history_verified=True,
    )
    notes = tuple(
        ApprovalTermsNote(
            ticket_id="ticket-1", approval_ref="original-review", note_id=f"note-{i}",
            author_id=f"approver-{i}", terms_digest="b" * 64, source_sequence=i + 2,
            content_digest=str(i) * 64,
            author_verified=True, terms_verified=True, history_verified=True,
        ) for i in (1, 2)
    )
    reopen = ApprovalReopenRead(
        ticket_id="ticket-1", held_sequence=2, history_verified=True,
        transition=StatusTransition(
            event_id="open-5", actor_id="technician",
            occurred_at=datetime(2026, 10, 12, tzinfo=UTC),
            source_sequence=5, before_status_id="hold", after_status_id="open",
        ),
    )
    return baseline, notes, reopen


def check(baseline, notes, reopen, **changes):
    inputs = dict(
        current_terms_digest="b" * 64, configuration_digest="c" * 64,
        on_hold_status_id="hold", open_status_id="open",
        current_source_sequence=6, current_order_verified=True,
    )
    inputs.update(changes)
    return reconfirmation(baseline, notes=notes, reopen=reopen, **inputs)


@pytest.mark.parametrize("original_terms", ["a" * 64, None])
def test_changed_and_legacy_terms_require_every_original_approver(original_terms):
    baseline, notes, reopen = evidence()
    baseline = baseline.model_copy(update={"approved_terms_digest": original_terms})
    assert check(baseline, (), reopen).missing_approver_ids == ("approver-1", "approver-2")
    pending = check(baseline, notes[:1], reopen)
    assert pending.state == "awaiting_confirmation"
    assert pending.missing_approver_ids == ("approver-2",)
    confirmed = check(baseline, notes, reopen)
    assert confirmed.state == "confirmed" and confirmed.note_ids == ("note-1", "note-2")


def test_unchanged_recorded_terms_need_no_reconfirmation():
    baseline, _, _ = evidence()
    result = check(baseline, (), None, current_terms_digest="a" * 64)
    assert result.state == "not_required" and result.note_ids == ()


@pytest.mark.parametrize("change", [
    {"author_id": "technician"}, {"ticket_id": "ticket-2"},
    {"approval_ref": "different-review"}, {"terms_digest": "d" * 64},
    {"updated_by_id": "technician"}, {"author_verified": False},
    {"terms_verified": False}, {"history_verified": False},
    {"source_sequence": None}, {"source_sequence": 2}, {"source_sequence": 5},
])
def test_unrelated_stale_edited_or_unverified_note_cannot_confirm_terms(change):
    baseline, notes, reopen = evidence()
    result = check(baseline, (notes[0].model_copy(update=change), notes[1]), reopen)
    assert result.state == "awaiting_confirmation"
    assert result.missing_approver_ids == ("approver-1",)


@pytest.mark.parametrize("change", [
    {"identity_verified": False}, {"history_verified": False}, {"source_sequence": None},
    {"source_sequence": 7}, {"original_approver_ids": ("approver-1", "approver-1")},
])
def test_unverified_original_review_cannot_be_replaced_by_current_notes(change):
    baseline, notes, reopen = evidence()
    result = check(baseline.model_copy(update=change), notes, reopen)
    assert result.state == "unverified"


@pytest.mark.parametrize("change", [
    {"configuration_digest": "d" * 64}, {"current_order_verified": False},
    {"current_source_sequence": None}, {"open_status_id": "hold"},
])
def test_configuration_change_or_unverified_current_order_blocks_confirmation(change):
    assert check(*evidence(), **change).state == "unverified"


@pytest.mark.parametrize("case", [
    "absent", "unverified", "wrong_ticket", "wrong_status", "future", "old_hold", "new_hold",
])
def test_notes_need_the_matching_verified_hold_to_open_transition(case):
    baseline, notes, reopen = evidence()
    if case == "absent":
        reopen = None
    elif case == "unverified":
        reopen = reopen.model_copy(update={"history_verified": False})
    elif case == "wrong_ticket":
        reopen = reopen.model_copy(update={"ticket_id": "ticket-2"})
    elif case == "old_hold":
        reopen = reopen.model_copy(update={"held_sequence": 0})
    elif case == "new_hold":
        reopen = reopen.model_copy(update={"held_sequence": 4})
    else:
        transition = reopen.transition.model_copy(update=(
            {"after_status_id": "resolved"} if case == "wrong_status" else {"source_sequence": 7}
        ))
        reopen = reopen.model_copy(update={"transition": transition})
    assert check(baseline, notes, reopen).state == "awaiting_confirmation"


def test_duplicate_note_identity_and_unbounded_note_input_are_unverified():
    baseline, notes, reopen = evidence()
    assert check(baseline, (notes[0], notes[0]), reopen).state == "unverified"
    assert check(baseline, notes * 51, reopen).state == "unverified"
