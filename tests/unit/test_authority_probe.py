import json
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr

from app.connectors.http import ReadOnlyHTTP
from app.connectors.servicedesk import ServiceDesk
from scripts.probe_servicedesk_authority import HISTORY_ALIAS_PATH, compare_history_alias


@pytest.mark.parametrize("case", ["match", "different", "changed", "denied", "partial"])
async def test_alias_comparison_preserves_unknown_authority_and_redacts_content(case):
    alias_calls = 0
    calls = []

    def respond(request):
        nonlocal alias_calls
        calls.append(request)
        row = {
            "id": "7", "request": {"id": "1"}, "by": {"id": "actor"},
            "time": {"value": 1000}, "operation": "update",
            "diff": [{"field": {"name": "status"},
                      "previous_value": {"id": "3"}, "current_value": {"id": "2"}}],
            "description": "private body sk-secret upstream employee@example.invalid",
        }
        is_alias = request.url.path.endswith("/_history")
        if is_alias:
            alias_calls += 1
            if case == "denied":
                return httpx.Response(403, text="sk-secret-denial")
            if case == "different" or (case == "changed" and alias_calls == 2):
                row["time"] = {"value": 2000}
        data = {
            "response_status": {"status": "success", "status_code": 2000},
            "history": [row], "list_info": {"has_more_rows": False},
        }
        if is_alias and case == "partial":
            data.pop("list_info")
        return httpx.Response(200, json=data)

    http = ReadOnlyHTTP(
        "https://fixture.invalid", SecretStr("private-technician-token"),
        (*ServiceDesk.PATHS, HISTORY_ALIAS_PATH), auth_header="authtoken",
        transport=httpx.MockTransport(respond), sleep=AsyncMock(),
    )
    try:
        desk = ServiceDesk(http)
        canonical = await desk.history("1")
        result = await compare_history_alias(desk, "1", canonical)
        assert result["comparison_passed"] is (case == "match")
        assert result["status"] == {
            "match": "ok", "different": "ok", "changed": "unstable",
            "denied": "unavailable", "partial": "incomplete",
        }[case]
        assert canonical.data.ordering_verified is False
        assert all(r.method == "GET" and r.url.host == "fixture.invalid" for r in calls)
        serialized = json.dumps(result)
        assert "sk-secret" not in serialized
        assert "employee@" not in serialized
        assert "private-technician-token" not in serialized
    finally:
        await http.close()
