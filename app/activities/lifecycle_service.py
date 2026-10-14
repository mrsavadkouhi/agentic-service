"""Operator recovery and expiry for generated fixture worlds, with no native writes."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.contracts.lifecycle import LifecycleReceipt
from app.contracts.tickets import stable_id
from app.policies.ownership import OwnershipLedger, scope_value, utc
from app.policies.provisioning import ProvisioningBlocked
from app.storage.lifecycle import LifecycleAudit, OwnedGrant, OwnedScope, RecoveryCommand
from app.storage.mirza_reviews import MirzaPolicyReview
from app.storage.observations import InferenceBudget, ObservationRecord
from app.storage.provisioning import (
    FixtureMessage,
    FixtureWorld,
    FulfillmentRecord,
    FulfillmentStep,
    ProvisioningSecret,
)
from app.storage.tickets import TicketAction


def audit(session, operation_id, code, identity):
    ref = stable_id(operation_id, code, str(identity))
    if session.get(LifecycleAudit, ref) is None:
        session.add(LifecycleAudit(audit_id=ref, operation_id=operation_id, code=code))


def next_command(record):
    return max((int(k) for k in record.payload.get("command_claims", {})), default=-1) + 1


class LifecycleService:
    def __init__(self, engine, fulfillment=None):
        self.engine, self.fulfillment = engine, fulfillment

    def command(self, operation_id, request_id, action, expected_revision, principal):
        command_id = stable_id(operation_id, "recovery", request_id)
        terms = {"action": action, "expected_revision": expected_revision, "principal": principal}
        with Session(self.engine) as session, session.begin():
            command = session.get(RecoveryCommand, command_id, with_for_update=True)
            if command:
                if command.payload["terms"] != terms:
                    raise ProvisioningBlocked("recovery_command_conflict")
                return {"command_id": command_id, "state": command.payload["state"]}
            record = session.get(FulfillmentRecord, operation_id, with_for_update=True)
            if record is None:
                raise KeyError(operation_id)
            revision = record.payload.get("lifecycle_revision", 0)
            if expected_revision != revision:
                raise ProvisioningBlocked("recovery_revision_conflict")
            if record.state in {"completed", "cancelled"}:
                raise ProvisioningBlocked("terminal_fulfillment")
            if action not in {"cancel", "resume"}:
                raise ProvisioningBlocked("unsupported_recovery_command")
            state = "pending"
            if action == "cancel":
                record.state, record.reason_code = "cancelled", "operator_cancelled"
                record.payload = {**record.payload, "lifecycle_revision": revision + 1}
                state = "applied"
                audit(session, operation_id, "cancelled_grants_retained", command_id)
            session.add(
                RecoveryCommand(
                    command_id=command_id,
                    operation_id=operation_id,
                    payload={"terms": terms, "state": state},
                )
            )
        return {"command_id": command_id, "state": state}

    def apply_resume(self, command_id):
        if self.fulfillment is None:
            raise ProvisioningBlocked("fixture_connector_disabled")
        with Session(self.engine) as session, session.begin():
            # Lock order is operation -> world -> command throughout recovery/effects.
            peek = session.get(RecoveryCommand, command_id)
            if peek is None:
                raise ProvisioningBlocked("unknown_recovery_command")
            record = session.get(FulfillmentRecord, peek.operation_id, with_for_update=True)
            row = session.get(FixtureWorld, record.world_id, with_for_update=True)
            command = session.get(
                RecoveryCommand, command_id, with_for_update=True, populate_existing=True
            )
            if command.payload["state"] in {"applied", "rejected"}:
                return LifecycleReceipt(**command.payload["result"])
            try:
                if (
                    command.payload["terms"]["action"] != "resume"
                    or record.state != "blocked"
                    or command.payload["terms"]["expected_revision"]
                    != record.payload.get("lifecycle_revision", 0)
                ):
                    raise ProvisioningBlocked("recovery_revision_conflict")
                world = deepcopy(row.payload)
                self.fulfillment.reconcile(session, record, world)
                self.fulfillment.context(record, world)
                if any(
                    step.state != "verified"
                    for step in session.scalars(
                        select(FulfillmentStep).where(
                            FulfillmentStep.operation_id == record.operation_id
                        )
                    )
                ):
                    raise ProvisioningBlocked("unreconciled_fixture_outcome")
                # Positive mutation receipts are checked before scheduling any delivery.
                mutation_id = stable_id(record.operation_id, "mutation", "")
                if mutation_id in world["receipts"]:
                    job = self.fulfillment.context(record, world)[1]
                    self.fulfillment.verify(session, record, world, job)
                record.state, record.reason_code = "running", "operator_resumed"
                record.payload = {
                    **record.payload,
                    "lifecycle_revision": record.payload.get("lifecycle_revision", 0) + 1,
                }
                result = LifecycleReceipt(
                    record.operation_id, "running", "operator_resumed", next_command(record)
                )
                state = "applied"
            except ProvisioningBlocked as error:
                result = LifecycleReceipt(record.operation_id, "blocked", str(error))
                state = "rejected"
            command.payload = {**command.payload, "state": state, "result": result.as_dict()}
            audit(session, record.operation_id, "resume_" + state, command_id)
            return result

    def reconcile(self, operation_id, now=None):
        now = now or datetime.now(UTC)
        with Session(self.engine) as session, session.begin():
            record = session.get(FulfillmentRecord, operation_id, with_for_update=True)
            if record is None:
                return LifecycleReceipt(operation_id, "blocked", "unknown_fixture_operation")
            row = session.get(FixtureWorld, record.world_id, with_for_update=True)
            world = deepcopy(row.payload)

            def receipt(state, reason, command=0, due=None):
                result = LifecycleReceipt(operation_id, state, reason, command, due)
                record.payload = {
                    **record.payload,
                    "last_reconciliation": {**result.as_dict(), "checked_at": now.isoformat()},
                }
                if state == "blocked":
                    audit(session, operation_id, "lifecycle_verification_failed", row.revision)
                return result

            expired, conflicts = OwnershipLedger.expire(session, record.world_id, world, now)
            row.payload, row.revision = world, row.revision + 1
            grants = session.scalars(
                select(OwnedGrant).where(
                    OwnedGrant.operation_id == operation_id, OwnedGrant.state == "active"
                )
            ).all()
            owned_conflict = False
            for grant in grants:
                scope = session.get(OwnedScope, grant.scope_id)
                try:
                    value = scope_value(world, scope.payload["descriptor"])
                except KeyError:
                    value = None
                if (
                    scope.state != "active"
                    or value != scope.payload["expected"]
                    or world.get("owned_scope_versions", {}).get(scope.scope_id, 0)
                    != scope.payload["version"]
                ):
                    owned_conflict = True
            if owned_conflict:
                audit(session, operation_id, "owned_scope_external_change", row.revision)
                return receipt("blocked", "owned_scope_external_change")
            if expired:
                audit(session, operation_id, "owned_grants_expired", row.revision)
            if conflicts:
                audit(session, operation_id, "expiry_conflict_in_world", row.revision)
            due = min((utc(g.expires_at) for g in grants if g.expires_at), default=None)
            reason = "owned_grants_verified"
            if record.state in {"planned", "running", "blocked"}:
                if self.fulfillment is None:
                    return receipt("blocked", "fixture_connector_disabled")
                try:
                    self.fulfillment.reconcile(session, record, world)
                    self.fulfillment.context(record, world)
                    if record.state == "blocked":
                        return receipt("blocked", record.reason_code, next_command(record), due)
                except ProvisioningBlocked as error:
                    record.state, record.reason_code = "blocked", str(error)
                    return receipt("blocked", str(error), next_command(record), due)
                return receipt("running", reason, next_command(record), due)
            # Only a verified Resolved receipt is a successful fulfillment outcome.
            if record.state == "completed" and not record.payload.get("retention_tombstone"):
                event = record.payload["event"]
                from app.contracts.tickets import TicketEvent

                workflow_id = TicketEvent.model_validate(event).workflow_id()
                if world["tickets"][workflow_id]["snapshot"]["status"] != "Resolved":
                    return receipt("blocked", "resolved_status_changed", next_command(record), due)
            return receipt("waiting" if due else "complete", reason, next_command(record), due)

    def view(self, operation_id):
        with Session(self.engine) as session:
            record = session.get(FulfillmentRecord, operation_id)
            if record is None:
                return None
            payload = record.payload
            auth = payload.get("authorization", {})
            baseline = auth.get("evidence", {}).get("baseline") or {}
            steps = session.scalars(
                select(FulfillmentStep)
                .where(FulfillmentStep.operation_id == operation_id)
                .order_by(FulfillmentStep.step_id)
            ).all()
            grants = session.scalars(
                select(OwnedGrant)
                .where(OwnedGrant.operation_id == operation_id)
                .order_by(OwnedGrant.grant_id)
            ).all()
            return {
                "operation_id": operation_id,
                "execution_domain": "synthetic",
                "state": record.state,
                "reason_code": record.reason_code,
                "last_reconciliation": payload.get("last_reconciliation"),
                "revision": payload.get("lifecycle_revision", 0),
                "terms_digest": payload.get("job_digest"),
                "approved_terms_baseline_recorded": bool(baseline),
                "original_approver_count": len(baseline.get("original_approver_ids", [])),
                "original_dwe_pinned": bool(
                    auth.get("tracking", {}).get("original_dwe_incharge_ref")
                ),
                "steps": [
                    {"phase": s.phase, "state": s.state, "evidence_ref": s.step_id} for s in steps
                ],
                "grants": [
                    {
                        "grant_ref": g.grant_id,
                        "scope_ref": g.scope_id,
                        "state": g.state,
                        "scope": session.get(OwnedScope, g.scope_id).payload["descriptor"],
                        "approved_target": g.desired,
                        "expires_at": utc(g.expires_at).isoformat() if g.expires_at else None,
                    }
                    for g in grants
                ],
                "audit": [
                    {"code": a.code, "evidence_ref": a.audit_id}
                    for a in session.scalars(
                        select(LifecycleAudit)
                        .where(LifecycleAudit.operation_id == operation_id)
                        .order_by(LifecycleAudit.created_at.desc())
                        .limit(100)
                    )
                ],
                "retention_tombstone": payload.get("retention_tombstone", False),
                "external_write_capabilities": [],
            }

    def metrics(self, now=None):
        now = now or datetime.now(UTC)
        with Session(self.engine) as session:
            states = dict(
                session.execute(
                    select(FulfillmentRecord.state, func.count()).group_by(FulfillmentRecord.state)
                ).all()
            )
            conflicts = session.scalar(
                select(func.count()).select_from(OwnedScope).where(OwnedScope.state == "conflict")
            )
            overdue = session.scalar(
                select(func.count())
                .select_from(OwnedGrant)
                .where(OwnedGrant.state == "active", OwnedGrant.expires_at <= now)
            )
            uncertain = session.scalar(
                select(func.count())
                .select_from(FulfillmentStep)
                .where(FulfillmentStep.state == "uncertain")
            )
            verification_failures = session.scalar(
                select(func.count())
                .select_from(FulfillmentRecord)
                .where(
                    (FulfillmentRecord.state == "blocked")
                    | (
                        FulfillmentRecord.payload["last_reconciliation"]["state"].as_string()
                        == "blocked"
                    )
                )
            )
            age = session.scalar(
                select(func.min(FulfillmentRecord.created_at)).where(
                    FulfillmentRecord.state.in_(("planned", "running", "blocked"))
                )
            )
            review_state = MirzaPolicyReview.result["state"].as_string()
            review_counts = dict(
                session.execute(select(review_state, func.count()).group_by(review_state)).all()
            )
            approval_age = session.scalar(
                select(func.min(MirzaPolicyReview.created_at)).where(
                    review_state == "awaiting_approval"
                )
            )
            observation_state = ObservationRecord.result["state"].as_string()
            protected_noops = session.scalar(
                select(func.count())
                .select_from(ObservationRecord)
                .where(observation_state == "no_op")
            )
            corrections = session.scalar(
                select(func.count())
                .select_from(TicketAction)
                .where(
                    TicketAction.operation == "correct_support_group",
                    TicketAction.state == "verified",
                )
            )
            reserved = session.scalar(select(func.sum(InferenceBudget.reserved_usd)))
            # Bounded sample; do not imply an unbounded latency scan is a service SLO.
            samples = session.scalars(
                select(FulfillmentRecord)
                .where(FulfillmentRecord.state == "completed")
                .order_by(FulfillmentRecord.created_at.desc())
                .limit(100)
            ).all()
            latencies = [
                max(
                    0,
                    (
                        datetime.fromisoformat(r.payload["completed_at"]) - utc(r.created_at)
                    ).total_seconds(),
                )
                for r in samples
                if r.payload.get("completed_at")
            ]
            return {
                "execution_domain": "synthetic",
                "fulfillment_states": states,
                "expiry_conflicts": conflicts,
                "overdue_grants": overdue,
                "uncertain_effects": uncertain,
                "verified_group_corrections": corrections,
                "protected_observation_noops": protected_noops,
                "local_review_states": review_counts,
                "oldest_approval_preview_seconds": max(
                    0, int((now - utc(approval_age)).total_seconds())
                )
                if approval_age
                else 0,
                "failed_verification_count": verification_failures,
                "model_reserved_usd": str(reserved or 0),
                "model_actual_spend_verified": False,
                "latency_sample_count": len(latencies),
                "latency_sample_mean_seconds": sum(latencies) / len(latencies)
                if latencies
                else None,
                "oldest_pending_seconds": max(0, int((now - utc(age)).total_seconds()))
                if age
                else 0,
                "alerts": {
                    "expiry_review_required": bool(conflicts or overdue),
                    "recovery_required": bool(uncertain or verification_failures),
                    "approval_preview_waiting": bool(approval_age),
                },
            }

    def retain(self, operation_id, expected_revision, now=None):
        """Fixture-only 180-day terminal tombstone; pending recovery and ownership survive."""
        now = now or datetime.now(UTC)
        with Session(self.engine) as session, session.begin():
            record = session.get(FulfillmentRecord, operation_id, with_for_update=True)
            if record is None:
                raise KeyError(operation_id)
            if record.payload.get("retention_tombstone"):
                return {"state": "retained_tombstone"}
            completed_at = record.payload.get("completed_at")
            if (
                record.state not in {"completed", "cancelled"}
                or not completed_at
                or datetime.fromisoformat(completed_at) > now - timedelta(days=180)
                or expected_revision != record.payload.get("lifecycle_revision", 0)
            ):
                raise ProvisioningBlocked("retention_not_eligible")
            # Never discard an abandoned/uncertain key or an unverified private post.
            if record.state != "completed" or any(
                s.state != "verified"
                for s in session.scalars(
                    select(FulfillmentStep).where(FulfillmentStep.operation_id == operation_id)
                )
            ):
                raise ProvisioningBlocked("retention_recovery_pending")
            if record.payload.get("last_reconciliation", {}).get("state") == "blocked":
                raise ProvisioningBlocked("retention_recovery_pending")
            row = session.get(FixtureWorld, record.world_id, with_for_update=True)
            world = deepcopy(row.payload)
            from app.contracts.tickets import TicketEvent

            event = TicketEvent.model_validate(record.payload["event"])
            world["tickets"].pop(event.workflow_id(), None)
            world["descriptions"].pop(event.workflow_id(), None)
            for table in (ProvisioningSecret, FixtureMessage):
                for saved in session.scalars(
                    select(table).where(table.operation_id == operation_id)
                ):
                    session.delete(saved)
            record.payload = {
                "job_digest": record.payload["job_digest"],
                "archived_job": event.proposal.operation,
                "retention_tombstone": True,
                "lifecycle_revision": expected_revision + 1,
            }
            row.payload, row.revision = world, row.revision + 1
            audit(session, operation_id, "fixture_private_data_tombstoned", expected_revision)
            return {"state": "retained_tombstone"}
