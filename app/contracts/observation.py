"""Observation contracts: proposals are not approval, intake or execution receipts."""

from dataclasses import dataclass
from typing import Literal

from pydantic import Field, model_validator

from app.contracts.tickets import Contract, Decision, Digest, Operation, Ref

GroupName = Literal["Helpdesk", "Network", "DWE", "VOIP"]
MissingField = Literal[
    "owner_email",
    "person_email",
    "team_id",
    "team_kind",
    "key_ref",
    "tool_team_id",
    "model_ids",
    "requested_model_id",
    "reasoning_level",
    "expires_at",
    "budget",
    "budget_amount",
    "budget_limit",
    "budget_duration",
    "initial_model_ids",
    "initial_budget",
    "team_alias",
    "budget_interpretation",
    "baseline_budget",
    "purpose",
    "department_mapping",
    "ticket_scoped_mapping",
    "additional_key_needed",
    "verified_intended_person",
    "served_models",
    "one_verified_tool_team",
    "verified_key_owner_and_tool_team",
    "existing_team_model_grants",
    "verified_team_kind",
    "manual_team",
    "existing_team_reference",
    "single_operation",
    "request_details",
]


class Classification(Contract):
    kind: Literal["ordinary", "mirza", "unsupported_mirza", "ambiguous"]
    group: GroupName | None = None
    operation: Operation | None = None

    @model_validator(mode="after")
    def coherent(self):
        if (self.kind == "ordinary") != (self.group is not None):
            raise ValueError("Only ordinary requests select a support group")
        if (self.kind == "mirza") != (self.operation is not None):
            raise ValueError("Supported Mirza requests require exactly one allowed operation")
        return self


class ClarificationDraft(Contract):
    template_ref: Literal["mirza-clarification-v1"] = "mirza-clarification-v1"
    contact_ref: Ref | None
    missing_fields: tuple[MissingField, ...]


class ObservationResult(Contract):
    state: Literal["proposed", "no_op", "manual_review", "unavailable", "blocked"]
    reason_code: Ref
    classification: Classification | None = None
    proposal: Decision | None = None
    clarification: ClarificationDraft | None = None
    policy_reason: Ref | None = None
    evidence_refs: tuple[Digest, ...] = Field(min_length=1)
    versions: dict[str, Ref]
    model_requests: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    latency_ms: int = Field(default=0, ge=0)
    authorized: Literal[False] = False


@dataclass
class ObservationStart:
    tenant_id: str
    ticket_id: str
    dispatch_queue: str
    mirza_queue: str


@dataclass
class ObservationReceipt:
    observation_id: str
    state: str
    reason_code: str
    kind: str | None = None
    operation: str | None = None


@dataclass
class PollStart:
    dispatch_queue: str
    mirza_queue: str
    poll_seconds: int = 60
    batch_size: int = 4
    cursor: int = 0


@dataclass
class PollBatch:
    ticket_ids: list[str]
    next_cursor: int
    status: str


def clarification_text(ticket_id: str, ticket_link: str, missing_fields) -> str:
    details = ", ".join(field.replace("_", " ") for field in missing_fields)
    return (
        f"Mirza request #{ticket_id} needs clarification: {ticket_link}. "
        f"Required details: {details}. Add these details in a ticket note and change "
        "its status from On Hold to Open so processing can continue."
    )
