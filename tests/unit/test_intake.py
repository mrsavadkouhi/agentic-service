import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api import main
from app.api.intake import configured_catalog, deliver_notifications
from app.policies.synthetic_events import event
from app.settings import Settings
from app.storage.ticket_repository import EventConflict


def config(**kwargs):
    return Settings(
        _env_file=None, database_url="postgresql+psycopg://unit:unit@localhost/unit", **kwargs
    )


@pytest.fixture
def application(monkeypatch):
    repository = MagicMock()
    repository.accept.return_value = {"workflow_id": "ticket-test", "duplicate": False}
    monkeypatch.setattr(main, "make_engine", lambda settings: MagicMock())
    monkeypatch.setattr(main.Client, "connect", AsyncMock(return_value=MagicMock()))
    monkeypatch.setattr(main, "TicketRepository", lambda engine: repository)
    monkeypatch.setattr(main, "configured_catalog", lambda settings: None)

    async def idle(*args):
        await asyncio.Event().wait()

    monkeypatch.setattr(main, "deliver_notifications", idle)
    return repository


def test_default_intake_and_operator_disabled(application):
    with TestClient(main.create_app(config())) as client:
        assert client.post("/v1/events", json=event().model_dump(mode="json")).status_code == 503
        assert client.get("/v1/workflows/test").status_code == 503
    application.accept.assert_not_called()


def test_auth_roles_and_invalid_body_never_echo_input(application):
    settings = config(intake_token="i" * 32, operator_token="o" * 32, enable_fixture_execution=True)
    intake = {"Authorization": "Bearer " + "i" * 32}
    operator = {"Authorization": "Bearer " + "o" * 32}
    with TestClient(main.create_app(settings)) as client:
        assert client.post("/v1/events", headers=operator, json={}).status_code == 401
        assert client.get("/v1/workflows/test", headers=intake).status_code == 401
        response = client.post("/v1/events", headers=intake, json={"raw_key": "sk-unit-secret"})
        assert response.status_code == 422 and "sk-unit-secret" not in response.text
        assert client.post("/v1/events", headers=intake, content=b"x" * 65537).status_code == 413
        assert (
            client.post(
                "/v1/events", headers=intake, json=event().model_dump(mode="json")
            ).status_code
            == 202
        )
        application.accept.side_effect = EventConflict("sensitive-detail")
        response = client.post("/v1/events", headers=intake, json=event().model_dump(mode="json"))
        assert response.status_code == 409 and "sensitive-detail" not in response.text
        assert (
            client.post("/v1/workflows/test/approve", headers=operator, json={}).status_code == 404
        )


def test_fixture_switch_does_not_accept_production_catalog(tmp_path):
    catalog = configured_catalog(config(enable_fixture_execution=True))
    assert catalog.environment == "synthetic"
    target = tmp_path / "production.json"
    target.write_text(catalog.model_copy(update={"environment": "production"}).model_dump_json())
    with pytest.raises(ValueError):
        configured_catalog(config(enable_fixture_execution=True, catalog_file=target))
    assert configured_catalog(config()) is None
    with pytest.raises(ValidationError):
        config(intake_token="i" * 32, operator_token="i" * 32)


async def test_outbox_ack_only_after_temporal_accepts():
    repository = MagicMock()
    repository.pending_notifications.return_value = [
        {"event_key": "event", "workflow_id": "ticket", "worker_role": "mirza"},
    ]
    client = MagicMock()
    client.start_workflow = AsyncMock(side_effect=RuntimeError("unavailable"))
    task = asyncio.create_task(deliver_notifications(repository, client, config()))
    await asyncio.sleep(0.03)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    repository.mark_notified.assert_not_called()
    client.start_workflow.side_effect = None
    task = asyncio.create_task(deliver_notifications(repository, client, config()))
    await asyncio.sleep(0.03)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    repository.mark_notified.assert_called_once_with("event")
    assert client.start_workflow.call_args.kwargs["start_signal"] == "wake"
