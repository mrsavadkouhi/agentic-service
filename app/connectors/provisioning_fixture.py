"""Persistent, network-free downstream simulator. No production adapter exists here."""

from copy import deepcopy
from decimal import Decimal

from app.connectors.mirza import budget, moment, reasoning
from app.connectors.observation import sanitize_text
from app.contracts.context import MirzaInventory, MirzaKey, MirzaTeam, MirzaUser
from app.contracts.tickets import Catalog, KeyMetadata, Person, Team, stable_id


def fixture_world(catalog: Catalog) -> dict:
    if catalog.environment != "synthetic" or any(
        not person.email.endswith(".invalid") for person in catalog.people
    ):
        raise ValueError("Only generated fixture identities are permitted")
    common = {
        "max_budget": "10",
        "spend": "0",
        "budget_duration": "30d",
        "budget_reset_at": None,
        "metadata": {"keep": "fixture-unrelated"},
    }
    users = {
        "fixture-user-" + stable_id(p.email): {
            **deepcopy(common),
            "user_id": "fixture-user-" + stable_id(p.email),
            "user_email": p.email,
            "teams": [],
            "models": ["preserved-person-model-field"],
        }
        for p in catalog.people
    }
    by_email = {row["user_email"]: row for row in users.values()}
    teams = {
        t.team_id: {
            **deepcopy(common),
            "team_id": t.team_id,
            "team_alias": t.alias,
            "kind": t.kind,
            "models": list(t.models),
        }
        for t in catalog.teams
    }
    keys = {}
    for k in catalog.keys:
        owner = by_email[k.owner_email]
        owner["teams"] = sorted(set(owner["teams"]) | {k.tool_team_id})
        keys[k.key_ref] = {
            **deepcopy(common),
            "key_ref": k.key_ref,
            "user_id": owner["user_id"],
            "team_id": k.tool_team_id,
            "expires": "2000-01-01T00:00:00+00:00" if k.expired else None,
            "expired": k.expired,
            "models": ["preserved-key-model-field"],
        }
    return {
        "catalog": catalog.model_dump(mode="json"),
        "users": users,
        "teams": teams,
        "keys": keys,
        "served_models": list(catalog.model_ids),
        "tickets": {},
        "receipts": {},
        "service_actor_ref": "fixture-agent",
        "descriptions": {},
        "directory_flags": {
            p.email: {"enabled": p.active, "expired": False, "matches": 1} for p in catalog.people
        },
        "bot": {"username": "servicedesk_agent", "active": True, "is_bot": True},
        "mattermost_people": {
            p.email: [
                {
                    "user_id": "fixture-mm-" + stable_id(p.email),
                    "email": p.email,
                    "active": True,
                    "is_bot": False,
                }
            ]
            for p in catalog.people
        },
        "faults": {},
    }


def inventory(world: dict) -> MirzaInventory:
    return MirzaInventory(
        users=tuple(
            MirzaUser(
                user_id=u["user_id"],
                email=u["user_email"],
                team_ids=tuple(u["teams"]),
                budget=budget(u),
                reasoning=reasoning(u),
            )
            for u in world["users"].values()
        ),
        teams=tuple(
            MirzaTeam(
                team_id=t["team_id"],
                alias=t["team_alias"],
                kind=t["kind"],
                models=tuple(t["models"]),
                budget=budget(t),
                reasoning=reasoning(t),
            )
            for t in world["teams"].values()
        ),
        keys=tuple(
            MirzaKey(
                key_ref=k["key_ref"],
                owner_id=k["user_id"],
                team_id=k["team_id"],
                expired=k["expired"],
                expires_at=moment(k["expires"]),
                budget=budget(k),
                reasoning=reasoning(k),
            )
            for k in world["keys"].values()
        ),
        served_models=tuple(world["served_models"]),
    )


def current_catalog(world: dict, current: MirzaInventory) -> Catalog:
    base = Catalog.model_validate(world["catalog"])
    users = {u.user_id: u.email for u in current.users}
    return Catalog.model_validate(
        {
            **base.model_dump(),
            "people": tuple(
                Person(
                    **{
                        **p.model_dump(),
                        "active": p.active
                        and world["directory_flags"][p.email]["enabled"]
                        and not world["directory_flags"][p.email]["expired"]
                        and world["directory_flags"][p.email]["matches"] == 1,
                    }
                )
                for p in base.people
            ),
            "teams": tuple(
                Team(team_id=t.team_id, alias=t.alias, kind=t.kind, models=t.models)
                for t in current.teams
            ),
            "keys": tuple(
                KeyMetadata(
                    key_ref=k.key_ref,
                    owner_email=users[k.owner_id],
                    tool_team_id=k.team_id,
                    expired=k.expired,
                )
                for k in current.keys
            ),
        }
    )


def fixture_description(value: str) -> str:
    return sanitize_text(value)


def has_budget(row: dict) -> bool:
    return row["max_budget"] is None or Decimal(str(row["spend"])) < Decimal(str(row["max_budget"]))
