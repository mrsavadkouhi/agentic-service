import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from temporalio.api.workflowservice.v1 import DescribeNamespaceRequest
from temporalio.client import Client

from app import __version__
from app.logging import configure_logging, correlation_id
from app.settings import Settings, WorkerRole
from app.storage.database import check_database, make_engine, worker_is_ready

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
        try:
            yield
        finally:
            app.state.engine.dispose()

    app = FastAPI(title="ICT workflow runtime", version=__version__, lifespan=lifespan)

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
        }

    return app
