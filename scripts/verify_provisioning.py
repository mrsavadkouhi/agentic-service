"""Local fixture-only provisioning, encrypted delivery and native restart/replay checks."""

import argparse
import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session
from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode
from temporalio.worker import Replayer, Worker

from app.activities.provisioning import ProvisioningActivities
from app.contracts.provisioning import FulfillmentReceipt, FulfillmentStart
from app.settings import Settings, WorkerRole
from app.storage.database import check_database, make_engine
from app.storage.provisioning import (
    FixtureMessage,
    FixtureWorld,
    FulfillmentRecord,
    FulfillmentStep,
    ProvisioningSecret,
)
from app.workflows.provisioning import MirzaFixtureFulfillmentWorkflow
from scripts.provisioning_cases import JOBS, case
from scripts.verify_observations import business_counts, local_config


def config(path):
    base = local_config(Settings())
    return Settings(
        _env_file=None,
        database_url=base.database_url,
        temporal_address=base.temporal_address,
        temporal_namespace="agentic",
        mirza_mode="automatic",
        enable_fixture_execution=True,
        enable_fixture_provisioning=True,
        fixture_vault_key_file=path,
    )


async def paused(handle):
    async with asyncio.timeout(90):
        while True:
            try:
                receipt = await handle.query("status", result_type=FulfillmentReceipt | None)
            except RPCError as error:
                if error.status not in {RPCStatusCode.NOT_FOUND, RPCStatusCode.FAILED_PRECONDITION}:
                    raise
                await asyncio.sleep(0.2)
                continue
            if receipt and receipt.phase == "mutation":
                return
            await asyncio.sleep(0.2)


def validate_private_state(service, operation_ids):
    keys = []
    with Session(service.engine) as session:
        for operation_id in operation_ids:
            record = session.get(FulfillmentRecord, operation_id)
            assert record.state == "completed"
            world = session.get(FixtureWorld, record.world_id).payload
            messages = session.scalars(
                select(FixtureMessage).where(FixtureMessage.operation_id == operation_id)
            ).all()
            assert len(messages) == 2
            assert all(
                step.state == "verified"
                for step in session.scalars(
                    select(FulfillmentStep).where(FulfillmentStep.operation_id == operation_id)
                )
            )
            secrets = session.scalars(
                select(ProvisioningSecret).where(ProvisioningSecret.operation_id == operation_id)
            ).all()
            for saved in secrets:
                material = service.cipher.open(saved.secret_ref, saved.ciphertext)
                raw = material["key"]
                keys.append(raw)
                assert raw not in json.dumps(world) and raw not in json.dumps(record.payload)
                assert raw.encode() not in saved.ciphertext
                for message in messages:
                    body = service.cipher.open(message.delivery_id, message.ciphertext)["body"]
                    assert (raw in body) is (message.kind == "user_dm")
                    if message.kind == "user_dm":
                        assert message.recipient_ref == record.payload["owner_dm_ref"]
                assert (
                    len(
                        [
                            k
                            for k in world["keys"].values()
                            if k["metadata"].get("operation_ref") == operation_id
                        ]
                    )
                    == 1
                )
    return keys


async def verify_concurrent_union(service, tenant):
    operation_ids = []
    world_id = tenant.removeprefix("fulfillment-fixture-") + "c" * 32
    for suffix, model in (("a", "model-b"), ("b", "model-c")):
        normalized, catalog, auth = case(
            3, tenant, fields={**JOBS[3], "model_ids": [model]}, ticket_id="concurrent-" + suffix
        )
        catalog = catalog.model_copy(update={"model_ids": (*catalog.model_ids, "model-c")})
        operation_ids.append(service.seed(normalized, catalog, auth, world_id=world_id))
    receipts = await asyncio.gather(
        *(asyncio.to_thread(service.advance, ref, 0) for ref in operation_ids)
    )
    assert all(receipt.state == "running" and receipt.phase == "mutation" for receipt in receipts)
    with Session(service.engine) as session:
        world = session.get(FixtureWorld, world_id).payload
        assert set(world["teams"]["tool-team"]["models"]) == {"model-a", "model-b", "model-c"}
        assert world["teams"]["tool-team"]["metadata"] == {"keep": "fixture-unrelated"}


async def run(args):
    args.check_stage = "local_configuration"
    settings = config(args.vault_key_file)
    engine = make_engine(settings)
    try:
        check_database(engine)
        before = business_counts(engine)
        activities = ProvisioningActivities(engine, settings, WorkerRole.MIRZA)
        client = await Client.connect(settings.temporal_address, namespace="agentic")
        if args.phase == "start":
            state = {"tenant": "fulfillment-fixture-" + uuid4().hex, "operations": []}
            for index in range(9):
                operation_id = activities.service.seed(*case(index, state["tenant"]))
                state["operations"].append(operation_id)
                with Session(engine) as session, session.begin():
                    record = session.get(FulfillmentRecord, operation_id)
                    row = session.get(FixtureWorld, record.world_id)
                    value = json.loads(json.dumps(row.payload))
                    value["faults"]["mutation"] = "after"
                    row.payload = value
            fd = os.open(args.state_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as output:
                json.dump(state, output)
        else:
            state = json.loads(args.state_file.read_text())
        if not state["tenant"].startswith("fulfillment-fixture-") or len(state["operations"]) != 9:
            raise ValueError("Invalid private verification state")
        queue = state["tenant"] + "-mirza"
        async with Worker(
            client,
            task_queue=queue,
            workflows=[MirzaFixtureFulfillmentWorkflow],
            activities=[activities.advance],
            max_concurrent_activities=1,
            max_concurrent_activity_task_polls=1,
            max_concurrent_workflow_tasks=2,
            max_concurrent_workflow_task_polls=2,
            max_cached_workflows=2,
        ):
            args.check_stage = "native_workflows"
            histories = []
            for operation_id in state["operations"]:
                owner_id = state["tenant"] + "-" + operation_id
                if args.phase == "start":
                    handle = await client.start_workflow(
                        MirzaFixtureFulfillmentWorkflow.run,
                        FulfillmentStart(operation_id, queue, pause_after_provisioning=True),
                        id=owner_id,
                        task_queue=queue,
                    )
                    await paused(handle)
                    assert activities.service.projection(operation_id)["deliveries"] == []
                else:
                    handle = client.get_workflow_handle(owner_id, result_type=FulfillmentReceipt)
                    await handle.signal("resume")
                    async with asyncio.timeout(90):
                        result = await handle.result()
                    assert result.state == "completed"
                    histories.append(await handle.fetch_history())
            if args.phase == "finish":
                args.check_stage = "encryption_and_replay"
                raw_keys = validate_private_state(activities.service, state["operations"])
                assert len(raw_keys) == 2  # Existing mapped Tool team and ticket-scoped new team.
                for history in histories:
                    assert all(
                        raw.encode() not in event.SerializeToString()
                        for raw in raw_keys
                        for event in history.events
                    )
                    assert all(
                        b"owner@example.invalid" not in event.SerializeToString()
                        for event in history.events
                    )
                    await Replayer(workflows=[MirzaFixtureFulfillmentWorkflow]).replay_workflow(
                        history
                    )
                await verify_concurrent_union(activities.service, state["tenant"])
        assert business_counts(engine) == before
        print(
            json.dumps(
                {
                    "phase": args.phase,
                    "cases": 9,
                    "allowed_operations": 8,
                    "replay_verified": args.phase == "finish",
                    "external_calls": 0,
                    "business_inbox_or_actions_created": 0,
                    "encrypted_keys_and_owner_only_delivery_verified": args.phase == "finish",
                    "concurrent_model_union_verified": args.phase == "finish",
                }
            )
        )
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["start", "finish"])
    parser.add_argument("--state-file", type=Path, required=True)
    parser.add_argument("--vault-key-file", type=Path, required=True)
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception as error:
        print(
            json.dumps(
                {
                    "verified": False,
                    "check_stage": getattr(args, "check_stage", "startup"),
                    "error_type": type(error).__name__,
                }
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
