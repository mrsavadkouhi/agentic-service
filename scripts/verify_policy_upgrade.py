"""Local synthetic v1 history replay and live v2 assignment protection.

No ServiceDesk, Mirza, model or message connectors are constructed. Activities
keep synthetic state in memory; only the local Temporal server receives events.
"""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from temporalio import activity
from temporalio.client import Client, WorkflowHistory
from temporalio.exceptions import ApplicationError
from temporalio.service import RPCError, RPCStatusCode
from temporalio.worker import Replayer, Worker

from app.contracts.execution import (
    ActionCommand,
    CommitTransition,
    ReminderCommand,
    StoredEvent,
    TicketWorkflowStart,
)
from app.contracts.tickets import Evaluation, Tracking, stable_id
from app.policies.synthetic_events import catalog, event
from app.settings import Settings
from app.workflows.tickets import TicketWorkflow
from scripts.verify_observations import local_config


def verify_fixture_hashes():
    root = Path(__file__).with_name("history_fixtures")
    manifest = json.loads((root / "manifest.json").read_text())
    if set(manifest["files"]) != {"policy_v1.py", "ticket_workflow_v1.py"}:
        raise ValueError("Unexpected historical fixture manifest")
    for name, proof in manifest["files"].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != proof["fixture_sha256"]:
            raise ValueError("Historical fixture changed")


def patch_ids(history: WorkflowHistory) -> set[str]:
    # History JSON base64-encodes payload data; inspect SDK core patch records.
    result = set()
    for item in history.events:
        if not item.HasField("marker_recorded_event_attributes"):
            continue
        marker = item.marker_recorded_event_attributes
        if marker.marker_name != "core_patch":
            continue
        if "patch-data" not in marker.details:
            raise ValueError("Unexpected SDK patch encoding")
        payloads = marker.details["patch-data"].payloads
        if len(payloads) != 1 or payloads[0].metadata.get("encoding") != b"json/plain":
            raise ValueError("Unexpected SDK patch encoding")
        data = json.loads(payloads[0].data)
        if not isinstance(data, dict) or not isinstance(data.get("id"), str):
            raise ValueError("Unexpected SDK patch data")
        result.add(data["id"])
    return result


class MemoryActivities:
    def __init__(self, owner_id):
        self.owner_id = owner_id
        self.events = []
        self.commits = {}
        self.tracking = Tracking()
        self.actions = 0

    def enqueue(self, normalized):
        if normalized.data_kind != "synthetic":
            raise ValueError("Only generated synthetic events are permitted")
        self.events.append(StoredEvent(
            stable_id(self.owner_id, normalized.event_id), normalized.model_dump_json(),
            catalog().model_dump_json(), "ticket",
        ))

    @activity.defn(name="next_ticket_event")
    async def next_event(self, owner_id: str) -> StoredEvent | None:
        if owner_id != self.owner_id:
            raise ApplicationError("Unexpected synthetic owner", non_retryable=True)
        return self.events.pop(0) if self.events else None

    @activity.defn(name="commit_ticket_transition")
    async def commit(self, command: CommitTransition) -> str:
        if command.workflow_id != self.owner_id:
            raise ApplicationError("Unexpected synthetic owner", non_retryable=True)
        if command.event_key in self.commits:
            previous = self.commits[command.event_key]
            if previous[0] != command.evaluation_json:
                raise ApplicationError("Conflicting synthetic decision", non_retryable=True)
            return previous[1]
        decision = Evaluation.model_validate_json(command.evaluation_json)
        if decision.authorized or command.expected_before_sequence != self.tracking.latest_sequence:
            raise ApplicationError("Unexpected synthetic authority", non_retryable=True)
        self.tracking = decision.tracking
        result = self.tracking.model_dump_json()
        self.commits[command.event_key] = (command.evaluation_json, result)
        return result

    @activity.defn(name="run_ticket_fixture_action")
    async def execute(self, command: ActionCommand) -> dict:
        self.actions += 1
        raise ApplicationError("Actions are forbidden in this check", non_retryable=True)

    @activity.defn(name="finish_ticket_action")
    async def finish(self, command: ActionCommand, result: dict) -> str:
        raise ApplicationError("Actions are forbidden in this check", non_retryable=True)

    @activity.defn(name="reserve_ticket_reminders")
    async def remind(self, command: ReminderCommand) -> int:
        return 0

    def methods(self):
        return [self.next_event, self.commit, self.execute, self.finish, self.remind]


def worker(client, queue, definition, activities):
    return Worker(
        client, task_queue=queue, workflows=[definition], activities=activities.methods(),
        max_concurrent_activities=1, max_concurrent_activity_task_polls=1,
        max_concurrent_workflow_tasks=2, max_concurrent_workflow_task_polls=2,
        max_cached_workflows=2,
    )


async def wait_state(handle, state, sequence):
    async with asyncio.timeout(90):
        while True:
            try:
                result = await handle.query("status")
            except RPCError as error:
                if error.status not in {RPCStatusCode.NOT_FOUND, RPCStatusCode.FAILED_PRECONDITION}:
                    raise
                await asyncio.sleep(0.2)
                continue
            if result["state"] == state and result["latest_sequence"] == sequence:
                return result
            await asyncio.sleep(0.2)


async def run(args):
    args.check_stage = "local_configuration"
    settings = local_config(Settings())
    verify_fixture_hashes()
    from scripts.history_fixtures.ticket_workflow_v1 import TicketWorkflow as LegacyWorkflow

    client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
    owner_id = "policy-upgrade-verify-" + uuid4().hex
    queue = owner_id + "-dispatch"
    memory = MemoryActivities(owner_id)
    first = event(owner_id, dedicated=False).model_copy(update={
        "policy_version": "step-1-confirmed-v1"
    })
    first = first.model_copy(update={"snapshot": first.snapshot.model_copy(update={
        "technician_ref": "technician"
    })})
    memory.enqueue(first)
    handle = None
    try:
        async with worker(client, queue, LegacyWorkflow, memory):
            args.check_stage = "legacy_wait"
            handle = await client.start_workflow(
                LegacyWorkflow.run, TicketWorkflowStart(owner_id, "mirza", queue, queue),
                id=owner_id, task_queue=queue,
            )
            await wait_state(handle, "awaiting_approval", 1)
            old_history = await handle.fetch_history()
        args.check_stage = "legacy_replay"
        await Replayer(workflows=[TicketWorkflow]).replay_workflow(old_history)
        async with worker(client, queue, TicketWorkflow, memory):
            next_event = event(owner_id, sequence=2, dedicated=False)
            next_event = next_event.model_copy(update={
                "snapshot": next_event.snapshot.model_copy(update={"technician_ref": "technician"})
            })
            memory.enqueue(next_event)
            args.check_stage = "live_v2_event"
            await handle.signal("wake")
            current = await wait_state(handle, "manual_review", 2)
            assert current["wait"] is None and memory.actions == 0
            last = list(memory.commits.values())[-1]
            decision = Evaluation.model_validate_json(last[0])
            assert decision.reason_code == "human_assignment_preserved"
            new_history = await handle.fetch_history()
        args.check_stage = "upgraded_replay"
        await Replayer(workflows=[TicketWorkflow]).replay_workflow(new_history)
        args.check_stage = "patch_markers"
        first_marker = "preserve-human-assignment-v2-" + stable_id(owner_id, first.event_id)
        next_marker = "preserve-human-assignment-v2-" + stable_id(owner_id, next_event.event_id)
        assert first_marker not in patch_ids(old_history)
        assert first_marker not in patch_ids(new_history)
        assert next_marker in patch_ids(new_history)
        report = {
            "legacy_v1_history_replayed": True, "live_v2_event_preserves_human_assignment": True,
            "upgraded_history_replayed": True, "actions": memory.actions,
            "per_event_patch_markers_verified": True,
            "external_service_or_model_calls": 0, "business_database_writes": 0,
        }
        if args.report:
            args.report.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report))
    finally:
        if handle:
            await handle.terminate("Local policy upgrade verification finished")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception as error:
        print(json.dumps({
            "policy_upgrade_verified": False, "error_type": type(error).__name__,
            "check_stage": getattr(args, "check_stage", "startup"),
        }))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
