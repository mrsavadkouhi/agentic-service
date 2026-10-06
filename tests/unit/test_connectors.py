import json
import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.connectors.context import ContextReader
from app.connectors.directory import Directory
from app.connectors.factory import Connectors
from app.connectors.http import ReadFailure, ReadOnlyHTTP, failed, ok
from app.connectors.mapping import DepartmentMap
from app.connectors.mattermost import Mattermost
from app.connectors.mirza import Mirza, effective_reasoning, reasoning
from app.connectors.servicedesk import ServiceDesk
from app.contracts.context import (
    ApprovalRead,
    DeskHistoryEvent,
    DeskHistoryRead,
    DeskNote,
    DirectoryPerson,
    ReasoningRead,
    RelationshipRead,
)
from app.settings import Settings


def transport(handler, paths, **kwargs):
    return ReadOnlyHTTP(
        "https://fixture.invalid",
        SecretStr("unit-read-token"),
        paths,
        transport=httpx.MockTransport(handler),
        sleep=AsyncMock(),
        **kwargs,
    )


def desk_page(key, rows, more=False):
    return {
        "response_status": {"status": "success", "status_code": 2000},
        key: rows,
        "list_info": {"has_more_rows": more},
    }


def desk_ticket(description="ticket text sk-sensitive-ticket-value", updated=1000):
    return {
        "response_status": {"status": "success", "status_code": 2000},
        "request": {
            "id": "1",
            "requester": {"id": "requester", "email_id": "owner@example.invalid"},
            "group": {"id": "helpdesk"},
            "template": {"id": "template"},
            "technician": None,
            "status": {"id": "open", "name": "Open"},
            "description": description,
            "subject": "a request",
            "last_updated_time": {"value": updated},
        },
    }


async def test_transport_get_only_does_not_follow_redirect_or_log_secret_url(caplog):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://other.invalid/collect"})

    http = transport(handle, Mirza.PATHS)
    caplog.set_level(logging.INFO)
    with pytest.raises(ReadFailure):
        await http.get("/key/info", {"key": "sk-secret-in-query"})
    with pytest.raises(ReadFailure):
        await http.get("/key/generate")
    assert len(requests) == 1 and requests[0].method == "GET"
    assert "sk-secret-in-query" not in caplog.text
    assert not hasattr(http, "post")
    await http.close()


@pytest.mark.parametrize("status", [401, 403, 404, 500])
async def test_non_success_is_not_an_empty_result(status):
    http = transport(
        lambda r: httpx.Response(status, json={"error": "sk-upstream-secret"}), Mirza.PATHS
    )
    result = await Mirza(http).inventory()
    assert result.status != "ok" and result.data is None
    assert "sk-upstream-secret" not in result.model_dump_json()
    await http.close()


async def test_bounded_retries_and_response_size():
    http = transport(lambda r: httpx.Response(503), Mirza.PATHS)
    result = await Mirza(http).inventory()
    assert result.status == "unavailable" and http.sleep.await_count == 2
    await http.close()
    http = transport(lambda r: httpx.Response(200, content=b"x" * 101), Mirza.PATHS, max_bytes=100)
    with pytest.raises(ReadFailure) as error:
        await http.get("/team/list")
    assert error.value.status == "incomplete"
    await http.close()


@pytest.mark.parametrize(
    "url",
    [
        "https://user:secret@fixture.invalid",
        "https://fixture.invalid?key=secret",
        "https://fixture.invalid/other",
        "http://remote.invalid",
    ],
)
def test_fixed_origin_configuration(url):
    with pytest.raises(ValueError):
        ReadOnlyHTTP(url, SecretStr("secret"), Mirza.PATHS)


async def test_servicedesk_complete_pagination_and_assignment_metadata():
    starts = []

    def handle(request):
        info = json.loads(request.url.params["input_data"])["list_info"]
        starts.append(info["start_index"])
        rows = [{"id": "1"}] if info["start_index"] == 1 else [{"id": "2"}]
        return httpx.Response(200, json=desk_page("requests", rows, len(starts) == 1))

    http = transport(handle, ServiceDesk.PATHS, auth_header="authtoken")
    result = await ServiceDesk(http, page_size=1).list_requests()
    assert result.data == ("1", "2") and starts == [1, 2]
    assert result.evidence.complete
    await http.close()


@pytest.mark.parametrize(
    "shape,expected",
    [
        (desk_page("requests", [{"id": "1"}], True), "unstable"),
        (
            {"requests": [], "response_status": {"status": "success", "status_code": 2000}},
            "incomplete",
        ),
        (
            {"requests": [], "response_status": {"status": "failed", "status_code": 4000}},
            "unavailable",
        ),
        (desk_page("requests", [], True), "incomplete"),
    ],
)
async def test_servicedesk_bad_pages_fail_closed(shape, expected):
    http = transport(lambda r: httpx.Response(200, json=shape), ServiceDesk.PATHS)
    result = await ServiceDesk(http, page_size=1).list_requests()
    assert result.status == expected and result.data is None
    await http.close()


async def test_ticket_content_and_notes_are_digest_only_and_process_not_inferred():
    def handle(request):
        if request.url.path == "/api/v3/requests/1":
            data = desk_ticket()
        elif request.url.path.endswith("/notes"):
            data = desk_page("notes", [{"id": "11"}])
        else:
            data = {
                "response_status": {"status": "success", "status_code": 2000},
                "note": {
                    "id": "11",
                    "request": {"id": "1"},
                    "added_by": {"id": "technician"},
                    "added_time": {"value": 1000},
                    "description": "clarification sk-sensitive-note-value",
                    "last_updated_by": {"id": "other"},
                    "last_updated_time": {"value": 2000},
                },
            }
        return httpx.Response(200, json=data)

    http = transport(handle, ServiceDesk.PATHS)
    desk = ServiceDesk(http)
    ticket, notes = await desk.ticket("1"), await desk.notes("1")
    assert not ticket.data.process_verified and not ticket.data.relationship_verified
    assert notes.data[0].author_id == "technician" and notes.data[0].updated_by_id == "other"
    assert "sk-sensitive" not in ticket.model_dump_json() + notes.model_dump_json()
    root = await ServiceDesk(http, lifecycle_template_ids={"template": "offboarding"}).ticket("1")
    assert root.data.process_verified and root.data.process_kind == "offboarding"
    await http.close()


async def test_history_and_approval_display_data_never_become_authorization():
    def handle(request):
        key = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(
            200, json=desk_page(key, [{"id": "1", "description": "Open approved"}])
        )

    http = transport(handle, ServiceDesk.PATHS)
    desk = ServiceDesk(http)
    assert (await desk.transitions("1")).status == "invalid"
    assert (await desk.approvals("1")).status == "invalid"
    assert (await desk.relationships("1")).status == "unsupported"
    await http.close()


async def test_servicedesk_structured_terms_change_content_and_revision_digests():
    source = desk_ticket()
    source["request"]["udf_fields"] = {"udf_char1": "sk-sensitive-structured-value"}
    http = transport(lambda r: httpx.Response(200, json=source), ServiceDesk.PATHS)
    desk = ServiceDesk(http)
    before = await desk.ticket("1")
    source["request"]["udf_fields"]["udf_char1"] = "changed term"
    after = await desk.ticket("1")
    assert before.data.content_digest != after.data.content_digest
    assert before.data.revision_digest != after.data.revision_digest
    assert "sk-sensitive" not in before.model_dump_json()
    await http.close()


@pytest.mark.parametrize("role_count,verified", [(0, False), (1, True), (2, False)])
async def test_servicedesk_dynamic_group_incharge_uses_native_role(role_count, verified):
    def handle(request):
        if request.url.path.endswith("/support_groups"):
            data = desk_page("support_groups", [{"id": "2101", "name": "DWE"}])
        else:
            data = {
                "response_status": {"status": "success", "status_code": 2000},
                "support_group": {
                    "id": "2101",
                    "role_associations": [
                        {
                            "group_role": {"display_name": "$GROUP_INCHARGE$"},
                            "user": {"id": "contact", "email_id": "contact@example.invalid"},
                        }
                    ]
                    * role_count,
                },
            }
        return httpx.Response(200, json=data)

    http = transport(handle, ServiceDesk.PATHS)
    result = await ServiceDesk(http).groups()
    assert result.status == "ok" and result.data[0].incharge_verified is verified
    if not verified:
        assert result.data[0].incharge is None
    await http.close()


async def test_servicedesk_history_retains_actor_and_status_without_inventing_sequence():
    history = {
        "id": "101",
        "request": {"id": "1"},
        "by": {"id": "contact"},
        "time": {"value": 3000},
        "operation": "UPDATE",
        "diff": [
            {
                "field": {"name": "status"},
                "previous_value": {"id": "hold"},
                "current_value": {"id": "open"},
            },
            {
                "field": {"name": "description"},
                "previous_value": "sk-sensitive-value",
                "current_value": "sk-sensitive-new-value",
            },
        ],
    }
    http = transport(
        lambda r: httpx.Response(200, json=desk_page("history", [history])), ServiceDesk.PATHS
    )
    desk = ServiceDesk(http)
    result = await desk.history("1")
    assert result.status == "ok" and result.data.events[0].actor_id == "contact"
    assert result.data.events[0].status_changes[0].after_status_id == "open"
    assert not result.data.ordering_verified and "sk-sensitive" not in result.model_dump_json()
    assert (await desk.transitions("1", result)).status == "unsupported"
    await http.close()


@pytest.mark.parametrize("deleted,configuration_verified", [(False, True), (True, False)])
async def test_servicedesk_native_approvals_preserve_deletion_and_do_not_bind_terms(
    deleted, configuration_verified
):
    updates = {}

    def handle(request):
        path = request.url.path
        if path == "/api/v3/requests/1":
            data = desk_ticket()
            data["request"]["template"]["id"] = "10"
            data["request"].update(updates)
        elif path == "/api/v3/request_templates/10":
            data = {
                "response_status": {"status": "success", "status_code": 2000},
                "request_template": {"id": "10", "approval_levels": [{"level": "1"}]},
            }
        elif path.endswith("/approvals"):
            data = desk_page(
                "approvals",
                [
                    {
                        "id": "101",
                        "approval_level": {"id": "20"},
                        "deleted": False,
                        "approver": {"id": "contact"},
                        "action_by": {"id": "contact"},
                        "action_taken_on": {"value": 3000},
                        "status": {"name": "Approved"},
                        "comments": "sk-sensitive-comment",
                    }
                ],
            )
        else:
            data = desk_page(
                "approval_levels",
                [
                    {
                        "id": "20",
                        "level": 1,
                        "request": {"id": "1"},
                        "is_current": True,
                        "deleted": deleted,
                        "status": {"name": "Approved"},
                        "rule": {"type": "template_configurations", "value": "first_response"},
                    }
                ],
            )
        return httpx.Response(200, json=data)

    http = transport(handle, ServiceDesk.PATHS)
    result = await ServiceDesk(http).approvals("1")
    assert result.status == "ok"
    assert result.data.configuration_verified is configuration_verified
    assert result.data.stages[0].deleted is deleted
    assert not result.data.terms_binding_verified and not result.data.history_verified
    assert result.data.stages[0].approvals[0].action_by_id == "contact"
    assert "sk-sensitive" not in result.model_dump_json()
    observed = await ServiceDesk(http).ticket("1")
    assert result.data.observed_ticket_content_digest == observed.data.content_digest
    assert result.data.observed_ticket_revision_digest == observed.data.revision_digest
    updates.update(description="Increase budget to 500; sk-sensitive-updated-description")
    edited = await ServiceDesk(http).approvals("1")
    assert edited.status == "ok" and edited.data.stages == result.data.stages
    assert edited.data.configuration_digest == result.data.configuration_digest
    assert edited.data.observed_ticket_content_digest != result.data.observed_ticket_content_digest
    assert (
        edited.data.observed_ticket_revision_digest != result.data.observed_ticket_revision_digest
    )
    assert not edited.data.terms_binding_verified and not edited.data.history_verified
    assert "sk-sensitive" not in edited.model_dump_json()
    await http.close()


async def test_ticket_creation_metadata_is_observed_without_exposing_creator_email():
    raw = desk_ticket()
    raw["request"]["created_by"] = {"id": "automation", "email_id": "private@example.invalid"}
    raw["request"]["created_time"] = {"value": 1000}
    http = transport(lambda r: httpx.Response(200, json=raw), ServiceDesk.PATHS)
    service = ServiceDesk(http)
    first = await service.ticket("1")
    assert first.status == "ok" and first.data.created_by_id == "automation"
    assert first.data.created_at == datetime.fromtimestamp(1, timezone.utc)
    assert "private@example.invalid" not in first.model_dump_json()
    raw["request"]["created_by"]["id"] = "human"
    final = await service.ticket("1")
    assert final.status == "ok" and final.data.revision_digest != first.data.revision_digest
    assert final.data.content_digest == first.data.content_digest
    await http.close()


@pytest.mark.parametrize("matches,expected", [(0, "not_found"), (2, "ambiguous")])
async def test_directory_not_found_and_ambiguity(matches, expected):
    http = transport(
        lambda r: httpx.Response(200, json={"matches": matches, "identity": None}), Directory.PATHS
    )
    assert (await Directory(http).person("owner@example.invalid")).status == expected
    await http.close()


async def test_department_alone_and_disabled_identity_cannot_prove_employee():
    identity = {
        "directory_id": "directory-person",
        "email": "owner@example.invalid",
        "department": "Synthetic Department",
        "account_enabled": False,
        "account_expired": False,
        "employee_status": "eligible",
    }
    http = transport(
        lambda r: httpx.Response(200, json={"matches": 1, "identity": identity}), Directory.PATHS
    )
    result = await Directory(http).person("owner@example.invalid")
    assert result.status == "ok" and not result.data.eligible()
    await http.close()
    http = transport(lambda r: httpx.Response(404), Directory.PATHS)
    assert (await Directory(http).person("owner@example.invalid")).status == "unsupported"
    await http.close()


@pytest.mark.parametrize(
    "enabled,expired,legacy_status,eligible",
    [
        (True, False, None, True),
        (True, False, "ineligible", True),
        (False, False, "eligible", False),
        (True, True, "eligible", False),
    ],
)
async def test_directory_eligibility_uses_unique_enabled_unexpired_rule(
    enabled, expired, legacy_status, eligible
):
    identity = {
        "directory_id": "directory-person",
        "email": "owner@example.invalid",
        "department": None,
        "account_enabled": enabled,
        "account_expired": expired,
    }
    if legacy_status is not None:
        identity["employee_status"] = legacy_status
    http = transport(
        lambda r: httpx.Response(200, json={"matches": 1, "identity": identity}), Directory.PATHS
    )
    result = await Directory(http).person("owner@example.invalid")
    assert result.status == "ok" and result.data.eligible() is eligible
    assert result.data.employee_status == ("eligible" if eligible else "ineligible")
    await http.close()


@pytest.mark.parametrize("field", ["account_enabled", "account_expired"])
@pytest.mark.parametrize("invalid", ["true", "false", 0, 1, None])
async def test_directory_account_flags_require_native_booleans(field, invalid):
    identity = {
        "directory_id": "directory-person",
        "email": "owner@example.invalid",
        "department": None,
        "account_enabled": True,
        "account_expired": False,
    }
    identity[field] = invalid
    http = transport(
        lambda r: httpx.Response(200, json={"matches": 1, "identity": identity}), Directory.PATHS
    )
    result = await Directory(http).person("owner@example.invalid")
    assert result.status == "invalid" and result.data is None
    await http.close()


def mirza_handler(request):
    money = {
        "spend": 2,
        "max_budget": 10,
        "budget_reset_at": "2026-10-10T00:00:00Z",
        "budget_duration": "30d",
    }
    if request.url.path == "/user/list":
        data = {
            "users": [
                {
                    "user_id": "owner",
                    "user_email": "owner@example.invalid",
                    "teams": ["tool", "ui"],
                    "metadata": {"reasoning_models": {"*": ["xhigh"]}},
                    **money,
                }
            ],
            "total_pages": 1,
            "total": 1,
            "page": 1,
        }
    elif request.url.path == "/key/list":
        data = {
            "keys": [
                {
                    "token": "sk-hidden-virtual-key",
                    "api_key": "sk-hidden-raw-key",
                    "user_id": "owner",
                    "team_id": "tool",
                    "expires": "2020-01-01T00:00:00Z",
                    "metadata": {"reasoning_models": {"model-a": ["high"]}},
                    **money,
                }
            ],
            "total_pages": 1,
            "total_count": 1,
            "current_page": 1,
        }
    elif request.url.path == "/team/list":
        data = [
            {
                "team_id": "tool",
                "team_alias": "Synthetic-Tool",
                "models": ["model-a"],
                "metadata": {},
                **money,
            },
            {
                "team_id": "ui",
                "team_alias": "Synthetic UI",
                "models": ["model-a"],
                "metadata": {},
                **money,
            },
        ]
    else:
        data = {"data": [{"id": "model-a"}]}
    return httpx.Response(200, json=data)


async def test_mirza_sanitizes_virtual_keys_budget_rows_and_expired_keys():
    http = transport(mirza_handler, Mirza.PATHS)
    result = await Mirza(http).inventory()
    assert result.status == "ok", result.reason_code
    assert result.data.keys[0].expired
    assert result.data.keys[0].team_id == "tool"
    assert result.data.teams[0].kind == "tool" and result.data.teams[1].kind == "non_tool"
    assert result.data.keys[0].budget.spend == 2
    assert "sk-hidden" not in result.model_dump_json()
    await http.close()


async def test_mirza_incomplete_pagination_cannot_mean_no_existing_keys():
    def handle(request):
        response = mirza_handler(request)
        if request.url.path == "/key/list":
            data = response.json()
            data.pop("total_pages")
            return httpx.Response(200, json=data)
        return response

    http = transport(handle, Mirza.PATHS)
    result = await Mirza(http).inventory()
    assert result.status == "incomplete" and result.data is None
    await http.close()


async def test_mirza_preserves_signed_spend_and_nonstandard_owner_ids():
    def handle(request):
        response = mirza_handler(request)
        data = response.json()
        if request.url.path == "/key/list":
            data["keys"][0].update(spend=-0.5, user_id="legacy owner + identifier")
        return httpx.Response(200, json=data)

    http = transport(handle, Mirza.PATHS)
    result = await Mirza(http).inventory()
    assert result.status == "ok"
    assert str(result.data.keys[0].budget.spend) == "-0.5"
    assert result.data.keys[0].owner_id == "legacy owner + identifier"
    assert "sk-hidden" not in result.model_dump_json()
    await http.close()


async def test_mirza_count_mismatch_cannot_be_a_complete_catalog():
    def handle(request):
        response = mirza_handler(request)
        data = response.json()
        if request.url.path == "/key/list":
            data["total_count"] = 2
        return httpx.Response(200, json=data)

    http = transport(handle, Mirza.PATHS)
    result = await Mirza(http).inventory()
    assert result.status == "incomplete" and result.data is None
    await http.close()


async def test_mirza_unknown_key_owner_is_preserved_without_resolving_identity():
    def handle(request):
        response = mirza_handler(request)
        data = response.json()
        if request.url.path == "/key/list":
            data["keys"][0]["user_id"] = None
        return httpx.Response(200, json=data)

    http = transport(handle, Mirza.PATHS)
    result = await Mirza(http).inventory()
    assert result.status == "ok" and result.data.keys[0].owner_id is None
    await http.close()


def test_reasoning_ceiling_uses_legacy_wildcard_and_model_grants():
    row = reasoning(
        {
            "metadata": {
                "reasoning_levels": ["high"],
                "reasoning_models": {"model-a": ["extra-high"]},
            }
        }
    )
    result = effective_reasoning([row, ReasoningRead(all_models=None, models={})])
    assert result.all_models == "high" and result.models == {"model-a": "xhigh"}
    with pytest.raises(ReadFailure):
        reasoning({"metadata": {"reasoning_models": {"*": ["invented"]}}})


@pytest.mark.parametrize("deleted,bot", [(1, False), (0, True)])
async def test_mattermost_requires_active_exact_human_account(deleted, bot):
    http = transport(
        lambda r: httpx.Response(
            200,
            json={
                "id": "mm-person",
                "email": "owner@example.invalid",
                "delete_at": deleted,
                "is_bot": bot,
            },
        ),
        Mattermost.PATHS,
    )
    assert (await Mattermost(http).person("owner@example.invalid")).status == "invalid"
    await http.close()


async def test_mattermost_omitted_false_bot_field_is_a_human():
    http = transport(
        lambda r: httpx.Response(
            200, json={"id": "mm-person", "email": "owner@example.invalid", "delete_at": 0}
        ),
        Mattermost.PATHS,
    )
    result = await Mattermost(http).person("owner@example.invalid")
    assert result.status == "ok" and result.data.active and not result.data.is_bot
    await http.close()


@pytest.mark.parametrize("case", ["valid", "wrong_username", "human", "missing_bot_flag",
                                  "deleted", "unknown_active", "bool_active"])
async def test_mattermost_bot_identity_requires_expected_active_bot(case):
    row = {"id": "mm-bot", "username": "servicedesk_agent", "delete_at": 0, "is_bot": True}
    if case == "wrong_username":
        row["username"] = "different_bot"
    elif case == "human":
        row["is_bot"] = False
    elif case == "missing_bot_flag":
        row.pop("is_bot")
    elif case == "deleted":
        row["delete_at"] = 1
    elif case == "unknown_active":
        row.pop("delete_at")
    elif case == "bool_active":
        row["delete_at"] = False
    row["email"] = "private-bot@example.invalid"
    http = transport(lambda r: httpx.Response(200, json=row), Mattermost.PATHS)
    result = await Mattermost(http).bot()
    assert result.status == ("ok" if case == "valid" else "invalid")
    assert "private-bot@example.invalid" not in result.model_dump_json()
    await http.close()


@pytest.mark.parametrize("status,expected", [(404, "not_found"), (405, "unsupported"),
                                          (401, "unavailable"), (403, "unavailable")])
async def test_mattermost_lookup_absence_is_distinct_from_unsupported_or_denied(status, expected):
    http = transport(
        lambda r: httpx.Response(status, json={"message": "private person sk-secret"}),
        Mattermost.PATHS,
    )
    result = await Mattermost(http).person("owner@example.invalid")
    assert result.status == expected and result.data is None
    assert "sk-secret" not in result.model_dump_json()
    await http.close()


async def test_servicedesk_named_catalogs_require_complete_pagination():
    def handle(request):
        resource = request.url.path.rsplit("/", 1)[1]
        return httpx.Response(200, json=desk_page(resource, [{"id": "1", "name": "Open"}]))

    http = transport(handle, ServiceDesk.PATHS)
    desk = ServiceDesk(http)
    assert (await desk.statuses()).data[0].item_id == "1"
    assert (await desk.categories()).data[0].name == "Open"
    assert (await desk.named_catalog("technicians")).status == "invalid"
    await http.close()


async def test_context_detects_changed_ticket_and_does_not_mix_key_with_ui_reasoning(tmp_path):
    http = transport(mirza_handler, Mirza.PATHS)
    mirza = Mirza(http)
    inventory = await mirza.inventory()
    person = DirectoryPerson(
        directory_id="directory-person",
        email="owner@example.invalid",
        department="Synthetic Department",
        account_enabled=True,
        account_expired=False,
        employee_status="eligible",
    )
    desk_http = transport(lambda r: httpx.Response(200, json=desk_ticket()), ServiceDesk.PATHS)
    ticket = await ServiceDesk(desk_http).ticket("1")
    mapping_file = tmp_path / "map.json"
    mapping_file.write_text(
        json.dumps(
            {
                "policy_version": "fixture-v1",
                "mappings": [
                    {
                        "approved": True,
                        "review_state": "approved",
                        "department": "Synthetic Department",
                        "approved_tool_team": {"kind": "tool", "team_id": "tool"},
                    }
                ],
            }
        )
    )
    desk = AsyncMock()
    desk.ticket.side_effect = [ticket, ticket]
    for method in (
        "groups",
        "templates",
        "statuses",
        "categories",
        "notes",
        "history",
        "transitions",
        "approvals",
        "relationships",
    ):
        getattr(desk, method).return_value = failed(
            "servicedesk", method, ReadFailure("unsupported", "contract_unknown")
        )
    directory = AsyncMock()
    directory.person.return_value = ok("directory", "person", person)
    mm = AsyncMock()
    mm.bot.return_value = failed("mattermost", "bot", ReadFailure())
    mm.person.return_value = failed("mattermost", "recipient", ReadFailure())
    map_before = mapping_file.read_bytes()
    mapping = DepartmentMap(mapping_file)
    assert mapping.resolve(person, inventory).tool_team_id == "tool"
    assert mapping.resolve(person, inventory, ticket_team_id="ui").state == "clarification"
    assert (
        mapping.resolve(
            person, inventory, ticket_team_id="absent", note_mapping_verified=True
        ).state
        == "clarification"
    )
    scoped = mapping.resolve(person, inventory, ticket_team_id="tool", note_mapping_verified=True)
    assert scoped.ticket_scoped and not mapping.resolve(person, inventory).ticket_scoped
    assert (
        mapping.resolve(person, failed("mirza", "inventory", ReadFailure())).state == "unavailable"
    )
    assert mapping_file.read_bytes() == map_before
    reader = ContextReader(desk, directory, mirza, mm, mapping)
    context = await reader.read("1", key_ref=inventory.data.keys[0].key_ref)
    assert context.effective_reasoning.all_models == "medium"
    assert context.effective_reasoning.models["model-a"] == "high"
    assert not context.grant_context_verified and not context.read_complete
    assert "sk-hidden" not in context.model_dump_json()
    desk.relationships.return_value = ok(
        "servicedesk",
        "relationships",
        RelationshipRead(
            parent_id="100",
            parent_ids=("100",),
            child_ids=(),
            process_association="lifecycle",
            process_kind="onboarding",
            source="onboarding_udf_index",
            evidence_ref="fixture-parent-evidence",
        ),
        "fixture",
    )
    desk.ticket.side_effect = [ticket, ticket]
    excluded = await reader.read("1")
    assert excluded.ticket.data.process_kind == "onboarding"
    assert excluded.ticket.data.process_verified and excluded.ticket.data.parent_id == "100"
    assert excluded.ticket.evidence.digest != ticket.evidence.digest
    assert "lifecycle_process_excluded" in excluded.blockers
    assert "relationship_coverage_unverified" in excluded.blockers
    assert not excluded.read_complete and not excluded.grant_context_verified
    changed = ticket.model_copy(
        update={"data": ticket.data.model_copy(update={"revision_digest": "f" * 64})}
    )
    desk.ticket.side_effect = [ticket, changed]
    context = await reader.read("1")
    assert context.ticket.status == "unstable"
    assert context.effective_reasoning.all_models == "xhigh"
    conflicting_owner = inventory.data.users[0].model_copy(
        update={"user_id": person.email, "email": "different@example.invalid"}
    )
    conflicting_inventory = inventory.model_copy(
        update={"data": inventory.data.model_copy(update={"users": (conflicting_owner,)})}
    )
    conflicting_mirza = AsyncMock()
    conflicting_mirza.inventory.return_value = conflicting_inventory
    desk.ticket.side_effect = [ticket, ticket]
    reader.mirza = conflicting_mirza
    context = await reader.read("1")
    assert "mirza_owner_missing_or_ambiguous" in context.blockers
    assert context.effective_reasoning is None
    await http.close()
    await desk_http.close()


@pytest.mark.parametrize("component", ["notes", "history", "approvals", "relationships"])
async def test_context_rechecks_independent_records_even_when_ticket_revision_is_unchanged(
    component,
):
    now = datetime(2026, 10, 6, tzinfo=timezone.utc)
    note = DeskNote(note_id="10", author_id="staff", updated_by_id=None, added_at=now,
                    updated_at=None, content_digest="a" * 64)
    history = DeskHistoryRead(events=())
    approval = ApprovalRead(stages=(), configured_stage_ids=(), configured_levels=(1,),
                            configuration_verified=False, terms_binding_verified=False,
                            history_verified=False, configuration_digest="a" * 64)
    relationship = RelationshipRead(parent_id="20", parent_ids=("20",), child_ids=(),
                                    process_association="lifecycle", process_kind="onboarding",
                                    source="onboarding_udf_index", evidence_ref="before")
    observations = {
        "notes": ((note,), (note.model_copy(update={"content_digest": "b" * 64}),)),
        "history": (history, DeskHistoryRead(events=(DeskHistoryEvent(
            event_id="11", actor_id="staff", occurred_at=now, operation="UPDATE",
            fields=("status",), status_changes=(), content_digest="b" * 64,
        ),))),
        "approvals": (approval, approval.model_copy(update={"configuration_digest": "b" * 64})),
        "relationships": (relationship, relationship.model_copy(update={"evidence_ref": "after"})),
    }
    connectors = Connectors(
        Settings(_env_file=None, database_url="postgresql+psycopg://unit:unit@localhost/unit")
    )
    desk_http = transport(lambda r: httpx.Response(200, json=desk_ticket()), ServiceDesk.PATHS)
    ticket = await ServiceDesk(desk_http).ticket("1")
    desk = AsyncMock()
    desk.ticket.return_value = ticket
    for name in ("groups", "templates", "statuses", "categories", "notes", "history",
                 "transitions", "approvals", "relationships"):
        getattr(desk, name).return_value = failed(
            "servicedesk", name, ReadFailure("unsupported", "contract_unknown")
        )
    before, after = observations[component]
    getattr(desk, component).side_effect = [
        ok("servicedesk", component, value, "fixture") for value in (before, after)
    ]
    connectors.reader.desk = desk
    context = await connectors.reader.read("1")
    result = getattr(context, component)
    assert context.ticket.status == "ok" and desk.ticket.await_count == 2
    assert result.status == "unstable" and result.data is None
    assert result.reason_code == component + "_changed_during_read"
    assert component + "_unstable" in context.blockers
    assert not context.read_complete and not context.grant_context_verified
    if component == "history":
        assert context.transitions.status == "unstable"
    await desk_http.close()
    await connectors.close()


async def test_unconfigured_connectors_return_traceable_unavailable_context():
    connectors = Connectors(
        Settings(_env_file=None, database_url="postgresql+psycopg://unit:unit@localhost/unit")
    )
    context = await connectors.reader.read("1")
    assert context.ticket.status == "unavailable" and not context.grant_context_verified
    assert context.mapping.state == "unavailable"
    assert context.relationships.evidence.component == "servicedesk"
    await connectors.close()


@pytest.mark.parametrize("correlation", ["matching", "content", "revision", "missing"])
async def test_context_correlates_approval_read_with_ticket_without_claiming_approved_terms(
    correlation,
):
    connectors = Connectors(
        Settings(_env_file=None, database_url="postgresql+psycopg://unit:unit@localhost/unit")
    )
    http = transport(lambda r: httpx.Response(200, json=desk_ticket()), ServiceDesk.PATHS)
    ticket = await ServiceDesk(http).ticket("1")
    content = ticket.data.content_digest
    revision = ticket.data.revision_digest
    if correlation == "content":
        content = "f" * 64
    elif correlation == "revision":
        revision = "f" * 64
    elif correlation == "missing":
        content = revision = None
    approval = ApprovalRead(
        stages=(), configured_stage_ids=(), configured_levels=(1,),
        configuration_verified=True, terms_binding_verified=False, history_verified=False,
        observed_ticket_content_digest=content, observed_ticket_revision_digest=revision,
    )
    desk = AsyncMock()
    desk.ticket.return_value = ticket
    for name in ("groups", "templates", "statuses", "categories", "notes", "history",
                 "transitions", "relationships"):
        getattr(desk, name).return_value = failed(
            "servicedesk", name, ReadFailure("unsupported", "contract_unknown")
        )
    desk.approvals.return_value = ok("servicedesk", "approvals", approval, "fixture")
    connectors.reader.desk = desk
    context = await connectors.reader.read("1")
    assert context.ticket.status == "ok" and desk.ticket.await_count == 2
    assert desk.approvals.await_count == 2
    if correlation in {"content", "revision"}:
        assert context.approvals.status == "unstable" and context.approvals.data is None
        assert context.approvals.reason_code == "approval_ticket_snapshot_mismatch"
    else:
        assert context.approvals.status == "ok"
        assert not context.approvals.data.terms_binding_verified
        assert "approval_authority_unverified" in context.blockers
        if correlation == "missing":
            assert "approval_ticket_correlation_unverified" in context.blockers
    assert not context.read_complete and not context.grant_context_verified
    await http.close()
    await connectors.close()


async def test_creator_guard_json_setting_reaches_only_servicedesk_reader(monkeypatch):
    monkeypatch.setenv("AGENTIC_SERVICEDESK_LIFECYCLE_CREATOR_IDS", '["90", "91"]')
    settings = Settings(
        _env_file=None, database_url="postgresql+psycopg://unit:unit@localhost/unit",
        servicedesk_url="https://fixture.invalid", servicedesk_read_token="fixture-token",
    )
    connectors = Connectors(settings)
    assert connectors.reader.desk.lifecycle_creator_ids == frozenset({"90", "91"})
    assert "servicedesk_lifecycle_creator_ids" not in repr(settings)
    await connectors.close()


@pytest.mark.parametrize("refs", [("0",), ("person@example.invalid",), (90,), ("90", "90")])
def test_creator_guard_rejects_invalid_or_duplicate_configuration(refs):
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None, database_url="postgresql+psycopg://unit:unit@localhost/unit",
            servicedesk_lifecycle_creator_ids=refs,
        )
