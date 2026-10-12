import json
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr

from app.connectors.http import ReadOnlyHTTP
from app.connectors.servicedesk import ServiceDesk
from scripts.probe_lifecycle_creator import verify_creator_samples


@pytest.mark.parametrize("case", [
    "same", "different", "changed", "denied", "identity", "unknown", "root",
])
async def test_creator_probe_checks_native_identities_and_keeps_account_and_bodies_private(case):
    reads = {}
    requests = []

    def handle(request):
        requests.append(request)
        ref = request.url.path.rsplit("/", 1)[-1]
        reads[ref] = reads.get(ref, 0) + 1
        if case == "denied":
            return httpx.Response(403, text="sk-sensitive employee@example.invalid")
        creator = "90"
        if (case == "different" and ref == "2") or (case == "changed" and reads[ref] == 2):
            creator = "91"
        return httpx.Response(200, json={
            "response_status": {"status_code": 2000, "status": "success"},
            "request": {
                "id": "3" if case == "identity" else ref,
                "template": {"id": "10" if case == "root" else "other"},
                "created_by": None if case == "unknown" else {"id": creator},
                "description": "sk-sensitive employee@example.invalid",
            },
        })

    http = ReadOnlyHTTP(
        "https://fixture.invalid", SecretStr("private-technician-token"), ServiceDesk.PATHS,
        transport=httpx.MockTransport(handle), auth_header="authtoken", sleep=AsyncMock(),
    )
    try:
        creator, report = await verify_creator_samples(
            ServiceDesk(http, lifecycle_template_ids={"10": "onboarding"}), ["1", "2"],
        )
        assert report["status"] == {
            "same": "ok", "different": "ambiguous", "changed": "unstable",
            "denied": "unavailable", "identity": "invalid", "unknown": "invalid",
            "root": "invalid",
        }[case]
        assert creator == ("90" if case == "same" else None)
        assert report["one_creator_observed"] is (case == "same")
        if case == "same":
            assert reads == {"1": 2, "2": 2}
        assert all(r.method == "GET" and r.url.host == "fixture.invalid" for r in requests)
        serialized = json.dumps(report)
        assert "90" not in serialized and "91" not in serialized
        assert "sk-sensitive" not in serialized and "employee@" not in serialized
        assert "private-technician-token" not in serialized
    finally:
        await http.close()


@pytest.mark.parametrize("refs", [[], ["1"], ["1", "1"], ["1", "sk-sensitive"],
                                 [str(i) for i in range(1, 22)]])
async def test_invalid_or_unbounded_creator_samples_make_no_requests(refs):
    desk = AsyncMock()
    creator, report = await verify_creator_samples(desk, refs)
    assert creator is None and report["status"] == "invalid"
    desk.http.get.assert_not_awaited()
