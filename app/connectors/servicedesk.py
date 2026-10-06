"""ServiceDesk v3 candidates; history/process authority needs installed verification."""

import json
import re
from datetime import UTC, datetime

from app.connectors.http import ReadFailure, failed, ok
from app.connectors.lifecycle import mentions_onboarding_child, onboarding_children
from app.contracts.context import (
    ApprovalObservation,
    ApprovalRead,
    ApprovalStage,
    DeskCatalogItem,
    DeskGroup,
    DeskHistoryEvent,
    DeskHistoryRead,
    DeskNote,
    DeskPerson,
    DeskTemplate,
    DeskTicket,
    HistoryStatusChange,
    RelationshipRead,
)
from app.contracts.tickets import stable_id


def identity(value):
    if not isinstance(value, dict) or value.get("id") is None:
        raise ReadFailure("invalid", "missing_servicedesk_identity")
    return DeskPerson(person_id=str(value["id"]), email=value.get("email_id"))


def timestamp(value):
    if value is None:
        return None
    if not isinstance(value, dict) or not str(value.get("value", "")).isdigit():
        raise ReadFailure("invalid", "invalid_source_timestamp")
    return datetime.fromtimestamp(int(value["value"]) / 1000, UTC)


def identifier(value):
    return str(value["id"]) if isinstance(value, dict) and value.get("id") is not None else None


def approval_state(value):
    name = str((value or {}).get("name", "")).strip().casefold()
    if name in {"approved", "rejected"}:
        return name
    if name in {"pending approval", "pending clarification", "to be sent", "pending"}:
        return "pending"
    return "unknown"


def ticket_digests(row):
    content_fields = ("subject", "description", "udf_fields", "resources")
    revision_fields = (
        "id", *content_fields, "last_updated_time", "created_by", "created_time",
        "requester", "technician", "group", "template", "category", "status",
        "linked_to_request", "has_linked_requests", "lifecycle",
    )
    return tuple(
        stable_id(json.dumps({key: row.get(key) for key in fields}, sort_keys=True))
        for fields in (content_fields, revision_fields)
    )


class ServiceDesk:
    PATHS = (
        r"/api/v3/requests",
        r"/api/v3/requests/[0-9]+",
        r"/api/v3/requests/[0-9]+/(notes|history|approval_levels|linked_requests)",
        r"/api/v3/requests/[0-9]+/notes/[0-9]+",
        r"/api/v3/(support_groups|group_roles|request_templates|users|statuses|categories)",
        r"/api/v3/support_groups/[0-9]+",
        r"/api/v3/request_templates/[0-9]+",
        r"/api/v3/requests/[0-9]+/approval_levels/[0-9]+/approvals",
    )

    def __init__(
        self,
        http,
        *,
        page_size=100,
        max_pages=40,
        contract="candidate",
        lifecycle_template_ids=None,
        offboarding=None,
        onboarding=None,
        lifecycle_creator_ids=(),
    ):
        self.http, self.page_size, self.max_pages = http, page_size, max_pages
        self.contract = contract
        self.lifecycle_template_ids = lifecycle_template_ids or {}
        self.offboarding = offboarding
        self.onboarding = onboarding
        if any(
            not isinstance(ref, str) or not re.fullmatch(r"[1-9][0-9]{0,29}", ref)
            for ref in lifecycle_creator_ids
        ):
            raise ValueError("Invalid lifecycle creator configuration")
        self.lifecycle_creator_ids = frozenset(lifecycle_creator_ids)

    @staticmethod
    def validate(data):
        if not isinstance(data, dict):
            raise ReadFailure("invalid", "invalid_servicedesk_envelope")
        statuses = data.get("response_status")
        statuses = statuses if isinstance(statuses, list) else [statuses]
        if not statuses or any(
            not isinstance(s, dict)
            or str(s.get("status_code")) != "2000"
            or s.get("status") != "success"
            for s in statuses
        ):
            raise ReadFailure("unavailable", "servicedesk_application_error")
        return data

    async def pages(self, path, key, *, criteria=None, fields=None):
        output, seen = [], set()
        for page in range(self.max_pages):
            info = {
                "row_count": self.page_size,
                "start_index": page * self.page_size + 1,
                "sort_field": "id",
                "sort_order": "asc",
            }
            if criteria is not None:
                info["search_criteria"] = criteria
            if fields is not None:
                info["fields_required"] = fields
            data = self.validate(
                await self.http.get(path, {"input_data": json.dumps({"list_info": info})})
            )
            rows, listing = data.get(key), data.get("list_info")
            if not isinstance(rows, list) or not isinstance(listing, dict):
                raise ReadFailure("incomplete", "missing_pagination_contract")
            if type(listing.get("has_more_rows")) is not bool or len(rows) > self.page_size:
                raise ReadFailure("incomplete", "unverified_pagination_end")
            for row in rows:
                if not isinstance(row, dict) or row.get("id") is None:
                    raise ReadFailure("invalid", "missing_list_identity")
                row_id = str(row["id"])
                if row_id in seen:
                    raise ReadFailure("unstable", "repeated_pagination_identity")
                seen.add(row_id)
            output.extend(rows)
            if listing["has_more_rows"] is False:
                return output
            if not rows:
                raise ReadFailure("incomplete", "empty_nonterminal_page")
        raise ReadFailure("incomplete", "pagination_limit")

    async def list_requests(self, criteria=None):
        try:
            rows = await self.pages("/api/v3/requests", "requests", criteria=criteria)
            return ok("servicedesk", "requests", tuple(str(r["id"]) for r in rows), self.contract)
        except Exception as exc:
            return failed("servicedesk", "requests", exc)

    async def groups(self):
        try:
            rows = await self.pages("/api/v3/support_groups", "support_groups")
            result = []
            for row in rows:
                charge = None
                verified = False
                if row["name"].strip().casefold() in {"helpdesk", "network", "dwe", "voip"}:
                    detail = self.validate(
                        await self.http.get(f"/api/v3/support_groups/{row['id']}")
                    )["support_group"]
                    if str(detail["id"]) != str(row["id"]):
                        raise ReadFailure("invalid", "wrong_group_identity")
                    roles = detail.get("role_associations")
                    if not isinstance(roles, list):
                        raise ReadFailure("invalid", "group_role_associations_missing")
                    # Build 15100 exposes the operator's incharge_group through
                    # its native Group Incharge role, rather than a direct field.
                    matching = [
                        role
                        for role in roles
                        if isinstance(role, dict)
                        and isinstance(role.get("group_role"), dict)
                        and role["group_role"].get("display_name") == "$GROUP_INCHARGE$"
                    ]
                    if len(matching) == 1:
                        charge = matching[0].get("user")
                        verified = isinstance(charge, dict) and charge.get("id") is not None
                result.append(
                    DeskGroup(
                        group_id=str(row["id"]),
                        name=row["name"],
                        incharge=identity(charge) if verified else None,
                        incharge_verified=verified,
                    )
                )
            return ok("servicedesk", "groups", tuple(result), self.contract)
        except Exception as exc:
            return failed("servicedesk", "groups", exc)

    async def templates(self):
        try:
            rows = await self.pages("/api/v3/request_templates", "request_templates")
            return ok(
                "servicedesk",
                "templates",
                tuple(DeskTemplate(template_id=str(r["id"]), name=r["name"]) for r in rows),
                self.contract,
            )
        except Exception as exc:
            return failed("servicedesk", "templates", exc)

    async def user(self, email):
        try:
            rows = await self.pages(
                "/api/v3/users",
                "users",
                criteria={"field": "email_id", "condition": "is", "value": email},
            )
            exact = [
                r for r in rows if str(r.get("email_id", "")).strip().casefold() == email.casefold()
            ]
            if len(exact) != 1:
                raise ReadFailure("not_found" if not exact else "ambiguous", "email_not_unique")
            return ok("servicedesk", "user", identity(exact[0]), self.contract)
        except Exception as exc:
            return failed("servicedesk", "user", exc)

    async def named_catalog(self, resource):
        try:
            if resource not in {"statuses", "categories"}:
                raise ReadFailure("invalid", "catalog_not_allowed")
            rows = await self.pages(f"/api/v3/{resource}", resource)
            items = tuple(DeskCatalogItem(item_id=str(r["id"]), name=r["name"]) for r in rows)
            return ok("servicedesk", resource, items, self.contract)
        except Exception as exc:
            return failed("servicedesk", resource, exc)

    async def statuses(self):
        return await self.named_catalog("statuses")

    async def categories(self):
        return await self.named_catalog("categories")

    async def ticket(self, ticket_id):
        try:
            data = self.validate(await self.http.get(f"/api/v3/requests/{ticket_id}"))
            row = data["request"]
            if str(row["id"]) != ticket_id:
                raise ReadFailure("invalid", "wrong_ticket_identity")
            template_id = identifier(row.get("template"))
            # Only an authoritative template-ID catalog can establish lifecycle roots.
            kind = self.lifecycle_template_ids.get(template_id)
            person = identity(row["requester"])
            content_digest, revision_digest = ticket_digests(row)
            ticket = DeskTicket(
                ticket_id=ticket_id,
                requester=person,
                group_id=identifier(row.get("group")),
                technician=identity(row["technician"]) if row.get("technician") else None,
                template_id=template_id,
                category_id=identifier(row.get("category")),
                status_id=identifier(row.get("status")),
                status_name=(row.get("status") or {}).get("name"),
                updated_at=timestamp(row.get("last_updated_time")),
                content_digest=content_digest,
                revision_digest=revision_digest,
                parent_id=None,
                child_ids=(),
                relationship_verified=False,
                process_kind=kind,
                process_verified=kind is not None,
                created_by_id=identifier(row.get("created_by")),
                created_at=timestamp(row.get("created_time")),
            )
            return ok("servicedesk", "ticket", ticket, self.contract)
        except Exception as exc:
            return failed("servicedesk", "ticket", exc)

    async def notes(self, ticket_id):
        try:
            rows = await self.pages(f"/api/v3/requests/{ticket_id}/notes", "notes")
            notes = []
            for listed in rows:
                row = self.validate(
                    await self.http.get(f"/api/v3/requests/{ticket_id}/notes/{listed['id']}")
                )["note"]
                if str(row["id"]) != str(listed["id"]):
                    raise ReadFailure("invalid", "note_identity_mismatch")
                if "description" not in row:
                    raise ReadFailure("invalid", "note_description_missing")
                if identifier(row.get("request")) != ticket_id:
                    raise ReadFailure("invalid", "note_request_mismatch")
                notes.append(
                    DeskNote(
                        note_id=str(row["id"]),
                        author_id=identifier(row.get("added_by")),
                        updated_by_id=identifier(row.get("last_updated_by")),
                        added_at=timestamp(row.get("added_time")),
                        updated_at=timestamp(row.get("last_updated_time")),
                        content_digest=stable_id(str(row["description"])),
                    )
                )
            return ok("servicedesk", "notes", tuple(notes), self.contract)
        except Exception as exc:
            return failed("servicedesk", "notes", exc)

    async def history(self, ticket_id):
        try:
            rows = await self.pages(f"/api/v3/requests/{ticket_id}/history", "history")
            events = []
            for row in rows:
                if identifier(row.get("request")) != ticket_id:
                    raise ReadFailure("invalid", "history_request_mismatch")
                diffs = row.get("diff")
                if not isinstance(diffs, list):
                    raise ReadFailure("invalid", "history_diff_shape")
                fields, changes = [], []
                for diff in diffs:
                    field = diff["field"]["name"]
                    if not isinstance(field, str) or not field:
                        raise ReadFailure("invalid", "history_field_name_missing")
                    # Some installed history entries use prose in field.name.
                    # Keep machine names, hash prose that may contain note text
                    # or employee details, and never parse it as a status event.
                    fields.append(
                        field
                        if re.fullmatch(r"[a-z][a-z0-9_.]{0,119}", field)
                        else "history-field-" + stable_id(field)
                    )
                    if field == "status":
                        changes.append(
                            HistoryStatusChange(
                                before_status_id=identifier(diff.get("previous_value")),
                                after_status_id=identifier(diff.get("current_value")),
                            )
                        )
                events.append(
                    DeskHistoryEvent(
                        event_id=str(row["id"]),
                        actor_id=identifier(row.get("by")),
                        occurred_at=timestamp(row.get("time")),
                        operation=row["operation"],
                        fields=tuple(fields),
                        status_changes=tuple(changes),
                        content_digest=stable_id(json.dumps(row, sort_keys=True)),
                    )
                )
            return ok(
                "servicedesk", "history", DeskHistoryRead(events=tuple(events)), self.contract
            )
        except Exception as exc:
            return failed("servicedesk", "history", exc)

    async def transitions(self, ticket_id, history=None):
        # A timestamp or display-text "Open" is not an ordered actor/status proof.
        # Read the candidate endpoint, but never infer authority from an unknown shape.
        try:
            history = history or await self.history(ticket_id)
            if history.status != "ok":
                raise ReadFailure(history.status, history.reason_code)
            raise ReadFailure("unsupported", "history_actor_order_contract_unverified")
        except Exception as exc:
            return failed("servicedesk", "transitions", exc)

    async def approvals(self, ticket_id):
        try:
            ticket = self.validate(await self.http.get(f"/api/v3/requests/{ticket_id}"))["request"]
            if str(ticket["id"]) != ticket_id:
                raise ReadFailure("invalid", "approval_request_mismatch")
            template = identifier(ticket.get("template"))
            if template is None:
                raise ReadFailure("unsupported", "approval_template_unknown")
            definition = self.validate(
                await self.http.get(f"/api/v3/request_templates/{template}")
            )["request_template"]
            if str(definition["id"]) != template:
                raise ReadFailure("invalid", "approval_template_mismatch")
            configured = definition.get("approval_levels")
            if not isinstance(configured, list):
                raise ReadFailure("unsupported", "configured_approval_levels_unknown")
            levels = tuple(int(level["level"]) for level in configured)
            if len(set(levels)) != len(levels) or any(level not in range(1, 6) for level in levels):
                raise ReadFailure("invalid", "configured_approval_levels_invalid")
            rows = await self.pages(
                f"/api/v3/requests/{ticket_id}/approval_levels", "approval_levels"
            )
            stages = []
            for row in rows:
                if identifier(row.get("request")) != ticket_id:
                    raise ReadFailure("invalid", "approval_level_request_mismatch")
                for flag in ("deleted", "is_current"):
                    if type(row.get(flag)) is not bool:
                        raise ReadFailure("invalid", "approval_level_flags_unknown")
                children = await self.pages(
                    f"/api/v3/requests/{ticket_id}/approval_levels/{row['id']}/approvals",
                    "approvals",
                )
                observations = []
                for child in children:
                    if identifier(child.get("approval_level")) != str(row["id"]):
                        raise ReadFailure("invalid", "approval_child_level_mismatch")
                    if type(child.get("deleted")) is not bool:
                        raise ReadFailure("invalid", "approval_deleted_unknown")
                    observations.append(
                        ApprovalObservation(
                            approval_id=str(child["id"]),
                            approver_id=identifier(child.get("approver")),
                            action_by_id=identifier(child.get("action_by")),
                            action_at=timestamp(child.get("action_taken_on")),
                            state=approval_state(child.get("status")),
                            deleted=child["deleted"],
                        )
                    )
                rule = row.get("rule") or {}
                stages.append(
                    ApprovalStage(
                        stage_id=str(row["id"]),
                        level=row["level"],
                        state=approval_state(row.get("status")),
                        deleted=row["deleted"],
                        is_current=row["is_current"],
                        rule_type=rule.get("type"),
                        rule_value=rule.get("value"),
                        approver_ids=tuple(
                            o.approver_id for o in observations if o.approver_id and not o.deleted
                        ),
                        approvals=tuple(observations),
                    )
                )
            current = [s for s in stages if s.is_current and not s.deleted]
            configuration_verified = bool(levels) and sorted(s.level for s in current) == sorted(
                levels
            )
            content_digest, revision_digest = ticket_digests(ticket)
            result = ApprovalRead(
                stages=tuple(stages),
                configured_levels=levels,
                configured_stage_ids=tuple(s.stage_id for s in current if s.level in levels),
                configuration_verified=configuration_verified,
                terms_binding_verified=False,
                history_verified=False,
                configuration_digest=stable_id(json.dumps(configured, sort_keys=True)),
                observed_ticket_content_digest=content_digest,
                observed_ticket_revision_digest=revision_digest,
            )
            return ok("servicedesk", "approvals", result, self.contract)
        except Exception as exc:
            return failed("servicedesk", "approvals", exc)

    async def offboarding_relationships(self, ticket_id, *, root=False):
        return await self.database_relationships(
            self.offboarding, ticket_id, "offboarding", root=root
        )

    async def onboarding_relationships(self, ticket_id, *, root=False):
        return await self.database_relationships(
            self.onboarding, ticket_id, "onboarding", root=root
        )

    async def database_relationships(self, reader, ticket_id, kind, *, root=False):
        if reader is None:
            return None
        first = await reader.read(ticket_id)
        if first.status != "ok":
            raise ReadFailure(first.status, first.reason_code)
        if not first.data:
            if root and kind == "offboarding":
                raise ReadFailure("incomplete", "offboarding_root_mapping_missing")
            return None
        parents, children = [], ()
        for process in first.data:
            if root:
                if process.parent_id != ticket_id:
                    raise ReadFailure("invalid", kind + "_root_is_child")
                children = process.child_ids
            else:
                parent = self.validate(
                    await self.http.get(f"/api/v3/requests/{process.parent_id}")
                )["request"]
                if str(parent["id"]) != process.parent_id or self.lifecycle_template_ids.get(
                    identifier(parent.get("template"))
                ) != kind:
                    raise ReadFailure("invalid", kind + "_parent_template_mismatch")
                parents.append(process.parent_id)
        final = await reader.read(ticket_id)
        if final.status != "ok" or final.data != first.data:
            raise ReadFailure("unstable", kind + "_mapping_changed_during_read")
        parents = tuple(sorted(set(parents)))
        return RelationshipRead(
            parent_id=parents[0] if len(parents) == 1 else None,
            parent_ids=parents,
            child_ids=children,
            process_association="lifecycle",
            process_kind=kind,
            source=kind + "_database",
            coverage_verified=False,
            evidence_ref=stable_id(str(first.data)),
        )

    async def relationships(self, ticket_id):
        try:
            if not self.lifecycle_template_ids:
                raise ReadFailure("unsupported", "lifecycle_catalog_not_configured")
            row = self.validate(await self.http.get(f"/api/v3/requests/{ticket_id}"))["request"]
            if str(row["id"]) != ticket_id:
                raise ReadFailure("invalid", "wrong_ticket_identity")
            kind = self.lifecycle_template_ids.get(identifier(row.get("template")))
            if kind is not None:
                if kind == "offboarding":
                    relationship = await self.offboarding_relationships(ticket_id, root=True)
                    if relationship is not None:
                        return ok("servicedesk", "relationships", relationship, self.contract)
                if kind == "onboarding" and not (row.get("udf_fields") or {}).get("udf_sline_6601"):
                    relationship = await self.onboarding_relationships(ticket_id, root=True)
                    if relationship is not None:
                        return ok("servicedesk", "relationships", relationship, self.contract)
                children = ()
                related_roots = ()
                source = "root_template"
                if kind == "onboarding":
                    udf = row.get("udf_fields") or {}
                    raw = udf.get("udf_sline_4217")
                    # Call-center roots refer to an ordinary onboarding root;
                    # they need not contain the packed child field themselves.
                    bridge = udf.get("udf_sline_6601")
                    if not raw and bridge is not None:
                        if not isinstance(bridge, str) or not re.fullmatch(r"[0-9]{1,30}", bridge):
                            raise ReadFailure("invalid", "invalid_onboarding_root_bridge")
                        if bridge == ticket_id:
                            raise ReadFailure("invalid", "self_referencing_lifecycle_root")
                        other = self.validate(
                            await self.http.get(f"/api/v3/requests/{bridge}")
                        )["request"]
                        other_udf = other.get("udf_fields") or {}
                        if (
                            str(other["id"]) != bridge
                            or self.lifecycle_template_ids.get(identifier(other.get("template")))
                            != "onboarding"
                            or other_udf.get("udf_sline_10449") != ticket_id
                        ):
                            raise ReadFailure("invalid", "onboarding_root_bridge_not_reciprocal")
                        raw = other_udf.get("udf_sline_4217")
                        children = onboarding_children(raw)
                        related_roots = (bridge,)
                        source = "onboarding_root_bridge"
                    if raw:
                        children = onboarding_children(raw)
                        if ticket_id in children or any(r in children for r in related_roots):
                            raise ReadFailure("invalid", "self_referencing_lifecycle_root")
                result = RelationshipRead(
                    parent_id=None,
                    child_ids=children,
                    related_root_ids=related_roots,
                    process_association="lifecycle",
                    process_kind=kind,
                    source=source,
                    coverage_verified=False,
                    evidence_ref=stable_id(json.dumps(row.get("udf_fields"), sort_keys=True)),
                )
                return ok("servicedesk", "relationships", result, self.contract)

            relationship = await self.offboarding_relationships(ticket_id)
            onboarding = await self.onboarding_relationships(ticket_id)
            if relationship is not None and onboarding is not None:
                raise ReadFailure("ambiguous", "multiple_lifecycle_process_kinds")
            if relationship is not None or onboarding is not None:
                return ok("servicedesk", "relationships", relationship or onboarding, self.contract)
            parents = []
            for template_id, root_kind in self.lifecycle_template_ids.items():
                if root_kind != "onboarding":
                    continue
                rows = await self.pages(
                    "/api/v3/requests",
                    "requests",
                    criteria=[{"field": "template.id", "condition": "eq", "value": template_id}],
                    fields=["id", "template.id", "udf_fields.udf_sline_4217"],
                )
                for root in rows:
                    # Never trust a server filter alone: existing views record
                    # ServiceDesk search predicates escaping their template scope.
                    if identifier(root.get("template")) != template_id:
                        raise ReadFailure("invalid", "lifecycle_template_filter_mismatch")
                    raw = (root.get("udf_fields") or {}).get("udf_sline_4217")
                    if not mentions_onboarding_child(raw, ticket_id):
                        continue
                    children = onboarding_children(raw)
                    if str(root["id"]) in children:
                        raise ReadFailure("invalid", "self_referencing_lifecycle_root")
                    if ticket_id in children:
                        # Re-read the matched root instead of trusting a list
                        # projection that might have changed during pagination.
                        detail = self.validate(
                            await self.http.get(f"/api/v3/requests/{root['id']}")
                        )["request"]
                        if str(detail["id"]) != str(root["id"]):
                            raise ReadFailure("invalid", "wrong_lifecycle_root_identity")
                        if identifier(detail.get("template")) != template_id or (
                            (detail.get("udf_fields") or {}).get("udf_sline_4217") != raw
                        ):
                            raise ReadFailure("unstable", "lifecycle_root_changed_during_read")
                        parents.append(str(root["id"]))
            if not parents:
                # A dedicated producer may create a child before its mapping is
                # saved, or leave it unregistered after failed persistence. This
                # identifies a review blocker, never positive process membership.
                if identifier(row.get("created_by")) in self.lifecycle_creator_ids:
                    raise ReadFailure("incomplete", "n8n_created_ticket_mapping_unconfirmed")
                # Offboarding children live in a separate automation database,
                # so even a complete onboarding scan cannot establish absence.
                reason = (
                    "offboarding_relationship_source_unconfigured" if self.offboarding is None
                    else "lifecycle_absence_contract_unverified"
                )
                raise ReadFailure("incomplete", reason)
            parents = tuple(sorted(set(parents)))
            result = RelationshipRead(
                parent_id=parents[0] if len(parents) == 1 else None,
                parent_ids=parents,
                child_ids=(),
                process_association="lifecycle",
                process_kind="onboarding",
                source="onboarding_udf_index",
                coverage_verified=False,
                evidence_ref=stable_id(ticket_id, *parents),
            )
            return ok("servicedesk", "relationships", result, self.contract)
        except Exception as exc:
            return failed("servicedesk", "relationships", exc)
