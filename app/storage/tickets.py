"""Durable inbox/outbox and projections. Temporal remains the transition owner."""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.storage.models import Base


class TicketWorkflowRecord(Base):
    __tablename__ = "ticket_workflows"
    __table_args__ = (UniqueConstraint("tenant_id", "ticket_id", name="uq_ticket_owner"),)
    workflow_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(200))
    ticket_id: Mapped[str] = mapped_column(String(200))
    worker_role: Mapped[str] = mapped_column(String(20))
    correlation_id: Mapped[str] = mapped_column(String(36))
    tracking: Mapped[dict] = mapped_column(JSON)
    snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    latest_sequence: Mapped[int] = mapped_column(BigInteger, default=-1)
    state: Mapped[str] = mapped_column(String(40), default="received")


class TicketInbox(Base):
    __tablename__ = "ticket_inbox"
    __table_args__ = (
        UniqueConstraint("workflow_id", "external_event_id", name="uq_ticket_event"),
        CheckConstraint("kind IN ('ticket', 'cancel')", name="ticket_event_kind"),
    )
    event_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("ticket_workflows.workflow_id"), index=True)
    external_event_id: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))
    sequence: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    payload_digest: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    result_tracking: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    processed: Mapped[bool] = mapped_column(Boolean, default=False)
    notified: Mapped[bool] = mapped_column(Boolean, default=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CatalogRecord(Base):
    __tablename__ = "ticket_catalogs"
    version: Mapped[str] = mapped_column(String(200), primary_key=True)
    payload_digest: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)


class TicketAction(Base):
    __tablename__ = "ticket_actions"
    __table_args__ = (
        CheckConstraint(
            "state IN ('planned', 'in_flight', 'uncertain', 'verified', 'superseded', 'cancelled')",
            name="ticket_action_state",
        ),
    )
    action_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("ticket_workflows.workflow_id"), index=True)
    authorized_sequence: Mapped[int] = mapped_column(BigInteger)
    terms_digest: Mapped[str] = mapped_column(String(64))
    worker_role: Mapped[str] = mapped_column(String(20))
    state: Mapped[str] = mapped_column(String(20))
    data_kind: Mapped[str] = mapped_column(String(20))
    operation: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict] = mapped_column(JSON)
    correlation_id: Mapped[str] = mapped_column(String(36))


class TicketAudit(Base):
    __tablename__ = "ticket_audit"
    audit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("ticket_workflows.workflow_id"), index=True)
    event_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(36))
    state: Mapped[str] = mapped_column(String(40))
    reason_code: Mapped[str] = mapped_column(String(200))
    metadata_refs: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TicketReminder(Base):
    __tablename__ = "ticket_reminders"
    __table_args__ = (
        UniqueConstraint(
            "workflow_id", "recipient_ref", "local_date", name="uq_daily_ticket_recipient"
        ),
    )
    reminder_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("ticket_workflows.workflow_id"), index=True)
    cycle_id: Mapped[str] = mapped_column(String(64))
    recipient_ref: Mapped[str] = mapped_column(String(200))
    local_date: Mapped[date] = mapped_column(Date)
    state: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(40))
    missing_fields: Mapped[list] = mapped_column(JSON)


class FixtureEffect(Base):
    """Synthetic downstream ledger, not a Mirza or ServiceDesk table."""

    __tablename__ = "fixture_effects"
    action_id: Mapped[str] = mapped_column(ForeignKey("ticket_actions.action_id"), primary_key=True)
    payload_digest: Mapped[str] = mapped_column(String(64))
    fail_once_triggered: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
