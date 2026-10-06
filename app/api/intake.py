import asyncio
import hmac
import logging
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from app.contracts.execution import TicketWorkflowStart
from app.contracts.tickets import Catalog, Contract, Ref, TicketEvent
from app.logging import correlation_id
from app.settings import Settings, WorkerRole
from app.storage.ticket_repository import EventConflict, TicketRepository

logger = logging.getLogger(__name__)


class CancelRequest(Contract):
    request_id: Ref
    expected_sequence: int = Field(ge=-1)


def authorize(request: Request, token) -> None:
    if token is None:
        raise HTTPException(503, "Endpoint disabled")
    supplied = request.headers.get("Authorization", "")
    if not hmac.compare_digest(supplied, "Bearer " + token.get_secret_value()):
        raise HTTPException(401, "Invalid credential")


def router(settings: Settings) -> APIRouter:
    routes = APIRouter()

    @routes.post("/v1/events", status_code=202)
    async def accept(request: Request):
        authorize(request, settings.intake_token)
        # Bound the streamed body even when Content-Length is absent or dishonest.
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 65536:
                raise HTTPException(413, "Event too large")
        try:
            event = TicketEvent.model_validate_json(body)
        except Exception:
            raise HTTPException(422, "Invalid normalized event") from None
        if event.data_kind == "synthetic" and not settings.enable_fixture_execution:
            raise HTTPException(403, "Synthetic intake disabled")
        try:
            return await asyncio.to_thread(
                request.app.state.tickets.accept, event, correlation_id.get()
            )
        except EventConflict:
            raise HTTPException(409, "Event identity conflict") from None

    @routes.get("/v1/workflows/{workflow_id}")
    async def projection(workflow_id: str, request: Request):
        authorize(request, settings.operator_token)
        result = await asyncio.to_thread(request.app.state.tickets.projection, workflow_id)
        if result is None:
            raise HTTPException(404, "Unknown workflow")
        return result

    @routes.post("/v1/workflows/{workflow_id}/cancel", status_code=202)
    async def cancel(workflow_id: str, command: CancelRequest, request: Request):
        authorize(request, settings.operator_token)
        try:
            return await asyncio.to_thread(
                request.app.state.tickets.cancel,
                workflow_id,
                command.request_id,
                command.expected_sequence,
                settings.operator_principal,
            )
        except EventConflict:
            raise HTTPException(409, "Cancellation revision or identity conflict") from None
        except KeyError:
            raise HTTPException(404, "Unknown workflow") from None

    return routes


async def deliver_notifications(repository: TicketRepository, client, settings: Settings):
    """Transactional inbox doubles as an outbox; acknowledge only after Temporal accepts."""
    while True:
        try:
            rows = await asyncio.to_thread(repository.pending_notifications)
            for row in rows:
                role = WorkerRole(row["worker_role"])
                await client.start_workflow(
                    "TicketWorkflow",
                    TicketWorkflowStart(
                        row["workflow_id"],
                        role.value,
                        settings.dispatch_task_queue,
                        settings.mirza_task_queue,
                    ),
                    id=row["workflow_id"],
                    task_queue=settings.task_queue(role),
                    start_signal="wake",
                    start_signal_args=[],
                    id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                    id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                    rpc_timeout=timedelta(seconds=settings.dependency_timeout_seconds),
                )
                await asyncio.to_thread(repository.mark_notified, row["event_key"])
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Ticket outbox will retry", extra={"error_type": type(exc).__name__})
        await asyncio.sleep(1)


def configured_catalog(settings: Settings) -> Catalog | None:
    path = settings.catalog_file
    if path is None and settings.enable_fixture_execution:
        path = Path(__file__).resolve().parents[1] / "policies" / "synthetic_catalog.json"
    if path is None:
        return None
    catalog = Catalog.model_validate_json(path.read_text())
    if settings.enable_fixture_execution and catalog.environment != "synthetic":
        raise ValueError("Synthetic execution requires a synthetic catalog")
    return catalog
