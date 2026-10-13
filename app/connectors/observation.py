"""Bounded in-memory source text; no raw content is persisted or returned to Temporal."""

import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

from app.connectors.http import ReadFailure
from app.connectors.servicedesk import identifier, ticket_digests
from app.contracts.tickets import Catalog, KeyMetadata, Person, Team, stable_id

MAX_TEXT_BYTES = 12000
MAX_SCOPE_BYTES = 8192


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"p", "div", "br"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def sanitize_text(value, secrets=()):
    parser = PlainText()
    parser.feed(value)
    text = "".join(parser.parts)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[credential removed]")
    text = re.sub(r"\bsk-[A-Za-z0-9_\-]+", "[key removed]", text)
    text = re.sub(r"(?i)\bBearer\s+[^\s<>]+", "[credential removed]", text)
    text = re.sub(r"(?i)(https?://)[^\s/@]+:[^\s/@]+@", r"\1[credentials removed]@", text)
    text = re.sub(
        r"\beyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", "[credential removed]", text
    )
    text = re.sub(
        r"(?i)\b(?:password|passwd|secret|token|authtoken|api[_ -]?key|authorization)"
        r'["\']?\s*[=:]\s*["\']?[^\s,"\'<>}]+',
        "[credential removed]",
        text,
    )
    # Oversized inputs are incomplete, never silently truncated into a different request.
    if len(text.encode()) > MAX_TEXT_BYTES:
        raise ReadFailure("incomplete", "observation_text_limit")
    return text


@dataclass(repr=False)
class ObservationPacket:
    ticket: object
    relationships: object
    notes: tuple
    groups: dict
    dwe_contact: str | None
    text: str = field(repr=False)
    input_digest: str
    evidence_refs: tuple[str, ...]
    tracked_handoff: bool = False


class ObservationSource:
    def __init__(self, connectors, settings):
        self.reader, self.settings = connectors.reader, settings

    async def candidates(self):
        desk = self.reader.desk
        groups = await desk.groups()
        if groups.status != "ok":
            raise ReadFailure("unavailable", "support_groups_unavailable")
        helpdesk = [g for g in groups.data if g.name.casefold() == "helpdesk"]
        if len(helpdesk) != 1:
            raise ReadFailure("ambiguous", "helpdesk_identity_unverified")
        result = set()
        for name, ref in (
            ("group", helpdesk[0].group_id),
            ("template", "11401"),
            ("template", "11702"),
        ):
            rows = await desk.pages(
                "/api/v3/requests",
                "requests",
                criteria=[
                    {
                        "field": name + ".id",
                        "condition": "eq",
                        "value": ref,
                    }
                ],
            )
            for row in rows:
                if identifier(row.get(name)) != ref:
                    raise ReadFailure("invalid", "candidate_filter_scope_mismatch")
                ticket_id = str(row["id"])
                if not re.fullmatch(r"[1-9][0-9]{0,29}", ticket_id):
                    raise ReadFailure("invalid", "invalid_candidate_identity")
                if (row.get("status") or {}).get("name", "").casefold() not in {
                    "resolved",
                    "closed",
                    "cancelled",
                }:
                    result.add(ticket_id)
        return sorted(result, key=int)

    async def collect(self, ticket_id):
        desk = self.reader.desk
        ticket = await desk.ticket(ticket_id)
        if ticket.status != "ok":
            raise ReadFailure(ticket.status, "ticket_unavailable")
        groups = await desk.groups()
        if groups.status != "ok":
            raise ReadFailure(groups.status, "groups_unavailable")
        identities = {}
        for name in ("Helpdesk", "Network", "DWE", "VOIP"):
            matches = [g for g in groups.data if g.name.casefold() == name.casefold()]
            if len(matches) != 1:
                raise ReadFailure("ambiguous", "group_identity_unverified")
            identities[name] = matches[0]
        relationships = await desk.relationships(ticket_id)
        if relationships.status != "ok":
            raise ReadFailure(relationships.status, "process_association_unverified")
        if relationships.data.process_association not in {
            "lifecycle",
            "non_lifecycle",
            "standalone",
        }:
            raise ReadFailure("incomplete", "process_association_unverified")
        if relationships.data.process_association != "lifecycle" and not (
            relationships.data.coverage_verified
        ):
            raise ReadFailure("incomplete", "process_coverage_unverified")
        if relationships.data.process_association == "lifecycle":
            return ObservationPacket(
                ticket=ticket.data,
                relationships=relationships.data,
                notes=(),
                text="",
                groups={name: group.group_id for name, group in identities.items()},
                dwe_contact=None,
                input_digest=stable_id(ticket.data.revision_digest, str(relationships.data)),
                evidence_refs=(ticket.data.revision_digest, relationships.evidence.digest),
            )
        if (
            ticket.data.group_id is None
            or ticket.data.template_id is None
            or ticket.data.status_name is None
            or ticket.data.updated_at is None
        ):
            raise ReadFailure("incomplete", "ticket_metadata_incomplete")
        row = desk.validate(await desk.http.get(f"/api/v3/requests/{ticket_id}"))["request"]
        records = await desk._note_records(
            ticket_id, max_records=50, max_content_bytes=MAX_TEXT_BYTES
        )
        _, revision = ticket_digests(row)
        if str(row["id"]) != ticket_id or revision != ticket.data.revision_digest:
            raise ReadFailure("unstable", "observation_ticket_changed")
        content = json.dumps(
            {key: row.get(key) for key in ("subject", "description", "udf_fields", "resources")},
            ensure_ascii=False,
            sort_keys=True,
        )
        content += "\nNotes:\n" + "\n".join(body for _, body in records)
        secret_values = tuple(
            token.get_secret_value()
            for token in (
                self.settings.inference_token,
                self.settings.servicedesk_read_token,
                self.settings.mirza_read_token,
                self.settings.directory_read_token,
                self.settings.mattermost_read_token,
            )
            if token
        )
        text = sanitize_text(content, secret_values)
        note_refs = tuple(note.content_digest for note, _ in records)
        packet = ObservationPacket(
            ticket=ticket.data,
            relationships=relationships.data,
            notes=tuple(note for note, _ in records),
            groups={name: group.group_id for name, group in identities.items()},
            dwe_contact=(
                identities["DWE"].incharge.person_id
                if identities["DWE"].incharge_verified
                else None
            ),
            text=text,
            input_digest=stable_id(
                ticket.data.revision_digest,
                str(relationships.data),
                str(groups.data),
                str(tuple(note for note, _ in records)),
            ),
            evidence_refs=(ticket.data.revision_digest, relationships.evidence.digest, *note_refs),
        )
        if not await self.current(packet):
            raise ReadFailure("unstable", "observation_changed_during_read")
        return packet

    async def current(self, packet):
        desk = self.reader.desk
        ticket = await desk.ticket(packet.ticket.ticket_id)
        notes = await desk.notes(packet.ticket.ticket_id)
        relationships = await desk.relationships(packet.ticket.ticket_id)
        return (
            ticket.status == notes.status == relationships.status == "ok"
            and ticket.data.revision_digest == packet.ticket.revision_digest
            and notes.data == packet.notes
            and relationships.data == packet.relationships
        )

    async def mirza_scope(self, packet):
        reader = self.reader
        inventory = await reader.mirza.inventory()
        if inventory.status != "ok":
            raise ReadFailure(inventory.status, "mirza_inventory_unavailable")
        emails = set(re.findall(r"[^\s\"'<>:,]+@[^\s\"'<>:,]+\.[A-Za-z]{2,}", packet.text))
        if packet.ticket.requester.email:
            emails.add(packet.ticket.requester.email)
        if len(emails) > 3:
            raise ReadFailure("ambiguous", "too_many_intended_people")
        people, displays, mapped, baselines = [], [], {}, {}
        users = inventory.data.users
        selected_teams = set()
        for email in sorted(emails):
            found = await reader.directory.person(email)
            if found.status != "ok" or not found.data.eligible():
                continue
            person = found.data
            people.append(
                Person(
                    person_id=person.directory_id,
                    email=person.email,
                    department=person.department,
                    active=True,
                )
            )
            mapping = reader.mapping.resolve(person, inventory)
            if mapping.state == "mapped":
                mapped[person.department] = mapping.tool_team_id
                selected_teams.add(mapping.tool_team_id)
            owner = [
                u
                for u in users
                if u.email == person.email
                or (u.email is None and u.user_id.casefold() == person.email)
            ]
            if len(owner) == 1:
                selected_teams.update(owner[0].team_ids)
                baselines[person.email] = owner[0].budget.limit
            displays.append(
                {
                    "email": person.email,
                    "department": person.department,
                    "mapped_tool_team": mapping.tool_team_id,
                    "mapping": mapping.state,
                }
            )
        teams = [
            t
            for t in inventory.data.teams
            if t.team_id in selected_teams
            or (len(t.alias) > 3 and t.alias.casefold() in packet.text.casefold())
            or t.team_id in packet.text
        ]
        if len(teams) > 20:
            raise ReadFailure("incomplete", "scoped_team_limit")
        by_id = {t.team_id: t for t in teams}
        owners = {p.email for p in people}
        owner_ids = {
            u.user_id: u.email or u.user_id.casefold()
            for u in users
            if (u.email or u.user_id.casefold()) in owners
        }
        keys = [k for k in inventory.data.keys if k.owner_id in owner_ids and k.team_id in by_id]
        if len(keys) > 20:
            raise ReadFailure("incomplete", "scoped_key_limit")
        for team in teams:
            baselines[team.team_id] = team.budget.limit
        for key in keys:
            baselines[key.key_ref] = key.budget.limit
        catalog = Catalog(
            version="observation-scoped-v1",
            environment="production",
            support_groups=packet.groups,
            dedicated_templates={"Mirza Access Request": "11702", "Mirza API Key": "11401"},
            people=tuple(people),
            teams=tuple(
                Team(
                    team_id=t.team_id,
                    alias=(
                        t.alias
                        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,199}", t.alias)
                        else "team-" + stable_id(t.alias)
                    ),
                    kind=t.kind,
                    models=tuple(m for m in t.models if m in inventory.data.served_models),
                )
                for t in teams
            ),
            keys=tuple(
                KeyMetadata(
                    key_ref=k.key_ref,
                    owner_email=owner_ids[k.owner_id],
                    tool_team_id=k.team_id,
                    expired=k.expired,
                )
                for k in keys
            ),
            model_ids=inventory.data.served_models,
            reasoning_levels=("none", "minimal", "low", "medium", "high", "xhigh"),
            department_tool_teams={d: t for d, t in mapped.items() if t in by_id},
            dwe_incharge_ref=packet.dwe_contact,
        )
        projection = {
            "people": displays,
            "teams": [
                {"team_id": t.team_id, "alias": t.alias, "kind": t.kind, "models": t.models}
                for t in teams
            ],
            "keys": [k.model_dump(mode="json") for k in catalog.keys],
            "served_models": catalog.model_ids,
            "budget_baselines": {
                ref: str(limit) if limit is not None else None for ref, limit in baselines.items()
            },
            "purpose_ref": "purpose-" + packet.ticket.content_digest,
        }
        encoded = json.dumps(projection, ensure_ascii=False, sort_keys=True)
        if len(encoded.encode()) > MAX_SCOPE_BYTES:
            raise ReadFailure("incomplete", "agent_scope_limit")
        tokens = tuple(
            t.get_secret_value()
            for t in (
                self.settings.inference_token,
                self.settings.servicedesk_read_token,
                self.settings.mirza_read_token,
                self.settings.directory_read_token,
            )
            if t
        )
        return catalog, sanitize_text(encoded, tokens), baselines
