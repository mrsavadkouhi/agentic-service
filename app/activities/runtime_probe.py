import asyncio
import logging
from uuid import UUID

from sqlalchemy import Engine
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from temporalio import activity
from temporalio.exceptions import ApplicationError

from app.contracts.runtime import ProbeInput
from app.settings import Settings, WorkerRole
from app.storage.models import RuntimeProbe, RuntimeProbeEvent

logger = logging.getLogger(__name__)


class RuntimeProbeActivities:
    def __init__(self, engine: Engine, settings: Settings, role: WorkerRole) -> None:
        self.engine = engine
        self.settings = settings
        self.role = role

    @activity.defn(name="record_runtime_probe")
    async def record(self, request: ProbeInput, phase: str) -> None:
        try:
            UUID(request.probe_id)
            UUID(request.correlation_id)
        except ValueError:
            raise ApplicationError("Probe IDs must be UUIDs", non_retryable=True) from None
        if request.worker_role != self.role.value or phase not in {"started", "completed"}:
            raise ApplicationError("Invalid runtime probe scope", non_retryable=True)
        await asyncio.to_thread(self.record_phase, request, phase)
        logger.info("Runtime probe recorded", extra={
            "event": phase, "probe_id": request.probe_id,
            "correlation_id": request.correlation_id, "worker_role": self.role.value,
        })

    def record_phase(self, request: ProbeInput, phase: str) -> None:
        with Session(self.engine) as session, session.begin():
            session.execute(insert(RuntimeProbe).values(
                probe_id=request.probe_id, correlation_id=request.correlation_id,
                worker_role=self.role.value, mode=self.settings.mode(self.role).value,
                state="waiting",
            ).on_conflict_do_nothing(index_elements=["probe_id"]))
            row = session.get(RuntimeProbe, request.probe_id, with_for_update=True)
            if row.correlation_id != request.correlation_id or row.worker_role != self.role.value:
                raise ApplicationError("Conflicting probe identity", non_retryable=True)
            session.execute(insert(RuntimeProbeEvent).values(
                probe_id=request.probe_id, phase=phase,
            ).on_conflict_do_nothing(index_elements=["probe_id", "phase"]))
            # A delayed retry of 'started' must never regress a completed projection.
            if phase == "completed":
                row.state = "completed"

