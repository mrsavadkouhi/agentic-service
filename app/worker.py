import argparse
import asyncio
import json
import logging
import signal
import time
from uuid import uuid4

from temporalio.client import Client
from temporalio.worker import Worker

from app.activities.mirza_review import MirzaReviewActivities
from app.activities.observation import ObservationActivities
from app.activities.provisioning import ProvisioningActivities
from app.activities.runtime_probe import RuntimeProbeActivities
from app.activities.tickets import TicketActivities
from app.connectors.factory import Connectors
from app.logging import configure_logging
from app.settings import Settings, WorkerRole
from app.storage.database import check_database, make_engine
from app.storage.mirza_reviews import MirzaReviewRepository
from app.storage.observations import ObservationRepository
from app.storage.ticket_repository import TicketRepository
from app.storage.workers import heartbeat
from app.worker_health import marker_path
from app.workflows.mirza_review import MirzaPolicyReviewWorkflow
from app.workflows.observation import (
    GroupCorrectionPreflightWorkflow,
    ObservationListenerWorkflow,
    ObservationTicketWorkflow,
)
from app.workflows.provisioning import MirzaFixtureFulfillmentWorkflow
from app.workflows.runtime_probe import RuntimeProbeWorkflow
from app.workflows.tickets import TicketWorkflow

logger = logging.getLogger(__name__)


async def serve(settings: Settings, role: WorkerRole) -> None:
    engine = make_engine(settings)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    worker_id = str(uuid4())
    worker = None
    worker_task = None
    health_task = None
    stop_task = None
    connectors = None
    observations = None
    path = marker_path(role.value)

    async def keep_alive():
        while not stop.is_set():
            state = "paused" if settings.paused(role) else "running"
            await asyncio.to_thread(heartbeat, engine, settings, role, worker_id, state)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(
                    {
                        "role": role.value,
                        "state": state,
                        "timestamp": time.time(),
                    }
                )
            )
            temporary.replace(path)
            await asyncio.sleep(settings.heartbeat_seconds)

    try:
        await asyncio.to_thread(check_database, engine)
        if not settings.paused(role):
            client = await Client.connect(
                settings.temporal_address, namespace=settings.temporal_namespace
            )
            activities = RuntimeProbeActivities(engine, settings, role)
            tickets = TicketActivities(TicketRepository(engine), settings, role)
            connectors = Connectors(settings)
            observations = ObservationActivities(
                ObservationRepository(engine), connectors, settings
            )
            reviews = MirzaReviewActivities(MirzaReviewRepository(engine),
                                           observations.repository, connectors, settings,
                                           observations.inference.versions)
            provisioning = ProvisioningActivities(engine, settings, role)
            observed_activities = (
                [observations.poll, observations.classify, observations.preflight]
                if role == WorkerRole.DISPATCH
                else [observations.extract, reviews.prepare, provisioning.advance]
            )
            observed_workflows = (
                [ObservationListenerWorkflow, ObservationTicketWorkflow,
                 GroupCorrectionPreflightWorkflow]
                if role == WorkerRole.DISPATCH
                else [MirzaPolicyReviewWorkflow, MirzaFixtureFulfillmentWorkflow]
            )
            worker = Worker(
                client,
                task_queue=settings.task_queue(role),
                workflows=[RuntimeProbeWorkflow, TicketWorkflow, *observed_workflows],
                activities=[
                    activities.record,
                    tickets.next_event,
                    tickets.commit,
                    tickets.execute,
                    tickets.finish,
                    tickets.remind,
                    *observed_activities,
                ],
                max_concurrent_activities=2,
                max_concurrent_workflow_tasks=2,
                max_cached_workflows=20,
            )
            worker_task = asyncio.create_task(worker.run())
        logger.info("Worker started", extra={"worker_role": role.value, "event": "started"})
        health_task = asyncio.create_task(keep_alive())
        stop_task = asyncio.create_task(stop.wait())
        watched = [health_task, stop_task] + ([worker_task] if worker_task else [])
        done, _ = await asyncio.wait(watched, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if task is not stop_task:
                try:
                    task.result()
                except Exception as error:
                    logger.error(
                        "Worker background task failed",
                        extra={
                            "worker_role": role.value,
                            "event": "heartbeat_failure"
                            if task is health_task
                            else "worker_failure",
                            "error_type": type(error).__name__,
                        },
                    )
                    raise
    finally:
        stop.set()
        # run() owns cleanup after a fatal failure. Calling shutdown() after Core
        # startup validation failed waits on an event that was never initialized.
        if worker is not None and worker_task is not None and not worker_task.done():
            await worker.shutdown()
        if worker_task is not None:
            await asyncio.gather(worker_task, return_exceptions=True)
        for task in (health_task, stop_task):
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        try:
            await asyncio.to_thread(heartbeat, engine, settings, role, worker_id, "stopped")
        except Exception:
            logger.warning("Final heartbeat unavailable", extra={"worker_role": role.value})
        path.unlink(missing_ok=True)
        if observations:
            await observations.inference.close()
        if connectors:
            await connectors.close()
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=[role.value for role in WorkerRole], required=True)
    args = parser.parse_args()
    configure_logging("INFO")
    try:
        settings = Settings()
        configure_logging(settings.log_level)
        asyncio.run(serve(settings, WorkerRole(args.role)))
    except Exception as exc:
        logger.error("Worker stopped after error", extra={"error_type": type(exc).__name__})
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
