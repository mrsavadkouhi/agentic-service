from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class RuntimeProbe(Base):
    __tablename__ = "runtime_probes"
    __table_args__ = (
        CheckConstraint("worker_role IN ('dispatch', 'mirza')", name="probe_role"),
        CheckConstraint("mode IN ('observe', 'review', 'automatic')", name="probe_mode"),
        CheckConstraint("state IN ('waiting', 'completed')", name="probe_state"),
    )

    probe_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    correlation_id: Mapped[str] = mapped_column(String(36))
    worker_role: Mapped[str] = mapped_column(String(20))
    mode: Mapped[str] = mapped_column(String(20))
    state: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RuntimeProbeEvent(Base):
    __tablename__ = "runtime_probe_events"
    __table_args__ = (CheckConstraint("phase IN ('started', 'completed')", name="probe_phase"),)

    probe_id: Mapped[str] = mapped_column(ForeignKey("runtime_probes.probe_id"), primary_key=True)
    phase: Mapped[str] = mapped_column(String(20), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RuntimeWorker(Base):
    __tablename__ = "runtime_workers"
    __table_args__ = (
        CheckConstraint("worker_role IN ('dispatch', 'mirza')", name="worker_role"),
        CheckConstraint("mode IN ('observe', 'review', 'automatic')", name="worker_mode"),
        CheckConstraint("state IN ('running', 'paused', 'stopped')", name="worker_state"),
    )

    worker_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    worker_role: Mapped[str] = mapped_column(String(20), index=True)
    task_queue: Mapped[str] = mapped_column(String(200))
    mode: Mapped[str] = mapped_column(String(20))
    state: Mapped[str] = mapped_column(String(20))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))

