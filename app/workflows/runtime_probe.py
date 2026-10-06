from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from app.contracts.runtime import ProbeInput, ProbeResult


@workflow.defn
class RuntimeProbeWorkflow:
    """Synthetic persistence/restart probe, with no ticket or Mirza connector."""

    def __init__(self) -> None:
        self.released = False
        self.state = "starting"

    @workflow.run
    async def run(self, request: ProbeInput) -> ProbeResult:
        for phase in ("started", "completed"):
            await workflow.execute_activity(
                "record_runtime_probe",
                args=[request, phase],
                start_to_close_timeout=timedelta(seconds=15),
                retry_policy=RetryPolicy(maximum_attempts=5),
            )
            if phase == "started":
                self.state = "waiting"
                await workflow.wait_condition(lambda: self.released)
        self.state = "completed"
        return ProbeResult(request.probe_id, request.worker_role, self.state)

    @workflow.signal
    async def release(self) -> None:
        self.released = True

    @workflow.query
    def status(self) -> str:
        return self.state

