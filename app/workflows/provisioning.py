"""Only opaque references cross this workflow; private key delivery stays in activities."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from app.contracts.provisioning import FulfillmentReceipt, FulfillmentStart


@workflow.defn
class MirzaFixtureFulfillmentWorkflow:
    def __init__(self):
        self.resumed = False
        self.receipt = None

    @workflow.run
    async def run(self, request: FulfillmentStart) -> FulfillmentReceipt:
        for command_index in range(20):
            try:
                self.receipt = await workflow.execute_activity(
                    "advance_fixture_mirza_fulfillment",
                    args=[request.operation_id, command_index],
                    task_queue=request.mirza_queue,
                    result_type=FulfillmentReceipt,
                    start_to_close_timeout=timedelta(seconds=30),
                    schedule_to_close_timeout=timedelta(seconds=180),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=2),
                        maximum_interval=timedelta(seconds=10),
                        maximum_attempts=3,
                    ),
                )
            except ActivityError:
                return FulfillmentReceipt(
                    request.operation_id, "blocked", "", "fixture_recovery_required"
                )
            if self.receipt.state in {"completed", "blocked"}:
                return self.receipt
            if request.pause_after_provisioning and self.receipt.phase == "mutation":
                await workflow.wait_condition(lambda: self.resumed)
        return FulfillmentReceipt(request.operation_id, "blocked", "", "fixture_progress_limit")

    @workflow.signal
    def resume(self):
        self.resumed = True

    @workflow.query
    def status(self) -> FulfillmentReceipt | None:
        return self.receipt
