from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from app import settings
from app.storage import database
from app.storage.models import Base


def test_review_migration_downgrade_preserves_observations_and_business_tables(
    tmp_path, monkeypatch
):
    url = "sqlite:///" + str(tmp_path / "migration.sqlite")
    monkeypatch.setattr(database, "make_engine", lambda config: create_engine(url))
    monkeypatch.setattr(settings, "Settings", lambda: None)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, "head")
    engine = create_engine(url)
    with engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
    command.downgrade(config, "0003_observations")
    with engine.connect() as connection:
        tables = connection.dialect.get_table_names(connection)
        assert "mirza_review_heads" not in tables and "mirza_policy_reviews" not in tables
        assert {"ticket_observations", "inference_budgets", "ticket_workflows"} <= set(tables)
    command.upgrade(config, "head")
    engine.dispose()
