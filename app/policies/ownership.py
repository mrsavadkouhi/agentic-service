"""Conditional grant cleanup. Original and independently approved access survive expiry."""

import json
from copy import deepcopy
from datetime import UTC
from decimal import Decimal

from sqlalchemy import select

from app.connectors.mirza import LEVELS, effective_reasoning, reasoning
from app.contracts.tickets import AddPersonToNonToolTeam, CreateApiKey, stable_id
from app.policies.provisioning import ProvisioningBlocked, budget_target, increase_reasoning
from app.storage.lifecycle import OwnedGrant, OwnedScope


def utc(value):
    return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


def scope_ref(world_id, descriptor):
    return stable_id(world_id, "owned-scope", json.dumps(descriptor, sort_keys=True))


def scope_value(world, descriptor):
    kind, ref = descriptor["kind"], descriptor["resource"]
    if kind == "membership":
        return descriptor["selector"] in world["users"][ref]["teams"]
    if kind == "model":
        return descriptor["selector"] in world["teams"][ref]["models"]
    row = world[descriptor["collection"]][ref]
    if kind == "reasoning":
        return {
            k: deepcopy(row["metadata"][k])
            for k in ("reasoning_models", "reasoning_levels")
            if k in row["metadata"]
        }
    if kind == "budget":
        return row["max_budget"]
    if kind == "key_expiry":
        return {k: row[k] for k in ("expired", "expires", "user_id", "team_id")}
    raise ProvisioningBlocked("unknown_owned_scope")


def write_scope(world, descriptor, value):
    kind, ref = descriptor["kind"], descriptor["resource"]
    if kind in {"membership", "model"}:
        collection, field = ("users", "teams") if kind == "membership" else ("teams", "models")
        values = set(world[collection][ref][field])
        (values.add if value else values.discard)(descriptor["selector"])
        world[collection][ref][field] = sorted(values)
    elif kind == "reasoning":
        metadata = world[descriptor["collection"]][ref]["metadata"]
        for name in ("reasoning_models", "reasoning_levels"):
            metadata.pop(name, None)
        metadata.update(deepcopy(value))
    elif kind == "budget":
        world[descriptor["collection"]][ref]["max_budget"] = value
    elif kind == "key_expiry":
        world["keys"][ref]["expired"] = value["expired"]
    else:
        raise ProvisioningBlocked("unknown_owned_scope")


def combined(scope, grants):
    value = deepcopy(scope.payload["baseline"])
    kind = scope.payload["descriptor"]["kind"]
    for grant in grants:
        if kind in {"membership", "model"}:
            value = value or grant.desired["present"]
        elif kind == "reasoning":
            value = increase_reasoning(
                value, tuple(grant.desired["models"]), grant.desired["level"]
            )
        elif kind == "budget":
            value = str(max(Decimal(value), Decimal(grant.desired["limit"])))
    if kind == "key_expiry" and not grants:
        value["expired"] = True
    return value


class OwnershipLedger:
    @staticmethod
    def claim(session, record, world, descriptor, desired, expires_at):
        scope_id = scope_ref(record.world_id, descriptor)
        scope = session.get(OwnedScope, scope_id, with_for_update=True)
        value = scope_value(world, descriptor)
        versions = world.setdefault("owned_scope_versions", {})
        if scope is None:
            scope = OwnedScope(
                scope_id=scope_id,
                world_id=record.world_id,
                state="active",
                payload={
                    "descriptor": descriptor,
                    "baseline": value,
                    "expected": value,
                    "version": versions.get(scope_id, 0),
                },
            )
            session.add(scope)
            session.flush()
        if (
            scope.state != "active"
            or scope.payload["expected"] != value
            or scope.payload["version"] != versions.get(scope_id, 0)
        ):
            raise ProvisioningBlocked("owned_scope_external_change")
        grant_id = stable_id(record.operation_id, scope_id)
        if session.get(OwnedGrant, grant_id) is None:
            session.add(
                OwnedGrant(
                    grant_id=grant_id,
                    scope_id=scope_id,
                    operation_id=record.operation_id,
                    desired=desired,
                    expires_at=expires_at,
                    state="active",
                )
            )
            session.flush()
        grants = session.scalars(
            select(OwnedGrant).where(OwnedGrant.scope_id == scope_id, OwnedGrant.state == "active")
        ).all()
        expected = combined(scope, grants)
        write_scope(world, descriptor, expected)
        versions[scope_id] = versions.get(scope_id, 0) + 1
        scope.payload = {**scope.payload, "expected": expected, "version": versions[scope_id]}

    @classmethod
    def register(cls, session, record, world, job):
        expires = getattr(job, "expires_at", None)
        if isinstance(job, CreateApiKey):
            return  # Creation is registered after the new key's positive receipt exists.
        if isinstance(job, AddPersonToNonToolTeam):
            dependency = {
                "kind": "model",
                "resource": job.team_id,
                "selector": job.requested_model_id,
            }
            scope = session.get(OwnedScope, scope_ref(record.world_id, dependency))
            if scope and not scope.payload["baseline"]:
                claims = session.scalars(
                    select(OwnedGrant).where(
                        OwnedGrant.scope_id == scope.scope_id, OwnedGrant.state == "active"
                    )
                ).all()
                if not any(
                    g.expires_at is None or (expires is not None and utc(g.expires_at) >= expires)
                    for g in claims
                ):
                    raise ProvisioningBlocked("dependent_model_expiry_conflict")
            owner = next(u for u in world["users"].values() if u["user_email"] == job.person_email)
            cls.claim(
                session,
                record,
                world,
                {"kind": "membership", "resource": owner["user_id"], "selector": job.team_id},
                {"present": True},
                expires,
            )
        elif job.operation == "grant_team_model_access":
            for model in job.model_ids:
                cls.claim(
                    session,
                    record,
                    world,
                    {"kind": "model", "resource": job.team_id, "selector": model},
                    {"present": True},
                    expires,
                )
        elif hasattr(job, "reasoning_level"):
            collection = "keys" if hasattr(job, "key_ref") else "teams"
            ref = job.key_ref if collection == "keys" else job.team_id
            models = tuple(job.model_ids)
            if collection == "keys":
                inherited = effective_reasoning([reasoning(world["teams"][job.tool_team_id])])
                team_scope = session.get(
                    OwnedScope,
                    scope_ref(
                        record.world_id,
                        {"kind": "reasoning", "collection": "teams", "resource": job.tool_team_id},
                    ),
                )
                if team_scope:
                    # A temporary inherited grant cannot stand in for this key's approval.
                    inherited = effective_reasoning(
                        [reasoning({"metadata": team_scope.payload["baseline"]})]
                    )
                models = tuple(
                    m
                    for m in models
                    if LEVELS.index(inherited.models.get(m.casefold(), inherited.all_models))
                    < LEVELS.index(job.reasoning_level)
                )
            if models:
                cls.claim(
                    session,
                    record,
                    world,
                    {"kind": "reasoning", "collection": collection, "resource": ref},
                    {"models": models, "level": job.reasoning_level},
                    expires,
                )
        elif hasattr(job, "budget"):
            collection = (
                "keys"
                if hasattr(job, "key_ref")
                else ("teams" if hasattr(job, "team_id") else "users")
            )
            ref = (
                job.key_ref
                if collection == "keys"
                else (
                    job.team_id
                    if collection == "teams"
                    else next(
                        u["user_id"]
                        for u in world["users"].values()
                        if u["user_email"] == job.person_email
                    )
                )
            )
            budget_target(world[collection][ref], job.budget)  # Check before taking ownership.
            cls.claim(
                session,
                record,
                world,
                {"kind": "budget", "collection": collection, "resource": ref},
                {"limit": str(job.budget.desired_limit)},
                None,
            )

    @classmethod
    def created_key(cls, session, record, world, job, key_ref):
        cls.claim(
            session,
            record,
            world,
            {"kind": "key_expiry", "collection": "keys", "resource": key_ref},
            {},
            job.expires_at,
        )

    @staticmethod
    def expire(session, world_id, world, now):
        expired, conflicts = 0, 0
        for scope in session.scalars(
            select(OwnedScope)
            .where(OwnedScope.world_id == world_id)
            .order_by(OwnedScope.scope_id)
            .with_for_update()
        ):
            grants = session.scalars(
                select(OwnedGrant).where(
                    OwnedGrant.scope_id == scope.scope_id, OwnedGrant.state == "active"
                )
            ).all()
            due = [g for g in grants if g.expires_at and utc(g.expires_at) <= now]
            if not due:
                continue
            descriptor = scope.payload["descriptor"]
            versions = world.setdefault("owned_scope_versions", {})
            try:
                current = scope_value(world, descriptor)
            except KeyError:
                current = None
            if (
                scope.state != "active"
                or current != scope.payload["expected"]
                or versions.get(scope.scope_id, 0) != scope.payload["version"]
            ):
                scope.state = "conflict"
                conflicts += len(due)
                continue
            for grant in due:
                grant.state = "expired"
            remaining = [g for g in grants if g not in due]
            value = combined(scope, remaining)
            write_scope(world, descriptor, value)
            versions[scope.scope_id] = versions.get(scope.scope_id, 0) + 1
            scope.payload = {
                **scope.payload,
                "expected": value,
                "version": versions[scope.scope_id],
            }
            expired += len(due)
        return expired, conflicts
