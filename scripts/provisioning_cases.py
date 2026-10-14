"""Generated synthetic authorization examples; never import as native request authority."""

from pydantic import TypeAdapter

from app.contracts.context import ApprovalTermsBaseline
from app.contracts.mirza_review import MirzaReviewState, ReviewEvidence
from app.contracts.tickets import Job, MirzaRequest, digest
from app.policies.synthetic_events import catalog, event

JOBS = [
    {
        "operation": "create_api_key",
        "owner_email": "owner@example.invalid",
        "tool_team": {"kind": "existing_tool", "team_id": "tool-team"},
        "purpose_ref": "fixture-client",
        "budget_limit": "5",
        "budget_duration": "30d",
        "expires_at": None,
    },
    {
        "operation": "increase_api_key_reasoning",
        "owner_email": "owner@example.invalid",
        "key_ref": "key-metadata-1",
        "tool_team_id": "tool-team",
        "model_ids": ["model-a"],
        "reasoning_level": "high",
        "expires_at": None,
    },
    {
        "operation": "increase_team_reasoning",
        "team_id": "ui-team",
        "team_kind": "non_tool",
        "model_ids": ["model-a"],
        "reasoning_level": "high",
        "expires_at": None,
    },
    {
        "operation": "grant_team_model_access",
        "team_id": "tool-team",
        "team_kind": "tool",
        "model_ids": ["model-b"],
        "expires_at": None,
    },
    {
        "operation": "add_person_to_non_tool_team",
        "person_email": "owner@example.invalid",
        "team_id": "ui-team",
        "requested_model_id": "model-a",
        "expires_at": None,
    },
    {
        "operation": "increase_person_budget",
        "person_email": "owner@example.invalid",
        "budget": {
            "amount": "5",
            "interpretation": "delta",
            "baseline_limit": "10",
            "desired_limit": "15",
        },
    },
    {
        "operation": "increase_api_key_budget",
        "owner_email": "owner@example.invalid",
        "key_ref": "key-metadata-1",
        "tool_team_id": "tool-team",
        "budget": {
            "amount": "5",
            "interpretation": "delta",
            "baseline_limit": "10",
            "desired_limit": "15",
        },
    },
    {
        "operation": "increase_team_budget",
        "team_id": "ui-team",
        "team_kind": "non_tool",
        "budget": {
            "amount": "5",
            "interpretation": "delta",
            "baseline_limit": "10",
            "desired_limit": "15",
        },
    },
]
NEW_TEAM_JOB = {
    **JOBS[0],
    "tool_team": {
        "kind": "new_tool",
        "alias": "Fixture-New-Tool",
        "initial_model_ids": ["model-a"],
        "initial_budget": "20",
        "budget_duration": "30d",
    },
}


def case(index, tenant="fulfillment-fixture-unit", fields=None, ticket_id=None):
    job = TypeAdapter(Job).validate_python(fields or (JOBS[index] if index < 8 else NEW_TEAM_JOB))
    current_catalog = (
        catalog().model_copy(update={"keys": ()})
        if job.operation == "create_api_key"
        else catalog().model_copy(
            update={"keys": tuple(k.model_copy(update={"expired": False}) for k in catalog().keys)}
        )
    )
    normalized = event(ticket_id or "case-" + str(index), sequence=6, approved=True).model_copy(
        update={
            "tenant_id": tenant,
            "proposal": MirzaRequest(kind="mirza", operation=job.operation, job=job),
        }
    )
    normalized = normalized.model_copy(
        update={
            "native_approval": normalized.native_approval.model_copy(
                update={"terms_digest": digest(job)}
            )
        }
    )
    evidence = ReviewEvidence(
        baseline=ApprovalTermsBaseline(
            ticket_id=normalized.ticket_id,
            approval_ref="approval-history",
            configuration_digest="c" * 64,
            original_approver_ids=("approver",),
            approved_terms_digest=digest(job),
            source_sequence=1,
            identity_verified=True,
            history_verified=True,
        ),
        configuration_digest="c" * 64,
        on_hold_status_id="hold",
        open_status_id="open",
    )
    state = MirzaReviewState(evidence=evidence)
    if index == 8:
        state = state.model_copy(
            update={
                "tracking": state.tracking.model_copy(
                    update={
                        "ticket_mapping_terms_digest": digest(job),
                    }
                )
            }
        )
    return normalized, current_catalog, state
