"""Local-only durable probe; accepts no tickets, user data or credentials."""

import argparse
import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from temporalio.client import Client

from app.activities.runtime_probe import RuntimeProbeActivities
from app.contracts.runtime import ProbeInput
from app.settings import Settings, WorkerRole
from app.storage.database import make_engine
from app.storage.models import RuntimeProbe, RuntimeProbeEvent
from app.workflows.runtime_probe import RuntimeProbeWorkflow


async def wait_state(handle, expected: str) -> None:
    for _ in range(60):
        if await handle.query(RuntimeProbeWorkflow.status) == expected:
            return
        await asyncio.sleep(0.5)
    raise RuntimeError(f"Probe did not reach {expected}")


async def run(args) -> None:
    settings = Settings()
    role = WorkerRole(args.role)
    engine = make_engine(settings)
    client = await Client.connect(
        settings.temporal_address, namespace=settings.temporal_namespace
    )
    try:
        if args.command == "start":
            async with httpx.AsyncClient() as http:
                response = await http.get(f"{args.api_url}/health/ready", timeout=15)
                response.raise_for_status()
                runtime = (await http.get(f"{args.api_url}/runtime")).json()
                assert runtime["external_write_capabilities"] == []
            probe_id, correlation_id = str(uuid4()), str(uuid4())
            request = ProbeInput(probe_id, correlation_id, role.value)
            workflow_id = f"runtime-probe-{probe_id}"
            handle = await client.start_workflow(
                RuntimeProbeWorkflow.run, request, id=workflow_id,
                task_queue=settings.task_queue(role),
            )
            await wait_state(handle, "waiting")
            payload = {"probe_id": probe_id, "correlation_id": correlation_id,
                       "workflow_id": workflow_id, "worker_role": role.value}
            fd = os.open(args.state_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as stream:
                json.dump(payload, stream)
            print(json.dumps({"worker_role": role.value, "state": "waiting"}))
        else:
            payload = json.loads(args.state_file.read_text())
            assert payload["worker_role"] == role.value
            handle = client.get_workflow_handle(payload["workflow_id"])
            await wait_state(handle, "waiting")
            await handle.signal(RuntimeProbeWorkflow.release)
            result = await asyncio.wait_for(handle.result(), timeout=45)
            assert result["state"] == "completed" and result["external_writes"] is False
            request = ProbeInput(payload["probe_id"], payload["correlation_id"], role.value)
            activities = RuntimeProbeActivities(engine, settings, role)
            # Simulate an activity retry after completion; audit/projection must stay stable.
            await asyncio.to_thread(activities.record_phase, request, "completed")
            await asyncio.to_thread(activities.record_phase, request, "started")
            with Session(engine) as session:
                row = session.get(RuntimeProbe, payload["probe_id"])
                assert row.state == "completed"
                count = session.scalar(select(func.count()).select_from(RuntimeProbeEvent).where(
                    RuntimeProbeEvent.probe_id == payload["probe_id"],
                ))
                assert count == 2
            print(json.dumps({"worker_role": role.value, "state": "completed",
                              "audit_events": count, "external_writes": False}))
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["start", "finish"])
    parser.add_argument("--role", choices=["dispatch", "mirza"], required=True)
    parser.add_argument("--state-file", type=Path, required=True)
    parser.add_argument("--api-url", default="http://api:8080")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()

