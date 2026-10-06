"""Sanitized read context. Unknown and unavailable never mean an empty catalog."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import AfterValidator, Field, StringConstraints, model_validator

from app.contracts.tickets import Contract, Digest, Email, Ref, opaque_reference

T = TypeVar("T")
# Upstream LiteLLM owner IDs need not follow our executable catalog-ID syntax.
# Preserve them for reconciliation; identity resolution still requires an exact
# unique directory email match. This does not relax the action contracts.
MirzaIdentityRef = Annotated[
    str, StringConstraints(min_length=1, max_length=256), AfterValidator(opaque_reference)
]
ReadStatus = Literal[
    "ok",
    "not_found",
    "ambiguous",
    "unavailable",
    "unsupported",
    "invalid",
    "incomplete",
    "unstable",
]


class Evidence(Contract):
    component: Literal["servicedesk", "directory", "mirza", "mattermost", "mapping"]
    resource: Ref
    observed_at: datetime
    digest: Digest | None = None
    complete: bool
    contract: Literal["candidate", "fixture", "installed"] = "candidate"


class ReadResult(Contract, Generic[T]):
    status: ReadStatus
    data: T | None = None
    evidence: Evidence
    reason_code: Ref | None = None

    @model_validator(mode="after")
    def success_has_data(self):
        if self.status == "ok" and (self.data is None or not self.evidence.complete):
            raise ValueError("Successful reads require complete data")
        if self.status != "ok" and self.data is not None:
            raise ValueError("Failed reads cannot expose partial data")
        return self


class DirectoryPerson(Contract):
    directory_id: Ref
    email: Email
    department: str | None
    account_enabled: bool = Field(strict=True)
    account_expired: bool = Field(strict=True)
    employee_status: Literal["eligible", "ineligible", "unknown"] = "unknown"

    def eligible(self) -> bool:
        # The directory reader verifies the exact email has one match. No
        # additional employee attribute or group is part of the approved rule.
        return self.account_enabled and not self.account_expired


class DeskPerson(Contract):
    person_id: Ref
    email: Email | None


class DeskGroup(Contract):
    group_id: Ref
    name: str
    incharge: DeskPerson | None
    incharge_verified: bool


class DeskTemplate(Contract):
    template_id: Ref
    name: str


class DeskCatalogItem(Contract):
    item_id: Ref
    name: str


class DeskNote(Contract):
    note_id: Ref
    author_id: Ref | None
    updated_by_id: Ref | None
    added_at: datetime
    updated_at: datetime | None
    content_digest: Digest


class StatusTransition(Contract):
    event_id: Ref
    actor_id: Ref
    occurred_at: datetime
    source_sequence: int = Field(ge=0)
    before_status_id: Ref
    after_status_id: Ref


class HistoryStatusChange(Contract):
    before_status_id: Ref | None
    after_status_id: Ref | None


class DeskHistoryEvent(Contract):
    event_id: Ref
    actor_id: Ref | None
    occurred_at: datetime
    operation: str
    fields: tuple[Ref, ...]
    status_changes: tuple[HistoryStatusChange, ...]
    content_digest: Digest


class DeskHistoryRead(Contract):
    events: tuple[DeskHistoryEvent, ...]
    ordering_verified: bool = False


class ApprovalObservation(Contract):
    approval_id: Ref
    approver_id: Ref | None
    action_by_id: Ref | None
    action_at: datetime | None
    state: Literal["pending", "approved", "rejected", "unknown"]
    deleted: bool


class ApprovalStage(Contract):
    stage_id: Ref
    level: int = Field(ge=1, le=5)
    state: Literal["pending", "approved", "rejected", "unknown"]
    deleted: bool
    is_current: bool
    rule_type: Ref | None
    rule_value: Ref | None
    approver_ids: tuple[Ref, ...]
    approvals: tuple[ApprovalObservation, ...]


class ApprovalRead(Contract):
    stages: tuple[ApprovalStage, ...]
    configured_stage_ids: tuple[Ref, ...]
    configured_levels: tuple[int, ...]
    configuration_verified: bool
    terms_binding_verified: bool
    history_verified: bool
    # Detect template configuration changes independently of ticket revisions.
    # This hash records observed configuration; it is not approved terms.
    configuration_digest: Digest | None = None
    # The ticket observed while reading approvals, not the terms an approver saw.
    observed_ticket_content_digest: Digest | None = None
    observed_ticket_revision_digest: Digest | None = None


class RelationshipRead(Contract):
    parent_id: Ref | None
    # The automation can reference one child from several roots. Preserve all
    # observed parents instead of silently choosing one.
    parent_ids: tuple[Ref, ...] = ()
    child_ids: tuple[Ref, ...]
    related_root_ids: tuple[Ref, ...] = ()
    process_association: Literal["standalone", "lifecycle", "non_lifecycle", "unknown"]
    process_kind: Literal["onboarding", "offboarding", "internal_transfer"] | None = None
    source: Ref = "unverified"
    coverage_verified: bool = False
    evidence_ref: Ref


class OffboardingProcess(Contract):
    parent_id: Ref
    child_ids: tuple[Ref, ...]


class OnboardingProcess(OffboardingProcess):
    pass


class DeskTicket(Contract):
    ticket_id: Ref
    requester: DeskPerson
    group_id: Ref | None
    technician: DeskPerson | None
    template_id: Ref | None
    category_id: Ref | None
    status_id: Ref | None
    status_name: str | None
    updated_at: datetime | None
    content_digest: Digest
    revision_digest: Digest
    parent_id: Ref | None
    child_ids: tuple[Ref, ...]
    relationship_verified: bool
    process_kind: Literal["onboarding", "offboarding", "internal_transfer"] | None
    process_verified: bool
    created_by_id: Ref | None = None
    created_at: datetime | None = None


class BudgetRead(Contract):
    limit: Decimal | None = Field(allow_inf_nan=False)
    # LiteLLM can record negative spend (credits/adjustments). Preserve the
    # observed ledger value; a read snapshot never authorizes a budget change.
    spend: Decimal = Field(allow_inf_nan=False)
    reset_at: datetime | None
    duration: str | None


class ReasoningRead(Contract):
    all_models: str | None
    models: dict[Ref, str]


class MirzaUser(Contract):
    user_id: MirzaIdentityRef
    email: Email | None
    team_ids: tuple[Ref, ...]
    budget: BudgetRead
    reasoning: ReasoningRead


class MirzaTeam(Contract):
    team_id: Ref
    alias: str
    kind: Literal["tool", "non_tool"]
    models: tuple[Ref, ...]
    budget: BudgetRead
    reasoning: ReasoningRead


class MirzaKey(Contract):
    key_ref: Ref
    owner_id: MirzaIdentityRef | None
    team_id: Ref | None
    expired: bool
    expires_at: datetime | None
    budget: BudgetRead
    reasoning: ReasoningRead


class MirzaInventory(Contract):
    users: tuple[MirzaUser, ...]
    teams: tuple[MirzaTeam, ...]
    keys: tuple[MirzaKey, ...]
    served_models: tuple[Ref, ...]


class MattermostBot(Contract):
    user_id: Ref
    username: Ref
    active: bool
    is_bot: bool


class MattermostPerson(Contract):
    user_id: Ref
    email: Email
    active: bool
    is_bot: bool


class ToolMapping(Contract):
    state: Literal["mapped", "clarification", "manual", "unavailable"]
    version: Ref
    department: str | None
    tool_team_id: Ref | None
    ticket_scoped: bool
    reason_code: Ref


class TicketContext(Contract):
    ticket: ReadResult[DeskTicket]
    groups: ReadResult[tuple[DeskGroup, ...]]
    templates: ReadResult[tuple[DeskTemplate, ...]]
    statuses: ReadResult[tuple[DeskCatalogItem, ...]]
    categories: ReadResult[tuple[DeskCatalogItem, ...]]
    notes: ReadResult[tuple[DeskNote, ...]]
    history: ReadResult[DeskHistoryRead]
    transitions: ReadResult[tuple[StatusTransition, ...]]
    approvals: ReadResult[ApprovalRead]
    relationships: ReadResult[RelationshipRead]
    requester: ReadResult[DirectoryPerson]
    recipient: ReadResult[DirectoryPerson]
    inventory: ReadResult[MirzaInventory]
    mattermost_bot: ReadResult[MattermostBot]
    mattermost_recipient: ReadResult[MattermostPerson]
    mapping: ToolMapping
    effective_reasoning: ReasoningRead | None
    blockers: tuple[Ref, ...]
    read_complete: bool
    grant_context_verified: bool = False
