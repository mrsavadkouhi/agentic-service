"""Read installed approval/history evidence; emit counts and verification flags."""

import argparse
import asyncio
import json
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import SecretStr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.connectors.http import ReadOnlyHTTP  # noqa: E402
from app.connectors.servicedesk import ServiceDesk  # noqa: E402


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
    desk = ServiceDesk(http, contract="installed")
    try:
        first = await desk.ticket(args.ticket_id)
        notes = await desk.notes(args.ticket_id)
        history = await desk.history(args.ticket_id)
        approvals = await desk.approvals(args.ticket_id)
        final_notes = await desk.notes(args.ticket_id)
        final_history = await desk.history(args.ticket_id)
        final_approvals = await desk.approvals(args.ticket_id)
        final = await desk.ticket(args.ticket_id)
        events = history.data.events if history.data else ()
        stages = approvals.data.stages if approvals.data else ()
        actions = [a for s in stages for a in s.approvals if not a.deleted]
        timestamp_counts = Counter(e.occurred_at for e in events)
        changes = [change for e in events for change in e.status_changes]
        stable = (first.status == final.status == "ok"
                  and first.data.revision_digest == final.data.revision_digest)
        notes_stable = (notes.status == final_notes.status == "ok"
                        and notes.data == final_notes.data)
        history_stable = (history.status == final_history.status == "ok"
                          and history.data == final_history.data)
        approvals_stable = (approvals.status == final_approvals.status == "ok"
                            and approvals.data == final_approvals.data)
        correlated = (
            first.status == approvals.status == "ok"
            and approvals.data.observed_ticket_content_digest == first.data.content_digest
            and approvals.data.observed_ticket_revision_digest == first.data.revision_digest
        )
        passed = stable and notes_stable and history_stable and approvals_stable and correlated
        print(json.dumps({
            "ticket_status": first.status, "notes_status": notes.status,
            "history_status": history.status, "approvals_status": approvals.status,
            "ticket_revision_stable": stable,
            "note_observation_stable": notes_stable,
            "history_observation_stable": history_stable,
            "approval_observation_stable": approvals_stable,
            "approval_observed_ticket_correlated": correlated,
            "dedicated_mirza_template": first.status == "ok"
                and first.data.template_id in {"11401", "11702"},
            "note_count": len(notes.data) if notes.data is not None else None,
            "notes_with_author": sum(n.author_id is not None for n in notes.data or ()),
            "history_event_count": len(events),
            "history_events_missing_actor": sum(e.actor_id is None for e in events),
            "history_same_timestamp_groups": sum(n > 1 for n in timestamp_counts.values()),
            "structured_status_change_count": len(changes),
            "status_changes_with_both_ids": sum(
                c.before_status_id is not None and c.after_status_id is not None for c in changes),
            "configured_approval_levels": len(approvals.data.configured_levels)
                if approvals.data else None,
            "approval_configuration_verified": bool(approvals.data
                and approvals.data.configuration_verified),
            "current_approval_stages": sum(s.is_current and not s.deleted for s in stages),
            "approved_current_stages": sum(
                s.is_current and not s.deleted and s.state == "approved" for s in stages),
            "approved_items": sum(a.state == "approved" for a in actions),
            "approved_items_with_actor_and_time": sum(a.state == "approved"
                and a.action_by_id is not None and a.action_at is not None for a in actions),
            "history_ordering_verified": bool(history.data and history.data.ordering_verified),
            "approval_terms_binding_verified": bool(approvals.data
                and approvals.data.terms_binding_verified),
            "read_probe_passed": passed, "grant_context_verified": False,
        }))
        return 0 if passed else 1
    finally:
        await http.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", type=Path, required=True)
    parser.add_argument("--node", default="Count All")
    parser.add_argument("--ticket-id", required=True)
    parser.add_argument("--allow-http", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9]{1,30}", args.ticket_id):
        parser.error("Invalid ticket reference")
    try:
        code = asyncio.run(verify(args))
    except Exception as exc:
        print(json.dumps({"read_probe_passed": False, "error_type": type(exc).__name__}))
        code = 1
    raise SystemExit(code)


if __name__ == "__main__":
    main()
