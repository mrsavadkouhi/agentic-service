"""Isolated ownership and operator evidence for synthetic fulfillment only."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.storage.models import Base


class OwnedScope(Base):
    __tablename__ = "mirza_fixture_owned_scopes"
    scope_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    world_id: Mapped[str] = mapped_column(ForeignKey("provisioning_fixture_worlds.world_id"))
    payload: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(30))


class OwnedGrant(Base):
    __tablename__ = "mirza_fixture_owned_grants"
    grant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope_id: Mapped[str] = mapped_column(ForeignKey("mirza_fixture_owned_scopes.scope_id"))
    operation_id: Mapped[str] = mapped_column(ForeignKey("mirza_fixture_fulfillments.operation_id"))
    desired: Mapped[dict] = mapped_column(JSON)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    state: Mapped[str] = mapped_column(String(30))


class RecoveryCommand(Base):
    __tablename__ = "mirza_fixture_recovery_commands"
    command_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    operation_id: Mapped[str] = mapped_column(ForeignKey("mirza_fixture_fulfillments.operation_id"))
    payload: Mapped[dict] = mapped_column(JSON)


class LifecycleAudit(Base):
    __tablename__ = "mirza_fixture_lifecycle_audit"
    audit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    operation_id: Mapped[str] = mapped_column(ForeignKey("mirza_fixture_fulfillments.operation_id"))
    code: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
