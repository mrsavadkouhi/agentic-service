"""Normalized connector data. Raw ticket bodies and secrets stay outside history."""

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
    model_validator,
)


def opaque_reference(value: str) -> str:
    if value.startswith("sk-"):
        raise ValueError("Use opaque references, never raw API keys")
    return value


Ref = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,199}$"),
    AfterValidator(opaque_reference),
]
Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
Email = Annotated[str, StringConstraints(pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", max_length=254)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    @field_validator("email", "owner_email", "person_email", mode="before", check_fields=False)
    @classmethod
    def normalize_identity(cls, value, info: ValidationInfo):
        if info.field_name in {"email", "owner_email", "person_email"} and isinstance(value, str):
            return value.strip().casefold()
        return value

    @field_validator("*")
    @classmethod
    def reject_raw_key(cls, value):
        if isinstance(value, str) and value.startswith("sk-"):
            raise ValueError("Use opaque references, never raw API keys")
        return value

    @model_validator(mode="after")
    def aware_timestamps(self):
        for value in self.__dict__.values():
            if isinstance(value, datetime) and value.tzinfo is None:
                raise ValueError("All timestamps require a timezone")
        return self


def digest(value: Contract) -> str:
    def normalize(item):
        if isinstance(item, Decimal):
            return format(item.normalize(), "f")
        if isinstance(item, datetime):
            return item.astimezone(UTC).isoformat()
        if isinstance(item, dict):
            return {key: normalize(val) for key, val in item.items()}
        if isinstance(item, (list, tuple)):
            return [normalize(val) for val in item]
        return item

    payload = json.dumps(normalize(value.model_dump()), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def stable_id(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()


class WorkflowState(StrEnum):
    RECEIVED = "received"
    EVALUATING = "evaluating"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    REJECTED = "rejected"
    MANUAL_REVIEW = "manual_review"
    CANCELLED = "cancelled"


class Person(Contract):
    person_id: Ref
    email: Email
    department: str | None
    active: bool

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().casefold()


class Team(Contract):
    team_id: Ref
    alias: Ref
    kind: Literal["tool", "non_tool"]
    models: tuple[Ref, ...]


class KeyMetadata(Contract):
    key_ref: Ref
    owner_email: Email
    tool_team_id: Ref
    expired: bool


class Catalog(Contract):
    version: Ref
    environment: Literal["synthetic", "production"]
    support_groups: dict[Literal["Helpdesk", "Network", "DWE", "VOIP"], Ref]
    dedicated_templates: dict[Literal["Mirza Access Request", "Mirza API Key"], Ref]
    people: tuple[Person, ...]
    teams: tuple[Team, ...]
    keys: tuple[KeyMetadata, ...]
    model_ids: tuple[Ref, ...]
    reasoning_levels: tuple[Ref, ...]
    department_tool_teams: dict[str, Ref]
    dwe_incharge_ref: Ref | None

    @model_validator(mode="after")
    def coherent_catalog(self):
        if set(self.support_groups) != {"Helpdesk", "Network", "DWE", "VOIP"}:
            raise ValueError("Four support groups required")
        groups = list(self.support_groups.values())
        if len(set(groups)) != 4:
            raise ValueError("Support-group IDs must be distinct")
        for values in (
            [p.person_id for p in self.people],
            [t.team_id for t in self.teams],
            [k.key_ref for k in self.keys],
        ):
            if len(values) != len(set(values)):
                raise ValueError("Duplicate catalog identities")
        if set(groups).intersection(t.team_id for t in self.teams):
            raise ValueError("Support groups and Mirza teams use separate identities")
        if set(self.dedicated_templates) != {"Mirza Access Request", "Mirza API Key"}:
            raise ValueError("Both dedicated template identities are required")
        if len(set(self.dedicated_templates.values())) != 2:
            raise ValueError("Dedicated templates must differ")
        emails = {p.email for p in self.people}
        if len(emails) != len(self.people):
            raise ValueError("Ambiguous email identity")
        teams = {t.team_id: t for t in self.teams}
        if any(not set(t.models).issubset(self.model_ids) for t in self.teams):
            raise ValueError("Unknown team models")
        if any(
            value not in teams or teams[value].kind != "tool"
            for value in self.department_tool_teams.values()
        ):
            raise ValueError("Department mappings require existing Tool teams")
        if any(
            k.owner_email not in emails
            or k.tool_team_id not in teams
            or teams[k.tool_team_id].kind != "tool"
            for k in self.keys
        ):
            raise ValueError("Key metadata requires verified owner and one Tool team")
        return self


class ProcessContext(Contract):
    association: Literal["standalone", "non_lifecycle", "lifecycle", "unknown"]
    kind: Literal["onboarding", "offboarding", "internal_transfer"] | None = None
    parent_ticket_id: Ref | None = None
    child_ticket_ids: tuple[Ref, ...] = ()
    evidence_ref: Ref | None = None

    @model_validator(mode="after")
    def lifecycle_requires_evidence(self):
        if self.association == "lifecycle" and (not self.kind or not self.evidence_ref):
            raise ValueError("Lifecycle association requires process evidence")
        return self


class TicketSnapshot(Contract):
    revision_id: Ref
    source_sequence: int | None = Field(ge=0)
    source_order_verified: bool
    requester_ref: Ref
    intended_person_ref: Ref | None
    support_group_id: Ref
    technician_ref: Ref | None
    template_id: Ref
    category_id: Ref | None
    status: Literal["Open", "On Hold", "Resolved", "Closed", "Cancelled"]
    source: Literal["email", "servicedesk_ui"]
    source_updated_at: datetime
    content_ref: Ref
    content_digest: Digest
    process: ProcessContext

    @field_validator("source_updated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Source timestamps require a timezone")
        return value


class Budget(Contract):
    amount: Decimal = Field(gt=0, allow_inf_nan=False)
    interpretation: Literal["absolute", "delta"]
    baseline_limit: Decimal = Field(ge=0, allow_inf_nan=False)
    desired_limit: Decimal = Field(gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def absolute_retry_target(self):
        expected = (
            self.amount if self.interpretation == "absolute" else self.baseline_limit + self.amount
        )
        if self.desired_limit != expected or self.desired_limit <= self.baseline_limit:
            raise ValueError("Budget requires a consistent increasing absolute target")
        return self


class NewToolTeam(Contract):
    kind: Literal["new_tool"]
    alias: Ref
    initial_model_ids: tuple[Ref, ...] = Field(min_length=1)
    initial_budget: Decimal = Field(gt=0, allow_inf_nan=False)
    budget_duration: Annotated[str, StringConstraints(pattern=r"^[1-9][0-9]*[smhdw]$")]


class ExistingToolTeam(Contract):
    kind: Literal["existing_tool"]
    team_id: Ref


class CreateApiKey(Contract):
    operation: Literal["create_api_key"]
    owner_email: Email
    tool_team: Annotated[ExistingToolTeam | NewToolTeam, Field(discriminator="kind")]
    purpose_ref: Ref
    budget_limit: Decimal = Field(gt=0, allow_inf_nan=False)
    budget_duration: Annotated[str, StringConstraints(pattern=r"^[1-9][0-9]*[smhdw]$")]
    expires_at: datetime | None


class IncreaseApiKeyReasoning(Contract):
    operation: Literal["increase_api_key_reasoning"]
    owner_email: Email
    key_ref: Ref
    tool_team_id: Ref
    model_ids: tuple[Ref, ...] = Field(min_length=1)
    reasoning_level: Ref
    expires_at: datetime | None


class IncreaseTeamReasoning(Contract):
    operation: Literal["increase_team_reasoning"]
    team_id: Ref
    team_kind: Literal["tool", "non_tool"]
    model_ids: tuple[Ref, ...] = Field(min_length=1)
    reasoning_level: Ref
    expires_at: datetime | None


class GrantTeamModelAccess(Contract):
    operation: Literal["grant_team_model_access"]
    team_id: Ref
    team_kind: Literal["tool", "non_tool"]
    model_ids: tuple[Ref, ...] = Field(min_length=1)
    expires_at: datetime | None


class AddPersonToNonToolTeam(Contract):
    operation: Literal["add_person_to_non_tool_team"]
    person_email: Email
    team_id: Ref
    requested_model_id: Ref
    expires_at: datetime | None


class IncreasePersonBudget(Contract):
    operation: Literal["increase_person_budget"]
    person_email: Email
    budget: Budget


class IncreaseApiKeyBudget(Contract):
    operation: Literal["increase_api_key_budget"]
    owner_email: Email
    key_ref: Ref
    tool_team_id: Ref
    budget: Budget


class IncreaseTeamBudget(Contract):
    operation: Literal["increase_team_budget"]
    team_id: Ref
    team_kind: Literal["tool", "non_tool"]
    budget: Budget


Job = Annotated[
    CreateApiKey
    | IncreaseApiKeyReasoning
    | IncreaseTeamReasoning
    | GrantTeamModelAccess
    | AddPersonToNonToolTeam
    | IncreasePersonBudget
    | IncreaseApiKeyBudget
    | IncreaseTeamBudget,
    Field(discriminator="operation"),
]

Operation = Literal[
    "create_api_key",
    "increase_api_key_reasoning",
    "increase_team_reasoning",
    "grant_team_model_access",
    "add_person_to_non_tool_team",
    "increase_person_budget",
    "increase_api_key_budget",
    "increase_team_budget",
]


class GroupCorrection(Contract):
    kind: Literal["correct_support_group"]
    destination_group_id: Ref


class NoOp(Contract):
    kind: Literal["no_op"]
    reason_code: Ref


class MirzaRequest(Contract):
    kind: Literal["mirza"]
    operation: Operation
    job: Job | None
    missing_fields: tuple[Ref, ...] = ()

    @model_validator(mode="after")
    def require_complete_or_missing(self):
        if self.job and (self.job.operation != self.operation or self.missing_fields):
            raise ValueError("Job operation/terms conflict")
        if self.job is None and not self.missing_fields:
            raise ValueError("Incomplete intent must identify missing fields")
        return self


Decision = Annotated[NoOp | GroupCorrection | MirzaRequest, Field(discriminator="kind")]


class NativeApproval(Contract):
    template_id: Ref
    final_state: Literal["pending", "approved", "rejected"]
    required_stages_complete: bool
    terms_digest: Digest
    source_sequence: int = Field(ge=0)
    history_verified: bool
    configuration_ref: Ref
    evidence_ref: Ref
    pending_approver_refs: tuple[Ref, ...] = ()


class FallbackApproval(Contract):
    terms_digest: Digest
    group_id: Ref
    held_event_ref: Ref
    held_sequence: int = Field(ge=0)
    open_event_ref: Ref
    open_sequence: int = Field(ge=0)
    actor_ref: Ref
    history_verified: bool


class ClarificationResponse(Contract):
    cycle_id: Digest
    note_ref: Ref
    note_author_ref: Ref
    note_sequence: int = Field(ge=0)
    open_event_ref: Ref
    open_actor_ref: Ref
    open_sequence: int = Field(ge=0)
    supplied_terms_digest: Digest
    history_verified: bool
    additional_key_decision: Literal["create_additional", "unnecessary"] | None = None
    explanation_ref: Ref | None = None


class TicketEvent(Contract):
    tenant_id: Ref
    ticket_id: Ref
    event_id: Ref
    data_kind: Literal["synthetic", "servicedesk"]
    catalog_version: Ref
    policy_version: Ref
    model_version: Ref
    prompt_version: Ref
    evidence_refs: tuple[Ref, ...] = Field(min_length=1)
    snapshot: TicketSnapshot
    proposal: Decision
    native_approval: NativeApproval | None = None
    fallback_approval: FallbackApproval | None = None
    clarification: ClarificationResponse | None = None

    def workflow_id(self) -> str:
        return "ticket-" + stable_id(self.tenant_id, self.ticket_id)


class WaitCycle(Contract):
    cycle_id: Digest
    reason: Literal["awaiting_approval", "awaiting_clarification"]
    baseline_sequence: int
    terms_digest: Digest
    contact_refs: tuple[Ref, ...]
    missing_fields: tuple[Ref, ...]
    baseline_revision_id: Ref


class Tracking(Contract):
    latest_sequence: int = -1
    latest_event_digest: str = ""
    state: WorkflowState = WorkflowState.RECEIVED
    fallback_enrolled: bool = False
    original_dwe_incharge_ref: Ref | None = None
    enrollment_sequence: int | None = None
    wait: WaitCycle | None = None
    cancelled: bool = False
    completed_terms_digest: Digest | None = None
    pending_action_id: Digest | None = None
    pending_action_role: Literal["dispatch", "mirza"] | None = None
    ticket_mapping_terms_digest: Digest | None = None
    additional_key_terms_digest: Digest | None = None


class Evaluation(Contract):
    state: WorkflowState
    reason_code: Ref
    tracking: Tracking
    action_id: Digest | None = None
    terms_digest: Digest | None = None
    target_role: Literal["dispatch", "mirza"] | None = None
    authorized: bool = False
