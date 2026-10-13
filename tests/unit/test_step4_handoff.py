import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.connectors.context import ContextReader
from app.connectors.http import ReadFailure, failed, ok
from app.connectors.mapping import DepartmentMap
from app.contracts.context import (
    ApprovalRead,
    BudgetRead,
    DeskGroup,
    DeskHistoryRead,
    DeskPerson,
    DeskTicket,
    DirectoryPerson,
    MattermostBot,
    MattermostPerson,
    MirzaInventory,
    MirzaTeam,
    MirzaUser,
    ReasoningRead,
    RelationshipRead,
)


def reader():
    desk, directory, mirza, mattermost = (AsyncMock() for _ in range(4))
    person = DeskPerson(person_id="owner", email="owner@example.invalid")
    ticket = DeskTicket(
        ticket_id="1", requester=person, group_id="helpdesk", technician=None,
        template_id="11702", category_id=None, status_id="2", status_name="Open",
        updated_at=datetime(2026, 10, 13, tzinfo=UTC), content_digest="a" * 64,
        revision_digest="b" * 64, parent_id=None, child_ids=(), relationship_verified=False,
        process_kind=None, process_verified=False, created_by_id="91",
    )
    desk.ticket.return_value = ok("servicedesk", "ticket", ticket, "fixture")
    desk.groups.return_value = ok("servicedesk", "groups", (
        DeskGroup(group_id="dwe", name="DWE", incharge=person, incharge_verified=True),
    ), "fixture")
    for name in ("templates", "statuses", "categories", "notes"):
        getattr(desk, name).return_value = ok("servicedesk", name, (), "fixture")
    desk.history.return_value = ok("servicedesk", "history", DeskHistoryRead(events=()), "fixture")
    desk.transitions.return_value = failed(
        "servicedesk", "transitions", ReadFailure("unsupported", "source_order_unverified")
    )
    desk.approvals.return_value = ok("servicedesk", "approvals", ApprovalRead(
        stages=(), configured_stage_ids=(), configured_levels=(1,), configuration_verified=False,
        terms_binding_verified=False, history_verified=False,
        observed_ticket_content_digest=ticket.content_digest,
        observed_ticket_revision_digest=ticket.revision_digest,
    ), "fixture")
    desk.relationships.return_value = ok("servicedesk", "relationships", RelationshipRead(
        parent_id=None, child_ids=(), process_association="non_lifecycle", coverage_verified=True,
        source="confirmed_n8n_creator_coverage", evidence_ref="creator-coverage",
    ), "fixture")
    directory.person.return_value = ok("directory", "person", DirectoryPerson(
        directory_id="owner", email=person.email, department="Fixture Department",
        account_enabled=True, account_expired=False,
    ), "fixture")
    budget = BudgetRead(limit="10", spend="0", reset_at=None, duration=None)
    reasoning = ReasoningRead(all_models="medium", models={})
    mirza.inventory.return_value = ok("mirza", "inventory", MirzaInventory(
        users=(MirzaUser(user_id="owner", email=person.email, team_ids=(),
                         budget=budget, reasoning=reasoning),),
        teams=(MirzaTeam(team_id="tool", alias="Fixture-Tool", kind="tool", models=("model-a",),
                         budget=budget, reasoning=reasoning),),
        keys=(), served_models=("model-a",),
    ), "fixture")
    mattermost.bot.return_value = ok("mattermost", "bot", MattermostBot(
        user_id="bot", username="servicedesk_agent", active=True, is_bot=True,
    ), "fixture")
    mattermost.person.return_value = ok("mattermost", "person", MattermostPerson(
        user_id="owner", email=person.email, active=True, is_bot=False,
    ), "fixture")
    mapping = DepartmentMap(SimpleNamespace(read_text=lambda: json.dumps({
        "policy_version": "fixture-v1", "mappings": [{
            "approved": True, "review_state": "approved", "department": "Fixture Department",
            "approved_tool_team": {"kind": "tool", "team_id": "tool"},
        }],
    })))
    return ContextReader(desk, directory, mirza, mattermost, mapping)


async def test_complete_read_observation_retains_unverified_authority_and_never_enrolls():
    source = reader()
    context = await source.read("1")
    assert context.observation_complete and context.observation_blockers == ()
    assert not context.read_complete and not context.grant_context_verified
    assert {"history_order_unverified", "approval_authority_unverified"} <= set(context.blockers)
    assert context.ticket.data.process_verified and context.mapping.state == "mapped"
    assert context.effective_reasoning.all_models == "medium"
    assert source.desk.ticket.await_count == 2 and source.desk.approvals.await_count == 2
    with pytest.raises(ValidationError):
        type(context).model_validate({**context.model_dump(), "grant_context_verified": True})
    assert "sk-" not in context.model_dump_json()


@pytest.mark.parametrize("component", ["ticket", "notes", "history", "approvals", "relationships"])
async def test_incomplete_required_source_prevents_complete_observation(component):
    source = reader()
    getattr(source.desk, component).return_value = failed(
        "servicedesk", component, ReadFailure("incomplete", "fixture_partial_source")
    )
    context = await source.read("1")
    assert not context.observation_complete
    assert component + "_incomplete" in context.observation_blockers
    assert not context.read_complete and not context.grant_context_verified


async def test_verified_absent_person_is_observed_but_cannot_be_used_for_fulfillment():
    source = reader()
    source.mattermost.person.return_value = failed(
        "mattermost", "person", ReadFailure("not_found", "resource_not_found")
    )
    context = await source.read("1")
    assert context.observation_complete
    assert "mattermost_recipient_not_found" in context.blockers
    assert not context.read_complete and not context.grant_context_verified


async def test_unknown_history_order_remains_unknown_without_manufacturing_a_sequence():
    source = reader()
    context = await source.read("1")
    assert context.history.data.ordering_verified is False
    assert context.transitions.status == "unsupported" and context.transitions.data is None
