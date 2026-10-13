import json
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage
from sqlalchemy import create_engine
from temporalio import workflow
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner

from app.agents.observation import Inference, Scope
from app.api import main
from app.connectors.http import ReadFailure, ReadOnlyHTTP, ok
from app.connectors.observation import ObservationSource
from app.connectors.servicedesk import ServiceDesk
from app.contracts.observation import ObservationResult, PollStart
from app.settings import Settings
from app.storage.models import Base
from app.storage.observations import ObservationRepository
from app.workflows.observation import ObservationListenerWorkflow, ObservationTicketWorkflow
from scripts.evaluate_observations import evaluate_labels


def config(**kwargs):
    return Settings(
        _env_file=None, database_url="postgresql+psycopg://unit:unit@localhost/unit", **kwargs
    )


def packet(text="fixture"):
    return SimpleNamespace(text=text, evidence_refs=("a" * 64,))


@pytest.mark.parametrize("case", ["unknown_tool", "invalid_output", "tool_loop", "timeout"])
async def test_invalid_model_behavior_is_bounded_and_error_details_are_private(case):
    calls = []

    async def respond(messages, info):
        calls.append(1)
        if case == "timeout":
            import asyncio

            await asyncio.sleep(1)
        if case == "unknown_tool":
            part = ToolCallPart("run_http_admin_write", {"secret": "sk-private-response"})
        elif case == "tool_loop":
            part = ToolCallPart("ownership_catalog", {})
        else:
            part = ToolCallPart(
                info.output_tools[0].name,
                {
                    "kind": "ordinary",
                    "group": "invented-team",
                    "authorized": True,
                },
            )
        return ModelResponse([part], usage=RequestUsage(input_tokens=100, output_tokens=20))

    settings = config(
        inference_request_limit=2,
        inference_tool_limit=1,
        inference_timeout_seconds=0.1 if case == "timeout" else 30,
    )
    runner = Inference(settings, classification_model=FunctionModel(respond))
    result = await runner.run("classify", Scope(packet()))
    assert result.state == "blocked" and len(calls) <= 2 and not result.authorized
    assert result.proposal is None and "sk-private-response" not in result.model_dump_json()


async def test_token_and_cost_caps_and_live_activity_requirement_prevent_unbounded_calls():
    async def respond(messages, info):
        return ModelResponse(
            [
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "kind": "ordinary",
                        "group": "Network",
                    },
                )
            ],
            usage=RequestUsage(input_tokens=1000, output_tokens=20),
        )

    runner = Inference(
        config(inference_input_token_limit=100), classification_model=FunctionModel(respond)
    )
    assert (await runner.run("classify", Scope(packet()))).state == "blocked"
    runner = Inference(
        config(inference_input_usd_per_million=1000, inference_output_usd_per_million=1000),
        classification_model=FunctionModel(respond),
    )
    assert (await runner.run("classify", Scope(packet()))).reason_code == "inference_cost_preflight"
    settings = config(
        inference_enabled=True,
        inference_url="https://fixture.invalid/v1",
        inference_token="dedicated-inference-token",
        inference_model="fixture-model",
        inference_input_usd_per_million=0.1,
        inference_output_usd_per_million=0.1,
    )
    runner = Inference(settings)
    assert (
        await runner.run("classify", Scope(packet()))
    ).reason_code == "inference_activity_required"
    assert runner.client is None


@pytest.mark.parametrize(
    "url",
    [
        "http://fixture.invalid/v1",
        "https://user:pass@fixture.invalid",
        "https://fixture.invalid/v1?token=secret",
        "https://fixture.invalid/admin",
    ],
)
def test_fixed_inference_origin_and_credential_separation(url):
    fields = dict(
        inference_enabled=True,
        inference_url=url,
        inference_token="dedicated-token",
        inference_model="fixture",
        inference_input_usd_per_million=0.1,
        inference_output_usd_per_million=0.1,
    )
    with pytest.raises(ValidationError):
        config(**fields)
    fields["inference_url"] = "https://fixture.invalid/v1"
    with pytest.raises(ValidationError):
        config(**fields, mirza_read_token="dedicated-token")


async def test_candidate_reads_reject_filter_escape_and_rotate_bounded_scope():
    groups = SimpleNamespace(group_id="301", name="Helpdesk")
    desk = AsyncMock()
    desk.groups.return_value = ok("servicedesk", "groups", (groups,), "fixture")
    desk.pages.return_value = [{"id": "1", "group": {"id": "2"}}]
    source = ObservationSource(SimpleNamespace(reader=SimpleNamespace(desk=desk)), config())
    with pytest.raises(ReadFailure):
        await source.candidates()


async def test_note_read_limits_stop_large_or_excessive_content_without_partial_records():
    def handle(request):
        if request.url.path.endswith("/notes"):
            return httpx.Response(
                200,
                json={
                    "response_status": {"status": "success", "status_code": 2000},
                    "notes": [{"id": "10"}],
                    "list_info": {"has_more_rows": False},
                },
            )
        return httpx.Response(
            200,
            json={
                "response_status": {"status": "success", "status_code": 2000},
                "note": {
                    "id": "10",
                    "request": {"id": "1"},
                    "description": "x" * 100,
                    "added_time": {"value": 1000},
                },
            },
        )

    from pydantic import SecretStr

    http = ReadOnlyHTTP(
        "https://fixture.invalid",
        SecretStr("fixture-token"),
        ServiceDesk.PATHS,
        transport=httpx.MockTransport(handle),
    )
    try:
        desk = ServiceDesk(http)
        with pytest.raises(ReadFailure):
            await desk._note_records("1", max_records=0)
        with pytest.raises(ReadFailure):
            await desk._note_records("1", max_content_bytes=50)
    finally:
        await http.close()


async def test_workflow_sandboxes_import_no_model_or_business_content():
    runner = SandboxedWorkflowRunner()
    for cls in (ObservationTicketWorkflow, ObservationListenerWorkflow):
        runner.prepare_workflow(workflow._Definition.must_from_class(cls))
    assert set(asdict(PollStart("dispatch", "mirza"))) == {
        "dispatch_queue",
        "mirza_queue",
        "poll_seconds",
        "batch_size",
        "cursor",
    }


@pytest.mark.parametrize("worker_inference_enabled", [False, True])
def test_operator_only_observation_routes_do_not_use_business_intake(
    monkeypatch, worker_inference_enabled
):
    engine, business, observations = MagicMock(), MagicMock(), MagicMock()
    client = SimpleNamespace(start_workflow=AsyncMock())
    observations.latest.return_value = []
    monkeypatch.setattr(main, "make_engine", lambda settings: engine)
    monkeypatch.setattr(main.Client, "connect", AsyncMock(return_value=client))
    monkeypatch.setattr(main, "TicketRepository", lambda value: business)
    monkeypatch.setattr(main, "ObservationRepository", lambda value: observations)

    async def idle(*args):
        import asyncio

        await asyncio.Event().wait()

    monkeypatch.setattr(main, "deliver_notifications", idle)
    settings = config(
        intake_token="i" * 32,
        operator_token="o" * 32,
        worker_inference_enabled=worker_inference_enabled,
    )
    operator, intake = (
        {"Authorization": "Bearer " + "o" * 32},
        {"Authorization": "Bearer " + "i" * 32},
    )
    with TestClient(main.create_app(settings)) as api:
        assert api.post("/v1/observations/1", headers=intake).status_code == 401
        assert api.get("/v1/observations/1", headers=intake).status_code == 401
        assert api.post("/v1/observations/sk-private", headers=operator).status_code == 422
        assert api.post("/v1/observations/1", headers=operator).status_code == 202
        assert api.get("/v1/observations/1", headers=operator).json() == []
        assert api.get("/runtime").json()["inference_enabled"] is worker_inference_enabled
    business.accept.assert_not_called()
    assert client.start_workflow.call_args.kwargs["start_signal"] == "wake"
    assert "text" not in asdict(client.start_workflow.call_args.args[1])


def test_observation_finish_rejects_authority_even_after_unvalidated_model_copy():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    repository = ObservationRepository(engine)
    result = ObservationResult(
        state="blocked",
        reason_code="fixture",
        evidence_refs=("a" * 64,),
        versions={"model": "fixture"},
    )
    with pytest.raises(ValidationError):
        repository.finish("a" * 64, result.model_copy(update={"authorized": True}))
    engine.dispose()


def test_quality_report_uses_reviewed_labels_and_returns_no_ticket_or_employee_data():
    repo = SimpleNamespace(
        latest=lambda tenant, ticket: [
            {
                "stage": "classify",
                "result": {
                    "state": "proposed",
                    "proposal": {"kind": "correct_support_group", "destination_group_id": "2"},
                    "latency_ms": 10,
                    "estimated_cost_usd": 0.01,
                },
            }
        ]
    )
    report = evaluate_labels(
        repo,
        [
            {
                "ticket_id": "private-reference",
                "expected_kind": "correct_support_group",
                "expected_group_id": "2",
            },
            {"ticket_id": "private-reference-2", "expected_kind": "no_op"},
        ],
    )
    assert report["accuracy"] == 0.5 and report["observed_cases"] == 2
    assert "private-reference" not in json.dumps(report)
    assert report["external_writes"] == 0
