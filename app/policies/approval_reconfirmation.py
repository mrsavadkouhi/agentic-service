"""Check terms reconfirmation separately from native approval and execution gates."""

from app.contracts.context import (
    ApprovalReconfirmationRead,
    ApprovalReopenRead,
    ApprovalTermsBaseline,
    ApprovalTermsNote,
)
from app.contracts.tickets import Digest, Ref


def reconfirmation(
    baseline: ApprovalTermsBaseline,
    current_terms_digest: Digest,
    configuration_digest: Digest,
    notes: tuple[ApprovalTermsNote, ...],
    reopen: ApprovalReopenRead | None,
    *,
    on_hold_status_id: Ref,
    open_status_id: Ref,
    current_source_sequence: int | None,
    current_order_verified: bool = False,
) -> ApprovalReconfirmationRead:
    # The caller supplies an immutable original-review record. Current approval
    # rows or observed ticket hashes cannot manufacture that historical record.
    reviewers = baseline.original_approver_ids
    if (
        not baseline.identity_verified
        or not baseline.history_verified
        or baseline.source_sequence is None
        or len(set(reviewers)) != len(reviewers)
        or configuration_digest != baseline.configuration_digest
        or len(notes) > 100
        or len({note.note_id for note in notes}) != len(notes)
        or on_hold_status_id == open_status_id
        or not current_order_verified
        or current_source_sequence is None
        or baseline.source_sequence > current_source_sequence
    ):
        return ApprovalReconfirmationRead(
            state="unverified", reason_code="original_approval_evidence_unverified"
        )
    if baseline.approved_terms_digest == current_terms_digest:
        return ApprovalReconfirmationRead(
            state="not_required", reason_code="approved_terms_unchanged"
        )
    confirmed = {}
    if (
        reopen is not None
        and reopen.history_verified
        and reopen.ticket_id == baseline.ticket_id
        and reopen.transition.before_status_id == on_hold_status_id
        and reopen.transition.after_status_id == open_status_id
        and baseline.source_sequence <= reopen.held_sequence
        and reopen.transition.source_sequence <= current_source_sequence
    ):
        for note in notes:
            if (
                note.ticket_id == baseline.ticket_id
                and note.approval_ref == baseline.approval_ref
                and note.author_id in reviewers
                and note.updated_by_id in {None, note.author_id}
                and note.author_verified
                and note.terms_verified
                and note.history_verified
                and note.terms_digest == current_terms_digest
                and note.source_sequence is not None
                and reopen.held_sequence < note.source_sequence
                < reopen.transition.source_sequence
            ):
                confirmed[note.author_id] = note.note_id
    missing = tuple(sorted(set(reviewers) - confirmed.keys()))
    return ApprovalReconfirmationRead(
        state="awaiting_confirmation" if missing else "confirmed",
        missing_approver_ids=missing,
        note_ids=tuple(sorted(confirmed.values())),
        reason_code="original_approver_confirmation_pending" if missing else "terms_reconfirmed",
    )
