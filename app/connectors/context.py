"""Compose safe read results without enrolling a workflow or authorizing a write."""

from app.connectors.http import ReadFailure, failed, ok
from app.connectors.mirza import effective_reasoning
from app.contracts.context import TicketContext


class ContextReader:
    def __init__(self, desk, directory, mirza, mattermost, mapping, reasoning_default="medium"):
        self.desk, self.directory, self.mirza, self.mattermost = desk, directory, mirza, mattermost
        self.mapping, self.reasoning_default = mapping, reasoning_default

    async def revalidate(self, name, ticket_id, observed):
        if observed.status != "ok":
            return observed
        current = await getattr(self.desk, name)(ticket_id)
        if current.status != "ok" or current.data != observed.data:
            return failed(
                "servicedesk", name, ReadFailure("unstable", name + "_changed_during_read")
            )
        return observed

    async def read(self, ticket_id, recipient_email=None, key_ref=None):
        # Sequential bounded reads keep rate/CPU/RAM usage predictable. Read back
        # the ticket after its dependent reads to detect concurrent ticket changes.
        first = await self.desk.ticket(ticket_id)
        groups = await self.desk.groups()
        templates = await self.desk.templates()
        statuses = await self.desk.statuses()
        categories = await self.desk.categories()
        notes = await self.desk.notes(ticket_id)
        history = await self.desk.history(ticket_id)
        transitions = await self.desk.transitions(ticket_id, history)
        approvals = await self.desk.approvals(ticket_id)
        relationships = await self.desk.relationships(ticket_id)
        requester_email = first.data.requester.email if first.status == "ok" else None
        recipient_email = recipient_email or requester_email
        requester = (
            await self.directory.person(requester_email)
            if requester_email
            else failed("directory", "requester", ReadFailure("invalid", "requester_email_unknown"))
        )
        recipient = (
            await self.directory.person(recipient_email)
            if recipient_email
            else failed("directory", "recipient", ReadFailure("invalid", "recipient_email_unknown"))
        )
        inventory = await self.mirza.inventory()
        mattermost_bot = await self.mattermost.bot()
        mattermost = (
            await self.mattermost.person(recipient.data.email)
            if recipient.status == "ok" and mattermost_bot.status == "ok"
            else failed(
                "mattermost", "recipient", ReadFailure("unavailable", "identity_or_bot_unverified")
            )
        )
        # Notes, approval stages/configuration and process mappings can change
        # without changing the exposed ticket revision. Recheck them separately.
        notes = await self.revalidate("notes", ticket_id, notes)
        history = await self.revalidate("history", ticket_id, history)
        approvals = await self.revalidate("approvals", ticket_id, approvals)
        relationships = await self.revalidate("relationships", ticket_id, relationships)
        if history.status == "unstable":
            transitions = failed(
                "servicedesk", "transitions",
                ReadFailure("unstable", "history_changed_during_read"),
            )
        final = await self.desk.ticket(ticket_id)
        ticket = first
        if first.status == "ok" and (
            final.status != "ok" or first.data.revision_digest != final.data.revision_digest
        ):
            ticket = failed(
                "servicedesk", "ticket", ReadFailure("unstable", "ticket_changed_during_read")
            )
        if ticket.status == "ok" and approvals.status == "ok":
            observed = approvals.data
            if (
                observed.observed_ticket_content_digest is not None
                and observed.observed_ticket_content_digest != ticket.data.content_digest
            ) or (
                observed.observed_ticket_revision_digest is not None
                and observed.observed_ticket_revision_digest != ticket.data.revision_digest
            ):
                approvals = failed(
                    "servicedesk", "approvals",
                    ReadFailure("unstable", "approval_ticket_snapshot_mismatch"),
                )
        if ticket.status == "ok" and relationships.status == "ok":
            relation = relationships.data
            if relation.process_association == "lifecycle" and relation.process_kind is not None:
                ticket = ok(
                    "servicedesk",
                    "ticket",
                    ticket.data.model_copy(
                        update={
                            "process_kind": relation.process_kind,
                            "process_verified": True,
                            "parent_id": relation.parent_id,
                            "child_ids": relation.child_ids,
                            "relationship_verified": True,
                        }
                    ),
                    ticket.evidence.contract,
                )
        mapping = self.mapping.resolve(
            recipient.data if recipient.status == "ok" else None, inventory
        )
        blockers = []
        for name, result in (
            ("ticket", ticket),
            ("groups", groups),
            ("templates", templates),
            ("statuses", statuses),
            ("categories", categories),
            ("notes", notes),
            ("history", history),
            ("transitions", transitions),
            ("approvals", approvals),
            ("relationships", relationships),
            ("requester", requester),
            ("recipient", recipient),
            ("inventory", inventory),
            ("mattermost_bot", mattermost_bot),
            ("mattermost_recipient", mattermost),
        ):
            if result.status != "ok":
                blockers.append(name + "_" + result.status)
        for name, result in (("requester", requester), ("recipient", recipient)):
            if result.status == "ok" and not result.data.eligible():
                blockers.append(name + "_employee_eligibility_unverified")
        if mapping.state != "mapped" and key_ref is None:
            blockers.append("tool_mapping_" + mapping.state)
        if history.status == "ok" and not history.data.ordering_verified:
            blockers.append("history_order_unverified")
        if approvals.status == "ok" and not (
            approvals.data.configuration_verified
            and approvals.data.terms_binding_verified
            and approvals.data.history_verified
        ):
            blockers.append("approval_authority_unverified")
        if approvals.status == "ok" and (
            approvals.data.observed_ticket_content_digest is None
            or approvals.data.observed_ticket_revision_digest is None
        ):
            blockers.append("approval_ticket_correlation_unverified")
        if ticket.status == "ok" and not ticket.data.process_verified:
            blockers.append("process_association_unverified")
        if ticket.status == "ok" and ticket.data.process_kind is not None:
            blockers.append("lifecycle_process_excluded")
        if relationships.status == "ok" and not relationships.data.coverage_verified:
            blockers.append("relationship_coverage_unverified")
        if groups.status == "ok":
            dwe = [g for g in groups.data if g.name.casefold() == "dwe"]
            if len(dwe) != 1 or not dwe[0].incharge_verified:
                blockers.append("dwe_incharge_unverified")
        reasoning = None
        if recipient.status == "ok" and inventory.status == "ok":
            owners = [
                u
                for u in inventory.data.users
                if u.email == recipient.data.email
                or (u.email is None and u.user_id.casefold() == recipient.data.email)
            ]
            if len(owners) != 1:
                blockers.append("mirza_owner_missing_or_ambiguous")
            else:
                owner = owners[0]
                by_id = {t.team_id: t for t in inventory.data.teams}
                if key_ref:
                    keys = [k for k in inventory.data.keys if k.key_ref == key_ref]
                    if (
                        len(keys) != 1
                        or keys[0].owner_id != owner.user_id
                        or keys[0].team_id not in by_id
                        or by_id[keys[0].team_id].kind != "tool"
                    ):
                        blockers.append("existing_key_owner_tool_team_unverified")
                    else:
                        # API-key scope never inherits personal/UI reasoning grants.
                        reasoning = effective_reasoning(
                            [keys[0].reasoning, by_id[keys[0].team_id].reasoning],
                            self.reasoning_default,
                        )
                elif any(team not in by_id for team in owner.team_ids):
                    blockers.append("ui_membership_catalog_incomplete")
                else:
                    reasoning = effective_reasoning(
                        [owner.reasoning]
                        + [
                            by_id[t].reasoning
                            for t in owner.team_ids
                            if by_id[t].kind == "non_tool"
                        ],
                        self.reasoning_default,
                    )
        return TicketContext(
            ticket=ticket,
            groups=groups,
            templates=templates,
            statuses=statuses,
            categories=categories,
            notes=notes,
            history=history,
            transitions=transitions,
            approvals=approvals,
            relationships=relationships,
            requester=requester,
            recipient=recipient,
            inventory=inventory,
            mattermost_bot=mattermost_bot,
            mattermost_recipient=mattermost,
            mapping=mapping,
            effective_reasoning=reasoning,
            blockers=tuple(blockers),
            read_complete=not blockers,
            grant_context_verified=False,
        )
