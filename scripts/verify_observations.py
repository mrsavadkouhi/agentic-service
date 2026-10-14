"""Local-only observation recovery check with fixture models and source records.

Run in the Compose API image as a separate capped process. The two phases allow
PostgreSQL/Temporal restarts between them; only local probe rows are written.
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic_ai.messages import ModelResponse, ToolCallPart  # noqa: E402
from pydantic_ai.models.function import FunctionModel  # noqa: E402
from pydantic_ai.usage import RequestUsage  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from temporalio.client import Client  # noqa: E402
from temporalio.service import RPCError, RPCStatusCode  # noqa: E402
from temporalio.worker import Replayer, Worker  # noqa: E402

from app.activities.mirza_review import MirzaReviewActivities  # noqa: E402
from app.activities.observation import ObservationActivities  # noqa: E402
from app.agents.observation import Inference  # noqa: E402
from app.connectors.observation import ObservationPacket, sanitize_text  # noqa: E402
from app.contracts.context import DeskPerson, DeskTicket, RelationshipRead  # noqa: E402
from app.contracts.mirza_review import (  # noqa: E402
    MirzaReviewReceipt,
    MirzaReviewResult,
    MirzaReviewStart,
)
from app.contracts.observation import (  # noqa: E402
    GroupPreflightStart,
    ObservationReceipt,
    ObservationResult,
    ObservationStart,
)
from app.contracts.tickets import stable_id  # noqa: E402
from app.policies.synthetic_events import catalog  # noqa: E402
from app.settings import OperationMode, Settings  # noqa: E402
from app.storage.database import check_database, make_engine  # noqa: E402
from app.storage.mirza_reviews import MirzaReviewRepository, ReviewConflict  # noqa: E402
from app.storage.observations import (  # noqa: E402
    InferenceBudget,
    ObservationRecord,
    ObservationRepository,
)
from app.storage.tickets import FixtureEffect, TicketAction, TicketInbox  # noqa: E402
from app.workflows.mirza_review import MirzaPolicyReviewWorkflow  # noqa: E402
from app.workflows.observation import (  # noqa: E402
    GroupCorrectionPreflightWorkflow,
    ObservationTicketWorkflow,
)

FIXTURE_TEXT = "OBSERVATION RECOVERY FIXTURE: never a real ticket"


def verify_history_privacy(history):
    # JSON renders payload bytes as base64 and can hide leaked source text.
    assert all(FIXTURE_TEXT.encode() not in item.SerializeToString() for item in history.events)


def local_config(original):
    """Keep local DB/runtime configuration; discard every external connector secret."""
    url = make_url(original.database_url.get_secret_value())
    if (
        url.host not in {"postgres", "127.0.0.1", "localhost", "::1"}
        or url.database != "agentic"
        or original.temporal_address.split(":")[0] not in {"temporal", "127.0.0.1", "localhost"}
        or original.temporal_namespace != "agentic"
        or original.dispatch_mode != OperationMode.OBSERVE
        or original.mirza_mode != OperationMode.OBSERVE
        or original.observation_listener_enabled
        or original.inference_enabled
        or original.worker_inference_enabled
        or original.enable_fixture_execution
    ):
        raise ValueError("Use the local observation-only stack with polling/inference off")
    return Settings(
        _env_file=None,
        database_url=original.database_url,
        temporal_address=original.temporal_address,
        temporal_namespace=original.temporal_namespace,
        inference_max_cost_usd=0.000001,
    )


class FixtureSource:
    def __init__(self):
        self.revision = 1
        self.catalog = catalog().model_copy(
            update={
                "environment": "production",
                "dedicated_templates": {"Mirza Access Request": "11702", "Mirza API Key": "11401"},
            }
        )

    async def collect(self, ticket_id):
        digest = stable_id("fixture", ticket_id, str(self.revision))
        return ObservationPacket(
            ticket=DeskTicket(
                ticket_id=ticket_id,
                requester=DeskPerson(person_id="requester", email="requester@example.invalid"),
                group_id="sd-helpdesk",
                technician=None,
                template_id="11702" if ticket_id == "2" else "other-template",
                category_id=None,
                status_id="open",
                status_name="Open",
                updated_at=datetime(2026, 10, 13, tzinfo=UTC),
                content_digest=digest,
                revision_digest=digest,
                parent_id=None,
                child_ids=(),
                relationship_verified=True,
                process_kind=None,
                process_verified=True,
            ),
            relationships=RelationshipRead(
                parent_id=None,
                child_ids=(),
                process_association="standalone",
                coverage_verified=True,
                evidence_ref="fixture-membership",
            ),
            notes=(),
            groups=self.catalog.support_groups,
            dwe_contact="incharge",
            text=FIXTURE_TEXT + (" Mirza budget" if ticket_id == "2" else " network"),
            input_digest=digest,
            evidence_refs=(digest,),
        )

    async def current(self, packet):
        return True

    async def mirza_scope(self, packet):
        return self.catalog, '{"fixture":true}', {"tool-team": Decimal(10)}


def fixture_inference(settings, calls):
    async def classify(messages, info):
        calls["classify"] += 1
        mirza = "Mirza budget" in messages[-1].parts[0].content
        payload = (
            {"kind": "mirza", "operation": "increase_team_budget"}
            if mirza
            else {"kind": "ordinary", "group": "Network"}
        )
        return ModelResponse(
            [ToolCallPart(info.output_tools[0].name, payload)],
            usage=RequestUsage(input_tokens=100, output_tokens=20),
        )

    async def extract(messages, info):
        calls["extract"] += 1
        payload = {
            "kind": "mirza",
            "operation": "increase_team_budget",
            "job": {
                "operation": "increase_team_budget",
                "team_id": "tool-team",
                "team_kind": "tool",
                "budget": {
                    "amount": "5",
                    "interpretation": "delta",
                    "baseline_limit": "10",
                    "desired_limit": "15",
                },
            },
        }
        return ModelResponse(
            [ToolCallPart(info.output_tools[0].name, payload)],
            usage=RequestUsage(input_tokens=100, output_tokens=20),
        )

    return Inference(
        settings,
        classification_model=FunctionModel(classify),
        extraction_model=FunctionModel(extract),
    )


def business_counts(engine):
    with Session(engine) as session:
        return [
            session.scalar(select(func.count()).select_from(table))
            for table in (TicketInbox, TicketAction, FixtureEffect)
        ]


async def verify_claim_locks(repository, tenant):
    """Exercise native uniqueness and daily-ledger locks, using only local probe rows."""
    request = ObservationStart(tenant + "-claims", "3", "unused-dispatch", "unused-mirza")
    base = ObservationResult(
        state="blocked",
        reason_code="local_verification",
        evidence_refs=("a" * 64,),
        versions={"model": "offline-fixture"},
    )
    claim_id = stable_id(tenant, "unique-claim")

    async def claim_same():
        return await asyncio.to_thread(
            repository.claim, claim_id, request, "classify", "b" * 64, base, Decimal(0), Decimal(2)
        )

    assert sorted(await asyncio.gather(claim_same(), claim_same())) == [False, True]
    # Keep fixture reservations separate from today's real accounting; never refund them.
    clock = datetime(2000, 1, 1, tzinfo=UTC)
    with Session(repository.engine) as session:
        existing = session.get(InferenceBudget, clock.date())
        cap = (existing.reserved_usd if existing else Decimal(0)) + Decimal("0.25")

    async def claim_budget(suffix):
        return await asyncio.to_thread(
            repository.claim,
            stable_id(tenant, suffix),
            request,
            "classify",
            "c" * 64,
            base,
            Decimal("0.25"),
            cap,
            clock,
        )

    assert sorted(await asyncio.gather(claim_budget("budget-a"), claim_budget("budget-b"))) == [
        False,
        True,
    ]


async def verify_review_locks(repository, tenant):
    result = MirzaReviewResult(state="blocked", reason_code="local_verification")

    async def commit(suffix):
        request = MirzaReviewStart(
            tenant + "-review-locks", "3", stable_id(tenant, suffix), "unused"
        )
        try:
            receipt = await asyncio.to_thread(repository.commit, request, 0, result)
            # Lost-response retry returns the same preview and never advances the head.
            assert receipt == await asyncio.to_thread(repository.commit, request, 0, result)
            return True
        except ReviewConflict:
            return False

    assert sorted(await asyncio.gather(commit("review-a"), commit("review-b"))) == [False, True]
    assert repository.load(tenant + "-review-locks", "3")[0] == 1


async def completed_count(handle):
    history = await handle.fetch_history()
    return sum(
        event.HasField("activity_task_completed_event_attributes") for event in history.events
    )


async def wait_receipt(handle, expected, previous=None):
    async with asyncio.timeout(90):
        while True:
            try:
                receipt = await handle.query(ObservationTicketWorkflow.status)
            except RPCError as exc:
                if exc.status not in {RPCStatusCode.NOT_FOUND, RPCStatusCode.FAILED_PRECONDITION}:
                    raise
                # A newly started owner may not have executed its first workflow task.
                await asyncio.sleep(0.2)
                continue
            if (
                receipt
                and receipt.state == "proposed"
                and receipt.observation_id != previous
                and receipt.reason_code == expected
                and (expected != "model_proposal_only" or receipt.kind is None)
            ):
                return receipt
            await asyncio.sleep(0.2)


async def wait_completed(handle, count):
    async with asyncio.timeout(90):
        while await completed_count(handle) < count:
            await asyncio.sleep(0.2)


async def run(args):
    args.check_stage = "configuration"
    settings = local_config(Settings())
    engine = make_engine(settings)
    inference = None
    try:
        await asyncio.to_thread(check_database, engine)
        args.check_stage = "temporal_connection"
        before = await asyncio.to_thread(business_counts, engine)
        client = await Client.connect(
            settings.temporal_address, namespace=settings.temporal_namespace
        )
        repository = ObservationRepository(engine)
        if args.phase == "start":
            state = {"tenant": "observation-verify-" + uuid4().hex, "observations": {}}
            fd = os.open(args.state_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as stream:
                json.dump(state, stream)  # recover the generated owners after an interrupted check
        else:
            state = json.loads(args.state_file.read_text())
        if (
            not isinstance(state.get("tenant"), str)
            or not state["tenant"].startswith("observation-verify-")
            or len(state["tenant"]) != len("observation-verify-") + 32
        ):
            raise ValueError("Invalid local verification state")
        queues = (state["tenant"] + "-dispatch", state["tenant"] + "-mirza")
        calls = {"classify": 0, "extract": 0}
        inference = fixture_inference(settings, calls)
        observed = ObservationActivities(
            repository, SimpleNamespace(reader=SimpleNamespace(desk=None)), settings, inference
        )
        observed.source = FixtureSource()
        reviews = MirzaReviewActivities(
            MirzaReviewRepository(engine), repository,
            SimpleNamespace(reader=SimpleNamespace(desk=None)), settings, inference.versions,
        )
        handles = []

        async def worker_failed(error):
            # This verifier has fixture data only; still redact local database credentials.
            url = make_url(settings.database_url.get_secret_value())
            detail = str(error)
            if len(detail.encode()) > 12000:
                detail = "worker_fatal_detail_limit"
            detail = sanitize_text(detail, (settings.database_url.get_secret_value(), url.password))
            print(
                json.dumps(
                    {
                        "local_worker_fatal_type": type(error).__name__,
                        "local_worker_fatal_detail": detail[:500],
                    }
                ),
                flush=True,
            )

        class CheckedWorker(Worker):
            async def run(self):
                try:
                    await super().run()
                except Exception as error:
                    # Core validation happens before the SDK's fatal-error callback.
                    await worker_failed(error)
                    raise

        async with (
            CheckedWorker(
                client,
                task_queue=queues[0],
                workflows=[ObservationTicketWorkflow, GroupCorrectionPreflightWorkflow],
                activities=[observed.classify, observed.preflight],
                max_concurrent_activities=1,
                max_concurrent_workflow_tasks=2,
                max_cached_workflows=2,
                max_concurrent_workflow_task_polls=2,
                max_concurrent_activity_task_polls=1,
            ),
            CheckedWorker(
                client,
                task_queue=queues[1],
                workflows=[MirzaPolicyReviewWorkflow],
                activities=[observed.extract, reviews.prepare],
                max_concurrent_activities=1,
                max_concurrent_activity_task_polls=1,
                max_concurrent_workflow_tasks=2, max_cached_workflows=2,
                max_concurrent_workflow_task_polls=2,
            ),
        ):
            args.check_stage = "initial_receipt"
            for ticket_id in ("1", "2"):
                workflow_id = state["tenant"] + "-" + ticket_id
                if args.phase == "start":
                    handle = await client.start_workflow(
                        ObservationTicketWorkflow.run,
                        ObservationStart(state["tenant"], ticket_id, *queues),
                        id=workflow_id,
                        task_queue=queues[0],
                    )
                else:
                    handle = client.get_workflow_handle(workflow_id)
                handles.append(handle)
                expected = (
                    "support_group_proposal_only" if ticket_id == "1" else "model_proposal_only"
                )
                receipt = await wait_receipt(handle, expected)
                if args.phase == "start":
                    state["observations"][ticket_id] = receipt.observation_id
                    await wait_completed(handle, 1 if ticket_id == "1" else 2)
                else:
                    assert receipt.observation_id == state["observations"][ticket_id]
                    completed = await completed_count(handle)
                    await handle.signal(ObservationTicketWorkflow.wake)
                    await wait_completed(handle, completed + (1 if ticket_id == "1" else 2))
                    assert (
                        await handle.query(ObservationTicketWorkflow.status)
                    ).observation_id == receipt.observation_id
                result = await asyncio.to_thread(repository.get, receipt.observation_id)
                assert (
                    result.authorized is False and result.policy_reason == "unverified_source_order"
                )
            if args.phase == "start":
                args.check_stage = "group_preflight"
                # Synthetic provenance must never be adopted as a native ticket.
                receipt = await client.execute_workflow(
                    GroupCorrectionPreflightWorkflow.run,
                    GroupPreflightStart(state["tenant"], "1", state["observations"]["1"],
                                        queues[0]),
                    id=state["tenant"] + "-group-review", task_queue=queues[0],
                )
                assert receipt.reason_code == "group_proposal_unverified"
                state["group_preflight"] = receipt.observation_id
                review_receipt = await client.execute_workflow(
                    MirzaPolicyReviewWorkflow.run,
                    MirzaReviewStart(state["tenant"], "2", state["observations"]["2"], queues[1]),
                    id=state["tenant"] + "-mirza-review", task_queue=queues[1],
                )
                assert review_receipt.reason_code == "mirza_proposal_unverified"
                state["mirza_policy_review"] = review_receipt.review_id
                assert calls == {"classify": 2, "extract": 1}
                args.state_file.write_text(json.dumps(state))
            else:
                args.check_stage = "revision_and_replay"
                assert calls == {"classify": 0, "extract": 0}, "Cached inputs repeated a model call"
                observed.source.revision = 2
                for ticket_id, handle in zip(("1", "2"), handles, strict=True):
                    await handle.signal(ObservationTicketWorkflow.wake)
                    expected = (
                        "support_group_proposal_only" if ticket_id == "1" else "model_proposal_only"
                    )
                    await wait_receipt(handle, expected, state["observations"][ticket_id])
                    await wait_completed(handle, 3 if ticket_id == "1" else 6)
                    history = await handle.fetch_history()
                    verify_history_privacy(history)
                    await Replayer(workflows=[ObservationTicketWorkflow]).replay_workflow(history)
                    await handle.terminate("Local observation verification completed")
                assert calls == {"classify": 2, "extract": 1}
                preflight = client.get_workflow_handle(
                    state["tenant"] + "-group-review", result_type=ObservationReceipt
                )
                receipt = await preflight.result()
                assert receipt.observation_id == state["group_preflight"]
                history = await preflight.fetch_history()
                verify_history_privacy(history)
                await Replayer(workflows=[GroupCorrectionPreflightWorkflow]).replay_workflow(
                    history
                )
                reviewed = client.get_workflow_handle(
                    state["tenant"] + "-mirza-review", result_type=MirzaReviewReceipt
                )
                review_receipt = await reviewed.result()
                assert review_receipt.review_id == state["mirza_policy_review"]
                history = await reviewed.fetch_history()
                verify_history_privacy(history)
                await Replayer(workflows=[MirzaPolicyReviewWorkflow]).replay_workflow(history)
                review_repository = MirzaReviewRepository(engine)
                assert not review_repository.get(review_receipt.review_id).authorized
                assert review_repository.load(state["tenant"], "2")[0] == 1
                await verify_review_locks(review_repository, state["tenant"])
                await verify_claim_locks(repository, state["tenant"])
                with Session(engine) as session:
                    rows = session.scalars(
                        select(ObservationRecord).where(
                            ObservationRecord.tenant_id == state["tenant"]
                        )
                    ).all()
                    assert len(rows) == 7 and all(row.result["authorized"] is False for row in rows)
        assert await asyncio.to_thread(business_counts, engine) == before
        print(
            json.dumps(
                {
                    "phase": args.phase,
                    "fixture_model_requests": sum(calls.values()),
                    "external_calls": 0,
                    "business_inbox_or_actions_created": 0,
                    "replay_verified": args.phase == "finish",
                    "group_preflight_replay_verified": args.phase == "finish",
                    "mirza_policy_review_replay_verified": args.phase == "finish",
                    "mirza_review_claim_locks_verified": args.phase == "finish",
                }
            )
        )
    finally:
        if inference:
            await inference.close()
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["start", "finish"])
    parser.add_argument("--state-file", type=Path, required=True)
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception as exc:
        print(
            json.dumps(
                {
                    "verified": False,
                    "error_type": type(exc).__name__,
                    "check_stage": getattr(args, "check_stage", "configuration"),
                    "rpc_status": exc.status.name if isinstance(exc, RPCError) else None,
                }
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
