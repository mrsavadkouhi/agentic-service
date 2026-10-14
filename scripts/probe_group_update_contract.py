"""Read installed request validators/schema; never attempt a write to test a predicate."""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import SecretStr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.connectors.http import ReadFailure, ReadOnlyHTTP  # noqa: E402
from app.connectors.servicedesk import ServiceDesk  # noqa: E402

FIELDS = {"id", "group", "technician", "last_updated_time", "revision", "version", "etag"}
TYPES = {"long", "datetime", "lookup", "string", "boolean", "integer", "text", "html",
         "udf", "unknown", "float", "double", "int", "object", "array"}


def safe_definition(value):
    result = {}
    if isinstance(value.get("type"), str) and value["type"] in TYPES:
        result["type"] = value["type"]
    for flag in ("read_only", "is_read_only", "readonly"):
        if isinstance(value.get(flag), bool):
            result[flag] = value[flag]
    return result


def schema_fields(value):
    found = {}
    stack = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        if depth > 12:
            raise ValueError("Schema nesting exceeds the diagnostic bound")
        if isinstance(item, dict):
            field = item.get("name") or item.get("field_name")
            if isinstance(field, str) and field in FIELDS:
                found[field] = safe_definition(item)
            for key, child in item.items():
                if key in FIELDS and isinstance(child, dict):
                    found[key] = safe_definition(child)
                if isinstance(child, (dict, list)):
                    stack.append((child, depth + 1))
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item if isinstance(child, (dict, list)))
    return found


async def run(args):
    if not re.fullmatch(r"[1-9][0-9]{0,29}", args.ticket_id):
        raise ValueError("Invalid request reference")
    source = json.loads(args.workflow.read_text())
    params = next(node for node in source["nodes"] if node["name"] == "Count All")["parameters"]
    origin = urlsplit(params["url"].lstrip("="))
    if not origin.hostname or origin.username or origin.password:
        raise ValueError("Invalid configured origin")
    token = next(header["value"] for header in params["headerParameters"]["parameters"]
                 if header["name"].casefold() == "authtoken")
    path = "/api/v3/requests/" + args.ticket_id
    http = ReadOnlyHTTP(
        f"{origin.scheme}://{origin.netloc}", SecretStr(token),
        (re.escape(path), r"/api/v3/requests/_metainfo"), auth_header="authtoken",
        allow_http=args.allow_http, attempts=1, timeout=8,
    )
    validators = {}

    async def headers(response):
        if response.request.url.path == path:
            etag = response.headers.get("etag")
            validators.update({"etag_present": etag is not None,
                               "strong_etag_present": bool(etag and not etag.startswith("W/")),
                               "last_modified_header_present": "last-modified" in response.headers})

    http.client.event_hooks["response"].append(headers)
    try:
        row = ServiceDesk.validate(await http.get(path))["request"]
        if str(row["id"]) != args.ticket_id:
            raise ValueError("Request identity mismatch")
        metadata = await http.get("/api/v3/requests/_metainfo")
        report = {
            "request_get_succeeded": True, "metadata_get_succeeded": True,
            "response_validators": validators,
            "technician_field_present": "technician" in row,
            "inspected_schema_fields": schema_fields(metadata),
            "atomic_update_contract_verified": False, "write_requests": 0,
            "note": "Read metadata/header presence does not verify conditional update enforcement.",
        }
        if args.report:
            args.report.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report))
    except ReadFailure as error:
        print(json.dumps({
            "read_probe_available": False, "reason": error.reason, "write_requests": 0
        }))
        raise SystemExit(1) from None
    finally:
        await http.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", type=Path, required=True)
    parser.add_argument("--ticket-id", required=True)
    parser.add_argument("--allow-http", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception as error:
        print(json.dumps({"read_probe_available": False, "error_type": type(error).__name__}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
