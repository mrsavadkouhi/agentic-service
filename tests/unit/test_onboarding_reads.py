import sqlite3
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr

from app.connectors.http import ReadFailure, ReadOnlyHTTP, failed, ok
from app.connectors.onboarding import QUERY, Onboarding, normalize_onboarding_processes
from app.connectors.servicedesk import ServiceDesk
from app.contracts.context import OffboardingProcess, OnboardingProcess


def mapping(parent="1", voip=None):
    return {"automation_id": parent, "office_id": "21", "ex_id": "22",
            "helpdesk_id": "23", "voip_id": voip}


@pytest.mark.parametrize("column,ref", [("office_id", "21"), ("ex_id", "22"),
                                       ("helpdesk_id", "23"), ("voip_id", "24")])
def test_actual_query_finds_all_confirmed_children_and_casts_native_bigints(column, ref):
    with sqlite3.connect(":memory:") as connection:
        connection.row_factory = sqlite3.Row
        connection.execute(
            "CREATE TABLE onboarding_process (automation_id INTEGER, "
            "office_id INTEGER, ex_id INTEGER, helpdesk_id INTEGER, voip_id INTEGER)"
        )
        connection.execute("INSERT INTO onboarding_process VALUES (1, 21, 22, 23, 24)")
        query = QUERY.replace("public.onboarding_process", "onboarding_process")
        for field in ("automation_id", "office_id", "ex_id", "helpdesk_id", "voip_id"):
            query = query.replace(field + "::text", "CAST(" + field + " AS TEXT)")
        rows = connection.execute(query.replace("%s", "?"), (ref,) * 5).fetchall()
        result = normalize_onboarding_processes([dict(row) for row in rows], ref)
        assert len(result) == 1 and isinstance(result[0], OnboardingProcess)
        assert result[0].parent_id == "1" and result[0].child_ids == ("21", "22", "23", "24")


def test_optional_children_and_shared_parents_are_preserved_without_absence_claim():
    result = normalize_onboarding_processes([mapping("1"), mapping("2")], "23")
    assert tuple(p.parent_id for p in result) == ("1", "2")
    assert result[0].child_ids == ("21", "22", "23")
    assert normalize_onboarding_processes([], "23") == ()
    bad = mapping()
    bad["voip_id"] = "sk-sensitive"
    with pytest.raises(ReadFailure):
        normalize_onboarding_processes([bad], "23")


async def test_postgres_reader_uses_its_own_fixed_read_only_query_and_hides_failures():
    connection, cursor = AsyncMock(), AsyncMock()
    connection.__aenter__.return_value = connection
    connection.execute.return_value = cursor
    cursor.fetchall.return_value = [mapping()]
    connect = AsyncMock(return_value=connection)
    reader = Onboarding(SecretStr("postgresql://fixture:sk-private@localhost/n8n"), connect=connect)
    result = await reader.read("23")
    assert result.status == "ok" and result.evidence.resource == "onboarding_relationships"
    assert connection.execute.call_args_list[0].args == ("SET TRANSACTION READ ONLY",)
    assert connection.execute.call_args_list[1].args == (QUERY, ("23",) * 5)
    assert "default_transaction_read_only=on" in connect.call_args.kwargs["options"]
    assert "sk-private" not in result.model_dump_json()
    connect.side_effect = RuntimeError("postgresql://sk-private@server employee records")
    result = await reader.read("23")
    assert result.status == "unavailable" and result.reason_code == "onboarding_read_unavailable"
    assert "sk-private" not in result.model_dump_json()


def source(processes):
    reader = AsyncMock()
    reader.read.return_value = ok("servicedesk", "onboarding_relationships", tuple(processes))
    return reader


def desk(onboarding, *, parent_template="10", offboarding=None):
    def handle(request):
        ref = request.url.path.rsplit("/", 1)[-1]
        if ref == "requests":
            return httpx.Response(200, json={
                "response_status": {"status_code": 2000, "status": "success"},
                "requests": [], "list_info": {"has_more_rows": False},
            })
        return httpx.Response(200, json={
            "response_status": {"status_code": 2000, "status": "success"},
            "request": {"id": ref, "template": {"id": "other" if ref == "23" else parent_template}},
        })
    http = ReadOnlyHTTP("https://fixture.invalid", SecretStr("fixture-token"), ServiceDesk.PATHS,
                        transport=httpx.MockTransport(handle))
    return ServiceDesk(http, lifecycle_template_ids={"10": "onboarding", "11": "offboarding"},
                       onboarding=onboarding, offboarding=offboarding)


@pytest.mark.parametrize("ref", ["1", "23"])
async def test_database_parent_and_child_are_excluded_without_a_refreshed_packed_field(ref):
    reader = source([OnboardingProcess(parent_id="1", child_ids=("21", "22", "23"))])
    service = desk(reader)
    result = await service.relationships(ref)
    assert result.status == "ok" and result.data.process_kind == "onboarding"
    assert result.data.source == "onboarding_database" and not result.data.coverage_verified
    assert result.data.child_ids == (("21", "22", "23") if ref == "1" else ())
    assert result.data.parent_ids == (("1",) if ref == "23" else ())
    assert reader.read.await_count == 2
    await service.http.close()


@pytest.mark.parametrize("case,expected", [("changed", "unstable"), ("wrong_parent", "invalid"),
                                          ("empty", "incomplete"), ("denied", "unavailable")])
async def test_missing_changed_or_wrong_evidence_cannot_qualify_a_standalone_child(case, expected):
    reader = source([OnboardingProcess(parent_id="1", child_ids=("23",))])
    if case == "changed":
        reader.read.side_effect = [reader.read.return_value, source([]).read.return_value]
    elif case == "empty":
        reader = source([])
    elif case == "denied":
        reader.read.return_value = failed("servicedesk", "onboarding_relationships", ReadFailure())
    service = desk(reader, parent_template="other" if case == "wrong_parent" else "10")
    result = await service.relationships("23")
    assert result.status == expected and result.data is None
    await service.http.close()


async def test_conflicting_process_kinds_fail_without_silently_selecting_a_parent():
    onboarding = source([OnboardingProcess(parent_id="1", child_ids=("23",))])
    offboarding = source([OffboardingProcess(parent_id="2", child_ids=("23",))])
    service = desk(onboarding, offboarding=offboarding)
    original = service.http.get

    async def get(path, *args, **kwargs):
        data = await original(path, *args, **kwargs)
        if path.endswith("/2"):
            data["request"]["template"]["id"] = "11"
        return data

    service.http.get = get
    result = await service.relationships("23")
    assert result.status == "ambiguous" and result.reason_code == "multiple_lifecycle_process_kinds"
    await service.http.close()
