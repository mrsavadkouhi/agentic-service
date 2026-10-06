"""Explicit read-only discovery; workflow credentials stay in memory."""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import SecretStr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.connectors.http import ReadOnlyHTTP  # noqa: E402
from app.connectors.lifecycle import installed_lifecycle_templates  # noqa: E402
from app.connectors.servicedesk import ServiceDesk  # noqa: E402


async def verify(args):
    source = json.loads(args.workflow.read_text())
    node = next(node for node in source["nodes"] if node["name"] == args.node)
    params = node["parameters"]
    url = urlsplit(params["url"].lstrip("="))
    if url.username or url.password or not url.hostname:
        raise ValueError("Invalid configured origin")
    token = next(
        header["value"]
        for header in params["headerParameters"]["parameters"]
        if header["name"].casefold() == "authtoken"
    )
    http = ReadOnlyHTTP(
        f"{url.scheme}://{url.netloc}",
        SecretStr(token),
        ServiceDesk.PATHS,
        auth_header="authtoken",
        allow_http=args.allow_http,
    )
    desk = ServiceDesk(
        http, contract="installed", lifecycle_template_ids=installed_lifecycle_templates()
    )
    passed = True
    try:
        for name in ("groups", "templates", "statuses", "categories"):
            result = await getattr(desk, name)()
            print(
                json.dumps(
                    {
                        "resource": name,
                        "status": result.status,
                        "reason": result.reason_code,
                        "count": len(result.data) if result.data is not None else None,
                    }
                )
            )
            passed = passed and result.status == "ok"
            if name == "groups" and result.status == "ok":
                dwe = [g for g in result.data if g.name.strip().casefold() == "dwe"]
                print(
                    json.dumps(
                        {
                            "dwe_incharge_verified": len(dwe) == 1
                            and dwe[0].incharge_verified
                            and bool(dwe[0].incharge.email)
                        }
                    )
                )
        ref = args.ticket_id
        if ref is None:
            data = desk.validate(
                await http.get(
                    "/api/v3/requests",
                    {"input_data": json.dumps({"list_info": {"row_count": 1, "start_index": 1}})},
                )
            )
            rows = data.get("requests", [])
            ref = str(rows[0]["id"]) if rows else None
        if ref is not None:
            if not re.fullmatch(r"[0-9]{1,30}", ref):
                raise ValueError("Invalid ticket reference")
            for name in ("ticket", "notes", "history", "approvals", "relationships"):
                result = await getattr(desk, name)(ref)
                print(
                    json.dumps(
                        {"resource": name, "status": result.status, "reason": result.reason_code}
                    )
                )
                if name in {"ticket", "notes", "history"}:
                    passed = passed and result.status == "ok"
        print(json.dumps({"read_probe_passed": passed, "grant_context_verified": False}))
        return 0 if passed else 1
    finally:
        await http.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", type=Path, required=True)
    parser.add_argument("--node", default="Count All")
    parser.add_argument("--ticket-id")
    parser.add_argument("--allow-http", action="store_true")
    args = parser.parse_args()
    try:
        result = asyncio.run(verify(args))
    except Exception as exc:
        # No original exception text, upstream body, origin or credential output.
        print(json.dumps({"read_probe_passed": False, "error_type": type(exc).__name__}))
        result = 1
    raise SystemExit(result)


if __name__ == "__main__":
    main()
