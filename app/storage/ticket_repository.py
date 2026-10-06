import json
from datetime import UTC, datetime

from sqlalchemy import Engine, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.contracts.execution import ActionCommand, CommitTransition, ReminderCommand, StoredEvent
from app.contracts.tickets import (
    Catalog,
    Evaluation,
    MirzaRequest,
    TicketEvent,
    Tracking,
    WorkflowState,
    digest,
    stable_id,
)
from app.policies.reminders import TEHRAN
from app.settings import Settings, WorkerRole
from app.storage.tickets import (
    CatalogRecord,
    FixtureEffect,
    TicketAction,
    TicketAudit,
    TicketInbox,
    TicketReminder,
    TicketWorkflowRecord,
)


class EventConflict(Exception):
    pass


class StaleAction(Exception):
    pass


class SimulatedLostResponse(Exception):
    pass


class TicketRepository:
    def __init__(self, engine: Engine):
        self.engine = engine

    def seed_catalog(self, catalog: Catalog) -> None:
        with Session(self.engine) as session, session.begin():
            session.execute(
                insert(CatalogRecord)
                .values(
                    version=catalog.version,
                    payload_digest=digest(catalog),
                    payload=catalog.model_dump(mode="json"),
                )
                .on_conflict_do_nothing(index_elements=["version"])
            )
            if session.get(CatalogRecord, catalog.version).payload_digest != digest(catalog):
                raise EventConflict("Catalog versions are immutable")

    def accept(self, event: TicketEvent, correlation_id: str) -> dict:
        workflow_id = event.workflow_id()
        role = "mirza" if isinstance(event.proposal, MirzaRequest) else "dispatch"
        event_key = stable_id(workflow_id, event.event_id)
        with Session(self.engine) as session, session.begin():
            session.execute(
                insert(TicketWorkflowRecord)
                .values(
                    workflow_id=workflow_id,
                    tenant_id=event.tenant_id,
                    ticket_id=event.ticket_id,
                    worker_role=role,
                    correlation_id=correlation_id,
                    tracking=Tracking().model_dump(mode="json"),
                    latest_sequence=-1,
                    state="received",
                )
                .on_conflict_do_nothing(index_elements=["workflow_id"])
            )
            owner = session.get(TicketWorkflowRecord, workflow_id, with_for_update=True)
            existing = session.get(TicketInbox, event_key)
            if existing:
                if existing.payload_digest != digest(event):
                    raise EventConflict("External event identity reused with different data")
                return {
                    "workflow_id": workflow_id,
                    "duplicate": True,
                    "correlation_id": owner.correlation_id,
                }
            session.add(
                TicketInbox(
                    event_key=event_key,
                    workflow_id=workflow_id,
                    external_event_id=event.event_id,
                    kind="ticket",
                    sequence=event.snapshot.source_sequence,
                    payload_digest=digest(event),
                    payload=event.model_dump(mode="json"),
                )
            )
            return {
                "workflow_id": workflow_id,
                "duplicate": False,
                "correlation_id": owner.correlation_id,
            }

    def cancel(
        self, workflow_id: str, request_id: str, expected_sequence: int, operator_ref: str
    ) -> dict:
        payload = {
            "request_id": request_id,
            "expected_sequence": expected_sequence,
            "operator_ref": operator_ref,
        }
        key = stable_id(workflow_id, "cancel", request_id)
        encoded = json.dumps(payload, sort_keys=True)
        with Session(self.engine) as session, session.begin():
            owner = session.get(TicketWorkflowRecord, workflow_id, with_for_update=True)
            if owner is None:
                raise KeyError("Unknown ticket")
            existing = session.get(TicketInbox, key)
            if existing:
                if existing.payload != payload:
                    raise EventConflict("Cancellation identity reused")
                return {"workflow_id": workflow_id, "duplicate": True}
            if owner.latest_sequence != expected_sequence:
                raise EventConflict("Cancellation revision is stale")
            if self.has_pending(session, workflow_id):
                raise EventConflict("Newer ticket input is awaiting evaluation")
            session.add(
                TicketInbox(
                    event_key=key,
                    workflow_id=workflow_id,
                    external_event_id="cancel-" + request_id,
                    kind="cancel",
                    sequence=expected_sequence,
                    payload_digest=stable_id(encoded),
                    payload=payload,
                )
            )
            return {"workflow_id": workflow_id, "duplicate": False}

    def pending_notifications(self) -> list[dict]:
        with Session(self.engine) as session:
            rows = session.execute(
                select(TicketInbox, TicketWorkflowRecord)
                .join(
                    TicketWorkflowRecord,
                    TicketWorkflowRecord.workflow_id == TicketInbox.workflow_id,
                )
                .where(TicketInbox.notified.is_(False))
                .order_by(TicketInbox.received_at)
                .limit(20)
            )
            return [
                {
                    "event_key": event.event_key,
                    "workflow_id": owner.workflow_id,
                    "worker_role": owner.worker_role,
                }
                for event, owner in rows
            ]

    def mark_notified(self, event_key: str) -> None:
        with Session(self.engine) as session, session.begin():
            session.get(TicketInbox, event_key).notified = True

    def next_event(self, workflow_id: str) -> StoredEvent | None:
        with Session(self.engine) as session:
            row = session.scalar(
                select(TicketInbox)
                .where(
                    TicketInbox.workflow_id == workflow_id,
                    TicketInbox.processed.is_(False),
                )
                .order_by(TicketInbox.received_at, TicketInbox.event_key)
                .limit(1)
            )
            if row is None:
                return None
            catalog = session.get(CatalogRecord, row.payload.get("catalog_version", ""))
            return StoredEvent(
                row.event_key,
                json.dumps(row.payload),
                json.dumps(catalog.payload) if catalog else None,
                row.kind,
            )

    @staticmethod
    def has_pending(session: Session, workflow_id: str) -> bool:
        return bool(
            session.scalar(
                select(TicketInbox.event_key)
                .where(
                    TicketInbox.workflow_id == workflow_id,
                    TicketInbox.processed.is_(False),
                )
                .limit(1)
            )
        )

    def commit(self, command: CommitTransition) -> str:
        evaluation = Evaluation.model_validate_json(command.evaluation_json)
        with Session(self.engine) as session, session.begin():
            owner = session.get(TicketWorkflowRecord, command.workflow_id, with_for_update=True)
            row = session.get(TicketInbox, command.event_key, with_for_update=True)
            if row is None or row.workflow_id != command.workflow_id:
                raise EventConflict("Event owner mismatch")
            if row.processed:
                return Tracking.model_validate(row.result_tracking).model_dump_json()
            if owner.latest_sequence != command.expected_before_sequence:
                raise EventConflict("Projection revision changed")
            frame = evaluation.tracking
            if evaluation.reason_code not in {"stale_event", "duplicate_revision"}:
                for old in session.scalars(
                    select(TicketAction).where(
                        TicketAction.workflow_id == owner.workflow_id,
                        TicketAction.state == "planned",
                    )
                ):
                    old.state = "superseded"
                for reminder in session.scalars(
                    select(TicketReminder).where(
                        TicketReminder.workflow_id == owner.workflow_id,
                        TicketReminder.state == "pending",
                    )
                ):
                    if not frame.wait or reminder.cycle_id != frame.wait.cycle_id:
                        reminder.state = "superseded"
            metadata = {"reason": evaluation.reason_code}
            if row.kind == "cancel":
                metadata.update(
                    operator_ref=row.payload["operator_ref"],
                    request_id=row.payload["request_id"],
                    expected_sequence=row.payload["expected_sequence"],
                )
            if row.kind == "ticket":
                event = TicketEvent.model_validate(row.payload)
                metadata.update(
                    policy_version=event.policy_version,
                    model_version=event.model_version,
                    prompt_version=event.prompt_version,
                    evidence_refs=event.evidence_refs,
                    terms_digest=evaluation.terms_digest,
                    native_approval=event.native_approval.model_dump(mode="json")
                    if event.native_approval
                    else None,
                    fallback_approval=event.fallback_approval.model_dump(mode="json")
                    if event.fallback_approval
                    else None,
                    clarification=event.clarification.model_dump(mode="json")
                    if event.clarification
                    else None,
                )
                if evaluation.reason_code not in {"stale_event", "duplicate_revision"}:
                    owner.snapshot = event.snapshot.model_dump(mode="json")
                if evaluation.authorized:
                    payload = event.proposal.model_dump(mode="json")
                    action = session.get(TicketAction, evaluation.action_id)
                    if action is None:
                        action = TicketAction(
                            action_id=evaluation.action_id,
                            workflow_id=owner.workflow_id,
                            authorized_sequence=frame.latest_sequence,
                            terms_digest=evaluation.terms_digest,
                            worker_role=evaluation.target_role,
                            state="planned",
                            data_kind=event.data_kind,
                            operation=event.proposal.operation
                            if isinstance(event.proposal, MirzaRequest)
                            else "correct_support_group",
                            payload=payload,
                            correlation_id=owner.correlation_id,
                        )
                        session.add(action)
                    elif action.state != "verified":
                        action.authorized_sequence = frame.latest_sequence
                        if action.state in {"cancelled", "superseded"}:
                            action.state = "planned"
                    if action.state == "verified":
                        frame = frame.model_copy(
                            update={
                                "state": WorkflowState.COMPLETED,
                                "completed_terms_digest": evaluation.terms_digest,
                                "pending_action_id": None,
                            }
                        )
                    else:
                        frame = frame.model_copy(
                            update={
                                "pending_action_id": action.action_id,
                                "pending_action_role": action.worker_role,
                            }
                        )
            owner.tracking = frame.model_dump(mode="json")
            owner.latest_sequence = frame.latest_sequence
            owner.state = frame.state.value
            row.processed = True
            row.result_tracking = owner.tracking
            session.add(
                TicketAudit(
                    audit_id=stable_id(row.event_key, "transition"),
                    workflow_id=owner.workflow_id,
                    event_key=row.event_key,
                    correlation_id=owner.correlation_id,
                    state=owner.state,
                    reason_code=evaluation.reason_code,
                    metadata_refs=metadata,
                )
            )
            return frame.model_dump_json()

    def run_fixture_action(
        self, command: ActionCommand, settings: Settings, worker_role: WorkerRole
    ) -> dict:
        lost_response = False
        with Session(self.engine) as session, session.begin():
            owner = session.get(TicketWorkflowRecord, command.workflow_id, with_for_update=True)
            action = session.get(TicketAction, command.action_id, with_for_update=True)
            if action is None or action.workflow_id != command.workflow_id:
                raise StaleAction("Unknown action")
            if not settings.enable_fixture_execution or action.data_kind != "synthetic":
                return {"state": "manual_review", "reason": "connector_unavailable"}
            if action.worker_role != worker_role.value or settings.paused(worker_role):
                return {"state": "manual_review", "reason": "worker_scope_or_pause"}
            effect = session.get(FixtureEffect, action.action_id)
            if effect:
                if effect.payload_digest != action.terms_digest:
                    raise StaleAction("Reconciliation terms mismatch")
                action.state = "verified"
                return {"state": "verified", "action_id": action.action_id, "reconciled": True}
            frame = Tracking.model_validate(owner.tracking)
            if (
                frame.cancelled
                or owner.latest_sequence != action.authorized_sequence
                or frame.pending_action_id != action.action_id
                or self.has_pending(session, owner.workflow_id)
            ):
                action.state = "superseded"
                return {"state": "superseded", "reason": "new_ticket_state"}
            if settings.mode(worker_role).value != "automatic":
                return {"state": "manual_review", "reason": "observation_or_review"}
            if action.state != "planned":
                # An uncertain write without a provable downstream receipt is never retried.
                return {"state": "manual_review", "reason": "unreconciled_result"}
            action.state = "in_flight"
        # Commit intent before a simulated external side effect.
        with Session(self.engine) as session, session.begin():
            owner = session.get(TicketWorkflowRecord, command.workflow_id, with_for_update=True)
            action = session.get(TicketAction, command.action_id, with_for_update=True)
            frame = Tracking.model_validate(owner.tracking)
            if (
                frame.cancelled
                or owner.latest_sequence != action.authorized_sequence
                or frame.pending_action_id != action.action_id
                or self.has_pending(session, owner.workflow_id)
            ):
                action.state = "superseded"
                return {"state": "superseded", "reason": "new_ticket_state"}
            # A second activity may have reconciled the same operation while this one yielded.
            effect = session.get(FixtureEffect, action.action_id)
            if effect is None:
                session.add(
                    FixtureEffect(
                        action_id=action.action_id,
                        payload_digest=action.terms_digest,
                        fail_once_triggered=settings.fixture_lose_response_once,
                    )
                )
                lost_response = settings.fixture_lose_response_once
                action.state = "uncertain" if lost_response else "verified"
            else:
                action.state = "verified"
        if lost_response:
            raise SimulatedLostResponse("Synthetic side effect committed before response was lost")
        return {"state": "verified", "action_id": command.action_id, "reconciled": False}

    def finish_action(self, command: ActionCommand, result: dict) -> str:
        with Session(self.engine) as session, session.begin():
            owner = session.get(TicketWorkflowRecord, command.workflow_id, with_for_update=True)
            action = session.get(TicketAction, command.action_id)
            frame = Tracking.model_validate(owner.tracking)
            if frame.pending_action_id != command.action_id:
                return frame.model_dump_json()
            fresh = (
                owner.latest_sequence == action.authorized_sequence
                and not self.has_pending(session, owner.workflow_id)
                and not frame.cancelled
            )
            if result["state"] == "verified" and fresh:
                if action.state != "verified":
                    raise StaleAction("Verification result has no durable receipt")
                frame = frame.model_copy(
                    update={
                        "completed_terms_digest": action.terms_digest,
                        "pending_action_id": None,
                        "pending_action_role": None,
                        "state": WorkflowState.COMPLETED,
                    }
                )
            else:
                frame = frame.model_copy(
                    update={
                        "pending_action_id": None,
                        "pending_action_role": None,
                        "state": WorkflowState.MANUAL_REVIEW,
                        "wait": None,
                    }
                )
            owner.tracking = frame.model_dump(mode="json")
            owner.state = frame.state.value
            session.execute(
                insert(TicketAudit)
                .values(
                    audit_id=stable_id(action.action_id, "verification", result["state"]),
                    workflow_id=owner.workflow_id,
                    event_key=None,
                    correlation_id=owner.correlation_id,
                    state=owner.state,
                    reason_code=result.get("reason", "verified_fixture_receipt"),
                    metadata_refs={"action_id": action.action_id, "verification": result},
                )
                .on_conflict_do_nothing(index_elements=["audit_id"])
            )
            return frame.model_dump_json()

    def reminders(self, command: ReminderCommand, clock: datetime | None = None) -> int:
        scheduled = datetime.fromisoformat(command.now_iso)
        now = (clock or datetime.now(UTC)).astimezone(TEHRAN)
        if scheduled.tzinfo is None or now.date() != scheduled.astimezone(TEHRAN).date():
            return 0  # An activity delayed across midnight must not send a missed reminder.
        if now.hour < 10:
            return 0
        with Session(self.engine) as session, session.begin():
            owner = session.get(TicketWorkflowRecord, command.workflow_id, with_for_update=True)
            frame = Tracking.model_validate(owner.tracking)
            wait = frame.wait
            if (
                not wait
                or wait.cycle_id != command.cycle_id
                or frame.cancelled
                or frame.state.value not in {"awaiting_approval", "awaiting_clarification"}
                or self.has_pending(session, owner.workflow_id)
            ):
                return 0
            count = 0
            for recipient in wait.contact_refs:
                inserted = session.scalar(
                    insert(TicketReminder)
                    .values(
                        reminder_id=stable_id(owner.workflow_id, recipient, str(now.date())),
                        workflow_id=owner.workflow_id,
                        cycle_id=wait.cycle_id,
                        recipient_ref=recipient,
                        local_date=now.date(),
                        state="pending",
                        reason=wait.reason,
                        missing_fields=list(wait.missing_fields),
                    )
                    .on_conflict_do_nothing(
                        index_elements=["workflow_id", "recipient_ref", "local_date"]
                    )
                    .returning(TicketReminder.reminder_id)
                )
                count += int(inserted is not None)
            return count

    def projection(self, workflow_id: str) -> dict | None:
        with Session(self.engine) as session:
            owner = session.get(TicketWorkflowRecord, workflow_id)
            if owner is None:
                return None
            actions = session.scalars(
                select(TicketAction).where(
                    TicketAction.workflow_id == workflow_id,
                )
            )
            return {
                "workflow_id": owner.workflow_id,
                "state": owner.state,
                "latest_sequence": owner.latest_sequence,
                "tracking": owner.tracking,
                "correlation_id": owner.correlation_id,
                "actions": [
                    {"action_id": a.action_id, "state": a.state, "operation": a.operation}
                    for a in actions
                ],
            }

    def counts(self, workflow_id: str) -> dict:
        with Session(self.engine) as session:

            def count(cls):
                return session.scalar(
                    select(func.count())
                    .select_from(cls)
                    .where(
                        cls.workflow_id == workflow_id,
                    )
                )

            effects = session.scalar(
                select(func.count())
                .select_from(FixtureEffect)
                .join(
                    TicketAction,
                    TicketAction.action_id == FixtureEffect.action_id,
                )
                .where(TicketAction.workflow_id == workflow_id)
            )
            return {
                "events": count(TicketInbox),
                "actions": count(TicketAction),
                "audit": count(TicketAudit),
                "reminders": count(TicketReminder),
                "synthetic_effects": effects,
            }
