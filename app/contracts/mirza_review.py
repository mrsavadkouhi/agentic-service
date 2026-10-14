"""Mirza policy previews are never executable approval or provisioning receipts."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from app.contracts.context import (
    ApprovalRead,
    ApprovalReopenRead,
    ApprovalReviewRequest,
    ApprovalTermsBaseline,
    ApprovalTermsNote,
    DeskPerson,
    MirzaIdentityRef,
)
from app.contracts.tickets import Contract, Digest, Job, Operation, Ref, Tracking

Change = Operation | Literal["create_tool_team", "add_owner_to_tool_team"]


class ReviewEvidence(Contract):
    baseline: ApprovalTermsBaseline | None = None
    review: ApprovalReviewRequest | None = None
    notes: tuple[ApprovalTermsNote, ...] = Field(default=(), max_length=100)
    reopen: ApprovalReopenRead | None = None
    configuration_digest: Digest | None = None
    on_hold_status_id: Ref | None = None
    open_status_id: Ref | None = None


class AccessPackage(Contract):
    job: Job
    scope: Literal["person", "api_key", "tool_team", "non_tool_team"]
    target_ref: MirzaIdentityRef
    owner_ref: MirzaIdentityRef | None = None
    team_id: Ref | None = None
    models_before: tuple[Ref, ...] = ()
    models_after: tuple[Ref, ...] = ()
    non_tool_memberships_before: tuple[Ref, ...] = ()
    non_tool_memberships_after: tuple[Ref, ...] = ()
    reasoning_before: dict[Ref, Ref] = Field(default_factory=dict)
    reasoning_after: dict[Ref, Ref] = Field(default_factory=dict)
    budget_before: Decimal | None = None
    budget_after: Decimal | None = None
    budget_duration: str | None = None
    expires_at: datetime | None = None
    changes: tuple[Change, ...] = ()


class ReviewIntent(Contract):
    kind: Literal["hold", "handoff", "clarification_dm", "approval_dm", "completion"]
    contact_refs: tuple[Ref, ...] = ()
    missing_fields: tuple[Ref, ...] = ()
    template_ref: Ref | None = None
    authorized: Literal[False] = False

    @model_validator(mode="after")
    def message_has_contact_and_template(self):
        if self.kind in {"clarification_dm", "approval_dm"} and (
            not self.contact_refs or self.template_ref is None
        ):
            raise ValueError("Message previews require a contact and template")
        return self


class MirzaReviewState(Contract):
    tracking: Tracking = Field(default_factory=Tracking)
    evidence: ReviewEvidence = Field(default_factory=ReviewEvidence)
    dwe_contact: DeskPerson | None = None
    dwe_observed_at: datetime | None = None
    dwe_source_digest: Digest | None = None
    first_approval_observation: ApprovalRead | None = None


class MirzaReviewResult(Contract):
    state: Literal["blocked", "no_op", "awaiting_clarification", "awaiting_approval", "ready"]
    reason_code: Ref
    package: AccessPackage | None = None
    intents: tuple[ReviewIntent, ...] = ()
    next_state: MirzaReviewState = Field(default_factory=MirzaReviewState)
    evidence_refs: tuple[Ref, ...] = ()
    completion_explanation_ref: Ref | None = None
    authorized: Literal[False] = False
    handoff_verified: Literal[False] = False
    reminder_hour: Literal[10] = 10
    reminder_timezone: Literal["Asia/Tehran"] = "Asia/Tehran"


class MirzaReviewRequest(Contract):
    observation_id: Digest


class MirzaReminderDraft(Contract):
    draft_id: Digest
    ticket_id: Ref
    contact_ref: Ref
    day: date
    action_refs: tuple[Ref, ...]
    authorized: Literal[False] = False


@dataclass
class MirzaReviewStart:
    tenant_id: str
    ticket_id: str
    observation_id: str
    mirza_queue: str


@dataclass
class MirzaReviewReceipt:
    review_id: str
    state: str
    reason_code: str
