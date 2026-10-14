from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from test_mirza_review import inventory

from app.activities.mirza_review import MirzaReviewActivities
from app.api import main
from app.connectors.http import ok
from app.contracts.context import ApprovalRead, DeskGroup, DeskPerson, DeskTemplate, DirectoryPerson
from app.contracts.mirza_review import MirzaReviewStart
from app.contracts.observation import Classification, ObservationResult, ObservationStart
from app.contracts.tickets import MirzaRequest
from app.settings import Settings
from app.storage.mirza_reviews import MirzaReviewRepository
from app.storage.models import Base
from app.storage.observations import ObservationRepository
from scripts.verify_observations import FixtureSource


@pytest.fixture
def stores():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield MirzaReviewRepository(engine), ObservationRepository(engine)
    engine.dispose()


async def prepared(stores):
    repository, observations = stores
    settings = Settings(_env_file=None, database_url="postgresql+psycopg://unit:unit@localhost/unit")
    connectors = SimpleNamespace(reader=AsyncMock())
    source = FixtureSource()
    packet = await source.collect("2")
    groups = tuple(DeskGroup(
        group_id=ref, name=name, incharge=DeskPerson(
            person_id="incharge", email="incharge@example.invalid",
        ) if name == "DWE" else None, incharge_verified=name == "DWE",
    ) for name, ref in packet.groups.items())
    requester = DirectoryPerson(directory_id="requester", email="requester@example.invalid",
                                department="Synthetic Department", account_enabled=True,
                                account_expired=False)
    recipient = requester.model_copy(update={
        "directory_id": "owner", "email": "owner@example.invalid",
    })
    context = SimpleNamespace(
        ticket=ok("servicedesk", "ticket", packet.ticket),
        groups=ok("servicedesk", "groups", groups),
        templates=ok("servicedesk", "templates", (
            DeskTemplate(template_id="11702", name="Mirza Access Request"),
            DeskTemplate(template_id="11401", name="Mirza API Key"),
        )),
        requester=ok("directory", "requester", requester),
        recipient=ok("directory", "recipient", recipient),
        inventory=ok("mirza", "inventory", inventory()),
        relationships=ok("servicedesk", "relationships", packet.relationships),
        notes=ok("servicedesk", "notes", packet.notes),
        approvals=ok("servicedesk", "approvals", ApprovalRead(
            stages=(), configured_stage_ids=(), configured_levels=(),
            configuration_verified=False, terms_binding_verified=False, history_verified=False,
        )),
        history=ok("servicedesk", "history", {}),
    )
    connectors.reader.read.return_value = context
    async def find_person(email):
        return ok("directory", "person", recipient.model_copy(update={"email": email}))

    connectors.reader.directory.person.side_effect = find_person
    connectors.reader.mirza.inventory.return_value = context.inventory
    connectors.reader.desk.groups.return_value = context.groups
    connectors.reader.mapping.resolve = MagicMock(return_value=SimpleNamespace(
        state="mapped", tool_team_id="tool-team",
    ))
    versions = {"policy": "current", "model": "local-qwen3.8", "prompt": "prompt"}
    observed = ObservationResult(
        state="proposed", reason_code="model_proposal_only", versions=versions,
        evidence_refs=packet.evidence_refs,
        classification=Classification(kind="mirza", operation="increase_person_budget"),
        proposal=MirzaRequest.model_validate({
            "kind": "mirza", "operation": "increase_person_budget", "job": {
                "operation": "increase_person_budget", "person_email": recipient.email,
                "budget": {"amount": "5", "interpretation": "delta", "baseline_limit": "10",
                           "desired_limit": "15"},
            },
        }),
    )
    observation_id = "a" * 64
    observations.claim(observation_id, ObservationStart("servicedesk", "2", "dispatch", "mirza"),
                       "extract", packet.input_digest, observed, Decimal(0), 0)
    observations.finish(observation_id, observed)
    worker = MirzaReviewActivities(repository, observations, connectors, settings, lambda: versions)
    worker.source.collect = AsyncMock(return_value=packet)
    worker.source.current = AsyncMock(return_value=True)
    return worker, packet, context, MirzaReviewStart("servicedesk", "2", observation_id, "mirza")


async def test_native_review_retains_authority_gap_and_retries_without_more_reads(stores):
    worker, packet, context, request = await prepared(stores)
    first = await worker.prepare(request)
    result = stores[0].get(first.review_id)
    assert result.state == "blocked" and result.reason_code == "unverified_source_order"
    assert result.package.budget_after == 15 and not result.authorized
    assert result.next_state.tracking.original_dwe_incharge_ref == "incharge"
    assert result.next_state.dwe_observed_at == context.groups.evidence.observed_at
    assert result.next_state.first_approval_observation == context.approvals.data
    assert result.next_state.evidence.baseline is None
    assert await worker.prepare(request) == first
    assert worker.source.collect.await_count == 1
    assert worker.source.reader.read.await_count == 1


async def test_later_incharge_change_keeps_original_review_contact(stores):
    worker, packet, context, request = await prepared(stores)
    await worker.prepare(request)
    groups = tuple(g.model_copy(update={"incharge": DeskPerson(
        person_id="new-incharge", email="new-incharge@example.invalid",
    )}) if g.name == "DWE" else g for g in context.groups.data)
    context.groups = ok("servicedesk", "groups", groups)
    worker.source.reader.desk.groups.return_value = context.groups
    request.observation_id = "b" * 64
    observed = worker.observations.get("a" * 64)
    worker.observations.claim(
        request.observation_id, ObservationStart("servicedesk", "2", "dispatch", "mirza"),
        "extract", packet.input_digest, observed, Decimal(0), 0,
    )
    worker.observations.finish(request.observation_id, observed)
    result = stores[0].get((await worker.prepare(request)).review_id)
    assert result.next_state.dwe_contact.person_id == "incharge"
    assert result.next_state.dwe_contact.email == "incharge@example.invalid"


@pytest.mark.parametrize("case", ["wrong_ticket", "synthetic", "changed_versions", "wrong_stage"])
async def test_untrusted_receipt_does_not_trigger_native_reads(stores, case):
    worker, packet, context, request = await prepared(stores)
    if case == "wrong_ticket":
        request.ticket_id = "3"
    elif case == "synthetic":
        request.tenant_id = "synthetic"
    elif case == "changed_versions":
        worker.versions = lambda: {}
    else:
        worker.observations.source_identity = MagicMock(
            return_value=("servicedesk", "2", "classify")
        )
    result = stores[0].get((await worker.prepare(request)).review_id)
    assert result.reason_code == "mirza_proposal_unverified" and result.package is None
    worker.source.collect.assert_not_awaited()


@pytest.mark.parametrize("case", ["evidence", "final_read", "inventory", "groups", "lifecycle"])
async def test_changed_context_drops_packages_and_uncommitted_contact_pins(stores, case):
    worker, packet, context, request = await prepared(stores)
    if case == "evidence":
        packet.evidence_refs = ("b" * 64,)
    elif case == "final_read":
        worker.source.current.return_value = False
    elif case == "inventory":
        worker.source.reader.mirza.inventory.return_value = ok(
            "mirza", "inventory", inventory().model_copy(update={"users": ()})
        )
    elif case == "groups":
        worker.source.reader.desk.groups.return_value = ok("servicedesk", "groups", ())
    else:
        packet.relationships = packet.relationships.model_copy(update={
            "process_association": "lifecycle", "process_kind": "onboarding",
        })
    result = stores[0].get((await worker.prepare(request)).review_id)
    assert result.package is None and result.intents == ()
    assert result.next_state.dwe_contact is None


def test_review_api_accepts_only_operator_receipt_references(monkeypatch):
    temporal = MagicMock(start_workflow=AsyncMock())
    monkeypatch.setattr(main, "make_engine", lambda config: MagicMock())
    monkeypatch.setattr(main.Client, "connect", AsyncMock(return_value=temporal))
    monkeypatch.setattr(main, "configured_catalog", lambda config: None)

    async def idle(*args):
        import asyncio
        await asyncio.Event().wait()

    monkeypatch.setattr(main, "deliver_notifications", idle)
    settings = Settings(_env_file=None, database_url="postgresql+psycopg://unit:unit@localhost/unit",
                        operator_token="o" * 32, intake_token="i" * 32)
    headers = {"Authorization": "Bearer " + "o" * 32}
    with TestClient(main.create_app(settings)) as client:
        body = {"observation_id": "a" * 64}
        assert client.post("/v1/mirza-reviews/2", json=body).status_code == 401
        for invalid in ({**body, "approved": True}, {**body, "job": {}},
                        {"observation_id": "sk-private-secret"}):
            reply = client.post("/v1/mirza-reviews/2", json=invalid, headers=headers)
            assert reply.status_code == 422 and "sk-private-secret" not in reply.text
        reply = client.post("/v1/mirza-reviews/2", json=body, headers=headers)
        assert reply.status_code == 202 and reply.json()["authorized"] is False
        args, kwargs = temporal.start_workflow.call_args
        assert args[1].mirza_queue == settings.mirza_task_queue
        assert kwargs["task_queue"] == settings.mirza_task_queue
        assert args[1].observation_id == "a" * 64
