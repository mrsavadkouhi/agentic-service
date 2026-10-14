"""Opaque fulfillment commands. Synthetic execution never grants native authority."""

from dataclasses import dataclass
from typing import Literal


@dataclass
class FulfillmentStart:
    operation_id: str
    mirza_queue: str
    pause_after_provisioning: bool = False


@dataclass
class FulfillmentReceipt:
    operation_id: str
    state: str
    phase: str
    reason_code: str
    execution_domain: Literal["synthetic"] = "synthetic"


PHASES = ("tool_team", "owner_membership", "mutation", "user_dm", "staff_dm", "resolve")
