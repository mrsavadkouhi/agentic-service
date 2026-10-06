"""Explicitly synthetic inputs shared by local verification; no user data."""

from datetime import UTC, datetime
from pathlib import Path

from app.contracts.tickets import (
    Catalog,
    IncreasePersonBudget,
    MirzaRequest,
    NativeApproval,
    TicketEvent,
    digest,
)
from app.policies.tickets import POLICY_VERSION


def catalog() -> Catalog:
    return Catalog.model_validate_json(
        Path(__file__).with_name("synthetic_catalog.json").read_text()
    )


def event(ticket_id="fixture", sequence=1, *, approved=False, dedicated=True) -> TicketEvent:
    job = IncreasePersonBudget.model_validate(
        {
            "operation": "increase_person_budget",
            "person_email": "owner@example.invalid",
            "budget": {
                "amount": "5",
                "interpretation": "delta",
                "baseline_limit": "10",
                "desired_limit": "15",
            },
        }
    )
    return TicketEvent.model_validate(
        {
            "tenant_id": "synthetic",
            "ticket_id": ticket_id,
            "event_id": f"revision-{sequence}",
            "data_kind": "synthetic",
            "catalog_version": "synthetic-step3-v1",
            "policy_version": POLICY_VERSION,
            "model_version": "synthetic-model-v1",
            "prompt_version": "synthetic-prompt-v1",
            "evidence_refs": ["source-history"],
            "snapshot": {
                "revision_id": f"revision-{sequence}",
                "source_sequence": sequence,
                "source_order_verified": True,
                "requester_ref": "requester",
                "intended_person_ref": "owner",
                "support_group_id": "sd-helpdesk",
                "technician_ref": None,
                "template_id": "template-mirza-access" if dedicated else "template-other",
                "category_id": None,
                "status": "Open",
                "source": "email",
                "source_updated_at": datetime(2026, 10, 6, tzinfo=UTC),
                "content_ref": "content-1",
                "content_digest": "a" * 64,
                "process": {"association": "standalone", "evidence_ref": "process-lookup"},
            },
            "proposal": MirzaRequest(kind="mirza", operation=job.operation, job=job),
            "native_approval": NativeApproval(
                template_id="template-mirza-access",
                final_state="approved" if approved else "pending",
                required_stages_complete=approved,
                terms_digest=digest(job),
                source_sequence=sequence,
                history_verified=True,
                configuration_ref="approval-config",
                evidence_ref="approval-history",
                pending_approver_refs=("approver",),
            )
            if dedicated
            else None,
        }
    )
