from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app import worker
from app.settings import Settings, WorkerRole


async def test_failed_core_validation_exits_without_waiting_on_shutdown(
    monkeypatch, tmp_path, caplog
):
    engine = MagicMock()
    failed = SimpleNamespace(
        run=AsyncMock(side_effect=RuntimeError("private startup detail")), shutdown=AsyncMock()
    )
    monkeypatch.setattr(worker, "make_engine", lambda config: engine)
    monkeypatch.setattr(worker, "check_database", lambda engine: None)
    monkeypatch.setattr(worker, "heartbeat", lambda *args: None)
    monkeypatch.setattr(worker, "marker_path", lambda role: tmp_path / "health.json")
    monkeypatch.setattr(worker.Client, "connect", AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(worker, "Worker", lambda *args, **kwargs: failed)
    config = Settings(_env_file=None, database_url="postgresql+psycopg://unit:unit@localhost/unit")
    with pytest.raises(RuntimeError, match="private startup detail"):
        await worker.serve(config, WorkerRole.MIRZA)
    failed.shutdown.assert_not_awaited()
    engine.dispose.assert_called_once()
    assert "private startup detail" not in caplog.text
    assert any(getattr(record, "event", None) == "worker_failure" for record in caplog.records)
