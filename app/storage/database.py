from datetime import timedelta

from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine, func, select, text
from sqlalchemy.orm import Session

from app.settings import Settings, WorkerRole
from app.storage.models import RuntimeWorker

SCHEMA_REVISION = "0001_runtime"


def make_engine(settings: Settings) -> Engine:
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_size=3,
        max_overflow=2,
        connect_args={"connect_timeout": int(settings.dependency_timeout_seconds),
                      "options": "-c statement_timeout=5000"},
    )


def check_database(engine: Engine) -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        if MigrationContext.configure(connection).get_current_revision() != SCHEMA_REVISION:
            raise RuntimeError("Application schema requires migration")


def worker_is_ready(engine: Engine, settings: Settings, role: WorkerRole) -> bool:
    with Session(engine) as session:
        return bool(session.scalar(select(RuntimeWorker.worker_id).where(
            RuntimeWorker.worker_role == role.value,
            RuntimeWorker.task_queue == settings.task_queue(role),
            RuntimeWorker.mode == settings.mode(role).value,
            RuntimeWorker.state == "running",
            RuntimeWorker.last_seen > func.now() - timedelta(seconds=settings.worker_stale_seconds),
        ).limit(1)))

