from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from app import settings
from app.storage import database
from app.storage.models import Base


def test_lifecycle_migration_parity_and_downgrade_preserves_cipher_and_business(
    tmp_path, monkeypatch
):
    url = "sqlite:///" + str(tmp_path / "lifecycle.sqlite")
    monkeypatch.setattr(database, "make_engine", lambda config: create_engine(url))
    monkeypatch.setattr(settings, "Settings", lambda: None)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, "head")
    engine = create_engine(url)
    with engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
    command.downgrade(config, "0005_provisioning_fixtures")
    with engine.connect() as connection:
        tables = set(connection.dialect.get_table_names(connection))
        assert "mirza_fixture_owned_grants" not in tables
        assert {"mirza_fixture_secrets", "mirza_policy_reviews", "ticket_actions"} <= tables
    command.upgrade(config, "head")
    engine.dispose()
