from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.activities.observation import ObservationActivities
from app.agents.observation import Inference, Scope
from app.connectors.factory import Connectors
from app.connectors.http import ReadFailure
from app.connectors.observation import ObservationPacket, sanitize_text
from app.contracts.context import DeskPerson, DeskTicket, RelationshipRead
from app.contracts.observation import ObservationResult, ObservationStart, PollStart
from app.policies.synthetic_events import catalog
from app.settings import Settings
from app.storage.models import Base
from app.storage.observations import InferenceBudget, ObservationRepository
from app.storage.tickets import FixtureEffect, TicketAction, TicketInbox


def config(**changes):
    return Settings(
        _env_file=None, database_url="postgresql+psycopg://unit:unit@localhost/unit", **changes
    )


def packet(**changes):
    ticket = DeskTicket(
        ticket_id="1",
        requester=DeskPerson(person_id="requester", email="requester@example.invalid"),
        group_id="sd-helpdesk",
        technician=None,
        template_id="11702",
        category_id=None,
        status_id="2",
        status_name="Open",
        updated_at=datetime(2026, 10, 13, tzinfo=UTC),
        content_digest="a" * 64,
        revision_digest="b" * 64,
        parent_id=None,
        child_ids=(),
        relationship_verified=True,
        process_kind=None,
        process_verified=True,
    ).model_copy(update=changes)
    return ObservationPacket(
        ticket=ticket,
        relationships=RelationshipRead(
            parent_id=None,
            child_ids=(),
            process_association="non_lifecycle",
            coverage_verified=True,
            evidence_ref="verified-creator",
        ),
        notes=(),
        groups=catalog().support_groups,
        dwe_contact="incharge",
        text="Synthetic request, owner@example.invalid, permanent/no expiry.",
        input_digest="c" * 64,
        evidence_refs=("b" * 64, "d" * 64),
    )


def model(payload, calls, tool=None):
    async def respond(messages, info):
        calls.append(messages)
        if tool and not any(
            getattr(part, "part_kind", "") == "tool-return"
            for message in messages
            for part in message.parts
        ):
            return ModelResponse(
                [ToolCallPart(tool, {})], usage=RequestUsage(input_tokens=100, output_tokens=20)
            )
        return ModelResponse(
            [ToolCallPart(info.output_tools[0].name, payload)],
            usage=RequestUsage(input_tokens=100, output_tokens=20),
        )

    return FunctionModel(respond)


@pytest.fixture
def repository():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    yield ObservationRepository(engine)
    engine.dispose()


def activities(
    repository, classified, extracted=None, *, source_packet=None, settings=None, tool=None
):
    settings = settings or config()
    calls, extraction_calls = [], []
    inference = Inference(
        settings,
        classification_model=model(classified, calls, tool),
        extraction_model=model(extracted, extraction_calls) if extracted else None,
    )
    worker = ObservationActivities(repository, Connectors(settings), settings, inference)
    source_packet = source_packet or packet()
    worker.source.collect = AsyncMock(return_value=source_packet)
    worker.source.current = AsyncMock(return_value=True)
    scope_catalog = catalog().model_copy(
        update={
            "environment": "production",
            "dedicated_templates": {"Mirza Access Request": "11702", "Mirza API Key": "11401"},
        }
    )
    worker.source.mirza_scope = AsyncMock(
        return_value=(
            scope_catalog,
            '{"scope":"bounded"}',
            {
                "owner@example.invalid": Decimal(10),
                "tool-team": Decimal(10),
                "ui-team": Decimal(10),
                "key-metadata-1": Decimal(10),
            },
        )
    )
    return worker, calls, extraction_calls


def request(ticket_id="1"):
    return ObservationStart("servicedesk", ticket_id, "dispatch", "mirza")


@pytest.mark.parametrize(
    "group,text",
    [
        ("Network", "Open a route to port 443"),
        ("Network", "دسترسی به پورت شبکه می‌خواهم"),
        ("VOIP", "My extension cannot make calls"),
        ("VOIP", "تلفن داخلی تماس نمی‌گیرد"),
        ("DWE", "Cannot sign in to Mattermost"),
        ("DWE", "دسترسی جیرا می‌خواهم"),
        ("Helpdesk", "Laptop keyboard broken"),
        ("Helpdesk", "چاپگر کار نمی‌کند"),
    ],
)
async def test_annotated_bilingual_routing_fixtures_produce_local_observations(
    repository, group, text
):
    source = packet(template_id="other")
    source.text = text
    worker, calls, _ = activities(
        repository,
        {"kind": "ordinary", "group": group},
        source_packet=source,
        tool="ownership_catalog",
    )
    receipt = await worker.classify(request())
    result = repository.get(receipt.observation_id)
    assert len(calls) == 2 and result.model_requests == 2
    assert result.authorized is False
    if group == "Helpdesk":
        assert result.state == "no_op"
    else:
        assert result.proposal.destination_group_id == source.groups[group]
        assert result.policy_reason == "unverified_source_order"
    with Session(repository.engine) as session:
        assert session.scalar(select(func.count()).select_from(TicketInbox)) == 0
        assert session.scalar(select(func.count()).select_from(TicketAction)) == 0
        assert session.scalar(select(func.count()).select_from(FixtureEffect)) == 0


@pytest.mark.parametrize("case", ["assigned", "outside", "lifecycle", "unknown", "unsupported"])
async def test_assignment_scope_and_process_guards_cannot_propose_writes(repository, case):
    source = packet(template_id="other")
    if case == "assigned":
        source.ticket = source.ticket.model_copy(
            update={
                "technician": DeskPerson(person_id="technician", email="technician@example.invalid")
            }
        )
    elif case == "outside":
        source.ticket = source.ticket.model_copy(update={"group_id": "sd-network"})
    elif case == "lifecycle":
        source.relationships = source.relationships.model_copy(
            update={"process_association": "lifecycle", "process_kind": "offboarding"}
        )
    classified = (
        {"kind": "unsupported_mirza"}
        if case == "unsupported"
        else {"kind": "ordinary", "group": "DWE"}
    )
    worker, calls, _ = activities(repository, classified, source_packet=source)
    if case == "unknown":
        worker.source.collect.side_effect = ReadFailure(
            "incomplete", "process_association_unverified"
        )
    receipt = await worker.classify(request())
    result = repository.get(receipt.observation_id)
    assert not result.authorized
    assert result.proposal is None or result.proposal.kind == "no_op"
    assert result.state in {"no_op", "manual_review"}
    if case in {"outside", "lifecycle", "unknown"}:
        assert calls == []


JOBS = [
    {
        "operation": "create_api_key",
        "owner_email": "owner@example.invalid",
        "tool_team": {"kind": "existing_tool", "team_id": "tool-team"},
        "purpose_ref": "purpose-" + "a" * 64,
        "budget_limit": 15,
        "budget_duration": "30d",
        "expires_at": None,
    },
    {
        "operation": "increase_api_key_reasoning",
        "owner_email": "owner@example.invalid",
        "key_ref": "key-metadata-1",
        "tool_team_id": "tool-team",
        "model_ids": ["model-a"],
        "reasoning_level": "high",
        "expires_at": None,
    },
    {
        "operation": "increase_team_reasoning",
        "team_id": "ui-team",
        "team_kind": "non_tool",
        "model_ids": ["model-a"],
        "reasoning_level": "high",
        "expires_at": None,
    },
    {
        "operation": "grant_team_model_access",
        "team_id": "ui-team",
        "team_kind": "non_tool",
        "model_ids": ["model-b"],
        "expires_at": None,
    },
    {
        "operation": "add_person_to_non_tool_team",
        "person_email": "owner@example.invalid",
        "team_id": "ui-team",
        "requested_model_id": "model-a",
        "expires_at": None,
    },
    {
        "operation": "increase_person_budget",
        "person_email": "owner@example.invalid",
        "budget": {
            "amount": 5,
            "interpretation": "delta",
            "baseline_limit": 10,
            "desired_limit": 15,
        },
    },
    {
        "operation": "increase_api_key_budget",
        "owner_email": "owner@example.invalid",
        "key_ref": "key-metadata-1",
        "tool_team_id": "tool-team",
        "budget": {
            "amount": 5,
            "interpretation": "delta",
            "baseline_limit": 10,
            "desired_limit": 15,
        },
    },
    {
        "operation": "increase_team_budget",
        "team_id": "tool-team",
        "team_kind": "tool",
        "budget": {
            "amount": 5,
            "interpretation": "delta",
            "baseline_limit": 10,
            "desired_limit": 15,
        },
    },
]


@pytest.mark.parametrize("job", JOBS, ids=[job["operation"] for job in JOBS])
async def test_eight_job_extraction_reuses_contracts_and_never_claims_approval(repository, job):
    worker, calls, extraction_calls = activities(
        repository,
        {"kind": "mirza", "operation": job["operation"]},
        {"kind": "mirza", "operation": job["operation"], "job": job},
    )
    if job["operation"] == "create_api_key":
        scope, projection, baselines = worker.source.mirza_scope.return_value
        worker.source.mirza_scope.return_value = (
            scope.model_copy(update={"keys": ()}),
            projection,
            baselines,
        )
    classified = await worker.classify(request())
    extracted = await worker.extract(request(), classified.observation_id)
    result = repository.get(extracted.observation_id)
    assert len(calls) == len(extraction_calls) == 1
    assert result.proposal.operation == job["operation"] and result.proposal.job is not None
    assert not result.authorized and result.policy_reason == "unverified_source_order"
    assert result.model_requests == 1 and result.input_tokens == 100


async def test_duplicate_expired_key_and_missing_terms_draft_for_technician(repository):
    source = packet(technician=DeskPerson(person_id="technician", email=None))
    job = JOBS[0]
    worker, _, _ = activities(
        repository,
        {"kind": "mirza", "operation": job["operation"]},
        {"kind": "mirza", "operation": job["operation"], "job": job},
        source_packet=source,
    )
    cls = await worker.classify(request())
    receipt = await worker.extract(request(), cls.observation_id)
    result = repository.get(receipt.observation_id)
    assert result.proposal.job is None
    assert result.clarification.missing_fields == ("additional_key_needed",)
    assert result.clarification.contact_ref == "technician"


async def test_cache_reuses_completed_model_calls_and_changed_revision_invalidates(repository):
    worker, calls, _ = activities(repository, {"kind": "ordinary", "group": "Network"})
    first = await worker.classify(request())
    again = await worker.classify(request())
    assert again == first and len(calls) == 1
    source = packet(revision_digest="e" * 64)
    source.input_digest = "e" * 64
    worker.source.collect.return_value = source
    changed = await worker.classify(request())
    assert changed.observation_id != first.observation_id and len(calls) == 2


async def test_assigned_fallback_mirza_retains_terms_but_cannot_change_group(repository):
    source = packet(template_id="other",
                    technician=DeskPerson(person_id="technician", email=None))
    job = JOBS[5]
    worker, _, _ = activities(
        repository, {"kind": "mirza", "operation": job["operation"]},
        {"kind": "mirza", "operation": job["operation"], "job": job}, source_packet=source,
    )
    classified = await worker.classify(request())
    extracted = await worker.extract(request(), classified.observation_id)
    result = repository.get(extracted.observation_id)
    assert result.policy_reason == "human_assignment_preserved" and not result.authorized
    assert result.proposal.job.operation == "increase_person_budget"
    assert source.ticket.group_id == "sd-helpdesk" and source.ticket.technician is not None


async def test_lost_post_inference_result_never_repeats_model_call(repository, monkeypatch):
    worker, calls, _ = activities(repository, {"kind": "ordinary", "group": "Network"})
    original = repository.finish
    monkeypatch.setattr(
        repository, "finish", lambda *args: (_ for _ in ()).throw(RuntimeError("private"))
    )
    with pytest.raises(Exception):
        await worker.classify(request())
    monkeypatch.setattr(repository, "finish", original)
    retried = await worker.classify(request())
    assert retried.reason_code == "inference_outcome_uncertain" and len(calls) == 1


async def test_changed_context_after_inference_is_blocked_and_bounded_poll_rotates(repository):
    worker, _, _ = activities(
        repository,
        {"kind": "ordinary", "group": "Network"},
        settings=config(observation_listener_enabled=True),
    )
    worker.source.current.return_value = False
    result = await worker.classify(request())
    assert repository.get(result.observation_id).state == "blocked"
    assert repository.get(result.observation_id).proposal is None
    worker.source.candidates = AsyncMock(return_value=["1", "2", "3", "4", "5"])
    start = PollStart("dispatch", "mirza", batch_size=2)
    first = await worker.poll(start)
    start.cursor = first.next_cursor
    second = await worker.poll(start)
    assert first.ticket_ids == ["1", "2"] and second.ticket_ids == ["3", "4"]


async def test_disabled_listener_does_not_read_sources_or_spawn_candidates(repository):
    worker, _, _ = activities(repository, {"kind": "ordinary", "group": "Network"})
    worker.source.candidates = AsyncMock(return_value=["1"])
    batch = await worker.poll(PollStart("dispatch", "mirza"))
    assert batch.status == "disabled" and batch.ticket_ids == []
    worker.source.candidates.assert_not_awaited()


def test_daily_budget_is_shared_durable_and_uncertain_reservations_are_not_refunded(repository):
    base = ObservationResult(
        state="blocked",
        reason_code="inference_outcome_uncertain",
        evidence_refs=("a" * 64,),
        versions={"model": "fixture"},
    )
    now = datetime(2026, 10, 13, tzinfo=UTC)
    assert repository.claim(
        "a" * 64, request(), "classify", "b" * 64, base, Decimal("0.25"), 0.25, now
    )
    assert not repository.claim(
        "c" * 64, request("2"), "extract", "d" * 64, base, Decimal("0.25"), 0.25, now
    )
    assert repository.receipt("c" * 64).reason_code == "daily_inference_budget"
    assert repository.claim(
        "c" * 64,
        request("2"),
        "extract",
        "d" * 64,
        base,
        Decimal("0.25"),
        0.25,
        now + timedelta(days=1),
    )
    with Session(repository.engine) as session:
        assert len(session.scalars(select(InferenceBudget)).all()) == 2
    # Sub-microdollar reservations round up rather than permitting free repeated calls.
    assert not repository.claim(
        "e" * 64,
        request("3"),
        "classify",
        "f" * 64,
        base,
        Decimal("0.0000004"),
        Decimal("0.0000004"),
        now + timedelta(days=2),
    )


@pytest.mark.parametrize(
    "text",
    [
        "sk-private123",
        "password=secret123",
        '"token": "secret123"',
        "Bearer secret123",
        "<script>secret123</script>",
    ],
)
def test_private_text_sanitization_does_not_forward_credentials(text):
    sanitized = sanitize_text(text)
    assert "secret123" not in sanitized and "sk-private123" not in sanitized
    with pytest.raises(ReadFailure):
        sanitize_text("x" * 12001)


async def test_disabled_inference_and_unknown_authority_have_no_model_calls():
    runner = Inference(config())
    result = await runner.run("classify", Scope(packet()))
    assert result.state == "unavailable" and result.reason_code == "inference_disabled"
    assert not result.authorized and runner.client is None


@pytest.mark.parametrize(
    "changes",
    [
        {"inference_enabled": True},
        {"observation_listener_enabled": True, "dispatch_mode": "automatic"},
        {"inference_max_cost_usd": 3},
        {"inference_request_limit": 5},
    ],
)
def test_invalid_inference_or_listener_configuration_is_rejected(changes):
    with pytest.raises(ValidationError):
        config(**changes)
