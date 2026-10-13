import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.connectors.http import ReadFailure, ok
from app.connectors.observation import ObservationSource
from app.connectors.servicedesk import ticket_digests
from app.contracts.context import (
    BudgetRead,
    DeskGroup,
    DeskPerson,
    DirectoryPerson,
    MirzaInventory,
    MirzaKey,
    MirzaTeam,
    MirzaUser,
    ReasoningRead,
    RelationshipRead,
)
from app.contracts.tickets import Tracking
from app.settings import Settings
from app.storage.models import Base
from app.storage.observations import ObservationRepository
from app.storage.tickets import TicketInbox, TicketWorkflowRecord


def settings():
    return Settings(_env_file=None, database_url="postgresql+psycopg://unit:unit@localhost/unit")


def budget():
    return BudgetRead(limit=Decimal(10), spend=Decimal(0), reset_at=None, duration="30d")


def reasoning():
    return ReasoningRead(all_models=None, models={})


async def test_real_scoped_catalog_excludes_unrelated_people_teams_and_keys():
    inventory = MirzaInventory(
        users=tuple(
            MirzaUser(
                user_id=owner,
                email=f"{owner}@example.invalid",
                team_ids=(team,),
                budget=budget(),
                reasoning=reasoning(),
            )
            for owner, team in (("owner", "owner-tool"), ("unrelated", "unrelated-tool"))
        ),
        teams=tuple(
            MirzaTeam(
                team_id=team,
                alias=team,
                kind="tool",
                models=("model-one",),
                budget=budget(),
                reasoning=reasoning(),
            )
            for team in ("owner-tool", "unrelated-tool")
        ),
        keys=tuple(
            MirzaKey(
                key_ref=ref,
                owner_id=owner,
                team_id=team,
                expired=expired,
                expires_at=None,
                budget=budget(),
                reasoning=reasoning(),
            )
            for ref, owner, team, expired in (
                ("owner-key", "owner", "owner-tool", True),
                ("unrelated-key", "unrelated", "unrelated-tool", False),
            )
        ),
        served_models=("model-one",),
    )
    directory = DirectoryPerson(
        directory_id="owner-id",
        email="owner@example.invalid",
        department="Cloud",
        account_enabled=True,
        account_expired=False,
    )
    reader = SimpleNamespace(
        desk=None,
        mirza=SimpleNamespace(
            inventory=AsyncMock(return_value=ok("mirza", "inventory", inventory))
        ),
        directory=SimpleNamespace(
            person=AsyncMock(return_value=ok("directory", "person", directory))
        ),
        mapping=SimpleNamespace(
            resolve=lambda *args: SimpleNamespace(state="mapped", tool_team_id="owner-tool")
        ),
    )
    source = ObservationSource(SimpleNamespace(reader=reader), settings())
    packet = SimpleNamespace(
        text="Increase reasoning for owner@example.invalid, owner-key",
        ticket=SimpleNamespace(
            requester=DeskPerson(person_id="owner-id", email="owner@example.invalid"),
            content_digest="a" * 64,
        ),
        groups={"Helpdesk": "1", "Network": "2", "DWE": "3", "VOIP": "4"},
        dwe_contact="incharge",
    )
    catalog, projection, baselines = await source.mirza_scope(packet)
    assert [team.team_id for team in catalog.teams] == ["owner-tool"]
    assert [key.key_ref for key in catalog.keys] == ["owner-key"]
    assert catalog.keys[0].expired and "unrelated" not in projection
    assert json.loads(projection)["people"][0]["email"] == directory.email
    assert set(baselines) == {directory.email, "owner-tool", "owner-key"}
    reader.directory.person.assert_awaited_once_with(directory.email)


async def test_source_collection_sanitizes_private_text_and_blocks_revision_changes():
    row = {
        "id": "1",
        "subject": "Need network access",
        "description": "<p>sk-private</p>",
        "group": {"id": "1"},
        "template": {"id": "other"},
        "last_updated_time": {"value": 1000},
    }
    content, revision = ticket_digests(row)
    ticket = SimpleNamespace(
        ticket_id="1",
        group_id="1",
        template_id="other",
        status_name="Open",
        updated_at=1000,
        revision_digest=revision,
        content_digest=content,
    )
    groups = tuple(
        DeskGroup(group_id=str(index), name=name, incharge=None, incharge_verified=False)
        for index, name in enumerate(("Helpdesk", "Network", "DWE", "VOIP"), 1)
    )
    relations = RelationshipRead(
        parent_id=None,
        child_ids=(),
        process_association="non_lifecycle",
        coverage_verified=True,
        evidence_ref="verified-creator",
    )
    desk = AsyncMock()
    desk.ticket.return_value = ok("servicedesk", "ticket", ticket)
    desk.groups.return_value = ok("servicedesk", "groups", groups)
    desk.relationships.return_value = ok("servicedesk", "relationships", relations)
    desk._note_records.return_value = ()
    desk.notes.return_value = ok("servicedesk", "notes", ())
    desk.http.get.return_value = {"request": row}
    desk.validate = lambda data: data
    source = ObservationSource(SimpleNamespace(reader=SimpleNamespace(desk=desk)), settings())
    packet = await source.collect("1")
    assert "sk-private" not in packet.text and "Need network access" in packet.text
    assert packet.groups["Network"] == "2" and packet.notes == ()
    changed = dict(row, subject="Changed while reading")
    desk.http.get.return_value = {"request": changed}
    with pytest.raises(ReadFailure, match="observation_ticket_changed"):
        await source.collect("1")


async def test_verified_lifecycle_is_excluded_before_reading_text_or_notes():
    desk = AsyncMock()
    desk.ticket.return_value = ok(
        "servicedesk", "ticket", SimpleNamespace(revision_digest="a" * 64)
    )
    groups = tuple(
        DeskGroup(group_id=str(index), name=name, incharge=None, incharge_verified=False)
        for index, name in enumerate(("Helpdesk", "Network", "DWE", "VOIP"), 1)
    )
    desk.groups.return_value = ok("servicedesk", "groups", groups)
    desk.relationships.return_value = ok(
        "servicedesk",
        "relationships",
        RelationshipRead(
            parent_id="10",
            child_ids=(),
            process_association="lifecycle",
            coverage_verified=True,
            evidence_ref="verified-parent",
            process_kind="onboarding",
        ),
    )
    source = ObservationSource(SimpleNamespace(reader=SimpleNamespace(desk=desk)), settings())
    packet = await source.collect("1")
    assert packet.text == "" and packet.notes == ()
    desk.http.get.assert_not_awaited()
    desk._note_records.assert_not_awaited()


@pytest.mark.parametrize(
    "data_kind,ordered,processed,expected",
    [
        ("servicedesk", True, True, True),
        ("synthetic", True, True, False),
        ("servicedesk", False, True, False),
        ("servicedesk", True, False, False),
    ],
)
def test_only_processed_native_handoffs_preserve_original_dwe_contact(
    data_kind, ordered, processed, expected
):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        session.add(
            TicketWorkflowRecord(
                workflow_id="workflow",
                tenant_id="servicedesk",
                ticket_id="1",
                worker_role="mirza",
                correlation_id="fixture",
                state="awaiting_approval",
                tracking=Tracking(
                    fallback_enrolled=True,
                    enrollment_sequence=1,
                    original_dwe_incharge_ref="original-incharge",
                ).model_dump(mode="json"),
            )
        )
        session.flush()
        session.add(
            TicketInbox(
                event_key="a" * 64,
                workflow_id="workflow",
                external_event_id="event",
                kind="ticket",
                sequence=1,
                payload_digest="b" * 64,
                processed=processed,
                payload={"data_kind": data_kind, "snapshot": {"source_order_verified": ordered}},
            )
        )
    assert ObservationRepository(engine).tracked_handoffs() == (
        {"1": "original-incharge"} if expected else {}
    )
    engine.dispose()
