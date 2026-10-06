import json

from app.contracts.context import ToolMapping


class DepartmentMap:
    def __init__(self, path):
        source = json.loads(path.read_text())
        self.version = source["policy_version"]
        self.approved = {}
        for row in source["mappings"]:
            if row.get("approved") is True and row.get("review_state") == "approved":
                target = row["approved_tool_team"]
                key = row["department"].strip().casefold()
                if key in self.approved or target["kind"] != "tool":
                    raise ValueError("Ambiguous department map")
                self.approved[key] = target["team_id"]

    def resolve(self, person, inventory, *, ticket_team_id=None, note_mapping_verified=False):
        department = person.department if person else None
        result = dict(
            version=self.version, department=department, tool_team_id=None, ticket_scoped=False
        )
        if person is None or not person.eligible() or inventory.status != "ok":
            return ToolMapping(
                **result, state="unavailable", reason_code="identity_or_catalog_unavailable"
            )
        target = self.approved.get((department or "").strip().casefold())
        if ticket_team_id is not None:
            if not note_mapping_verified:
                return ToolMapping(
                    **result, state="clarification", reason_code="mapping_note_unverified"
                )
            target = ticket_team_id
            result["ticket_scoped"] = True
        if target is None:
            return ToolMapping(
                **result, state="clarification", reason_code="department_mapping_missing"
            )
        teams = [t for t in inventory.data.teams if t.team_id == target]
        if len(teams) != 1 or teams[0].kind != "tool":
            return ToolMapping(
                **result, state="clarification", reason_code="mapped_tool_team_absent_or_invalid"
            )
        if teams[0].alias.casefold() == "tapsibox-manager-tool":
            return ToolMapping(**result, state="manual", reason_code="manager_team_manual")
        result["tool_team_id"] = target
        return ToolMapping(**result, state="mapped", reason_code="verified_existing_tool_team")
