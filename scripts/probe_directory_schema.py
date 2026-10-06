"""Read the dynamic DWE contact through Mirza; return verification flags only."""

import argparse
import asyncio
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import SecretStr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.connectors.http import ReadOnlyHTTP  # noqa: E402
from app.connectors.servicedesk import ServiceDesk  # noqa: E402


async def contact(args):
    source = json.loads(args.workflow.read_text())
    params = next(n["parameters"] for n in source["nodes"] if n["name"] == args.node)
    url = urlsplit(params["url"].lstrip("="))
    if url.username or url.password or not url.hostname:
        raise ValueError("Invalid origin")
    token = next(h["value"] for h in params["headerParameters"]["parameters"]
                 if h["name"].casefold() == "authtoken")
    http = ReadOnlyHTTP(f"{url.scheme}://{url.netloc}", SecretStr(token), ServiceDesk.PATHS,
                        auth_header="authtoken", allow_http=args.allow_http)
    try:
        groups = await ServiceDesk(http, contract="installed").groups()
        dwe = [g for g in groups.data or () if g.name.strip().casefold() == "dwe"]
        if len(dwe) != 1 or not dwe[0].incharge_verified or not dwe[0].incharge.email:
            raise ValueError("Contact unverified")
        return dwe[0].incharge.email
    finally:
        await http.close()


async def verify(args):
    email = await contact(args)
    root = Path(__file__).resolve().parents[1]
    names = ["app.contracts.tickets", "app.contracts.context", "app.connectors.http",
             "app.connectors.directory", "app.connectors.mirza", "app.connectors.mapping"]
    bundle = {name: (root / (name.replace(".", "/") + ".py")).read_text() for name in names}
    mapping_json = (root / "docs" / "department-tool-team-map.json").read_text()
    script = """
import sys, types, os, json, asyncio
for name in ['app', 'app.contracts', 'app.connectors']:
    module = types.ModuleType(name)
    module.__path__ = []
    sys.modules[name] = module
"""
    # Only the email needed by the directory lookup crosses this SSH connection;
    # the ServiceDesk credential stays in the local process.
    script += "email = " + repr(email) + "\nbundle = " + repr(bundle) + "\n"
    script += "mapping_json = " + repr(mapping_json) + "\n"
    script += """
for name, source in bundle.items():
    module = types.ModuleType(name)
    module.__package__ = name.rsplit('.', 1)[0]
    sys.modules[name] = module
    exec(compile(source, name, 'exec'), module.__dict__)
from app.connectors.http import ReadOnlyHTTP
from app.connectors.directory import Directory
from app.connectors.mapping import DepartmentMap
from app.connectors.mirza import Mirza
from pydantic import SecretStr
async def verify():
    origin = os.environ.get('ADAPTER_INTERNAL_URL', 'http://adapter:8100')
    http = ReadOnlyHTTP(origin, SecretStr(os.environ['LITELLM_MASTER_KEY']),
                        Directory.PATHS, allow_http=True)
    wrong = ReadOnlyHTTP(origin, SecretStr('invalid-probe-credential'),
                         Directory.PATHS, allow_http=True)
    mirza_http = ReadOnlyHTTP('http://127.0.0.1:4000',
        SecretStr(os.environ['LITELLM_MASTER_KEY']), Mirza.PATHS)
    try:
        directory = Directory(http, contract='installed')
        found = await directory.person(email)
        missing = await directory.person('agentic-read-probe-not-a-user@example.invalid')
        denied = await Directory(wrong).person(email)
        inventory = await Mirza(mirza_http, contract='installed').inventory()
        mapping = DepartmentMap(types.SimpleNamespace(read_text=lambda: mapping_json)).resolve(
            found.data if found.status == 'ok' else None, inventory)
        passed = (found.status == 'ok' and found.data.eligible()
                  and missing.status == 'not_found' and denied.status == 'unavailable'
                  and inventory.status == 'ok'
                  and mapping.state in {'mapped', 'clarification', 'manual'})
        print(json.dumps({'directory_read_status': found.status, 'reason': found.reason_code,
            'eligible_unique_contact': found.status == 'ok' and found.data.eligible(),
            'department_present': bool(found.data.department) if found.data else False,
            'missing_identity_status': missing.status, 'wrong_credential_status': denied.status,
            'inventory_read_status': inventory.status, 'mapping_resolution_state': mapping.state,
            'mapped_destination_verified': mapping.state == 'mapped',
            'probe_passed': passed, 'grant_context_verified': False}))
        if not passed:
            raise SystemExit(1)
    finally:
        await http.close()
        await wrong.close()
        await mirza_http.close()
asyncio.run(verify())
"""
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", args.ssh_host,
         shlex.join(["docker", "exec", "-i", args.container, "python", "-"])],
        input=script, text=True, capture_output=True, timeout=45,
    )
    printed = False
    allowed = {"directory_read_status", "reason", "eligible_unique_contact", "department_present",
               "missing_identity_status", "wrong_credential_status", "probe_passed",
               "inventory_read_status", "mapping_resolution_state", "mapped_destination_verified",
               "grant_context_verified"}
    for line in result.stdout.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and set(row) == allowed:
            print(json.dumps(row))
            printed = True
    if result.returncode or not printed:
        raise RuntimeError("Remote read unavailable")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", type=Path, required=True)
    parser.add_argument("--node", default="Count All")
    parser.add_argument("--allow-http", action="store_true")
    parser.add_argument("--ssh-host", required=True)
    parser.add_argument("--container", default="mirza-litellm")
    args = parser.parse_args()
    if not all(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value)
               for value in (args.ssh_host, args.container)):
        parser.error("Invalid host/container reference")
    try:
        asyncio.run(verify(args))
    except Exception as exc:
        print(json.dumps({"probe_passed": False, "error_type": type(exc).__name__}))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
