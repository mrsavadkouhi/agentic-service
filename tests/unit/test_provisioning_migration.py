from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from app import settings
from app.storage import database
from app.storage.models import Base


def test_fixture_migration_preserves_review_observation_and_business_tables(tmp_path, monkeypatch):
    url = "sqlite:///" + str(tmp_path / "migration.sqlite")
    monkeypatch.setattr(database, "make_engine", lambda config: create_engine(url))
    monkeypatch.setattr(settings, "Settings", lambda: None)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, "head")
    engine = create_engine(url)
    with engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
    command.downgrade(config, "0004_mirza_reviews")
    with engine.connect() as connection:
        tables = connection.dialect.get_table_names(connection)
        assert "mirza_fixture_secrets" not in tables and "provisioning_fixture_worlds" not in tables
        assert {"mirza_policy_reviews", "ticket_observations", "ticket_actions"} <= set(tables)
    command.upgrade(config, "head")
    engine.dispose()
