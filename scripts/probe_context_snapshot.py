"""Assemble one installed read-only context in memory; emit statuses and flags only."""

import argparse
import asyncio
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

from pydantic import SecretStr, TypeAdapter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.connectors.context import ContextReader  # noqa: E402
from app.connectors.http import ReadOnlyHTTP  # noqa: E402
from app.connectors.lifecycle import installed_lifecycle_templates  # noqa: E402
from app.connectors.mapping import DepartmentMap  # noqa: E402
from app.connectors.mattermost import Mattermost  # noqa: E402
from app.connectors.servicedesk import ServiceDesk, identifier  # noqa: E402
from app.contracts.context import DirectoryPerson, MirzaInventory, ReadResult  # noqa: E402
from scripts.probe_lifecycle_creator import verify_creator_samples  # noqa: E402


def remote_reads(args, emails):
    root = Path(__file__).resolve().parents[1]
    names = ("app.contracts.tickets", "app.contracts.context", "app.connectors.http",
             "app.connectors.directory", "app.connectors.mirza")
    bundle = {name: (root / (name.replace(".", "/") + ".py")).read_text() for name in names}
    script = """
import sys, types, os, json, asyncio
for name in ['app', 'app.contracts', 'app.connectors']:
    module = types.ModuleType(name)
    module.__path__ = []
    sys.modules[name] = module
"""
    script += "bundle = " + repr(bundle) + "\nemails = " + repr(sorted(set(emails))) + "\n"
    script += """
for name, source in bundle.items():
    module = types.ModuleType(name)
    module.__package__ = name.rsplit('.', 1)[0]
    sys.modules[name] = module
    exec(compile(source, name, 'exec'), module.__dict__)
from app.connectors.http import ReadOnlyHTTP
from app.connectors.directory import Directory
from app.connectors.mirza import Mirza
from pydantic import SecretStr
async def read():
    token = SecretStr(os.environ['LITELLM_MASTER_KEY'])
    mh = ReadOnlyHTTP('http://127.0.0.1:4000', token, Mirza.PATHS)
    dh = ReadOnlyHTTP(os.environ.get('ADAPTER_INTERNAL_URL', 'http://adapter:8100'),
                     token, Directory.PATHS, allow_http=True)
    try:
        inventory = await Mirza(mh, contract='installed').inventory()
        directory = Directory(dh, contract='installed')
        people = {email: (await directory.person(email)).model_dump(mode='json')
                  for email in emails}
        # These normalized records cross the encrypted SSH pipe only; the local
        # process captures them privately and never prints or saves the payload.
        print(json.dumps({'inventory': inventory.model_dump(mode='json'), 'people': people}))
    finally:
        await mh.close()
        await dh.close()
asyncio.run(read())
"""
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", args.ssh_host,
         shlex.join(["docker", "exec", "-i", args.container, "python", "-"])],
        input=script, text=True, capture_output=True, timeout=55,
    )
    if result.returncode or len(result.stdout.encode()) > 2_000_000:
        raise ValueError("Remote read unavailable")
    payload = json.loads(result.stdout)
    if set(payload) != {"inventory", "people"} or set(payload["people"]) != set(emails):
        raise ValueError("Remote read shape invalid")
    inventory = TypeAdapter(ReadResult[MirzaInventory]).validate_python(payload["inventory"])
    people = {email: TypeAdapter(ReadResult[DirectoryPerson]).validate_python(value)
              for email, value in payload["people"].items()}
    return inventory, people


async def verify(args, mattermost_token):
    source = json.loads(args.workflow.read_text())
    params = next(n["parameters"] for n in source["nodes"] if n["name"] == args.node)
    url = urlsplit(params["url"].lstrip("="))
    if url.username or url.password or not url.hostname:
        raise ValueError("Invalid configured origin")
    token = next(h["value"] for h in params["headerParameters"]["parameters"]
                 if h["name"].casefold() == "authtoken")
    dh = ReadOnlyHTTP(f"{url.scheme}://{url.netloc}", SecretStr(token), ServiceDesk.PATHS,
                      auth_header="authtoken", allow_http=args.allow_http)
    mh = ReadOnlyHTTP("https://mattermost.tapsi.tech", SecretStr(mattermost_token),
                      Mattermost.PATHS)
    try:
        templates = installed_lifecycle_templates()
        probe = ServiceDesk(dh, lifecycle_template_ids=templates, contract="installed")
        creator, samples = await verify_creator_samples(probe, args.child_ticket_id)
        if creator is None:
            raise ValueError("Creator samples unverified")
        desk = ServiceDesk(
            dh, lifecycle_template_ids=templates, contract="installed",
            lifecycle_creator_ids=(creator,), lifecycle_creator_coverage_confirmed=True,
        )
        groups = await desk.groups()
        dwe = [g for g in groups.data or () if g.name.strip().casefold() == "dwe"]
        if len(dwe) != 1 or not dwe[0].incharge_verified or not dwe[0].incharge.email:
            raise ValueError("Contact identity unavailable")
        data = desk.validate(await dh.get("/api/v3/requests", {"input_data": json.dumps({
            "list_info": {"row_count": 25, "start_index": 1, "search_criteria": [{
                "field": "template.id", "condition": "eq", "value": "11702",
            }]},
        })}))
        rows = data.get("requests")
        if not isinstance(rows, list) or len(rows) > 25:
            raise ValueError("Candidate window invalid")
        candidate = next((str(row["id"]) for row in rows
                          if isinstance(row, dict)
                          and re.fullmatch(r"[1-9][0-9]{0,29}", str(row.get("id", "")))
                          and identifier(row.get("template")) == "11702"
                          and identifier(row.get("created_by")) not in {None, creator}), None)
        if candidate is None:
            raise ValueError("No bounded candidate")
        ticket = await desk.ticket(candidate)
        if ticket.status != "ok" or not ticket.data.requester.email:
            raise ValueError("Requester identity unavailable")
        recipient = dwe[0].incharge.email
        inventory, people = await asyncio.to_thread(
            remote_reads, args, (ticket.data.requester.email, recipient)
        )

        async def person(email):
            return people[email]

        async def catalog():
            return inventory

        mapping_path = Path(__file__).resolve().parents[1] / "docs/department-tool-team-map.json"
        reader = ContextReader(
            desk, SimpleNamespace(person=person), SimpleNamespace(inventory=catalog),
            Mattermost(mh, contract="installed", expected_bot_username="servicedesk_agent"),
            DepartmentMap(mapping_path),
        )
        context = await reader.read(candidate, recipient_email=recipient)
        passed = context.observation_complete and not context.grant_context_verified
        print(json.dumps({
            "creator_samples": samples,
            "recipient_lookup_scope": "dynamic_dwe_contact_probe",
            "observation_complete": context.observation_complete,
            "observation_blockers": context.observation_blockers,
            "authority_and_eligibility_blockers": context.blockers,
            "mapping_state": context.mapping.state,
            "grant_context_verified": context.grant_context_verified,
            "read_probe_passed": passed,
        }))
        return 0 if passed else 1
    finally:
        await dh.close()
        await mh.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", type=Path, required=True)
    parser.add_argument("--node", default="Count All")
    parser.add_argument("--child-ticket-id", action="append", required=True)
    parser.add_argument("--ssh-host", required=True)
    parser.add_argument("--container", default="mirza-litellm")
    parser.add_argument("--confirm-historical-creator-coverage", action="store_true", required=True)
    parser.add_argument("--allow-http", action="store_true")
    args = parser.parse_args()
    if not all(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value)
               for value in (args.ssh_host, args.container)):
        parser.error("Invalid host/container reference")
    try:
        # No CLI/environment echo or secret file: accept the already-authorized
        # bot token from stdin. Disable terminal echo when using an interactive TTY.
        token = sys.stdin.readline().strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{20,128}", token):
            raise ValueError("Read token unavailable")
        raise SystemExit(asyncio.run(verify(args, token)))
    except Exception as exc:
        print(json.dumps({"read_probe_passed": False, "error_type": type(exc).__name__}))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
