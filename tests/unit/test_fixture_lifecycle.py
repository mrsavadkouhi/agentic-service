import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.activities.fulfillment_service import FixtureFulfillmentService
from app.activities.lifecycle_service import LifecycleService
from app.activities.provisioning import ProvisioningActivities
from app.api.lifecycle import lifecycle_router
from app.connectors.secret_cipher import SecretCipher
from app.policies.provisioning import LostFixtureResponse, ProvisioningBlocked
from app.settings import Settings, WorkerRole
from app.storage.lifecycle import OwnedGrant
from app.storage.models import Base
from app.storage.provisioning import (
    FixtureMessage,
    FixtureWorld,
    FulfillmentRecord,
    ProvisioningSecret,
)
from scripts.provisioning_cases import JOBS, case


@pytest.fixture
def services():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    fulfillment = FixtureFulfillmentService(engine, SecretCipher(Fernet.generate_key()))
    yield fulfillment, LifecycleService(engine, fulfillment)
    engine.dispose()


def mutate(service, op, edit):
    with Session(service.engine) as session, session.begin():
        operation = session.get(FulfillmentRecord, op)
        row = session.get(FixtureWorld, operation.world_id)
        value = deepcopy(row.payload)
        edit(value)
        row.payload, row.revision = value, row.revision + 1


def world(service, op):
    with Session(service.engine) as session:
        record = session.get(FulfillmentRecord, op)
        return deepcopy(session.get(FixtureWorld, record.world_id).payload)


def finish(service, op):
    for _ in range(20):
        try:
            result = service.advance(op)
        except LostFixtureResponse:
            continue
        if result.state in {"completed", "blocked", "cancelled"}:
            return result
    raise AssertionError("No bounded progress")


@pytest.mark.parametrize("index", [0, 1, 2, 3, 4])
def test_approved_expiry_cleans_only_owned_scope_and_is_idempotent(services, index):
    service, lifecycle = services
    expires = datetime.now(UTC) + timedelta(days=1)
    op = service.seed(*case(index, fields={**JOBS[index], "expires_at": expires}))
    before = world(service, op)
    assert finish(service, op).state == "completed"
    assert lifecycle.reconcile(op).state == "waiting"
    assert lifecycle.reconcile(op, expires + timedelta(seconds=1)).state == "complete"
    assert lifecycle.reconcile(op, expires + timedelta(days=2)).state == "complete"
    after = world(service, op)
    if index == 0:
        assert len(after["keys"]) == 1
        assert next(iter(after["keys"].values()))["expired"] is True
        # Supporting membership is retained; other keys could depend on it.
        assert after["teams"] == before["teams"]
    elif index in {1, 2}:
        collection, ref = ("keys", "key-metadata-1") if index == 1 else ("teams", "ui-team")
        assert after[collection][ref]["metadata"] == before[collection][ref]["metadata"]
    elif index == 3:
        assert after["teams"] == before["teams"]
    else:
        assert after["users"] == before["users"]
    with Session(service.engine) as session:
        assert all(g.state == "expired" for g in session.scalars(select(OwnedGrant)))


@pytest.mark.parametrize("index", [2, 3, 4])
def test_independently_approved_permanent_grant_survives_other_ticket_expiry(services, index):
    service, lifecycle = services
    expiry = datetime.now(UTC) + timedelta(days=1)
    op1 = service.seed(
        *case(index, fields={**JOBS[index], "expires_at": expiry}), world_id="a" * 64
    )
    assert finish(service, op1).state == "completed"
    op2 = service.seed(*case(index, ticket_id="independent"), world_id="a" * 64)
    assert finish(service, op2).state == "completed"
    before = world(service, op2)
    assert lifecycle.reconcile(op1, expiry + timedelta(seconds=1)).state == "complete"
    after = world(service, op2)
    assert after["users"] == before["users"] and after["teams"] == before["teams"]
    assert lifecycle.reconcile(op2).state == "complete"


def test_reasoning_expiry_restores_legacy_baseline_and_preserves_other_models_metadata(services):
    service, lifecycle = services
    expires = datetime.now(UTC) + timedelta(days=1)
    op = service.seed(*case(2, fields={**JOBS[2], "expires_at": expires}))
    original = {
        "keep": {"nested": "value"},
        "reasoning_levels": ["medium"],
        "reasoning_models": {"model-b": ["xhigh"]},
    }
    mutate(service, op, lambda value: value["teams"]["ui-team"].update({"metadata": original}))
    assert finish(service, op).state == "completed"
    lifecycle.reconcile(op, expires + timedelta(seconds=1))
    assert world(service, op)["teams"]["ui-team"]["metadata"] == original


@pytest.mark.parametrize("external", ["value", "same_value_revision"])
def test_external_writers_stop_expiry_instead_of_removing_access(services, external):
    service, lifecycle = services
    expires = datetime.now(UTC) + timedelta(days=1)
    op = service.seed(*case(2, fields={**JOBS[2], "expires_at": expires}))
    assert finish(service, op).state == "completed"
    if external == "value":
        mutate(
            service,
            op,
            lambda w: w["teams"]["ui-team"]["metadata"]["reasoning_models"].update(
                {"model-c": ["xhigh"]}
            ),
        )
    else:
        # Cooperating fixture writers invalidate ownership even for an equal-value update.
        mutate(
            service,
            op,
            lambda w: w["owned_scope_versions"].update(
                {k: v + 1 for k, v in w["owned_scope_versions"].items()}
            ),
        )
    before = world(service, op)
    assert lifecycle.reconcile(op, expires + timedelta(seconds=1)).state == "blocked"
    assert world(service, op)["teams"] == before["teams"]
    assert lifecycle.metrics(expires + timedelta(seconds=1))["alerts"]["expiry_review_required"]


def test_temporary_inherited_team_reasoning_does_not_replace_key_approval(services):
    service, lifecycle = services
    expires = datetime.now(UTC) + timedelta(days=1)
    team_fields = {**JOBS[2], "team_id": "tool-team", "team_kind": "tool", "expires_at": expires}
    first = service.seed(*case(2, fields=team_fields), world_id="b" * 64)
    assert finish(service, first).state == "completed"
    second = service.seed(*case(1, ticket_id="key-independent"), world_id="b" * 64)
    assert finish(service, second).state == "completed"
    lifecycle.reconcile(first, expires + timedelta(seconds=1))
    assert world(service, second)["keys"]["key-metadata-1"]["metadata"]["reasoning_models"][
        "model-a"
    ] == ["high"]


def test_membership_cannot_silently_extend_temporary_team_model_grant(services):
    service, _ = services
    expiry = datetime.now(UTC) + timedelta(days=1)
    fields = {
        **JOBS[3],
        "team_id": "ui-team",
        "team_kind": "non_tool",
        "model_ids": ["model-b"],
        "expires_at": expiry,
    }
    op1 = service.seed(*case(3, fields=fields), world_id="c" * 64)
    assert finish(service, op1).state == "completed"
    op2 = service.seed(
        *case(4, fields={**JOBS[4], "requested_model_id": "model-b"}, ticket_id="membership"),
        world_id="c" * 64,
    )
    assert finish(service, op2).reason_code == "dependent_model_expiry_conflict"


def test_cancellation_stops_delivery_but_preserves_grant_and_approved_expiry(services):
    service, lifecycle = services
    expiry = datetime.now(UTC) + timedelta(days=1)
    op = service.seed(*case(2, fields={**JOBS[2], "expires_at": expiry}))
    assert service.advance(op).phase == "mutation"
    revision = lifecycle.view(op)["revision"]
    command = lifecycle.command(op, "cancel-a", "cancel", revision, "operator")
    assert lifecycle.command(op, "cancel-a", "cancel", revision, "operator") == command
    assert finish(service, op).state == "cancelled"
    assert service.projection(op)["deliveries"] == []
    assert world(service, op)["teams"]["ui-team"]["metadata"]["reasoning_models"]
    assert lifecycle.reconcile(op).state == "waiting"
    lifecycle.reconcile(op, expiry + timedelta(seconds=1))
    assert world(service, op)["teams"]["ui-team"]["metadata"] == {"keep": "fixture-unrelated"}
    with pytest.raises(ProvisioningBlocked):
        lifecycle.command(op, "resume-cancelled", "resume", revision + 1, "operator")


def test_operator_resume_revalidates_fixed_context_and_never_repeats_key_or_dm(services):
    service, lifecycle = services
    op = service.seed(*case(0))
    while service.advance(op).phase != "mutation":
        pass
    mutate(service, op, lambda w: w["bot"].update({"active": False}))
    assert finish(service, op).state == "blocked"
    mutate(service, op, lambda w: w["bot"].update({"active": True}))
    revision = lifecycle.view(op)["revision"]
    command = lifecycle.command(op, "resume-1", "resume", revision, "operator")
    initial = lifecycle.apply_resume(command["command_id"])
    assert initial.state == "running"
    assert lifecycle.apply_resume(command["command_id"]) == initial
    assert finish(service, op).state == "completed"
    assert len(world(service, op)["keys"]) == 1 and len(service.projection(op)["deliveries"]) == 2


@pytest.mark.parametrize("invalid", ["uncertain", "changed_terms", "stale_revision"])
def test_operator_cannot_override_missing_outcome_or_terms_authority(services, invalid):
    service, lifecycle = services
    normalized, catalog, auth = case(0)
    op = service.seed(normalized, catalog, auth)
    if invalid == "uncertain":
        mutate(service, op, lambda w: w["faults"].update({"mutation": "before"}))
    else:
        mutate(service, op, lambda w: w["bot"].update({"active": False}))
    assert finish(service, op).state == "blocked"
    mutate(service, op, lambda w: w["bot"].update({"active": True}))
    if invalid == "changed_terms":
        mutate(
            service,
            op,
            lambda w: w["tickets"][normalized.workflow_id()]["proposal"]["job"].update(
                {"budget_limit": "100"}
            ),
        )
    revision = lifecycle.view(op)["revision"]
    command = lifecycle.command(op, "resume-denied", "resume", revision, "operator")
    if invalid == "stale_revision":
        lifecycle.command(op, "cancel-other", "cancel", revision, "operator")
    assert lifecycle.apply_resume(command["command_id"]).state == "blocked"
    assert service.projection(op)["deliveries"] == []


def test_authenticated_operator_view_and_metrics_hide_private_data(services):
    service, lifecycle = services
    op = service.seed(*case(0))
    assert finish(service, op).state == "completed"
    payload = json.dumps({"view": lifecycle.view(op), "metrics": lifecycle.metrics()})
    assert "sk-fixture-" not in payload and "example.invalid" not in payload
    assert "ciphertext" not in payload and "approved_terms_baseline_recorded" in payload
    config = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://unit:unit@localhost/agentic",
        operator_token="o" * 32,
    )
    app = FastAPI()
    app.state.engine = service.engine
    app.include_router(lifecycle_router(config))
    with TestClient(app) as client:
        assert client.get("/v1/operations/" + op).status_code == 401
        headers = {"Authorization": "Bearer " + "o" * 32}
        assert client.get("/v1/operations/" + op, headers=headers).json() == lifecycle.view(op)
        assert client.get("/v1/operations/metrics", headers=headers).status_code == 200
        assert (
            client.post(
                "/v1/operations/" + op + "/resume",
                headers=headers,
                json={"request_id": "r", "expected_revision": 0},
            ).status_code
            == 403
        )


def test_resume_api_retries_durable_command_after_temporal_outage(services):
    service, lifecycle = services
    op = service.seed(*case(5))
    mutate(service, op, lambda w: w["bot"].update({"active": False}))
    assert finish(service, op).state == "blocked"
    config = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://unit:unit@localhost/agentic",
        operator_token="o" * 32,
        enable_fixture_execution=True,
        enable_fixture_provisioning=True,
        mirza_mode="automatic",
        fixture_vault_key_file="/tmp/unused-private-key",
    )
    app = FastAPI()
    app.state.engine = service.engine
    app.state.temporal = MagicMock(start_workflow=AsyncMock(side_effect=RuntimeError("outage")))
    app.include_router(lifecycle_router(config))
    headers = {"Authorization": "Bearer " + "o" * 32}
    body = {"request_id": "resume-api", "expected_revision": lifecycle.view(op)["revision"]}
    with TestClient(app, raise_server_exceptions=False) as client:
        assert (
            client.post("/v1/operations/" + op + "/resume", headers=headers, json=body).status_code
            == 500
        )
        app.state.temporal.start_workflow.side_effect = None
        assert (
            client.post("/v1/operations/" + op + "/resume", headers=headers, json=body).status_code
            == 202
        )
        args = app.state.temporal.start_workflow.call_args.args
        assert args[0] == "MirzaFixtureLifecycleWorkflow"
        assert lifecycle.apply_resume(args[1].recovery_command).state == "blocked"


def test_terminal_retention_removes_private_text_and_cipher_but_keeps_ownership(services):
    service, lifecycle = services
    op = service.seed(*case(0))
    assert finish(service, op).state == "completed"
    revision = lifecycle.view(op)["revision"]
    with pytest.raises(ProvisioningBlocked):
        lifecycle.retain(op, revision)
    assert (
        lifecycle.retain(op, revision, datetime.now(UTC) + timedelta(days=181))["state"]
        == "retained_tombstone"
    )
    with Session(service.engine) as session:
        assert session.scalar(select(func.count()).select_from(ProvisioningSecret)) == 0
        assert session.scalar(select(func.count()).select_from(FixtureMessage)) == 0
        assert session.scalar(select(func.count()).select_from(OwnedGrant)) == 1
        assert "event" not in session.get(FulfillmentRecord, op).payload
    assert lifecycle.reconcile(op).state == "complete"
    assert service.advance(op).state == "completed"
    assert service.projection(op)["job"] == "create_api_key"


def test_retention_never_discards_pending_key_material(services):
    service, lifecycle = services
    op = service.seed(*case(0))
    while service.advance(op).phase != "mutation":
        pass
    with pytest.raises(ProvisioningBlocked):
        lifecycle.retain(
            op, lifecycle.view(op)["revision"], datetime.now(UTC) + timedelta(days=181)
        )
    with Session(service.engine) as session:
        assert session.scalar(select(func.count()).select_from(ProvisioningSecret)) == 1


def test_summary_contains_actual_limit_and_expiry_without_key_in_staff_dm(services):
    service, _ = services
    expiry = datetime.now(UTC) + timedelta(days=1)
    op = service.seed(*case(0, fields={**JOBS[0], "expires_at": expiry}))
    assert finish(service, op).state == "completed"
    with Session(service.engine) as session:
        staff = session.scalar(select(FixtureMessage).where(FixtureMessage.kind == "staff_dm"))
        body = service.cipher.open(staff.delivery_id, staff.ciphertext)["body"]
        assert "Budget limit: 5" in body and expiry.isoformat() in body
        assert "Tool team: tool-team" in body and "sk-fixture-" not in body


async def test_lifecycle_activity_stays_disabled_for_default_and_dispatch_roles(services):
    service, _ = services
    config = Settings(
        _env_file=None, database_url="postgresql+psycopg://unit:unit@localhost/agentic"
    )
    for role in WorkerRole:
        activities = ProvisioningActivities(service.engine, config, role)
        assert (await activities.lifecycle("a" * 64)).reason_code == "fixture_connector_disabled"
        assert (await activities.resume("a" * 64)).reason_code == "fixture_connector_disabled"


def test_finite_grants_require_timer_owning_workflow_boundary(services):
    service, _ = services
    expiry = datetime.now(UTC) + timedelta(days=1)
    op = service.seed(*case(2, fields={**JOBS[2], "expires_at": expiry}))
    settings = Settings(
        _env_file=None, database_url="postgresql+psycopg://unit:unit@localhost/agentic"
    )
    activities = ProvisioningActivities(service.engine, settings, WorkerRole.MIRZA)
    activities.service = service
    result = activities.advance_checked(op, 0, expiry_owned=False)
    assert result.reason_code == "managed_expiry_workflow_required"
    assert world(service, op)["teams"]["ui-team"]["metadata"] == {"keep": "fixture-unrelated"}
    lifecycle = LifecycleService(service.engine, service)
    command = lifecycle.command(
        op, "correct-workflow", "resume", lifecycle.view(op)["revision"], "operator"
    )
    assert lifecycle.apply_resume(command["command_id"]).state == "running"
    assert activities.advance_checked(op, 0, expiry_owned=True).phase == "mutation"


def test_changed_final_status_is_visible_and_does_not_cancel_approved_expiry(services):
    service, lifecycle = services
    expiry = datetime.now(UTC) + timedelta(days=1)
    normalized, catalog, auth = case(2, fields={**JOBS[2], "expires_at": expiry})
    op = service.seed(normalized, catalog, auth)
    assert finish(service, op).state == "completed"
    mutate(
        service,
        op,
        lambda w: w["tickets"][normalized.workflow_id()]["snapshot"].update({"status": "Open"}),
    )
    result = lifecycle.reconcile(op)
    assert result.reason_code == "resolved_status_changed" and result.due_at == expiry
    assert lifecycle.view(op)["last_reconciliation"]["state"] == "blocked"
    assert lifecycle.metrics()["alerts"]["recovery_required"]
    with pytest.raises(ProvisioningBlocked):
        lifecycle.retain(
            op, lifecycle.view(op)["revision"], datetime.now(UTC) + timedelta(days=181)
        )
    lifecycle.reconcile(op, expiry + timedelta(seconds=1))
    assert world(service, op)["teams"]["ui-team"]["metadata"] == {"keep": "fixture-unrelated"}
