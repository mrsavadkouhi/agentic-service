import asyncio

from sqlalchemy.exc import SQLAlchemyError
from temporalio import activity
from temporalio.exceptions import ApplicationError

from app.contracts.execution import ActionCommand, CommitTransition, ReminderCommand, StoredEvent
from app.settings import Settings, WorkerRole
from app.storage.ticket_repository import (
    EventConflict,
    SimulatedLostResponse,
    StaleAction,
    TicketRepository,
)


class TicketActivities:
    def __init__(self, repository: TicketRepository, settings: Settings, role: WorkerRole):
        self.repository, self.settings, self.role = repository, settings, role

    async def call(self, function, *args):
        try:
            return await asyncio.to_thread(function, *args)
        except (EventConflict, StaleAction) as exc:
            raise ApplicationError(type(exc).__name__, non_retryable=True) from None
        except SimulatedLostResponse:
            raise ApplicationError("Synthetic response lost", type="LostResponse") from None
        except SQLAlchemyError as exc:
            # SQL/validation exception text can contain parameters; never put it in history.
            raise ApplicationError("Ticket activity unavailable", type=type(exc).__name__) from None
        except Exception as exc:
            raise ApplicationError(
                "Ticket activity invalid", type=type(exc).__name__, non_retryable=True
            ) from None

    @activity.defn(name="next_ticket_event")
    async def next_event(self, workflow_id: str) -> StoredEvent | None:
        return await self.call(self.repository.next_event, workflow_id)

    @activity.defn(name="commit_ticket_transition")
    async def commit(self, command: CommitTransition) -> str:
        return await self.call(self.repository.commit, command)

    @activity.defn(name="run_ticket_fixture_action")
    async def execute(self, command: ActionCommand) -> dict:
        return await self.call(
            self.repository.run_fixture_action, command, self.settings, self.role
        )

    @activity.defn(name="finish_ticket_action")
    async def finish(self, command: ActionCommand, result: dict) -> str:
        return await self.call(self.repository.finish_action, command, result)

    @activity.defn(name="reserve_ticket_reminders")
    async def remind(self, command: ReminderCommand) -> int:
        return await self.call(self.repository.reminders, command)
