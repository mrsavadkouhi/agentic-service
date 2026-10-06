import json
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr

from app.connectors.http import ReadFailure, ReadOnlyHTTP
from app.connectors.lifecycle import (
    installed_lifecycle_templates,
    mentions_onboarding_child,
    onboarding_children,
)
from app.connectors.servicedesk import ServiceDesk


def packed(last="viop_id:24"):
    return f"office_id:21|office_status:Open|ex_id:22|helpdesk_id:23|{last}"


def detail(ref, template, raw=None):
    return {
        "response_status": {"status_code": 2000, "status": "success"},
        "request": {
            "id": ref,
            "template": {"id": template},
            "udf_fields": {"udf_sline_4217": raw},
        },
    }


def reader(handler, **kwargs):
    http = ReadOnlyHTTP(
        "https://fixture.invalid",
        SecretStr("fixture-token"),
        ServiceDesk.PATHS,
        transport=httpx.MockTransport(handler),
    )
    return ServiceDesk(
        http,
        lifecycle_template_ids={"10": "onboarding", "11": "offboarding", "12": "internal_transfer"},
        contract="fixture",
        **kwargs,
    )


def test_observed_catalog_and_strict_packed_child_parser():
    assert set(installed_lifecycle_templates().values()) == {
        "onboarding", "offboarding", "internal_transfer"
    }
    assert onboarding_children(packed()) == ("21", "22", "23", "24")
    assert onboarding_children(packed("voip_id:24")) == ("21", "22", "23", "24")
    assert onboarding_children(packed("voip_id:24|viop_id:24")) == ("21", "22", "23", "24")
    assert mentions_onboarding_child(packed(), "23")
    assert not mentions_onboarding_child(packed(), "2")
    assert not mentions_onboarding_child("office_status:23", "23")


@pytest.mark.parametrize(
    "raw",
    [None, "", {}, "office_id:21", packed("viop_id:bad"), packed("viop_id:23"),
     packed("viop_id:24|voip_id:25"), packed("viop_id:24|office_id:25"),
     packed("viop_id:24|unknown_id:25"), packed("viop_id:24|no-separator")],
)
def test_incomplete_or_conflicting_children_fail_without_raw_text(raw):
    with pytest.raises(ReadFailure):
        onboarding_children(raw)


@pytest.mark.parametrize("template,kind", [("10", "onboarding"), ("11", "offboarding"),
                                          ("12", "internal_transfer")])
async def test_roots_are_excluded_without_claiming_complete_child_coverage(template, kind):
    desk = reader(lambda request: httpx.Response(200, json=detail("1", template, packed())))
    result = await desk.relationships("1")
    assert result.status == "ok" and result.data.process_kind == kind
    assert result.data.process_association == "lifecycle"
    assert result.data.child_ids == (("21", "22", "23", "24") if kind == "onboarding" else ())
    assert not result.data.coverage_verified
    await desk.http.close()


async def test_child_reverse_lookup_uses_projection_preserves_shared_parents_and_rechecks():
    read_parents = []

    def handle(request):
        if request.url.path == "/api/v3/requests":
            info = json.loads(request.url.params["input_data"])["list_info"]
            assert info["search_criteria"] == [
                {"field": "template.id", "condition": "eq", "value": "10"}
            ]
            assert info["fields_required"] == ["id", "template.id", "udf_fields.udf_sline_4217"]
            return httpx.Response(200, json={
                "response_status": {"status_code": 2000, "status": "success"},
                "requests": [detail(ref, "10", packed())["request"] for ref in ("1", "2")],
                "list_info": {"has_more_rows": False},
            })
        ref = request.url.path.rsplit("/", 1)[-1]
        if ref != "23":
            read_parents.append(ref)
        return httpx.Response(200, json=detail(ref, "other" if ref == "23" else "10", packed()))

    desk = reader(handle)
    result = await desk.relationships("23")
    assert result.status == "ok" and result.data.parent_ids == ("1", "2")
    assert result.data.parent_id is None and read_parents == ["1", "2"]
    assert result.data.source == "onboarding_udf_index" and not result.data.coverage_verified
    await desk.http.close()


@pytest.mark.parametrize("reciprocal", [True, False])
async def test_call_center_bridge_requires_reciprocal_onboarding_root(reciprocal):
    def handle(request):
        ref = request.url.path.rsplit("/", 1)[-1]
        data = detail(ref, "10", None if ref == "1" else packed())
        data["request"]["udf_fields"].update(
            {"udf_sline_6601": "2"} if ref == "1"
            else {"udf_sline_10449": "1" if reciprocal else "3"}
        )
        return httpx.Response(200, json=data)

    index = AsyncMock()
    desk = reader(handle, onboarding=index)
    result = await desk.relationships("1")
    if reciprocal:
        assert result.status == "ok" and result.data.child_ids == ("21", "22", "23", "24")
        assert result.data.related_root_ids == ("2",)
        assert result.data.source == "onboarding_root_bridge"
        assert not result.data.coverage_verified
    else:
        assert result.status == "invalid" and result.data is None
    index.read.assert_not_awaited()
    await desk.http.close()


@pytest.mark.parametrize(
    "case,expected",
    [("no_match", "incomplete"), ("filter_escape", "invalid"), ("root_changed", "unstable"),
     ("partial", "incomplete"), ("self_link", "invalid"), ("missing_detail", "unsupported")],
)
async def test_negative_partial_or_changed_index_never_proves_standalone(case, expected):
    def handle(request):
        if request.url.path == "/api/v3/requests":
            root = detail("1", "other" if case == "filter_escape" else "10", packed())["request"]
            if case == "self_link":
                root["id"] = "23"
            return httpx.Response(200, json={
                "response_status": {"status_code": 2000, "status": "success"},
                "requests": [] if case == "no_match" else [root],
                "list_info": {"has_more_rows": case == "partial"},
            })
        ref = request.url.path.rsplit("/", 1)[-1]
        if ref == "1" and case == "missing_detail":
            return httpx.Response(404)
        raw = packed("viop_id:25") if case == "root_changed" else packed()
        return httpx.Response(200, json=detail(ref, "other" if ref == "23" else "10", raw))

    desk = reader(handle, max_pages=1)
    result = await desk.relationships("23")
    assert result.status == expected and result.data is None
    await desk.http.close()


async def test_history_prose_field_names_are_digest_only_not_status_proofs():
    row = {
        "id": "31",
        "request": {"id": "23"},
        "by": {"id": "32"},
        "time": {"value": 1000},
        "operation": "UPDATE",
        "diff": [{"field": {"name": "Open approved for person@example.invalid sk-sensitive"},
                  "previous_value": None, "current_value": "private note"}],
    }
    desk = reader(lambda request: httpx.Response(200, json={
        "response_status": {"status_code": 2000, "status": "success"},
        "history": [row], "list_info": {"has_more_rows": False},
    }))
    result = await desk.history("23")
    assert result.status == "ok"
    assert result.data.events[0].fields[0].startswith("history-field-")
    assert result.data.events[0].status_changes == () and not result.data.ordering_verified
    assert "person@example.invalid" not in result.model_dump_json()
    assert "sk-sensitive" not in result.model_dump_json()
    await desk.http.close()


@pytest.mark.parametrize("creator,registered", [("90", False), ("90", True), ("91", False),
                                               (None, False)])
async def test_dedicated_creator_without_mapping_is_a_blocker_never_membership(creator, registered):
    def handle(request):
        if request.url.path == "/api/v3/requests":
            return httpx.Response(200, json={
                "response_status": {"status_code": 2000, "status": "success"},
                "requests": [detail("1", "10", packed())["request"]] if registered else [],
                "list_info": {"has_more_rows": False},
            })
        ref = request.url.path.rsplit("/", 1)[-1]
        data = detail(ref, "other" if ref == "23" else "10", packed())
        if ref == "23":
            data["request"]["created_by"] = {"id": creator} if creator else None
        return httpx.Response(200, json=data)

    desk = reader(handle, lifecycle_creator_ids=("90",))
    result = await desk.relationships("23")
    if registered:
        assert result.status == "ok" and result.data.parent_ids == ("1",)
        assert not result.data.coverage_verified
    else:
        assert result.status == "incomplete" and result.data is None
        assert result.reason_code == (
            "n8n_created_ticket_mapping_unconfirmed" if creator == "90"
            else "offboarding_relationship_source_unconfigured"
        )
    await desk.http.close()
