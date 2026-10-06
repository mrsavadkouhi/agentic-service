"""Read-only Mirza schema probe: code in memory, credentials/records stay remote."""

import argparse
import json
import re
import shlex
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ssh-host", required=True)
    parser.add_argument("--container", required=True)
    args = parser.parse_args()
    for value in (args.ssh_host, args.container):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
            parser.error("Invalid host/container reference")
    root = Path(__file__).resolve().parents[1]
    mapping_json = (root / "docs" / "department-tool-team-map.json").read_text()
    modules = [
        "app.contracts.tickets",
        "app.contracts.context",
        "app.connectors.http",
        "app.connectors.mirza",
        "app.connectors.mapping",
    ]
    bundle = {name: (root / (name.replace(".", "/") + ".py")).read_text() for name in modules}
    script = """
import sys, types, os, json, asyncio
for name in ['app', 'app.contracts', 'app.connectors']:
    module = types.ModuleType(name)
    module.__path__ = []
    sys.modules[name] = module
"""
    script += "bundle = " + repr(bundle) + "\nmapping_json = " + repr(mapping_json) + "\n"
    script += """
for name, source in bundle.items():
    module = types.ModuleType(name)
    module.__package__ = name.rsplit('.', 1)[0]
    sys.modules[name] = module
    exec(compile(source, name, 'exec'), module.__dict__)
from app.connectors.http import ReadOnlyHTTP
from app.connectors.mapping import DepartmentMap
from app.contracts.context import DirectoryPerson
import app.connectors.mirza as mirza
from pydantic import SecretStr, ValidationError
original_failed = mirza.failed
def safe_diagnostic(component, resource, error):
    detail = {'normalization_error_type': type(error).__name__}
    if isinstance(error, ValidationError):
        fields = {'user_id','email','team_ids','team_id','alias','kind','models','budget','limit',
                  'spend','reset_at','duration','reasoning','all_models','key_ref','owner_id',
                  'expired','expires_at','served_models'}
        detail['fields'] = [[x if isinstance(x, int) or x in fields else 'dynamic-field'
                             for x in e['loc']] for e in error.errors()]
        detail['error_codes'] = [e['type'] for e in error.errors()]
    print(json.dumps(detail))
    return original_failed(component, resource, error)
mirza.failed = safe_diagnostic
async def verify():
    http = ReadOnlyHTTP('http://127.0.0.1:4000', SecretStr(os.environ['LITELLM_MASTER_KEY']),
                        mirza.Mirza.PATHS)
    result = await mirza.Mirza(http, contract='installed').inventory()
    print(json.dumps({'normalized_inventory_status': result.status,
        'reason_code': result.reason_code, 'counts': {
            'users': len(result.data.users), 'teams': len(result.data.teams),
            'keys': len(result.data.keys), 'models': len(result.data.served_models)
        } if result.data else None}))
    mapping = DepartmentMap(types.SimpleNamespace(read_text=lambda: mapping_json))
    # Synthetic identities exercise the approved map against the live catalog;
    # they are never sent to LDAP or used as employee/authorization evidence.
    verified = 0
    for department in mapping.approved:
        person = DirectoryPerson(directory_id='catalog-probe', email='probe@example.invalid',
            department=department, account_enabled=True, account_expired=False)
        verified += mapping.resolve(person, result).state == 'mapped'
    mapping_passed = bool(mapping.approved) and verified == len(mapping.approved)
    print(json.dumps({'approved_mappings': len(mapping.approved),
        'verified_tool_destinations': verified, 'mapping_catalog_passed': mapping_passed}))
    await http.close()
    if result.status != 'ok' or not mapping_passed:
        raise SystemExit(1)
asyncio.run(verify())
"""
    result = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            args.ssh_host,
            shlex.join(["docker", "exec", "-i", args.container, "python", "-"]),
        ],
        input=script,
        text=True,
        capture_output=True,
        timeout=60,
    )
    # The probe intentionally emits only status/counts/schema paths. Never print
    # remote stderr, which could include credential-bearing dependency exceptions.
    for line in result.stdout.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if not isinstance(value, dict):
            continue
        if set(value) in (
            {"normalized_inventory_status", "reason_code", "counts"},
            {"normalization_error_type"},
            {"normalization_error_type", "fields", "error_codes"},
            {"approved_mappings", "verified_tool_destinations", "mapping_catalog_passed"},
        ):
            print(json.dumps(value))
    if result.returncode:
        raise SystemExit("Remote read probe unavailable")


if __name__ == "__main__":
    main()
