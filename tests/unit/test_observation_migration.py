from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from app import settings
from app.storage import database
from app.storage.models import Base


def test_observation_migration_matches_metadata_and_downgrades_only_its_tables(
    tmp_path, monkeypatch
):
    path = tmp_path / "migration.sqlite"
    url = "sqlite:///" + str(path)
    monkeypatch.setattr(database, "make_engine", lambda config: create_engine(url))
    monkeypatch.setattr(settings, "Settings", lambda: None)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, "head")
    engine = create_engine(url)
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        assert context.get_current_revision() == database.SCHEMA_REVISION
        assert compare_metadata(context, Base.metadata) == []
    command.downgrade(config, "0002_tickets")
    with engine.connect() as connection:
        assert MigrationContext.configure(connection).get_current_revision() == "0002_tickets"
        tables = connection.dialect.get_table_names(connection)
        assert "ticket_observations" not in tables and "inference_budgets" not in tables
        assert "ticket_workflows" in tables and "ticket_actions" in tables
    command.upgrade(config, "head")
    engine.dispose()
