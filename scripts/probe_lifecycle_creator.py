"""Verify supplied child creators with GETs; print only counts and outcome flags."""

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
from app.connectors.lifecycle import installed_lifecycle_templates  # noqa: E402
from app.connectors.servicedesk import ServiceDesk, identifier  # noqa: E402


async def verify_creator_samples(desk, ticket_ids):
    result = {"status": "invalid", "sample_count": len(ticket_ids),
              "observations_stable": False, "one_creator_observed": False}
    creator_ids = set()
    try:
        if not 2 <= len(ticket_ids) <= 20 or len(set(ticket_ids)) != len(ticket_ids):
            raise ReadFailure("invalid", "invalid_creator_sample_count")
        if any(not re.fullmatch(r"[1-9][0-9]{0,29}", ref) for ref in ticket_ids):
            raise ReadFailure("invalid", "invalid_creator_sample_identity")
        for ref in ticket_ids:
            observations = []
            for _ in range(2):
                row = desk.validate(await desk.http.get(f"/api/v3/requests/{ref}"))["request"]
                creator = identifier(row.get("created_by"))
                template = identifier(row.get("template"))
                if (
                    str(row["id"]) != ref or creator is None
                    or not re.fullmatch(r"[1-9][0-9]{0,29}", creator)
                    or template is None or template in desk.lifecycle_template_ids
                ):
                    raise ReadFailure("invalid", "child_creator_identity_unverified")
                observations.append((creator, template))
            if observations[0] != observations[1]:
                raise ReadFailure("unstable", "child_creator_changed_during_read")
            creator_ids.add(observations[0][0])
        result.update(status="ok" if len(creator_ids) == 1 else "ambiguous",
                      observations_stable=True, one_creator_observed=len(creator_ids) == 1)
        # The native account ID stays private for the following read-only check.
        return (next(iter(creator_ids)) if len(creator_ids) == 1 else None), result
    except Exception as exc:
        result["status"] = exc.status if isinstance(exc, ReadFailure) else "invalid"
        return None, result


async def verify(args):
    source = json.loads(args.workflow.read_text())
    params = next(n["parameters"] for n in source["nodes"] if n["name"] == args.node)
    url = urlsplit(params["url"].lstrip("="))
    if url.username or url.password or not url.hostname:
        raise ValueError("Invalid configured origin")
    token = next(h["value"] for h in params["headerParameters"]["parameters"]
                 if h["name"].casefold() == "authtoken")
    http = ReadOnlyHTTP(f"{url.scheme}://{url.netloc}", SecretStr(token), ServiceDesk.PATHS,
                        auth_header="authtoken", allow_http=args.allow_http)
    templates = installed_lifecycle_templates()
    desk = ServiceDesk(http, lifecycle_template_ids=templates, contract="installed")
    try:
        creator, report = await verify_creator_samples(desk, args.child_ticket_id)
        comparison = None
        if creator is not None and args.confirm_historical_creator_coverage:
            data = desk.validate(await http.get("/api/v3/requests", {
                "input_data": json.dumps({"list_info": {
                    "row_count": 25, "start_index": 1,
                    "fields_required": ["id", "template.id", "created_by.id"],
                }}),
            }))
            rows = data.get("requests")
            if not isinstance(rows, list) or len(rows) > 25:
                raise ReadFailure("invalid", "invalid_creator_comparison_window")
            ref = next((str(row["id"]) for row in rows
                        if isinstance(row, dict) and re.fullmatch(r"[1-9][0-9]{0,29}",
                                                                 str(row.get("id", "")))
                        and identifier(row.get("template")) not in templates
                        and identifier(row.get("created_by")) not in {None, creator}), None)
            if ref is not None:
                guarded = ServiceDesk(
                    http, lifecycle_template_ids=templates, contract="installed",
                    lifecycle_creator_ids=(creator,), lifecycle_creator_coverage_confirmed=True,
                )
                relation = await guarded.relationships(ref)
                comparison = {"status": relation.status,
                              "non_lifecycle_verified": bool(relation.data
                                  and relation.data.process_association == "non_lifecycle"
                                  and relation.data.coverage_verified)}
        print(json.dumps({
            "creator_samples": report,
            "comparison": comparison,
            "historical_coverage_source": "operator_confirmation"
                if args.confirm_historical_creator_coverage else "unconfigured",
            "read_probe_passed": creator is not None and (
                comparison is None or comparison["non_lifecycle_verified"]
            ),
            "grant_context_verified": False,
        }))
        return 0 if creator is not None and (
            comparison is None or comparison["non_lifecycle_verified"]
        ) else 1
    finally:
        await http.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", type=Path, required=True)
    parser.add_argument("--node", default="Count All")
    parser.add_argument("--child-ticket-id", action="append", required=True)
    parser.add_argument("--confirm-historical-creator-coverage", action="store_true")
    parser.add_argument("--allow-http", action="store_true")
    args = parser.parse_args()
    try:
        code = asyncio.run(verify(args))
    except Exception as exc:
        print(json.dumps({"read_probe_passed": False, "error_type": type(exc).__name__}))
        code = 1
    raise SystemExit(code)


if __name__ == "__main__":
    main()
