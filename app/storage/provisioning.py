"""Synthetic fulfillment ledger and encrypted delivery data; never Mirza DB tables."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.storage.models import Base


class FixtureWorld(Base):
    __tablename__ = "provisioning_fixture_worlds"
    world_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSON)


class FulfillmentRecord(Base):
    __tablename__ = "mirza_fixture_fulfillments"
    operation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    world_id: Mapped[str] = mapped_column(ForeignKey("provisioning_fixture_worlds.world_id"))
    payload: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(30))
    reason_code: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FulfillmentStep(Base):
    __tablename__ = "mirza_fixture_steps"
    step_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    operation_id: Mapped[str] = mapped_column(ForeignKey("mirza_fixture_fulfillments.operation_id"))
    phase: Mapped[str] = mapped_column(String(30))
    state: Mapped[str] = mapped_column(String(30))
    claim_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProvisioningSecret(Base):
    __tablename__ = "mirza_fixture_secrets"
    secret_ref: Mapped[str] = mapped_column(String(80), primary_key=True)
    operation_id: Mapped[str] = mapped_column(ForeignKey("mirza_fixture_fulfillments.operation_id"))
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)


class FixtureMessage(Base):
    __tablename__ = "mirza_fixture_messages"
    delivery_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    operation_id: Mapped[str] = mapped_column(ForeignKey("mirza_fixture_fulfillments.operation_id"))
    recipient_ref: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
