from dataclasses import dataclass


@dataclass
class TicketWorkflowStart:
    workflow_id: str
    worker_role: str
    dispatch_queue: str
    mirza_queue: str
    tracking_json: str = "{}"


@dataclass
class StoredEvent:
    event_key: str
    event_json: str
    catalog_json: str | None
    kind: str


@dataclass
class CommitTransition:
    workflow_id: str
    event_key: str
    evaluation_json: str
    expected_before_sequence: int


@dataclass
class ActionCommand:
    workflow_id: str
    action_id: str


@dataclass
class ReminderCommand:
    workflow_id: str
    cycle_id: str
    now_iso: str
