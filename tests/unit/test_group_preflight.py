from unittest.mock import AsyncMock

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.activities.observation import ObservationActivities
from app.agents.observation import Inference
from app.contracts.context import DeskPerson
from app.contracts.observation import GroupPreflightStart, ObservationStart
from app.contracts.tickets import GroupCorrection
from app.policies.group_correction import group_only_payload
from app.settings import Settings
from app.storage.models import Base
from app.storage.observations import InferenceBudget, ObservationRepository
from app.storage.tickets import FixtureEffect, TicketAction, TicketInbox
from scripts.verify_observations import FixtureSource

GROUPS = {"Helpdesk": "301", "Network": "2", "DWE": "2101", "VOIP": "901"}


@pytest.fixture
def repository():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    yield ObservationRepository(engine)
    engine.dispose()


async def observed(repository):
    calls = []

    async def classify(messages, info):
        calls.append(1)
        return ModelResponse([
            ToolCallPart(info.output_tools[0].name, {"kind": "ordinary", "group": "Network"})
        ], usage=RequestUsage(input_tokens=100, output_tokens=20))

    config = Settings(_env_file=None, database_url="postgresql+psycopg://unit:unit@localhost/unit")
    inference = Inference(config, classification_model=FunctionModel(classify))
    source = await FixtureSource().collect("1")
    source.groups = GROUPS.copy()
    source.ticket = source.ticket.model_copy(update={"group_id": GROUPS["Helpdesk"]})
    worker = ObservationActivities(repository, AsyncMock(), config, inference)
    worker.source.collect = AsyncMock(return_value=source)
    worker.source.current = AsyncMock(return_value=True)
    receipt = await worker.classify(ObservationStart("servicedesk", "1", "dispatch", "mirza"))
    return worker, source, calls, GroupPreflightStart(
        "servicedesk", "1", receipt.observation_id, "dispatch"
    )


async def test_valid_draft_is_still_blocked_with_no_model_spend_or_business_actions(repository):
    worker, source, calls, request = await observed(repository)
    with Session(repository.engine) as session:
        reserved = session.scalar(select(InferenceBudget.reserved_usd))
    first = await worker.preflight(request)
    assert first == await worker.preflight(request)
    result = repository.get(first.observation_id)
    assert result.reason_code == "native_atomic_group_update_unverified"
    assert result.state == "blocked" and not result.authorized
    assert group_only_payload(result.proposal, source.groups) == {
        "request": {"group": {"id": "2"}}
    }
    assert calls == [1] and result.model_requests == 0
    with Session(repository.engine) as session:
        assert session.scalar(select(InferenceBudget.reserved_usd)) == reserved
        for table in (TicketInbox, TicketAction, FixtureEffect):
            assert session.scalar(select(func.count()).select_from(table)) == 0


@pytest.mark.parametrize("change,reason", [
    ("technician", "human_assignment_preserved"),
    ("group", "outside_helpdesk_scope"),
    ("already_correct", "support_group_already_correct"),
    ("lifecycle", "excluded_lifecycle_process"),
    ("unknown_process", "process_coverage_unverified"),
    ("evidence", "observation_snapshot_changed"),
    ("concurrent_change", "group_context_changed"),
    ("policy", "observation_policy_changed"),
])
async def test_preflight_rechecks_mutable_state_and_never_prepares_a_stale_write(
    repository, change, reason
):
    worker, source, calls, request = await observed(repository)
    if change == "technician":
        source.ticket = source.ticket.model_copy(update={
            "technician": DeskPerson(person_id="human", email=None)
        })
    elif change in {"group", "already_correct"}:
        source.ticket = source.ticket.model_copy(update={
            "group_id": GROUPS["DWE" if change == "group" else "Network"]
        })
    elif change == "lifecycle":
        source.relationships = source.relationships.model_copy(update={
            "process_association": "lifecycle", "process_kind": "onboarding"
        })
    elif change == "unknown_process":
        source.relationships = source.relationships.model_copy(update={"coverage_verified": False})
    elif change == "evidence":
        source.evidence_refs = ("b" * 64,)
    elif change == "concurrent_change":
        worker.source.current.return_value = False
    elif change == "policy":
        worker.settings.inference_model = "offline-fixture-new-revision"
    result = repository.get((await worker.preflight(request)).observation_id)
    assert result.reason_code == reason and result.proposal is None and not result.authorized
    assert calls == [1]


@pytest.mark.parametrize("change", ["wrong_ticket", "synthetic_tenant", "missing_observation"])
async def test_preflight_cannot_adopt_an_unrelated_or_synthetic_receipt(repository, change):
    worker, source, calls, request = await observed(repository)
    worker.source.collect.reset_mock()
    if change == "wrong_ticket":
        request.ticket_id = "2"
    elif change == "synthetic_tenant":
        request.tenant_id = "synthetic"
    else:
        request.observation_id = "f" * 64
    result = repository.get((await worker.preflight(request)).observation_id)
    assert result.reason_code == "group_proposal_unverified" and result.proposal is None
    worker.source.collect.assert_not_awaited()


@pytest.mark.parametrize("target", ["301", "999", "auto", "2/template"])
def test_preview_cannot_select_helpdesk_unverified_or_non_native_destinations(target):
    with pytest.raises(ValueError):
        group_only_payload(GroupCorrection(kind="correct_support_group",
                                           destination_group_id=target), GROUPS)


def test_preview_cannot_use_duplicate_group_identities():
    with pytest.raises(ValueError):
        group_only_payload(GroupCorrection(kind="correct_support_group", destination_group_id="2"),
                           {**GROUPS, "DWE": "2"})
