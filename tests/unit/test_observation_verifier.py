from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from temporalio.service import RPCError, RPCStatusCode

from app.activities.observation import ObservationActivities
from app.contracts.observation import ObservationReceipt, ObservationStart
from app.settings import Settings
from app.storage.models import Base
from app.storage.observations import ObservationRepository
from scripts.verify_observations import FixtureSource, fixture_inference, local_config, wait_receipt


def config(**fields):
    return Settings(
        _env_file=None, database_url="postgresql+psycopg://unit:unit@postgres/agentic", **fields
    )


@pytest.mark.parametrize(
    "fields",
    [
        {"temporal_address": "production.invalid:7233"},
        {"temporal_namespace": "production"},
        {"observation_listener_enabled": True},
        {"worker_inference_enabled": True},
        {"dispatch_mode": "review"},
        {"enable_fixture_execution": True},
    ],
)
def test_native_verifier_rejects_nonlocal_or_active_stacks(fields):
    with pytest.raises(ValueError):
        local_config(config(**fields))


def test_verifier_drops_external_urls_and_credentials():
    original = config(
        mirza_url="https://external.invalid",
        mirza_read_token="fixture-only",
        servicedesk_url="https://external.invalid",
        servicedesk_read_token="fixture-only",
    )
    safe = local_config(original)
    assert safe.mirza_url is safe.servicedesk_url is None
    assert safe.mirza_read_token is safe.servicedesk_read_token is None
    assert not safe.inference_enabled


async def test_receipt_wait_retries_startup_race_and_waits_for_extraction(monkeypatch):
    classified = ObservationReceipt("a" * 64, "proposed", "model_proposal_only", "mirza")
    extracted = ObservationReceipt("b" * 64, "proposed", "model_proposal_only")
    handle = AsyncMock()
    handle.query.side_effect = [
        RPCError("initial workflow task pending", RPCStatusCode.NOT_FOUND, b""),
        classified,
        extracted,
    ]
    monkeypatch.setattr("scripts.verify_observations.asyncio.sleep", AsyncMock())
    assert await wait_receipt(handle, "model_proposal_only") == extracted
    assert handle.query.await_count == 3


async def test_native_verifier_fixture_calls_are_valid_cached_and_never_authorized():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    safe, calls = local_config(config()), {"classify": 0, "extract": 0}
    inference = fixture_inference(safe, calls)
    repository = ObservationRepository(engine)
    worker = ObservationActivities(repository, AsyncMock(), safe, inference)
    worker.source = FixtureSource()
    try:
        for ticket_id in ("1", "2"):
            request = ObservationStart("observation-verify-unit", ticket_id, "dispatch", "mirza")
            classified = await worker.classify(request)
            receipt = (
                await worker.extract(request, classified.observation_id)
                if ticket_id == "2"
                else classified
            )
            result = repository.get(receipt.observation_id)
            assert result.state == "proposed" and result.authorized is False
            assert result.policy_reason == "unverified_source_order"
            repeated = await worker.classify(request)
            assert repeated.observation_id == classified.observation_id
            if ticket_id == "2":
                assert (
                    await worker.extract(request, repeated.observation_id)
                ).observation_id == receipt.observation_id
        assert calls == {"classify": 2, "extract": 1}
    finally:
        await inference.close()
        engine.dispose()
