from dataclasses import asdict, dataclass
from datetime import datetime

from pydantic import Field

from app.contracts.tickets import Contract, Ref


class RecoveryRequest(Contract):
    request_id: Ref
    expected_revision: int = Field(ge=0)


@dataclass
class LifecycleStart:
    operation_id: str
    mirza_queue: str
    recovery_command: str | None = None
    pause_after_provisioning: bool = False
    fulfill: bool = True


@dataclass
class LifecycleReceipt:
    operation_id: str
    state: str
    reason_code: str
    next_command: int = 0
    due_at: datetime | None = None

    def as_dict(self):
        result = asdict(self)
        result["due_at"] = self.due_at.isoformat() if self.due_at else None
        return result
