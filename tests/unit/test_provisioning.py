import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.activities.fulfillment_service import FixtureFulfillmentService
from app.activities.provisioning import ProvisioningActivities
from app.connectors.secret_cipher import SecretCipher
from app.contracts.tickets import TicketEvent
from app.policies.provisioning import LostFixtureResponse, increase_reasoning
from app.settings import Settings, WorkerRole
from app.storage.models import Base
from app.storage.observations import InferenceBudget
from app.storage.provisioning import (
    FixtureMessage,
    FixtureWorld,
    FulfillmentRecord,
    FulfillmentStep,
    ProvisioningSecret,
)
from app.storage.tickets import TicketAction, TicketInbox
from scripts.provisioning_cases import case


@pytest.fixture
def service():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    yield FixtureFulfillmentService(engine, SecretCipher(Fernet.generate_key()))
    engine.dispose()


def world(service, operation_id):
    with Session(service.engine) as session:
        operation = session.get(FulfillmentRecord, operation_id)
        return deepcopy(session.get(FixtureWorld, operation.world_id).payload)


def change_world(service, operation_id, mutate):
    with Session(service.engine) as session, session.begin():
        operation = session.get(FulfillmentRecord, operation_id)
        row = session.get(FixtureWorld, operation.world_id)
        value = deepcopy(row.payload)
        mutate(value)
        row.payload = value
        row.revision += 1


def finish(service, operation_id):
    for _ in range(20):
        try:
            receipt = service.advance(operation_id)
        except LostFixtureResponse:
            continue
        if receipt.state in {"completed", "blocked"}:
            return receipt
    raise AssertionError("Fixture made no bounded progress")


@pytest.mark.parametrize("index", range(9))
def test_all_eight_jobs_and_ticket_scoped_new_team_complete_without_external_writes(service, index):
    normalized, catalog, state = case(index)
    op = service.seed(normalized, catalog, state)
    before = world(service, op)
    result = finish(service, op)
    assert result.state == "completed", result.reason_code
    after = world(service, op)
    current = TicketEvent.model_validate(after["tickets"][normalized.workflow_id()])
    assert current.snapshot.status == "Resolved"
    assert current.snapshot.technician_ref == normalized.snapshot.technician_ref
    assert current.snapshot.template_id == normalized.snapshot.template_id
    assert current.snapshot.support_group_id == normalized.snapshot.support_group_id
    assert len(service.projection(op)["deliveries"]) == 2
    assert service.advance(op).state == "completed"
    assert len(service.projection(op)["deliveries"]) == 2
    if index in {1, 6}:
        assert (
            after["keys"]["key-metadata-1"]["models"] == before["keys"]["key-metadata-1"]["models"]
        )
        assert (
            after["keys"]["key-metadata-1"]["user_id"]
            == before["keys"]["key-metadata-1"]["user_id"]
        )
        assert after["keys"]["key-metadata-1"]["team_id"] == "tool-team"
    if index == 4:
        assert after["teams"] == before["teams"]
        owner = service.owner(after, "owner@example.invalid")
        assert "ui-team" in owner["teams"]
        assert owner["models"] == ["preserved-person-model-field"]
    if index in {0, 8}:
        created = next(
            k for k in after["keys"].values() if k["metadata"].get("operation_ref") == op
        )
        assert (
            "models" not in created
            and created["user_id"] == service.owner(after, "owner@example.invalid")["user_id"]
        )
        assert (
            after["catalog"]["department_tool_teams"] == before["catalog"]["department_tool_teams"]
        )
    with Session(service.engine) as session:
        for table in (TicketInbox, TicketAction, InferenceBudget):
            assert session.scalar(select(func.count()).select_from(table)) == 0


@pytest.mark.parametrize("phase", ["mutation", "user_dm", "staff_dm", "resolve"])
def test_lost_responses_reconcile_same_key_and_messages(service, phase):
    op = service.seed(*case(0))
    change_world(service, op, lambda value: value["faults"].update({phase: "after"}))
    assert finish(service, op).state == "completed"
    assert len(world(service, op)["keys"]) == 1
    with Session(service.engine) as session:
        assert session.scalar(select(func.count()).select_from(ProvisioningSecret)) == 1
        assert session.scalar(select(func.count()).select_from(FixtureMessage)) == 2
        assert all(s.state == "verified" for s in session.scalars(select(FulfillmentStep)))


def test_indexed_retry_returns_same_mutation_receipt_before_any_delivery(service):
    op = service.seed(*case(0))
    change_world(service, op, lambda value: value["faults"].update({"mutation": "after"}))
    assert service.advance(op, 0).phase == "owner_membership"
    with pytest.raises(LostFixtureResponse):
        service.advance(op, 1)
    receipt = service.advance(op, 1)
    assert receipt.phase == "mutation" and service.advance(op, 1) == receipt
    assert service.projection(op)["deliveries"] == []
    assert len(world(service, op)["keys"]) == 1


def test_free_text_operation_metadata_without_creation_receipt_does_not_hide_duplicates(service):
    op = service.seed(*case(0))

    def spoof(value):
        owner = service.owner(value, "owner@example.invalid")
        value["keys"]["foreign-key"] = {
            "key_ref": "foreign-key",
            "user_id": owner["user_id"],
            "team_id": "tool-team",
            "expired": True,
            "expires": "2000-01-01T00:00:00+00:00",
            "max_budget": "5",
            "spend": "0",
            "budget_duration": "30d",
            "budget_reset_at": None,
            "metadata": {"operation_ref": op},
        }

    change_world(service, op, spoof)
    result = finish(service, op)
    assert result.state == "blocked" and result.reason_code == "awaiting_clarification"
    assert len(world(service, op)["keys"]) == 1 and service.projection(op)["deliveries"] == []


def test_existing_higher_tool_team_reasoning_needs_no_key_metadata_write(service):
    op = service.seed(*case(1))
    before = world(service, op)["keys"]["key-metadata-1"]["metadata"]
    change_world(
        service,
        op,
        lambda value: value["teams"]["tool-team"]["metadata"].update(
            {
                "reasoning_models": {"*": ["xhigh"]},
            }
        ),
    )
    assert finish(service, op).state == "completed"
    assert world(service, op)["keys"]["key-metadata-1"]["metadata"] == before


def test_agent_principal_cannot_be_its_own_native_approver(service):
    op = service.seed(*case(0))
    change_world(service, op, lambda value: value.update({"service_actor_ref": "approver"}))
    result = finish(service, op)
    assert result.reason_code == "agent_cannot_approve_own_work"
    assert world(service, op)["keys"] == {}


def test_budget_update_keeps_spend_reset_and_metadata_on_lost_response(service):
    op = service.seed(*case(6))

    def setup(value):
        value["keys"]["key-metadata-1"]["spend"] = "-2"
        value["keys"]["key-metadata-1"]["budget_reset_at"] = "2026-11-01T00:00:00+00:00"
        value["faults"]["mutation"] = "after"

    change_world(service, op, setup)
    before = world(service, op)["keys"]["key-metadata-1"]
    assert finish(service, op).state == "completed"
    after = world(service, op)["keys"]["key-metadata-1"]
    assert after["max_budget"] == "15"
    assert {k: v for k, v in after.items() if k != "max_budget"} == {
        k: v for k, v in before.items() if k != "max_budget"
    }


def test_uncertain_absent_receipt_is_not_blindly_retried(service):
    op = service.seed(*case(0))
    change_world(service, op, lambda value: value["faults"].update({"mutation": "before"}))
    result = finish(service, op)
    assert result.state == "blocked" and result.reason_code == "unreconciled_fixture_outcome"
    assert world(service, op)["keys"] == {} and service.projection(op)["deliveries"] == []


def test_raw_key_is_only_inside_encrypted_owner_post_and_vault(service):
    op = service.seed(*case(0), description="Synthetic ticket sk-untrusted-secret")
    assert finish(service, op).state == "completed"
    with Session(service.engine) as session:
        secret = session.scalar(select(ProvisioningSecret))
        value = service.cipher.open(secret.secret_ref, secret.ciphertext)
        raw = value["key"]
        assert raw.encode() not in secret.ciphertext
        messages = session.scalars(select(FixtureMessage)).all()
        for message in messages:
            body = service.cipher.open(message.delivery_id, message.ciphertext)["body"]
            assert (raw in body) is (message.kind == "user_dm")
            assert "sk-untrusted-secret" not in body
            assert raw.encode() not in message.ciphertext
            if message.kind == "user_dm":
                assert (
                    message.recipient_ref
                    == world(service, op)["mattermost_people"]["owner@example.invalid"][0][
                        "user_id"
                    ]
                )
        assert raw not in json.dumps(world(service, op))
        assert raw not in json.dumps(service.projection(op))


def test_vault_binding_and_missing_generated_material_never_create_another_key(service):
    op = service.seed(*case(0))
    while service.advance(op).phase != "mutation":
        pass
    with Session(service.engine) as session, session.begin():
        secret = session.scalar(select(ProvisioningSecret))
        with pytest.raises(ValueError, match="binding"):
            service.cipher.open("wrong-binding", secret.ciphertext)
        session.delete(secret)
    result = finish(service, op)
    assert result.state == "blocked" and result.reason_code == "generated_key_material_unavailable"
    assert len(world(service, op)["keys"]) == 1 and service.projection(op)["deliveries"] == []


def test_wrong_key_plaintext_inside_correctly_bound_cipher_is_not_delivered(service):
    op = service.seed(*case(0))
    while service.advance(op).phase != "mutation":
        pass
    with Session(service.engine) as session, session.begin():
        saved = session.scalar(select(ProvisioningSecret))
        material = service.cipher.open(saved.secret_ref, saved.ciphertext)
        material["key"] = "sk-fixture-wrong-material"
        saved.ciphertext = service.cipher.seal(saved.secret_ref, material)
    assert finish(service, op).reason_code == "generated_key_binding_mismatch"
    assert len(world(service, op)["keys"]) == 1 and service.projection(op)["deliveries"] == []


def test_null_technician_completion_keeps_original_dwe_contact(service):
    op = service.seed(*case(5))
    change_world(
        service,
        op,
        lambda value: value["catalog"].update(
            {
                "dwe_incharge_ref": "new-incharge",
            }
        ),
    )
    assert finish(service, op).state == "completed"
    staff = [m for m in service.projection(op)["deliveries"] if m["kind"] == "staff_dm"]
    assert (
        staff[0]["recipient_ref"]
        == world(service, op)["mattermost_people"]["incharge@example.invalid"][0]["user_id"]
    )


@pytest.mark.parametrize(
    "case_name", ["lifecycle", "terms", "recipient", "bot", "owner_disabled", "models"]
)
def test_revalidation_blocks_changes_before_any_key_or_message(service, case_name):
    normalized, catalog, state = case(0)
    op = service.seed(normalized, catalog, state)

    def mutate(value):
        if case_name in {"lifecycle", "terms"}:
            event = value["tickets"][normalized.workflow_id()]
            if case_name == "lifecycle":
                event["snapshot"]["process"] = {
                    "association": "lifecycle",
                    "kind": "onboarding",
                    "evidence_ref": "fixture-parent",
                }
            else:
                event["proposal"]["job"]["budget_limit"] = "50"
        elif case_name == "recipient":
            value["mattermost_people"]["owner@example.invalid"][0]["user_id"] = "another-account"
        elif case_name == "bot":
            value["bot"]["is_bot"] = False
        elif case_name == "owner_disabled":
            value["directory_flags"]["owner@example.invalid"]["enabled"] = False
        else:
            value["teams"]["tool-team"]["models"].append("model-b")

    change_world(service, op, mutate)
    assert finish(service, op).state == "blocked"
    assert world(service, op)["keys"] == {} and service.projection(op)["deliveries"] == []


def test_completion_follows_current_technician_after_an_earlier_staff_dm(service):
    normalized, catalog, state = case(5)
    op = service.seed(normalized, catalog, state)
    while service.advance(op).phase != "staff_dm":
        pass

    def assign(value):
        current = value["tickets"][normalized.workflow_id()]
        current["snapshot"]["technician_ref"] = "technician"
        current["snapshot"]["source_sequence"] += 1

    change_world(service, op, assign)
    assert finish(service, op).state == "completed"
    messages = service.projection(op)["deliveries"]
    assert len(messages) == 3
    assert len([m for m in messages if m["kind"] == "user_dm"]) == 1
    assert any(
        m["recipient_ref"]
        == world(service, op)["mattermost_people"]["technician@example.invalid"][0]["user_id"]
        for m in messages
    )


def test_personal_budget_is_not_spent_or_increased_to_make_tool_key_work(service):
    op = service.seed(*case(0))

    def exhaust_person(value):
        owner = service.owner(value, "owner@example.invalid")
        owner["max_budget"], owner["spend"] = "1", "999"

    change_world(service, op, exhaust_person)
    assert finish(service, op).state == "completed"
    owner = service.owner(world(service, op), "owner@example.invalid")
    assert owner["max_budget"] == "1" and owner["spend"] == "999"


def test_expiring_non_key_grant_is_blocked_until_managed_expiry_exists(service):
    fields = {
        **case(2)[0].proposal.job.model_dump(),
        "expires_at": datetime.now(UTC) + timedelta(days=1),
    }
    op = service.seed(*case(2, fields=fields))
    assert finish(service, op).reason_code == "managed_expiry_unavailable"
    assert world(service, op)["teams"]["ui-team"]["metadata"] == {"keep": "fixture-unrelated"}


def test_reasoning_merge_folds_legacy_without_lowering_or_losing_unrelated_metadata():
    metadata = {
        "keep": {"nested": "value"},
        "reasoning_levels": ["high"],
        "reasoning_models": {"model-b": ["xhigh"]},
    }
    changed = increase_reasoning(metadata, ("model-a",), "xhigh")
    assert changed["keep"] == metadata["keep"] and changed["reasoning_models"]["*"] == ["high"]
    assert changed["reasoning_models"]["model-b"] == ["xhigh"]
    assert changed["reasoning_models"]["model-a"] == ["xhigh"]
    assert "reasoning_levels" not in changed and "reasoning_levels" in metadata


def test_native_events_and_real_emails_cannot_enter_fixture_seeding(service):
    normalized, catalog, state = case(0)
    with pytest.raises(ValueError, match="generated"):
        service.seed(normalized.model_copy(update={"data_kind": "servicedesk"}), catalog, state)
    bad = catalog.model_copy(
        update={"people": (catalog.people[0].model_copy(update={"email": "real@example.com"}),)}
    )
    with pytest.raises(ValueError, match="fixture identities"):
        service.seed(normalized, bad, state)


async def test_mode_and_master_read_credential_cannot_activate_provisioning(service):
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://unit:unit@localhost/agentic",
        mirza_mode="automatic",
        mirza_read_token="sk-admin-credential",
    )
    activity = ProvisioningActivities(service.engine, settings, WorkerRole.MIRZA)
    assert (await activity.advance("a" * 64)).reason_code == "fixture_connector_disabled"
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            database_url="postgresql+psycopg://unit:unit@remote/agentic",
            enable_fixture_provisioning=True,
            enable_fixture_execution=True,
            mirza_mode="automatic",
            fixture_vault_key_file="/tmp/unused",
        )
