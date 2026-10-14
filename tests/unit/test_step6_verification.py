import json
from types import SimpleNamespace

import httpx
import pytest
from temporalio.api.common.v1 import Payload, Payloads
from temporalio.api.history.v1 import (
    ActivityTaskCompletedEventAttributes,
    HistoryEvent,
    MarkerRecordedEventAttributes,
)
from temporalio.client import WorkflowHistory
from temporalio.exceptions import ApplicationError

from app.connectors.http import ReadOnlyHTTP
from app.contracts.execution import CommitTransition
from app.contracts.tickets import Evaluation, Tracking, WorkflowState
from app.policies.synthetic_events import event
from scripts import probe_group_update_contract as probe
from scripts.verify_observations import FIXTURE_TEXT, verify_history_privacy
from scripts.verify_policy_upgrade import MemoryActivities, patch_ids, verify_fixture_hashes


def test_frozen_historical_sources_match_manifest():
    verify_fixture_hashes()


def test_patch_marker_proof_decodes_payload_and_ignores_other_marker_types():
    payload = Payloads(payloads=[Payload(
        metadata={"encoding": b"json/plain"},
        data=b'{"id":"synthetic-patch","deprecated":false}',
    )])
    other = HistoryEvent(marker_recorded_event_attributes=MarkerRecordedEventAttributes(
        marker_name="core_local_activity", details={"patch-data": payload},
    ))
    patch = HistoryEvent(marker_recorded_event_attributes=MarkerRecordedEventAttributes(
        marker_name="core_patch", details={"patch-data": payload},
    ))
    assert patch_ids(WorkflowHistory("synthetic", [other])) == set()
    assert patch_ids(WorkflowHistory("synthetic", [other, patch])) == {"synthetic-patch"}
    with pytest.raises(ValueError, match="encoding"):
        patch_ids(WorkflowHistory("synthetic", [HistoryEvent(
            marker_recorded_event_attributes=MarkerRecordedEventAttributes(marker_name="core_patch")
        )]))


def test_native_history_privacy_rejects_text_hidden_by_json_payload_encoding():
    leaked = HistoryEvent(
        activity_task_completed_event_attributes=ActivityTaskCompletedEventAttributes(
            result=Payloads(payloads=[Payload(data=FIXTURE_TEXT.encode())]),
        )
    )
    history = WorkflowHistory("synthetic", [leaked])
    assert FIXTURE_TEXT not in history.to_json()
    with pytest.raises(AssertionError):
        verify_history_privacy(history)
    verify_history_privacy(WorkflowHistory("synthetic", [HistoryEvent()]))


async def test_historical_test_activity_rejects_non_synthetic_and_authorized_decisions():
    memory = MemoryActivities("synthetic-owner")
    with pytest.raises(ValueError, match="Only generated synthetic"):
        memory.enqueue(event().model_copy(update={"data_kind": "servicedesk"}))
    decision = Evaluation(
        state=WorkflowState.EXECUTING, reason_code="fixture", tracking=Tracking(),
        authorized=True, terms_digest="a" * 64, target_role="mirza", action_id="a" * 64,
    )
    with pytest.raises(ApplicationError, match="Unexpected synthetic authority"):
        await memory.commit(CommitTransition("synthetic-owner", "a" * 64,
                                             decision.model_dump_json(), -1))


async def test_installed_contract_probe_only_gets_and_drops_private_data(
    tmp_path, monkeypatch, capsys
):
    secret = "unit-read-token"
    workflow = tmp_path / "source.json"
    workflow.write_text(json.dumps({"nodes": [{"name": "Count All", "parameters": {
        "url": "https://fixture.invalid/api/v3/requests",
        "headerParameters": {"parameters": [{"name": "authtoken", "value": secret}]},
    }}]}))
    requests = []

    def reply(request):
        requests.append(request)
        assert request.headers["authtoken"] == secret
        body = ({"response_status": {"status": "success", "status_code": 2000},
                 "request": {"id": "1", "subject": "private ticket", "technician": None}}
                if request.url.path.endswith("/1") else {
                    "fields": {"last_updated_time": {"type": "datetime", "read_only": True},
                               "technician": {"type": secret, "example": "private person"}}
                })
        return httpx.Response(200, json=body)

    original = ReadOnlyHTTP
    monkeypatch.setattr(probe, "ReadOnlyHTTP", lambda *args, **kwargs: original(
        *args, **kwargs, transport=httpx.MockTransport(reply)
    ))
    args = SimpleNamespace(workflow=workflow, ticket_id="1", allow_http=False, report=None)
    await probe.run(args)
    output = capsys.readouterr().out
    assert len(requests) == 2 and all(request.method == "GET" for request in requests)
    assert all(value not in output for value in (secret, "private ticket", "private person"))
    assert json.loads(output)["atomic_update_contract_verified"] is False


def test_schema_probe_bounds_nesting():
    value = {}
    for _ in range(14):
        value = {"child": value}
    with pytest.raises(ValueError, match="nesting"):
        probe.schema_fields(value)
