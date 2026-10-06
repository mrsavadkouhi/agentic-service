import json
import logging
from unittest.mock import AsyncMock, MagicMock, create_autospec
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from temporalio.service import WorkflowService

from app.api import main
from app.logging import JsonFormatter
from app.settings import Settings


def config(**kwargs):
    return Settings(
        _env_file=None,
        database_url="postgresql+psycopg://unit:unit-password@localhost/unit",
        **kwargs,
    )


@pytest.fixture
def dependencies(monkeypatch):
    engine = MagicMock()
    temporal = MagicMock()
    temporal.workflow_service = create_autospec(WorkflowService, instance=True)
    monkeypatch.setattr(main, "make_engine", lambda settings: engine)
    monkeypatch.setattr(main.Client, "connect", AsyncMock(return_value=temporal))
    monkeypatch.setattr(main, "check_database", lambda engine: None)
    monkeypatch.setattr(main, "worker_is_ready", lambda engine, settings, role: True)
    return temporal


def test_unavailable_dependency_is_not_ready_but_api_stays_live(dependencies):
    dependencies.workflow_service.describe_namespace.side_effect = RuntimeError("dependency down")
    with TestClient(main.create_app(config())) as client:
        assert client.get("/health/live").status_code == 200
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json()["dependencies"]["temporal"] == "unavailable"
        assert "dependency down" not in response.text


def test_missing_worker_is_not_ready_and_pause_is_independent(dependencies, monkeypatch):
    monkeypatch.setattr(main, "worker_is_ready", lambda engine, settings, role: False)
    with TestClient(main.create_app(config(dispatch_paused=True))) as client:
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json()["dependencies"]["worker_dispatch"] == "paused"
        assert response.json()["dependencies"]["worker_mirza"] == "unavailable"
    with TestClient(main.create_app(config(dispatch_paused=True, mirza_paused=True))) as client:
        assert client.get("/health/ready").status_code == 200


def test_mode_configuration_does_not_enable_unimplemented_external_writes(dependencies):
    with TestClient(main.create_app(config(dispatch_mode="review", mirza_mode="automatic"))) as c:
        payload = c.get("/runtime").json()
        assert payload["workflows"]["dispatch"]["mode"] == "review"
        assert payload["workflows"]["mirza"]["mode"] == "automatic"
        assert payload["external_write_capabilities"] == []
        assert payload["business_workflows_implemented"] is False
        assert "unit-password" not in json.dumps(payload)
        assert c.post("/tickets", json={"subject": "Create a key"}).status_code == 404


def test_correlation_header_roundtrip_and_untrusted_header_replacement(dependencies):
    with TestClient(main.create_app(config())) as client:
        request_id = str(uuid4())
        response = client.get("/health/live", headers={"X-Correlation-ID": request_id})
        assert response.headers["X-Correlation-ID"] == request_id
        response = client.get("/health/live", headers={"X-Correlation-ID": "secret-like-value"})
        assert str(UUID(response.headers["X-Correlation-ID"])) == response.headers[
            "X-Correlation-ID"
        ]


def test_invalid_database_configuration_hides_its_value():
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, database_url="invalid://unit-password")
    assert "unit-password" not in str(error.value)
    with pytest.raises(ValidationError):
        config(dispatch_task_queue="same", mirza_task_queue="same")


def test_exception_formatter_omits_secret_bearing_exception_body():
    exc = RuntimeError("credential-bearing-url")
    record = logging.LogRecord("unit", logging.ERROR, __file__, 1, "Operation failed", (),
                               (type(exc), exc, None))
    formatted = JsonFormatter().format(record)
    assert "credential-bearing-url" not in formatted
    assert json.loads(formatted)["error_type"] == "RuntimeError"
