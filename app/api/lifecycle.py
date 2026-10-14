"""Authenticated operator projections and fixture-only recovery commands."""

import asyncio
import re

from fastapi import APIRouter, HTTPException, Request
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from app.activities.lifecycle_service import LifecycleService
from app.api.intake import authorize
from app.contracts.lifecycle import LifecycleStart, RecoveryRequest
from app.contracts.tickets import stable_id
from app.policies.provisioning import ProvisioningBlocked


def lifecycle_router(settings):
    router = APIRouter()

    def reference(value):
        if not re.fullmatch(r"[a-f0-9]{64}", value):
            raise HTTPException(422, "Invalid operation reference")

    def repository(request):
        authorize(request, settings.operator_token)
        return LifecycleService(request.app.state.engine)

    def enabled():
        if not settings.enable_fixture_provisioning or settings.mirza_paused:
            raise HTTPException(403, "Fixture recovery disabled")

    @router.get("/v1/operations/metrics")
    async def metrics(request: Request):
        return await asyncio.to_thread(repository(request).metrics)

    @router.get("/v1/operations/{operation_id}")
    async def view(operation_id: str, request: Request):
        service = repository(request)
        reference(operation_id)
        value = await asyncio.to_thread(service.view, operation_id)
        if value is None:
            raise HTTPException(404, "Unknown operation")
        return value

    @router.post("/v1/operations/{operation_id}/{action}", status_code=202)
    async def command(operation_id: str, action: str, body: RecoveryRequest, request: Request):
        service = repository(request)
        reference(operation_id)
        if action not in {"cancel", "resume", "reconcile", "retain"}:
            raise HTTPException(404, "Unknown command")
        enabled()
        try:
            if action == "retain":
                return await asyncio.to_thread(service.retain, operation_id, body.expected_revision)
            if action == "reconcile":
                current = await asyncio.to_thread(service.view, operation_id)
                if current is None:
                    raise KeyError(operation_id)
                if current["revision"] != body.expected_revision:
                    raise ProvisioningBlocked("recovery_revision_conflict")
                command_id = stable_id(operation_id, "reconcile", body.request_id)
                result = {"command_id": command_id, "state": "scheduled"}
            else:
                result = await asyncio.to_thread(
                    service.command,
                    operation_id,
                    body.request_id,
                    action,
                    body.expected_revision,
                    settings.operator_principal,
                )
            # A durable pending resume can be retried after a failed Temporal start.
            # Cancellation keeps expiry cleanup scheduled; it never revokes a grant.
            await request.app.state.temporal.start_workflow(
                "MirzaFixtureLifecycleWorkflow",
                LifecycleStart(
                    operation_id,
                    settings.mirza_task_queue,
                    result["command_id"] if action == "resume" else None,
                    fulfill=action == "resume",
                ),
                id="fixture-recovery-" + result["command_id"],
                task_queue=settings.mirza_task_queue,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )
            return {**result, "execution_domain": "synthetic", "external_write_capabilities": []}
        except KeyError:
            raise HTTPException(404, "Unknown operation") from None
        except ProvisioningBlocked:
            raise HTTPException(409, "Recovery state or revision conflict") from None

    return router
