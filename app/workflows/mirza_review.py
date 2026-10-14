"""Mirza-queue review activity; only opaque input references and receipts in history."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from app.contracts.mirza_review import MirzaReviewReceipt, MirzaReviewStart


@workflow.defn
class MirzaPolicyReviewWorkflow:
    @workflow.run
    async def run(self, request: MirzaReviewStart) -> MirzaReviewReceipt:
        return await workflow.execute_activity(
            "prepare_mirza_policy_review", request, result_type=MirzaReviewReceipt,
            task_queue=request.mirza_queue,
            start_to_close_timeout=timedelta(seconds=300),
            schedule_to_close_timeout=timedelta(seconds=900),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
