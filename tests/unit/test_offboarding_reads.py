import sqlite3
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr

from app.connectors.http import ReadFailure, ReadOnlyHTTP, failed, ok
from app.connectors.offboarding import QUERY, Offboarding, normalize_processes
from app.connectors.servicedesk import ServiceDesk
from app.contracts.context import OffboardingProcess


def mapping(parent="1", child="21"):
    return {"automation_id": parent, "helpdesk_id": child, "sysadmin_id": None,
            "network_id": "22", "devflow_id": "23", "foundation_id": None,
            "voip_id": None, "platform_id": None, "di_id": None}


def test_mapping_retains_optional_and_shared_child_relationships():
    result = normalize_processes([mapping("1"), mapping("2")], "21")
    assert tuple(p.parent_id for p in result) == ("1", "2")
    assert result[0].child_ids == ("21", "22", "23")
    assert normalize_processes([], "21") == ()


@pytest.mark.parametrize(
    "rows,expected",
    [([mapping("1"), mapping("1")], "ambiguous"),
     ([mapping("21")], "invalid"),
     ([mapping("1", "22")], "invalid"),
     ([mapping("1", "sk-sensitive")], "invalid"),
     ([mapping("1", "other-person@example.invalid")], "invalid"),
     ([{}], "invalid"),
     ([mapping(str(i + 100)) for i in range(101)], "incomplete")],
)
def test_invalid_ambiguous_or_partial_map_never_becomes_empty(rows, expected):
    with pytest.raises(ReadFailure) as error:
        normalize_processes(rows, "21")
    assert error.value.status == expected
    assert "sk-sensitive" not in str(error.value)
    assert "example.invalid" not in str(error.value)


async def test_postgres_select_is_parameterized_bounded_and_transaction_read_only():
    connection, cursor = AsyncMock(), AsyncMock()
    connection.__aenter__.return_value = connection
    connection.execute.return_value = cursor
    cursor.fetchall.return_value = [mapping()]
    connect = AsyncMock(return_value=connection)
    source = Offboarding(SecretStr("postgresql://fixture:sk-private@localhost/fixture"),
                        connect=connect, contract="fixture")
    result = await source.read("21")
    assert result.status == "ok" and result.data[0].parent_id == "1"
    assert connection.execute.call_args_list[0].args == ("SET TRANSACTION READ ONLY",)
    assert connection.execute.call_args_list[1].args == (QUERY, ("21",) * 9)
    assert "LIMIT 101" in QUERY
    assert "default_transaction_read_only=on" in connect.call_args.kwargs["options"]
    assert "statement_timeout=8000" in connect.call_args.kwargs["options"]
    assert "sk-private" not in result.model_dump_json()
    assert not hasattr(source, "write")
    connection.__aexit__.assert_awaited_once()


@pytest.mark.parametrize("column", ["foundation_id", "voip_id", "platform_id", "di_id"])
def test_additional_installed_children_are_found_by_the_actual_reverse_query(column):
    # These child fields exist in the installed table and older/current n8n
    # flows. Exercise the SQL predicate, not a mock that returns any supplied row.
    with sqlite3.connect(":memory:") as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("""
            CREATE TABLE offboarding_process (
                automation_id TEXT, helpdesk_id TEXT, sysadmin_id TEXT,
                network_id TEXT, devflow_id TEXT, foundation_id TEXT,
                voip_id TEXT, platform_id TEXT, di_id TEXT
            )
        """)
        row = mapping()
        row[column] = "24"
        connection.execute(
            "INSERT INTO offboarding_process VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            tuple(row.values()),
        )
        # Only the schema prefix and DB-API bind syntax differ from PostgreSQL.
        query = QUERY.replace("public.offboarding_process", "offboarding_process")
        rows = connection.execute(query.replace("%s", "?"), ("24",) * 9).fetchall()
        result = normalize_processes([dict(row) for row in rows], "24")
        assert len(result) == 1 and result[0].parent_id == "1"
        assert result[0].child_ids == ("21", "22", "23", "24")


@pytest.mark.parametrize("column", ["foundation_id", "voip_id", "platform_id", "di_id"])
def test_new_child_columns_do_not_hide_invalid_or_self_referencing_ids(column):
    for invalid in ("sk-sensitive", "1", "21"):
        row = mapping()
        row[column] = invalid
        with pytest.raises(ReadFailure) as error:
            normalize_processes([row], "21")
        assert error.value.status == "invalid" and "sk-sensitive" not in str(error.value)


async def test_database_failures_hide_credentials_and_invalid_ids_never_connect():
    connect = AsyncMock(side_effect=RuntimeError("postgresql://sk-private@server rows secret"))
    source = Offboarding(
        SecretStr("postgresql://fixture:secret@localhost/fixture"), connect=connect
    )
    result = await source.read("21")
    assert result.status == "unavailable" and result.data is None
    assert "sk-private" not in result.model_dump_json()
    connect.reset_mock()
    result = await source.read("21 OR 1=1")
    assert result.status == "invalid" and result.data is None
    connect.assert_not_awaited()


def desk(source, *, parent_template="11"):
    def handle(request):
        ref = request.url.path.rsplit("/", 1)[-1]
        if ref == "requests":
            return httpx.Response(200, json={
                "response_status": {"status_code": 2000, "status": "success"},
                "requests": [], "list_info": {"has_more_rows": False},
            })
        return httpx.Response(200, json={
            "response_status": {"status_code": 2000, "status": "success"},
            "request": {"id": ref, "template": {"id": parent_template if ref != "21" else "other"}},
        })
    http = ReadOnlyHTTP("https://fixture.invalid", SecretStr("fixture-token"), ServiceDesk.PATHS,
                        transport=httpx.MockTransport(handle))
    return ServiceDesk(http, contract="fixture", lifecycle_template_ids={"11": "offboarding"},
                       offboarding=source)


def observed(processes):
    return ok("servicedesk", "offboarding_relationships", tuple(processes), "fixture")


@pytest.mark.parametrize("ref", ["1", "21"])
async def test_offboarding_parent_and_child_use_verified_parent_template_and_mapping(ref):
    source = AsyncMock()
    source.read.return_value = observed([OffboardingProcess(parent_id="1", child_ids=("21", "22"))])
    reader = desk(source)
    result = await reader.relationships(ref)
    assert result.status == "ok" and result.data.process_kind == "offboarding"
    assert result.data.source == "offboarding_database"
    assert result.data.child_ids == (("21", "22") if ref == "1" else ())
    assert result.data.parent_ids == (("1",) if ref == "21" else ())
    assert not result.data.coverage_verified and source.read.await_count == 2
    await reader.http.close()


async def test_offboarding_shared_parents_are_preserved():
    source = AsyncMock()
    source.read.return_value = observed([
        OffboardingProcess(parent_id="1", child_ids=("21",)),
        OffboardingProcess(parent_id="2", child_ids=("21",)),
    ])
    reader = desk(source)
    result = await reader.relationships("21")
    assert result.status == "ok" and result.data.parent_ids == ("1", "2")
    assert result.data.parent_id is None
    await reader.http.close()


@pytest.mark.parametrize("case,expected", [("wrong_template", "invalid"), ("changed", "unstable"),
                                          ("unavailable", "unavailable"), ("empty", "incomplete")])
async def test_missing_changed_or_wrong_parent_evidence_does_not_authorize(case, expected):
    source = AsyncMock()
    original = observed([OffboardingProcess(parent_id="1", child_ids=("21",))])
    if case == "unavailable":
        source.read.return_value = failed("servicedesk", "offboarding_relationships", ReadFailure())
    elif case == "empty":
        source.read.return_value = observed([])
    elif case == "changed":
        source.read.side_effect = [original, observed([])]
    else:
        source.read.return_value = original
    reader = desk(source, parent_template="other" if case == "wrong_template" else "11")
    result = await reader.relationships("21")
    assert result.status == expected and result.data is None
    if case == "empty":
        assert result.reason_code == "lifecycle_absence_contract_unverified"
    await reader.http.close()
