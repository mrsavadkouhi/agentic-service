from sqlalchemy import Engine, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.settings import Settings, WorkerRole
from app.storage.models import RuntimeWorker


def heartbeat(
    engine: Engine, settings: Settings, role: WorkerRole, worker_id: str, state: str
) -> None:
    with Session(engine) as session, session.begin():
        statement = insert(RuntimeWorker).values(
            worker_id=worker_id, worker_role=role.value,
            task_queue=settings.task_queue(role), mode=settings.mode(role).value,
            state=state, last_seen=func.now(),
        )
        session.execute(statement.on_conflict_do_update(
            index_elements=["worker_id"],
            set_={"state": state, "last_seen": func.now()},
        ))

