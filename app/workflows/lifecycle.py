"""New workflow version: independent fulfillment recovery and durable expiry timers."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from app.contracts.lifecycle import LifecycleReceipt, LifecycleStart
    from app.contracts.provisioning import FulfillmentReceipt


@workflow.defn
class MirzaFixtureLifecycleWorkflow:
    def __init__(self):
        self.receipt = None
        self.resumed = False

    async def call(self, name, args, queue, result_type):
        return await workflow.execute_activity(
            name,
            args=args,
            task_queue=queue,
            result_type=result_type,
            start_to_close_timeout=timedelta(seconds=30),
            schedule_to_close_timeout=timedelta(seconds=180),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=2),
                maximum_interval=timedelta(seconds=10),
                maximum_attempts=3,
            ),
        )

    @workflow.run
    async def run(self, request: LifecycleStart) -> LifecycleReceipt:
        try:
            if request.recovery_command:
                initial = await self.call(
                    "resume_fixture_fulfillment",
                    [request.recovery_command],
                    request.mirza_queue,
                    LifecycleReceipt,
                )
            else:
                initial = await self.call(
                    "reconcile_fixture_lifecycle",
                    [request.operation_id],
                    request.mirza_queue,
                    LifecycleReceipt,
                )
            if initial.operation_id != request.operation_id:
                return LifecycleReceipt(
                    request.operation_id, "blocked", "recovery_binding_mismatch"
                )
            if request.fulfill and initial.state == "running":
                for index in range(initial.next_command, initial.next_command + 20):
                    self.receipt = await self.call(
                        "advance_fixture_mirza_fulfillment",
                        [request.operation_id, index],
                        request.mirza_queue,
                        FulfillmentReceipt,
                    )
                    if self.receipt.state in {"completed", "blocked", "cancelled"}:
                        break
                    if request.pause_after_provisioning and self.receipt.phase == "mutation":
                        await workflow.wait_condition(lambda: self.resumed)
            while True:
                self.receipt = await self.call(
                    "reconcile_fixture_lifecycle",
                    [request.operation_id],
                    request.mirza_queue,
                    LifecycleReceipt,
                )
                if self.receipt.due_at is None:
                    return self.receipt
                delay = max(timedelta(0), self.receipt.due_at - workflow.now())
                await workflow.sleep(delay)
        except ActivityError:
            return LifecycleReceipt(request.operation_id, "blocked", "fixture_recovery_required")

    @workflow.signal
    def resume(self):
        self.resumed = True

    @workflow.query
    def status(self) -> FulfillmentReceipt | LifecycleReceipt | None:
        return self.receipt
