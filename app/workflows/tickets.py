import json
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

with workflow.unsafe.imports_passed_through():
    from app.contracts.execution import (
        ActionCommand,
        CommitTransition,
        ReminderCommand,
        StoredEvent,
        TicketWorkflowStart,
    )
    from app.contracts.tickets import Catalog, Evaluation, TicketEvent, Tracking, WorkflowState
    from app.policies.reminders import next_morning, reminder_due
    from app.policies.tickets import evaluate

RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=10),
    maximum_attempts=5,
)


@workflow.defn
class TicketWorkflow:
    """One serial owner per ticket; only activities access storage or connectors."""

    def __init__(self):
        self.generation = 0
        self.tracking = Tracking()

    async def call(self, name, *args, result_type=None, task_queue=None):
        while True:
            try:
                return await workflow.execute_activity(
                    name,
                    args=args,
                    result_type=result_type,
                    task_queue=task_queue,
                    start_to_close_timeout=timedelta(seconds=15),
                    schedule_to_close_timeout=timedelta(seconds=120),
                    retry_policy=RETRY,
                )
            except ActivityError as exc:
                if (
                    name == "run_ticket_fixture_action"
                    or isinstance(exc.cause, ApplicationError)
                    and exc.cause.non_retryable
                ):
                    raise
                # Infrastructure outage: preserve the actor and original command;
                # each retry batch is bounded, human waits never expire.
                await workflow.sleep(timedelta(seconds=30))

    @workflow.run
    async def run(self, request: TicketWorkflowStart) -> None:
        self.tracking = Tracking.model_validate_json(request.tracking_json)
        transitions = 0
        while True:
            if transitions >= 100 or workflow.info().is_continue_as_new_suggested():
                workflow.continue_as_new(
                    TicketWorkflowStart(
                        request.workflow_id,
                        request.worker_role,
                        request.dispatch_queue,
                        request.mirza_queue,
                        self.tracking.model_dump_json(),
                    )
                )
            generation = self.generation
            event = await self.call(
                "next_ticket_event", request.workflow_id, result_type=StoredEvent | None
            )
            if event:
                prior = self.tracking
                if event.kind == "cancel":
                    self.tracking = prior.model_copy(
                        update={
                            "state": WorkflowState.CANCELLED,
                            "cancelled": True,
                            "wait": None,
                            "pending_action_id": None,
                            "pending_action_role": None,
                        }
                    )
                    decision = Evaluation(
                        state=WorkflowState.CANCELLED,
                        reason_code="operator_cancelled",
                        tracking=self.tracking,
                    )
                else:
                    normalized = TicketEvent.model_validate_json(event.event_json)
                    catalog = (
                        Catalog.model_validate_json(event.catalog_json)
                        if event.catalog_json
                        else None
                    )
                    decision = evaluate(normalized, prior, catalog)
                receipt = await self.call(
                    "commit_ticket_transition",
                    CommitTransition(
                        request.workflow_id,
                        event.event_key,
                        decision.model_dump_json(),
                        prior.latest_sequence,
                    ),
                    result_type=str,
                )
                self.tracking = Tracking.model_validate_json(receipt)
                transitions += 1
                continue  # Drain newer revisions before executing a staged action.
            if self.tracking.pending_action_id:
                command = ActionCommand(request.workflow_id, self.tracking.pending_action_id)
                queue = (
                    request.mirza_queue
                    if self.tracking.pending_action_role == "mirza"
                    else request.dispatch_queue
                )
                try:
                    result = await self.call(
                        "run_ticket_fixture_action", command, result_type=dict, task_queue=queue
                    )
                except ActivityError:
                    result = {"state": "manual_review", "reason": "activity_recovery_required"}
                receipt = await self.call("finish_ticket_action", command, result, result_type=str)
                self.tracking = Tracking.model_validate_json(receipt)
                transitions += 1
                continue
            wait = self.tracking.wait
            if wait:
                scheduled = next_morning(workflow.now())
                try:
                    await workflow.wait_condition(
                        lambda: self.generation != generation, timeout=scheduled - workflow.now()
                    )
                except TimeoutError:
                    if reminder_due(scheduled, workflow.now()):
                        await self.call(
                            "reserve_ticket_reminders",
                            ReminderCommand(
                                request.workflow_id,
                                wait.cycle_id,
                                workflow.now().isoformat(),
                            ),
                            result_type=int,
                        )
                    transitions += 1
            else:
                await workflow.wait_condition(lambda: self.generation != generation)

    @workflow.signal
    def wake(self) -> None:
        self.generation += 1

    @workflow.query
    def status(self) -> dict:
        return json.loads(self.tracking.model_dump_json())
