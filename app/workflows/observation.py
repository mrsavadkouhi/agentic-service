"""Temporal owns listening/wake/replay; no content, models or privileged actions here."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.workflow import ParentClosePolicy

with workflow.unsafe.imports_passed_through():
    from app.contracts.observation import ObservationReceipt, ObservationStart, PollBatch, PollStart
    from app.contracts.tickets import stable_id

RETRY = RetryPolicy(maximum_attempts=3)


@workflow.defn
class ObservationTicketWorkflow:
    def __init__(self):
        self.generation = 0
        self.receipt = None

    @workflow.run
    async def run(self, request: ObservationStart):
        count = 0
        while True:
            if count >= 100 or workflow.info().is_continue_as_new_suggested():
                workflow.continue_as_new(request)
            generation = self.generation
            self.receipt = await workflow.execute_activity(
                "classify_observation_ticket",
                request,
                result_type=ObservationReceipt,
                task_queue=request.dispatch_queue,
                start_to_close_timeout=timedelta(seconds=180),
                schedule_to_close_timeout=timedelta(seconds=600),
                retry_policy=RETRY,
            )
            if self.receipt.state == "proposed" and self.receipt.kind == "mirza":
                self.receipt = await workflow.execute_activity(
                    "extract_observation_ticket",
                    args=[request, self.receipt.observation_id],
                    result_type=ObservationReceipt,
                    task_queue=request.mirza_queue,
                    start_to_close_timeout=timedelta(seconds=180),
                    schedule_to_close_timeout=timedelta(seconds=600),
                    retry_policy=RETRY,
                )
            count += 1
            await workflow.wait_condition(lambda: self.generation != generation)

    @workflow.signal
    def wake(self):
        self.generation += 1

    @workflow.query
    def status(self) -> ObservationReceipt | None:
        return self.receipt


@workflow.defn
class ObservationListenerWorkflow:
    @workflow.run
    async def run(self, request: PollStart):
        count = 0
        while True:
            if count >= 100 or workflow.info().is_continue_as_new_suggested():
                workflow.continue_as_new(request)
            batch = await workflow.execute_activity(
                "poll_observation_candidates",
                request,
                result_type=PollBatch,
                task_queue=request.dispatch_queue,
                start_to_close_timeout=timedelta(seconds=180),
                schedule_to_close_timeout=timedelta(seconds=600),
                retry_policy=RETRY,
            )
            for ticket_id in batch.ticket_ids:
                owner_id = "observation-" + stable_id("servicedesk", ticket_id)
                try:
                    await workflow.start_child_workflow(
                        ObservationTicketWorkflow.run,
                        ObservationStart(
                            "servicedesk", ticket_id, request.dispatch_queue, request.mirza_queue
                        ),
                        id=owner_id,
                        task_queue=request.dispatch_queue,
                        parent_close_policy=ParentClosePolicy.ABANDON,
                    )
                except WorkflowAlreadyStartedError:
                    await workflow.get_external_workflow_handle(owner_id).signal("wake")
            request.cursor = batch.next_cursor
            count += 1
            await workflow.sleep(timedelta(seconds=request.poll_seconds))
