"""Group-only review payloads; no installed atomic writer exists yet."""

import re

from app.contracts.tickets import GroupCorrection


def group_only_payload(proposal: GroupCorrection, groups: dict) -> dict:
    if set(groups) != {"Helpdesk", "Network", "DWE", "VOIP"}:
        raise ValueError("Four verified support groups are required")
    if len(set(groups.values())) != 4:
        raise ValueError("Support-group IDs must be distinct")
    if (
        proposal.destination_group_id not in {groups[name] for name in ("Network", "DWE", "VOIP")}
        or not re.fullmatch(r"[1-9][0-9]{0,29}", proposal.destination_group_id)
    ):
        raise ValueError("Destination must be a verified native support-group ID")
    return {"request": {"group": {"id": proposal.destination_group_id}}}


def draft_issue(prior, packet, versions):
    """Return the local review outcome; every path remains unauthorized."""
    if prior.versions != versions:
        return "manual_review", "observation_policy_changed"
    classified = prior.classification
    if (
        prior.state != "proposed" or not isinstance(prior.proposal, GroupCorrection)
        or classified is None or classified.kind != "ordinary"
        or classified.group not in {"Network", "DWE", "VOIP"}
        or prior.proposal.destination_group_id != packet.groups[classified.group]
    ):
        return "manual_review", "group_proposal_unverified"
    if packet.relationships.process_association == "lifecycle":
        return "no_op", "excluded_lifecycle_process"
    if (not packet.relationships.coverage_verified
            or packet.relationships.process_association not in {"standalone", "non_lifecycle"}):
        return "manual_review", "process_coverage_unverified"
    if packet.ticket.technician is not None:
        return "no_op", "human_assignment_preserved"
    if packet.ticket.group_id == prior.proposal.destination_group_id:
        return "no_op", "support_group_already_correct"
    if packet.ticket.group_id != packet.groups["Helpdesk"]:
        return "no_op", "outside_helpdesk_scope"
    if packet.ticket.status_name.casefold() in {"resolved", "closed", "cancelled"}:
        return "no_op", "ticket_terminal"
    if prior.evidence_refs != packet.evidence_refs:
        return "manual_review", "observation_snapshot_changed"
    try:
        group_only_payload(prior.proposal, packet.groups)
    except ValueError:
        return "manual_review", "destination_group_unverified"
    return "blocked", "native_atomic_group_update_unverified"
