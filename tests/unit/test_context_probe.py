import json
from types import SimpleNamespace

import pytest

from app.connectors.http import ok
from app.contracts.context import DirectoryPerson, MirzaInventory
from scripts.probe_context_snapshot import remote_reads


@pytest.mark.parametrize("case", ["ok", "failed", "noise", "wrong_people", "oversized"])
def test_private_ssh_context_reads_validate_shape_and_never_print_records(
    monkeypatch, capsys, case,
):
    email = "owner@example.invalid"
    inventory = ok("mirza", "inventory", MirzaInventory(
        users=(), teams=(), keys=(), served_models=(),
    ), "fixture")
    person = ok("directory", "person", DirectoryPerson(
        directory_id="private-person", email=email, department="private-department",
        account_enabled=True, account_expired=False,
    ), "fixture")
    payload = {"inventory": inventory.model_dump(mode="json"),
               "people": {email: person.model_dump(mode="json")}}
    if case == "wrong_people":
        payload["people"] = {}
    body = json.dumps(payload)
    if case == "noise":
        body = "sk-private-secret\n" + body
    elif case == "oversized":
        body = "x" * 2_000_001
    response = SimpleNamespace(returncode=1 if case == "failed" else 0,
                               stdout=body, stderr="sk-private-secret upstream credentials")

    def run(command, **kwargs):
        assert command[:5] == ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
        assert kwargs["capture_output"] and kwargs["timeout"] == 55
        assert "sk-private-secret" not in kwargs["input"]
        assert "docker exec -i mirza-litellm python -" == command[-1]
        return response

    monkeypatch.setattr("scripts.probe_context_snapshot.subprocess.run", run)
    args = SimpleNamespace(ssh_host="mirza-ha1", container="mirza-litellm")
    if case == "ok":
        observed, people = remote_reads(args, (email,))
        assert observed == inventory and people[email] == person
    else:
        with pytest.raises(ValueError):
            remote_reads(args, (email,))
    output = capsys.readouterr()
    assert output.out == output.err == ""
