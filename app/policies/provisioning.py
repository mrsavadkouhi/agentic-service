"""Narrow mutation helpers matching Mirza scope and reasoning semantics."""

from copy import deepcopy
from decimal import Decimal

from app.connectors.mirza import LEVELS, effective_reasoning, reasoning


class ProvisioningBlocked(ValueError):
    """Fixed policy reasons only; source/credential text must not appear here."""


class LostFixtureResponse(Exception):
    pass


class FulfillmentBusy(Exception):
    pass


def increase_reasoning(metadata: dict, models: tuple[str, ...], level: str) -> dict:
    current = reasoning({"metadata": metadata})
    effective = effective_reasoning([current])
    requested = {
        model: max(
            (level, effective.models.get(model.casefold(), effective.all_models)), key=LEVELS.index
        )
        for model in models
    }
    if all(
        value == effective.models.get(model.casefold(), effective.all_models)
        for model, value in requested.items()
    ):
        return deepcopy(metadata)
    result = deepcopy(metadata)
    grants = deepcopy(result.get("reasoning_models", {}))
    if current.all_models:
        grants["*"] = [current.all_models]
    result.pop("reasoning_levels", None)
    for model, value in requested.items():
        for old in tuple(grants):
            if old.casefold() == model.casefold():
                del grants[old]
        grants[model] = [value]
    result["reasoning_models"] = grants
    return result


def budget_target(row: dict, budget) -> str:
    if row.get("max_budget") is None:
        raise ProvisioningBlocked("budget_baseline_unknown")
    current = Decimal(str(row["max_budget"]))
    if current >= budget.desired_limit:
        return str(current)
    if current != budget.baseline_limit:
        raise ProvisioningBlocked("budget_baseline_changed")
    return str(budget.desired_limit)


def recipient_id(world: dict, email: str) -> str:
    matches = world["mattermost_people"].get(email, [])
    if (
        len(matches) != 1
        or matches[0]["email"] != email
        or not matches[0]["active"]
        or matches[0]["is_bot"]
    ):
        raise ProvisioningBlocked("delivery_recipient_unverified")
    return matches[0]["user_id"]


def completion_text(ticket_id, ticket_link, description, summary):
    return (
        f"Mirza request #{ticket_id} completed: {ticket_link}. "
        f"Request: {description}. Work done: {summary}."
    )
