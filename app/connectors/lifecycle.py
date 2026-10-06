"""Installed lifecycle exclusions; an absent match never proves standalone intake."""

import json
import re
from pathlib import Path

from app.connectors.http import ReadFailure


def installed_lifecycle_templates():
    catalog = Path(__file__).resolve().parents[2] / "docs" / "servicedesk-catalog.json"
    return json.loads(catalog.read_text())["lifecycle_root_exclusions"]


def mentions_onboarding_child(raw, ticket_id):
    if not isinstance(raw, str):
        return False
    keys = {"office_id", "ex_id", "helpdesk_id", "viop_id", "voip_id"}
    for part in raw.split("|"):
        key, separator, value = part.partition(":")
        if separator and key.strip().lower() in keys and value.strip() == ticket_id:
            return True
    return False


def onboarding_children(raw):
    # This is the packed field used by the existing onboarding views. Status
    # strings are deliberately ignored; only explicitly named child IDs count.
    if raw is None or raw == "":
        raise ReadFailure("incomplete", "onboarding_children_not_recorded")
    if not isinstance(raw, str):
        raise ReadFailure("invalid", "onboarding_children_shape")
    values = {}
    roles = {"office", "ex", "helpdesk", "viop", "voip"}
    for part in raw.split("|"):
        key, separator, value = part.partition(":")
        key, value = key.strip().lower(), value.strip()
        if not separator or key in values or key not in {
            f"{role}_{suffix}" for role in roles for suffix in ("id", "status")
        }:
            raise ReadFailure("invalid", "onboarding_children_shape")
        values[key] = value
    children = []
    for role in ("office", "ex", "helpdesk"):
        value = values.get(f"{role}_id")
        if not value or not re.fullmatch(r"[0-9]{1,30}", value):
            raise ReadFailure("incomplete", "onboarding_child_id_missing")
        children.append(value)
    voip = [values[key] for key in ("viop_id", "voip_id") if key in values]
    if not voip or any(not re.fullmatch(r"[0-9]{1,30}", v) for v in voip):
        raise ReadFailure("incomplete", "onboarding_child_id_missing")
    if len(set(voip)) != 1:
        raise ReadFailure("ambiguous", "conflicting_voip_child_ids")
    children.append(voip[0])
    if len(set(children)) != len(children):
        raise ReadFailure("ambiguous", "duplicate_onboarding_child_id")
    return tuple(children)
