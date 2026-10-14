"""Read-only native review preparation; no inference, intake, delivery or provisioning."""

import asyncio
import re

from temporalio import activity
from temporalio.exceptions import ApplicationError

from app.connectors.http import ReadFailure
from app.connectors.mirza import catalog_state
from app.connectors.observation import ObservationSource
from app.contracts.mirza_review import MirzaReviewResult, MirzaReviewStart
from app.contracts.tickets import (
    Catalog,
    KeyMetadata,
    MirzaRequest,
    Person,
    ProcessContext,
    Team,
    TicketEvent,
    TicketSnapshot,
    stable_id,
)
from app.policies.mirza_review import review_mirza
from app.policies.tickets import POLICY_VERSION


class MirzaReviewActivities:
    def __init__(self, repository, observations, connectors, settings, versions):
        self.repository, self.observations = repository, observations
        self.source = ObservationSource(connectors, settings)
        self.versions = versions

    async def store(self, function, *args):
        try:
            return await asyncio.to_thread(function, *args)
        except Exception:
            raise ApplicationError("Mirza review storage conflict or unavailable",
                                   type="MirzaReviewStorage") from None

    @activity.defn(name="prepare_mirza_policy_review")
    async def prepare(self, request: MirzaReviewStart):
        owner = stable_id(request.tenant_id, request.ticket_id)
        review_id = stable_id("mirza-policy-review-v1", owner, request.observation_id)
        if await self.store(self.repository.get, review_id):
            return await self.store(self.repository.receipt, review_id)
        revision, state = await self.store(
            self.repository.load, request.tenant_id, request.ticket_id
        )
        persisted_state = state
        result = MirzaReviewResult(state="blocked", reason_code="mirza_proposal_unverified",
                                   next_state=state)
        identity = await self.store(self.observations.source_identity, request.observation_id)
        observed = await self.store(self.observations.get, request.observation_id)
        if (request.tenant_id == "servicedesk"
                and identity == ("servicedesk", request.ticket_id, "extract")
                and observed and observed.state == "proposed"
                and isinstance(observed.proposal, MirzaRequest)
                and observed.classification and observed.classification.kind == "mirza"
                and observed.classification.operation == observed.proposal.operation
                and observed.versions == self.versions()):
            try:
                packet = await self.source.collect(request.ticket_id)
                if observed.evidence_refs != packet.evidence_refs:
                    raise ReadFailure("unstable", "mirza_observation_snapshot_changed")
                if packet.relationships.process_association == "lifecycle":
                    result = MirzaReviewResult(state="no_op",
                                               reason_code="excluded_lifecycle_process",
                                               next_state=state, evidence_refs=packet.evidence_refs)
                else:
                    job = observed.proposal.job
                    email = getattr(job, "owner_email", getattr(job, "person_email", None))
                    context = await self.source.reader.read(
                        request.ticket_id, email, getattr(job, "key_ref", None)
                    )
                    for name in ("ticket", "groups", "templates", "requester", "recipient",
                                 "inventory", "relationships", "notes", "approvals", "history"):
                        if getattr(context, name).status != "ok":
                            raise ReadFailure("incomplete", "mirza_" + name + "_unavailable")
                    if (context.ticket.data.revision_digest != packet.ticket.revision_digest
                            or context.relationships.data != packet.relationships
                            or context.notes.data != packet.notes):
                        raise ReadFailure("unstable", "mirza_context_changed")
                    if not (context.requester.data.eligible()
                            and context.recipient.data.eligible()):
                        raise ReadFailure("invalid", "verified_intended_person")
                    catalog, state = await self.catalog(context, packet, state)
                    if (packet.ticket.template_id in catalog.dedicated_templates.values()
                            and state.first_approval_observation is None):
                        state = state.model_copy(update={
                            "first_approval_observation": context.approvals.data,
                        })
                    snapshot = TicketSnapshot(
                        revision_id=packet.ticket.revision_digest,
                        source_sequence=None, source_order_verified=False,
                        requester_ref=next(p.person_id for p in catalog.people
                                           if p.email == context.requester.data.email),
                        intended_person_ref=next((p.person_id for p in catalog.people
                                                 if p.email == email), None),
                        support_group_id=packet.ticket.group_id,
                        technician_ref=packet.ticket.technician.person_id
                        if packet.ticket.technician else None,
                        template_id=packet.ticket.template_id,
                        category_id=packet.ticket.category_id,
                        status={"Onhold": "On Hold", "On Hold": "On Hold", "Open": "Open",
                                "Resolved": "Resolved", "Closed": "Closed",
                                "Cancelled": "Cancelled"}[packet.ticket.status_name],
                        source="unknown", source_updated_at=packet.ticket.updated_at,
                        content_ref="content-" + packet.ticket.content_digest,
                        content_digest=packet.ticket.content_digest,
                        process=ProcessContext(association=packet.relationships.process_association),
                    )
                    event = TicketEvent(
                        tenant_id=request.tenant_id, ticket_id=request.ticket_id,
                        event_id="review-" + packet.input_digest, data_kind="servicedesk",
                        catalog_version=catalog.version, policy_version=POLICY_VERSION,
                        model_version=observed.versions["model"],
                        prompt_version=observed.versions["prompt"],
                        evidence_refs=packet.evidence_refs, snapshot=snapshot,
                        proposal=observed.proposal,
                    )
                    # Installed readers do not prove source sequence, original
                    # approved terms or hold/note/Open ordering. Never synthesize them.
                    result = review_mirza(event, state, catalog, context.inventory.data)
                    if state.evidence.review:
                        notes = await self.source.reader.desk.confirmation_notes(
                            request.ticket_id, state.evidence.review
                        )
                        if notes.status != "ok":
                            raise ReadFailure("incomplete", "mirza_confirmation_notes_unavailable")
                        updated_evidence = result.next_state.evidence.model_copy(update={
                            "notes": notes.data,
                        })
                        result = result.model_copy(update={
                            "next_state": result.next_state.model_copy(update={
                                "evidence": updated_evidence,
                            }),
                        })
                    current_inventory = await self.source.reader.mirza.inventory()
                    if (current_inventory.status != "ok" or catalog_state(current_inventory.data)
                            != catalog_state(context.inventory.data)):
                        raise ReadFailure("unstable", "mirza_inventory_changed")
                    current_groups = await self.source.reader.desk.groups()
                    if current_groups.status != "ok" or current_groups.data != context.groups.data:
                        raise ReadFailure("unstable", "mirza_groups_changed")
                    if not await self.source.current(packet):
                        raise ReadFailure("unstable", "mirza_context_changed")
            except Exception as error:
                reason = error.reason if isinstance(error, ReadFailure) else "mirza_context_invalid"
                # Do not publish a package built from a partial or changed snapshot.
                result = MirzaReviewResult(state="blocked", reason_code=reason,
                                           next_state=persisted_state)
        return await self.store(self.repository.commit, request, revision, result)

    async def catalog(self, context, packet, state):
        people = {p.email: Person(person_id=p.directory_id, email=p.email,
                                 department=p.department, active=p.eligible())
                  for p in (context.requester.data, context.recipient.data)}
        dedicated = packet.ticket.template_id in {
            t.template_id for t in context.templates.data
            if t.name in {"Mirza Access Request", "Mirza API Key"}
        }
        eligible = dedicated or (packet.ticket.group_id == packet.groups["Helpdesk"]
                                 and packet.ticket.technician is None)
        if eligible and state.dwe_contact is None:
            dwe = next(g for g in context.groups.data if g.group_id == packet.groups["DWE"])
            if dwe.incharge_verified and dwe.incharge and dwe.incharge.email:
                found = await self.source.reader.directory.person(dwe.incharge.email)
                if (found.status == "ok" and found.data.eligible()
                        and found.data.email == dwe.incharge.email):
                    state = state.model_copy(update={
                        "dwe_contact": dwe.incharge,
                        "dwe_observed_at": context.groups.evidence.observed_at,
                        "dwe_source_digest": context.groups.evidence.digest
                        or stable_id(str(dwe)),
                        "tracking": state.tracking.model_copy(update={
                            "original_dwe_incharge_ref": dwe.incharge.person_id,
                        }),
                    })
        for contact in (packet.ticket.technician, state.dwe_contact):
            if contact and contact.email:
                found = await self.source.reader.directory.person(contact.email)
                if (found.status == "ok" and found.data.eligible()
                        and found.data.email == contact.email):
                    people[contact.email] = Person(person_id=contact.person_id, email=contact.email,
                                                   department=found.data.department, active=True)
        inventory = context.inventory.data
        owner_ids = {u.user_id: u.email or u.user_id.casefold() for u in inventory.users
                     if (u.email or u.user_id.casefold()) in people}
        tool_teams = {t.team_id for t in inventory.teams if t.kind == "tool"}
        mappings = {}
        for person in (context.requester.data, context.recipient.data):
            mapping = self.source.reader.mapping.resolve(person, context.inventory)
            if mapping.state == "mapped":
                mappings[person.department] = mapping.tool_team_id
        return Catalog(
            version="mirza-review-catalog-v1", environment="production",
            support_groups=packet.groups,
            dedicated_templates={t.name: t.template_id for t in context.templates.data
                                 if t.name in {"Mirza Access Request", "Mirza API Key"}},
            people=tuple(people.values()),
            teams=tuple(Team(
                team_id=t.team_id, alias=t.alias if re.fullmatch(
                    r"[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,199}", t.alias
                ) else "team-" + stable_id(t.alias), kind=t.kind,
                models=tuple(m for m in t.models if m in inventory.served_models),
            ) for t in inventory.teams),
            keys=tuple(KeyMetadata(key_ref=k.key_ref, owner_email=owner_ids[k.owner_id],
                                   tool_team_id=k.team_id, expired=k.expired)
                       for k in inventory.keys
                       if k.owner_id in owner_ids and k.team_id in tool_teams),
            model_ids=inventory.served_models,
            reasoning_levels=("none", "minimal", "low", "medium", "high", "xhigh"),
            department_tool_teams=mappings,
            dwe_incharge_ref=state.tracking.original_dwe_incharge_ref,
        ), state
