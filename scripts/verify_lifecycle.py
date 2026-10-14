"""Capped native fixture timers/recovery across PostgreSQL and Temporal restart."""

import argparse
import asyncio
import json
import os
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session
from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode
from temporalio.worker import Replayer, Worker

from app.activities.lifecycle_service import LifecycleService
from app.activities.provisioning import ProvisioningActivities
from app.contracts.lifecycle import LifecycleReceipt, LifecycleStart
from app.contracts.provisioning import FulfillmentReceipt, FulfillmentStart
from app.settings import WorkerRole
from app.storage.database import check_database, make_engine
from app.storage.lifecycle import OwnedGrant
from app.storage.provisioning import (
    FixtureMessage,
    FixtureWorld,
    FulfillmentRecord,
    ProvisioningSecret,
)
from app.workflows.lifecycle import MirzaFixtureLifecycleWorkflow
from app.workflows.provisioning import MirzaFixtureFulfillmentWorkflow
from scripts.provisioning_cases import JOBS, case
from scripts.verify_observations import business_counts
from scripts.verify_provisioning import config


def change(service, op, edit):
    with Session(service.engine) as session, session.begin():
        record = session.get(FulfillmentRecord, op)
        row = session.get(FixtureWorld, record.world_id)
        world = deepcopy(row.payload)
        edit(world)
        row.payload, row.revision = world, row.revision + 1


async def waiting(handle):
    async with asyncio.timeout(90):
        while True:
            try:
                value = await handle.query(
                    "status", result_type=LifecycleReceipt | FulfillmentReceipt | None
                )
            except RPCError as error:
                if error.status not in {RPCStatusCode.NOT_FOUND, RPCStatusCode.FAILED_PRECONDITION}:
                    raise
                await asyncio.sleep(0.2)
                continue
            if isinstance(value, LifecycleReceipt) and value.state == "waiting":
                return
            await asyncio.sleep(0.2)


async def run(args):
    settings = config(args.vault_key_file)
    engine = make_engine(settings)
    try:
        check_database(engine)
        before = business_counts(engine)
        activities = ProvisioningActivities(engine, settings, WorkerRole.MIRZA)
        service = activities.service
        lifecycle = LifecycleService(engine, service)
        client = await Client.connect(settings.temporal_address, namespace="agentic")
        if args.phase == "start":
            state = {"tenant": "fulfillment-fixture-" + uuid4().hex, "expiring": []}
        else:
            state = json.loads(args.state_file.read_text())
        if not state["tenant"].startswith("fulfillment-fixture-"):
            raise ValueError("Invalid generated fixture state")
        queue = state["tenant"] + "-lifecycle"
        histories = []
        if args.phase == "finish":
            # Start the private Mirza worker only once its persisted timers are overdue.
            expiry = datetime.fromisoformat(state["expiry"])
            delay = (expiry - datetime.now(UTC)).total_seconds()
            if delay > 0:
                await asyncio.sleep(min(delay + 0.1, 50))
            assert expiry <= datetime.now(UTC)
        async with Worker(
            client,
            task_queue=queue,
            workflows=[MirzaFixtureLifecycleWorkflow, MirzaFixtureFulfillmentWorkflow],
            activities=[activities.advance, activities.lifecycle, activities.resume],
            max_concurrent_activities=1,
            max_concurrent_activity_task_polls=1,
            max_concurrent_workflow_tasks=2,
            max_concurrent_workflow_task_polls=2,
            max_cached_workflows=8,
        ):
            if args.phase == "start":
                # Complete notifications first, then let expiry become overdue while down.
                expiry = datetime.now(UTC) + timedelta(seconds=45)
                state["expiry"] = expiry.isoformat()
                for index in (0, 1, 3, 4):
                    op = service.seed(
                        *case(index, state["tenant"], fields={**JOBS[index], "expires_at": expiry})
                    )
                    state["expiring"].append(op)
                    handle = await client.start_workflow(
                        MirzaFixtureLifecycleWorkflow.run,
                        LifecycleStart(op, queue),
                        id="fixture-lifecycle-" + op,
                        task_queue=queue,
                    )
                    await waiting(handle)
                    assert service.projection(op)["state"] == "completed"
                # An independently approved permanent membership must survive the first expiry.
                with Session(engine) as session:
                    shared_world = session.get(FulfillmentRecord, state["expiring"][-1]).world_id
                op = service.seed(
                    *case(4, state["tenant"], ticket_id="independent-membership"),
                    world_id=shared_world,
                )
                state["permanent"] = op
                handle = await client.start_workflow(
                    MirzaFixtureLifecycleWorkflow.run,
                    LifecycleStart(op, queue),
                    id="fixture-lifecycle-" + op,
                    task_queue=queue,
                )
                assert (await handle.result()).state == "complete"
                # Abandoned owner delivery retains precisely the original encrypted key.
                op = service.seed(*case(0, state["tenant"], ticket_id="recovery-key"))
                while service.advance(op).phase != "mutation":
                    pass
                change(service, op, lambda w: w["bot"].update({"active": False}))
                assert service.advance(op).state == "blocked"
                state["recovery"] = op
                # Existing Step 8 workflow type remains runnable/replayable without edits.
                op = service.seed(*case(5, state["tenant"], ticket_id="original-workflow"))
                state["original"] = op
                handle = await client.start_workflow(
                    MirzaFixtureFulfillmentWorkflow.run,
                    FulfillmentStart(op, queue),
                    id="fixture-original-" + op,
                    task_queue=queue,
                )
                assert (await handle.result()).state == "completed"
                # The old workflow cannot bypass the new timer-owning boundary.
                op = service.seed(
                    *case(
                        2,
                        state["tenant"],
                        ticket_id="old-workflow-expiry",
                        fields={**JOBS[2], "expires_at": datetime.now(UTC) + timedelta(days=1)},
                    )
                )
                state["guard"] = op
                handle = await client.start_workflow(
                    MirzaFixtureFulfillmentWorkflow.run,
                    FulfillmentStart(op, queue),
                    id="fixture-expiry-guard-" + op,
                    task_queue=queue,
                )
                assert (await handle.result()).reason_code == "managed_expiry_workflow_required"
                assert service.projection(op)["deliveries"] == []
                fd = os.open(args.state_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as output:
                    json.dump(state, output)
            else:
                assert len(state["expiring"]) == 4
                for op in [*state["expiring"], state["permanent"]]:
                    handle = client.get_workflow_handle(
                        "fixture-lifecycle-" + op, result_type=LifecycleReceipt
                    )
                    async with asyncio.timeout(120):
                        assert (await handle.result()).state == "complete"
                    histories.append(await handle.fetch_history())
                op = state["recovery"]
                change(service, op, lambda w: w["bot"].update({"active": True}))
                command = lifecycle.command(
                    op,
                    "restart-resume",
                    "resume",
                    lifecycle.view(op)["revision"],
                    "fixture-verifier",
                )
                handle = await client.start_workflow(
                    MirzaFixtureLifecycleWorkflow.run,
                    LifecycleStart(op, queue, command["command_id"]),
                    id="fixture-recovery-" + op,
                    task_queue=queue,
                )
                assert (await handle.result()).state == "complete"
                histories.append(await handle.fetch_history())
                handle = client.get_workflow_handle("fixture-expiry-guard-" + state["guard"])
                histories.append(await handle.fetch_history())
                handle = client.get_workflow_handle("fixture-original-" + state["original"])
                histories.append(await handle.fetch_history())
                with Session(engine) as session:
                    for op in state["expiring"]:
                        assert all(
                            g.state == "expired"
                            for g in session.scalars(
                                select(OwnedGrant).where(OwnedGrant.operation_id == op)
                            )
                        )
                    member = session.get(FulfillmentRecord, state["permanent"])
                    world = session.get(FixtureWorld, member.world_id).payload
                    owner = service.owner(world, "owner@example.invalid")
                    assert "ui-team" in owner["teams"]
                    recovery = session.get(FulfillmentRecord, state["recovery"])
                    world = session.get(FixtureWorld, recovery.world_id).payload
                    assert len(world["keys"]) == 1
                    saved = session.scalar(
                        select(ProvisioningSecret).where(
                            ProvisioningSecret.operation_id == recovery.operation_id
                        )
                    )
                    raw = service.cipher.open(saved.secret_ref, saved.ciphertext)["key"]
                    messages = session.scalars(
                        select(FixtureMessage).where(
                            FixtureMessage.operation_id == recovery.operation_id
                        )
                    ).all()
                    assert len(messages) == 2
                    for message in messages:
                        body = service.cipher.open(message.delivery_id, message.ciphertext)["body"]
                        assert (raw in body) is (message.kind == "user_dm")
                for history in histories:
                    assert all(
                        raw.encode() not in event.SerializeToString()
                        and b"owner@example.invalid" not in event.SerializeToString()
                        for event in history.events
                    )
                    await Replayer(
                        workflows=[MirzaFixtureLifecycleWorkflow, MirzaFixtureFulfillmentWorkflow]
                    ).replay_workflow(history)
        assert business_counts(engine) == before
        print(
            json.dumps(
                {
                    "phase": args.phase,
                    "native_workflows": 8,
                    "expiry_cases": 4,
                    "external_calls": 0,
                    "business_inbox_or_actions_created": 0,
                    "restart_timer_replay_verified": args.phase == "finish",
                    "independent_membership_preserved": args.phase == "finish",
                    "original_key_owner_only_recovery_verified": args.phase == "finish",
                    "original_workflow_replay_verified": args.phase == "finish",
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
        print(json.dumps({"verified": False, "error_type": type(error).__name__}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
