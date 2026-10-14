"""Durable policy previews and pinned reviewer state, outside executable intake."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Engine, Integer, String, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.contracts.mirza_review import MirzaReviewReceipt, MirzaReviewResult, MirzaReviewState
from app.contracts.tickets import stable_id
from app.storage.models import Base


class ReviewConflict(ValueError):
    pass


class MirzaReviewHead(Base):
    __tablename__ = "mirza_review_heads"
    owner_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer)
    state: Mapped[dict] = mapped_column(JSON)


class MirzaPolicyReview(Base):
    __tablename__ = "mirza_policy_reviews"
    review_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(200))
    ticket_id: Mapped[str] = mapped_column(String(200), index=True)
    observation_id: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MirzaReviewRepository:
    def __init__(self, engine: Engine):
        self.engine = engine
        self.insert = sqlite_insert if engine.dialect.name == "sqlite" else pg_insert

    def load(self, tenant_id, ticket_id):
        with Session(self.engine) as session:
            head = session.get(MirzaReviewHead, stable_id(tenant_id, ticket_id))
            return (head.revision, MirzaReviewState.model_validate(head.state)) if head else (
                0, MirzaReviewState()
            )

    def get(self, review_id):
        with Session(self.engine) as session:
            row = session.get(MirzaPolicyReview, review_id)
            return MirzaReviewResult.model_validate(row.result) if row else None

    def receipt(self, review_id):
        result = self.get(review_id)
        if result is None:
            raise KeyError("Unknown policy preview")
        return MirzaReviewReceipt(review_id, result.state, result.reason_code)

    def commit(self, request, expected_revision, result):
        result = MirzaReviewResult.model_validate(result.model_dump())
        owner = stable_id(request.tenant_id, request.ticket_id)
        review_id = stable_id("mirza-policy-review-v1", owner, request.observation_id)
        with Session(self.engine) as session, session.begin():
            session.execute(self.insert(MirzaReviewHead).values(
                owner_id=owner, revision=0, state=MirzaReviewState().model_dump(mode="json"),
            ).on_conflict_do_nothing(index_elements=["owner_id"]))
            head = session.get(MirzaReviewHead, owner, with_for_update=True)
            previous = session.get(MirzaPolicyReview, review_id)
            if previous:
                return MirzaReviewReceipt(review_id, previous.result["state"],
                                          previous.result["reason_code"])
            if head.revision != expected_revision:
                raise ReviewConflict("Policy preview revision changed")
            old = MirzaReviewState.model_validate(head.state)
            if old.tracking.original_dwe_incharge_ref and (
                old.tracking.original_dwe_incharge_ref
                != result.next_state.tracking.original_dwe_incharge_ref
                or old.dwe_contact != result.next_state.dwe_contact
                or old.dwe_source_digest != result.next_state.dwe_source_digest
                or old.dwe_observed_at != result.next_state.dwe_observed_at
            ):
                raise ReviewConflict("Original DWE identity changed")
            if (old.evidence.baseline
                    and old.evidence.baseline != result.next_state.evidence.baseline):
                raise ReviewConflict("Original approval baseline changed")
            if (old.first_approval_observation is not None
                    and old.first_approval_observation
                    != result.next_state.first_approval_observation):
                raise ReviewConflict("First approval observation changed")
            head.revision += 1
            head.state = result.next_state.model_dump(mode="json")
            session.add(MirzaPolicyReview(
                review_id=review_id, tenant_id=request.tenant_id, ticket_id=request.ticket_id,
                observation_id=request.observation_id, result=result.model_dump(mode="json"),
            ))
        return self.receipt(review_id)

    def latest(self, tenant_id, ticket_id):
        with Session(self.engine) as session:
            rows = session.scalars(select(MirzaPolicyReview).where(
                MirzaPolicyReview.tenant_id == tenant_id, MirzaPolicyReview.ticket_id == ticket_id,
            ).order_by(MirzaPolicyReview.created_at.desc(), MirzaPolicyReview.review_id).limit(10))
            return [{"review_id": row.review_id, "observation_id": row.observation_id,
                     "result": row.result} for row in rows]
