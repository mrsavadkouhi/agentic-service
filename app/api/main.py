import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from temporalio.api.workflowservice.v1 import DescribeNamespaceRequest
from temporalio.client import Client

from app import __version__
from app.api.intake import configured_catalog, deliver_notifications, router
from app.logging import configure_logging, correlation_id
from app.settings import Settings, WorkerRole
from app.storage.database import check_database, make_engine, worker_is_ready
from app.storage.ticket_repository import TicketRepository

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()
    configure_logging(config.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.engine = make_engine(config)
        app.state.temporal = await Client.connect(
            config.temporal_address, namespace=config.temporal_namespace, lazy=True
        )
        app.state.tickets = TicketRepository(app.state.engine)
        delivery = None
        try:
            catalog = configured_catalog(config)
            if catalog:
                await asyncio.to_thread(app.state.tickets.seed_catalog, catalog)
            if config.intake_token or config.operator_token:
                delivery = asyncio.create_task(deliver_notifications(
                    app.state.tickets, app.state.temporal, config,
                ))
            yield
        finally:
            if delivery:
                delivery.cancel()
                await asyncio.gather(delivery, return_exceptions=True)
            app.state.engine.dispose()

    app = FastAPI(title="ICT workflow runtime", version=__version__, lifespan=lifespan)
    app.include_router(router(config))

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request, exc):
        return JSONResponse({"detail": "Invalid request"}, status_code=422)

    @app.exception_handler(Exception)
    async def unavailable(request, exc):
        logger.error("Request unavailable", extra={"error_type": type(exc).__name__})
        return JSONResponse({"detail": "Service unavailable"}, status_code=503)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        try:
            request_id = str(UUID(request.headers.get("X-Correlation-ID", "")))
        except ValueError:
            request_id = str(uuid4())
        token = correlation_id.set(request_id)
        try:
            response = await call_next(request)
            response.headers["X-Correlation-ID"] = request_id
            logger.info("HTTP request completed", extra={"event": "http_request"})
            return response
        finally:
            correlation_id.reset(token)

    @app.get("/health/live")
    async def live():
        return {"status": "alive", "version": __version__}

    @app.get("/health/ready")
    async def ready(request: Request):
        dependencies = {}
        try:
            await asyncio.wait_for(
                asyncio.to_thread(check_database, request.app.state.engine),
                timeout=config.dependency_timeout_seconds + 1,
            )
            dependencies["postgresql"] = "ready"
        except Exception as exc:
            dependencies["postgresql"] = "unavailable"
            logger.warning("Database not ready", extra={"error_type": type(exc).__name__})
        try:
            await request.app.state.temporal.workflow_service.describe_namespace(
                DescribeNamespaceRequest(namespace=config.temporal_namespace),
                timeout=timedelta(seconds=config.dependency_timeout_seconds),
            )
            dependencies["temporal"] = "ready"
        except Exception as exc:
            dependencies["temporal"] = "unavailable"
            logger.warning("Temporal not ready", extra={"error_type": type(exc).__name__})
        for role in WorkerRole:
            if config.paused(role):
                dependencies[f"worker_{role.value}"] = "paused"
            elif dependencies["postgresql"] != "ready":
                dependencies[f"worker_{role.value}"] = "unavailable"
            else:
                try:
                    present = await asyncio.wait_for(
                        asyncio.to_thread(worker_is_ready, request.app.state.engine, config, role),
                        timeout=config.dependency_timeout_seconds + 1,
                    )
                    dependencies[f"worker_{role.value}"] = "ready" if present else "unavailable"
                except Exception as exc:
                    dependencies[f"worker_{role.value}"] = "unavailable"
                    logger.warning("Worker readiness unavailable", extra={
                        "worker_role": role.value, "error_type": type(exc).__name__,
                    })
        healthy = all(value in {"ready", "paused"} for value in dependencies.values())
        return JSONResponse(
            {"status": "ready" if healthy else "not_ready", "dependencies": dependencies},
            status_code=200 if healthy else 503,
        )

    @app.get("/runtime")
    async def runtime():
        return {
            "version": __version__,
            "workflows": {
                role.value: {"mode": config.mode(role).value, "paused": config.paused(role)}
                for role in WorkerRole
            },
            "business_workflows_implemented": False,
            "external_write_capabilities": [],
            "registered_workflow": "RuntimeProbeWorkflow",
            "ticket_contracts_implemented": True,
            "registered_workflows": ["RuntimeProbeWorkflow", "TicketWorkflow"],
            "synthetic_connector_enabled": config.enable_fixture_execution,
        }

    return app
