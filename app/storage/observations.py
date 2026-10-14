"""Local observation cache and conservative spend reservations; no business inbox writes."""

from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal

from sqlalchemy import JSON, Date, DateTime, Engine, Numeric, String, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.contracts.observation import ObservationReceipt, ObservationResult
from app.contracts.tickets import Tracking
from app.policies.reminders import TEHRAN
from app.storage.models import Base
from app.storage.tickets import TicketInbox, TicketWorkflowRecord


class ObservationRecord(Base):
    __tablename__ = "ticket_observations"
    observation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(200))
    ticket_id: Mapped[str] = mapped_column(String(200), index=True)
    stage: Mapped[str] = mapped_column(String(20))
    input_digest: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(20))
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    budget_day: Mapped[object] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=lambda: datetime.now(UTC)
    )


class InferenceBudget(Base):
    __tablename__ = "inference_budgets"
    budget_day: Mapped[object] = mapped_column(Date, primary_key=True)
    reserved_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6))


class ObservationRepository:
    def __init__(self, engine: Engine):
        self.engine = engine
        self.insert = sqlite_insert if engine.dialect.name == "sqlite" else pg_insert

    def get(self, observation_id):
        with Session(self.engine) as session:
            record = session.get(ObservationRecord, observation_id)
            return (
                ObservationResult.model_validate(record.result)
                if record and record.result
                else None
            )

    def source_identity(self, observation_id):
        with Session(self.engine) as session:
            record = session.get(ObservationRecord, observation_id)
            return (record.tenant_id, record.ticket_id, record.stage) if record else None

    def receipt(self, observation_id):
        result = self.get(observation_id)
        if result is None:
            return ObservationReceipt(observation_id, "blocked", "inference_outcome_uncertain")
        return ObservationReceipt(
            observation_id,
            result.state,
            result.reason_code,
            result.classification.kind if result.classification else None,
            result.classification.operation if result.classification else None,
        )

    def claim(
        self, observation_id, request, stage, input_digest, base, reserve, daily_cap, clock=None
    ):
        day = (clock or datetime.now(UTC)).astimezone(TEHRAN).date()
        reserve = reserve.quantize(Decimal("0.000001"), rounding=ROUND_CEILING)
        with Session(self.engine) as session, session.begin():
            inserted = session.scalar(
                self.insert(ObservationRecord)
                .values(
                    observation_id=observation_id,
                    tenant_id=request.tenant_id,
                    ticket_id=request.ticket_id,
                    stage=stage,
                    input_digest=input_digest,
                    state="running",
                    result=None,
                    budget_day=day,
                    updated_at=datetime.now(UTC),
                )
                .on_conflict_do_nothing(index_elements=["observation_id"])
                .returning(ObservationRecord.observation_id)
            )
            if inserted is None:
                record = session.get(ObservationRecord, observation_id, with_for_update=True)
                if not (
                    record.result
                    and record.result["reason_code"] == "daily_inference_budget"
                    and record.budget_day < day
                ):
                    return False
                record.state, record.result, record.budget_day = "running", None, day
            else:
                record = session.get(ObservationRecord, observation_id)
            if reserve > 0:
                session.execute(
                    self.insert(InferenceBudget)
                    .values(
                        budget_day=day,
                        reserved_usd=Decimal(0),
                    )
                    .on_conflict_do_nothing(index_elements=["budget_day"])
                )
                budget = session.get(InferenceBudget, day, with_for_update=True)
                if budget.reserved_usd + reserve > Decimal(str(daily_cap)):
                    record.state = "complete"
                    record.result = base.model_copy(
                        update={
                            "state": "blocked",
                            "reason_code": "daily_inference_budget",
                        }
                    ).model_dump(mode="json")
                    return False
                # Never refund an uncertain call: a lost response may have been billed.
                budget.reserved_usd += reserve
            return True

    def finish(self, observation_id, result: ObservationResult):
        result = ObservationResult.model_validate(result.model_dump())
        with Session(self.engine) as session, session.begin():
            record = session.get(ObservationRecord, observation_id, with_for_update=True)
            if record is None:
                raise ValueError("Observation has no durable claim")
            if record.result is None:
                record.result = result.model_dump(mode="json")
                record.state = "complete"
        return self.receipt(observation_id)

    def latest(self, tenant_id, ticket_id):
        with Session(self.engine) as session:
            rows = session.scalars(
                select(ObservationRecord)
                .where(
                    ObservationRecord.tenant_id == tenant_id,
                    ObservationRecord.ticket_id == ticket_id,
                )
                .order_by(ObservationRecord.updated_at.desc(), ObservationRecord.observation_id)
                .limit(10)
            )
            return [
                {
                    "observation_id": row.observation_id,
                    "stage": row.stage,
                    "state": row.state,
                    "result": row.result,
                }
                for row in rows
            ]

    def tracked_handoffs(self):
        """Read native processed handoffs; synthetic records cannot enroll real tickets."""
        with Session(self.engine) as session:
            owners = session.scalars(
                select(TicketWorkflowRecord)
                .where(
                    TicketWorkflowRecord.tenant_id == "servicedesk",
                    TicketWorkflowRecord.worker_role == "mirza",
                    TicketWorkflowRecord.state.in_(
                        ["awaiting_approval", "awaiting_clarification", "evaluating"]
                    ),
                )
                .limit(1001)
            ).all()
            if len(owners) > 1000:
                raise ValueError("Tracked handoff read limit")
            result = {}
            for owner in owners:
                frame = Tracking.model_validate(owner.tracking)
                last = session.scalar(
                    select(TicketInbox)
                    .where(
                        TicketInbox.workflow_id == owner.workflow_id,
                        TicketInbox.kind == "ticket",
                        TicketInbox.processed.is_(True),
                    )
                    .order_by(TicketInbox.sequence.desc())
                    .limit(1)
                )
                if (
                    frame.fallback_enrolled
                    and frame.original_dwe_incharge_ref
                    and frame.enrollment_sequence is not None
                    and last
                    and last.payload.get("data_kind") == "servicedesk"
                    and last.payload.get("snapshot", {}).get("source_order_verified") is True
                ):
                    result[owner.ticket_id] = frame.original_dwe_incharge_ref
            return result
