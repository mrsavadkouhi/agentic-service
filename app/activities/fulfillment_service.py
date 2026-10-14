"""Local synthetic provisioning/delivery with durable claims and downstream receipts.

The fixture world is NOT a Mirza database. All effects are confined to dedicated
application fixture tables; no HTTP/SSH connectors or model clients are imported.
"""

import secrets
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.mirza import LEVELS, effective_reasoning, reasoning
from app.connectors.provisioning_fixture import (
    current_catalog,
    fixture_description,
    fixture_world,
    has_budget,
    inventory,
)
from app.contracts.mirza_review import MirzaReviewState
from app.contracts.provisioning import FulfillmentReceipt
from app.contracts.tickets import (
    AddPersonToNonToolTeam,
    CreateApiKey,
    MirzaRequest,
    NewToolTeam,
    TicketEvent,
    digest,
    stable_id,
)
from app.policies.mirza_review import review_mirza
from app.policies.ownership import OwnershipLedger
from app.policies.provisioning import (
    FulfillmentBusy,
    LostFixtureResponse,
    ProvisioningBlocked,
    budget_target,
    completion_text,
    increase_reasoning,
    recipient_id,
)
from app.storage.provisioning import (
    FixtureMessage,
    FixtureWorld,
    FulfillmentRecord,
    FulfillmentStep,
    ProvisioningSecret,
)


class FixtureFulfillmentService:
    def __init__(self, engine, cipher):
        self.engine, self.cipher = engine, cipher

    def seed(
        self,
        normalized,
        catalog,
        authorization_state=None,
        *,
        world_id=None,
        description="Synthetic approved Mirza request",
    ):
        if (
            normalized.data_kind != "synthetic"
            or catalog.environment != "synthetic"
            or not normalized.tenant_id.startswith("fulfillment-fixture-")
            or not isinstance(normalized.proposal, MirzaRequest)
            or normalized.proposal.job is None
        ):
            raise ValueError("Only explicit generated fulfillment fixtures may be seeded")
        generated = fixture_world(catalog)  # Reject real directory identities before storage.
        job = normalized.proposal.job
        operation_id = stable_id("fixture-fulfillment-v1", normalized.workflow_id(), digest(job))
        world_id = world_id or stable_id("fixture-world", normalized.workflow_id())
        with Session(self.engine) as session, session.begin():
            existing = session.get(FulfillmentRecord, operation_id)
            if existing:
                return operation_id
            row = session.get(FixtureWorld, world_id, with_for_update=True)
            if row is None:
                row = FixtureWorld(world_id=world_id, revision=0, payload=generated)
                session.add(row)
                session.flush()
            world = deepcopy(row.payload)
            observed = inventory(world)
            auth = authorization_state or MirzaReviewState()
            result = review_mirza(normalized, auth, current_catalog(world, observed), observed)
            if result.state not in {"ready", "no_op"} or result.package is None:
                raise ProvisioningBlocked(result.reason_code)
            if result.state == "no_op" and result.reason_code not in {
                "additional_key_unnecessary",
                "requested_access_already_present",
            }:
                raise ProvisioningBlocked("fixture_authorization_unverified")
            # Keep the authorization's prior sequence, while pinning exact review identities.
            tracking = auth.tracking.model_copy(
                update={
                    name: getattr(result.next_state.tracking, name)
                    for name in (
                        "original_dwe_incharge_ref",
                        "ticket_mapping_terms_digest",
                        "additional_key_terms_digest",
                    )
                }
            )
            auth = result.next_state.model_copy(update={"tracking": tracking})
            world["tickets"][normalized.workflow_id()] = normalized.model_dump(mode="json")
            world["descriptions"][normalized.workflow_id()] = fixture_description(description)
            row.payload = world
            owner_email = getattr(job, "owner_email", getattr(job, "person_email", None))
            owner_email = owner_email or next(
                p.email for p in catalog.people if p.person_id == normalized.snapshot.requester_ref
            )
            session.add(
                FulfillmentRecord(
                    operation_id=operation_id,
                    world_id=world_id,
                    state="planned",
                    reason_code="seeded",
                    payload={
                        "event": normalized.model_dump(mode="json"),
                        "authorization": auth.model_dump(mode="json"),
                        "package": result.package.model_dump(mode="json"),
                        "job_digest": digest(job),
                        "owner_email": owner_email,
                        "owner_dm_ref": recipient_id(world, owner_email),
                        "target_team_models": world["teams"][job.team_id]["models"]
                        if isinstance(job, AddPersonToNonToolTeam)
                        else [],
                        "skip_mutation": result.reason_code == "additional_key_unnecessary",
                        "completion_explanation_ref": result.completion_explanation_ref,
                        "commands": {},
                        "command_claims": {},
                    },
                )
            )
        return operation_id

    @staticmethod
    def context(record, world):
        original = TicketEvent.model_validate(record.payload["event"])
        event = TicketEvent.model_validate(world["tickets"][original.workflow_id()])
        job = original.proposal.job
        if (
            event.tenant_id != original.tenant_id
            or event.ticket_id != original.ticket_id
            or event.data_kind != "synthetic"
            or not isinstance(event.proposal, MirzaRequest)
            or event.proposal.job is None
            or digest(event.proposal.job) != record.payload["job_digest"]
        ):
            raise ProvisioningBlocked("approved_terms_changed")
        auth = MirzaReviewState.model_validate(record.payload["authorization"])
        service = world["service_actor_ref"]
        if (
            (auth.evidence.baseline and service in auth.evidence.baseline.original_approver_ids)
            or (event.fallback_approval and event.fallback_approval.actor_ref == service)
            or (event.clarification and event.clarification.note_author_ref == service)
        ):
            raise ProvisioningBlocked("agent_cannot_approve_own_work")
        current = inventory(world)
        if isinstance(job, CreateApiKey):
            key_proof = world["receipts"].get(stable_id(record.operation_id, "mutation", ""), {})
            team_proof = world["receipts"].get(stable_id(record.operation_id, "tool_team", ""), {})
            excluded_keys = (
                {key_proof["key_ref"]}
                if (key_proof.get("operation_id") == record.operation_id and "key_ref" in key_proof)
                else set()
            )
            excluded_teams = (
                {team_proof["team_id"]}
                if (
                    team_proof.get("operation_id") == record.operation_id
                    and "team_id" in team_proof
                )
                else set()
            )
            # Only this operation's positively correlated resources are hidden from
            # the pre-creation duplicate/absent-team checks. Full state is verified below.
            current = current.model_copy(
                update={
                    "keys": tuple(k for k in current.keys if k.key_ref not in excluded_keys),
                    "teams": tuple(t for t in current.teams if t.team_id not in excluded_teams),
                    "users": tuple(
                        u.model_copy(
                            update={
                                "team_ids": tuple(
                                    ref for ref in u.team_ids if ref not in excluded_teams
                                )
                            }
                        )
                        for u in current.users
                    ),
                }
            )
        catalog = current_catalog(world, current)
        checked = review_mirza(event, auth, catalog, current)
        if checked.state not in {"ready", "no_op"} or checked.package is None:
            raise ProvisioningBlocked(checked.reason_code)
        expiry = getattr(job, "expires_at", None)
        if expiry is not None and expiry.tzinfo is None:
            raise ProvisioningBlocked("expiry_timezone_unspecified")
        if (
            getattr(job, "expires_at", None) is not None
            and not isinstance(job, CreateApiKey)
            and job.expires_at <= datetime.now(UTC)
        ):
            raise ProvisioningBlocked("requested_grant_expiry_elapsed")
        if (
            isinstance(job, CreateApiKey)
            and job.expires_at is not None
            and job.expires_at <= datetime.now(UTC)
        ):
            raise ProvisioningBlocked("requested_key_expiry_elapsed")
        if hasattr(job, "key_ref") and world["keys"][job.key_ref]["expired"]:
            raise ProvisioningBlocked("existing_key_expired")
        if not record.payload["skip_mutation"] and (
            isinstance(job, AddPersonToNonToolTeam)
            or (isinstance(job, CreateApiKey) and not isinstance(job.tool_team, NewToolTeam))
        ):
            team_id = (
                job.team_id if isinstance(job, AddPersonToNonToolTeam) else job.tool_team.team_id
            )
            approved = set(record.payload["package"]["models_before"])
            if isinstance(job, AddPersonToNonToolTeam):
                # Membership grants the entire team, not a personal model list.
                base = original.proposal.job.team_id
                approved = set(record.payload["target_team_models"])
                team_id = base
            if set(world["teams"][team_id]["models"]) != approved:
                raise ProvisioningBlocked("approved_team_model_scope_changed")
        if (
            world["bot"] != {"username": "servicedesk_agent", "active": True, "is_bot": True}
            or recipient_id(world, record.payload["owner_email"]) != record.payload["owner_dm_ref"]
        ):
            raise ProvisioningBlocked("delivery_identity_changed")
        return event, job, catalog

    @staticmethod
    def owner(world, email):
        rows = [u for u in world["users"].values() if u["user_email"] == email]
        if len(rows) != 1:
            raise ProvisioningBlocked("verified_owner_missing_or_ambiguous")
        return rows[0]

    @staticmethod
    def tool_team_id(job, operation_id):
        return (
            "fixture-tool-" + stable_id(operation_id)
            if isinstance(job.tool_team, NewToolTeam)
            else job.tool_team.team_id
        )

    @staticmethod
    def step_id(operation_id, phase, recipient=""):
        return stable_id(operation_id, phase, recipient)

    def staff(self, record, event, catalog, world):
        auth = MirzaReviewState.model_validate(record.payload["authorization"])
        contact = event.snapshot.technician_ref or auth.tracking.original_dwe_incharge_ref
        person = next((p for p in catalog.people if p.person_id == contact and p.active), None)
        if person is None:
            raise ProvisioningBlocked("completion_contact_unverified")
        return recipient_id(world, person.email)

    def phase(self, record, event, job, catalog, world):
        phases = []
        if isinstance(job, CreateApiKey) and not record.payload["skip_mutation"]:
            if isinstance(job.tool_team, NewToolTeam):
                phases.append(("tool_team", ""))
            phases.append(("owner_membership", ""))
        phases.extend(
            (
                ("mutation", ""),
                ("user_dm", record.payload["owner_dm_ref"]),
                ("staff_dm", self.staff(record, event, catalog, world)),
                ("resolve", ""),
            )
        )
        for phase, recipient in phases:
            key = self.step_id(record.operation_id, phase, recipient)
            if key not in world["receipts"]:
                return phase, recipient, key
        return None

    def advance(self, operation_id, command_index=None):
        phase, recipient, step_id, claim = "", "", "", uuid4().hex
        try:
            with Session(self.engine) as session, session.begin():
                record = session.get(FulfillmentRecord, operation_id, with_for_update=True)
                if record is None:
                    raise ProvisioningBlocked("unknown_fixture_operation")
                row = session.get(FixtureWorld, record.world_id, with_for_update=True)
                world = deepcopy(row.payload)
                self.reconcile(session, record, world)
                if command_index is None:
                    command_index = len(record.payload.get("command_claims", {}))
                cached = record.payload.get("commands", {}).get(str(command_index))
                if cached:
                    return FulfillmentReceipt(**cached)
                if record.state in {"completed", "blocked", "cancelled"}:
                    return FulfillmentReceipt(operation_id, record.state, "", record.reason_code)
                event, job, catalog = self.context(record, world)
                pending = self.phase(record, event, job, catalog, world)
                if pending is None:
                    record.state, record.reason_code = "completed", "resolved_fixture"
                    return FulfillmentReceipt(
                        operation_id, "completed", "resolve", "resolved_fixture"
                    )
                phase, recipient, step_id = pending
                payload = deepcopy(record.payload)
                existing_claim = payload.setdefault("command_claims", {}).get(str(command_index))
                if existing_claim is not None and existing_claim != step_id:
                    raise ProvisioningBlocked("command_claim_changed")
                step = session.get(FulfillmentStep, step_id, with_for_update=True)
                if step:
                    until = step.lease_until
                    until = until.replace(tzinfo=UTC) if until and until.tzinfo is None else until
                    if step.state == "claimed" and until and until > datetime.now(UTC):
                        raise FulfillmentBusy
                    # No positive downstream receipt: never repeat an uncertain create/post.
                    raise ProvisioningBlocked("unreconciled_fixture_outcome")
                session.add(
                    FulfillmentStep(
                        step_id=step_id,
                        operation_id=operation_id,
                        phase=phase,
                        state="claimed",
                        claim_ref=claim,
                        lease_until=datetime.now(UTC) + timedelta(seconds=60),
                    )
                )
                payload["command_claims"][str(command_index)] = step_id
                record.payload = payload
            # Claim is durable before the simulated downstream transaction.
            lost = False
            with Session(self.engine) as session, session.begin():
                record = session.get(FulfillmentRecord, operation_id, with_for_update=True)
                if record.state == "cancelled":
                    return FulfillmentReceipt(operation_id, "cancelled", "", "operator_cancelled")
                row = session.get(FixtureWorld, record.world_id, with_for_update=True)
                step = session.get(FulfillmentStep, step_id, with_for_update=True)
                if step.claim_ref != claim or step.state != "claimed":
                    raise ProvisioningBlocked("stale_fulfillment_claim")
                world = deepcopy(row.payload)
                event, job, catalog = self.context(record, world)
                selected = self.phase(record, event, job, catalog, world)
                if selected != (phase, recipient, step_id):
                    raise ProvisioningBlocked("fulfillment_context_changed")
                fault = world["faults"].get(phase)
                if fault == "before":
                    world["faults"].pop(phase)
                    step.state = "uncertain"
                    lost = True
                else:
                    proof = self.effect(
                        session, record, world, event, job, catalog, phase, recipient
                    )
                    world["receipts"][step_id] = {
                        **proof,
                        "operation_id": operation_id,
                        "phase": phase,
                    }
                    step.state = "verified"
                    if fault == "after":
                        world["faults"].pop(phase)
                        step.state, lost = "uncertain", True
                    record.state = "completed" if phase == "resolve" else "running"
                    record.reason_code = (
                        "resolved_fixture" if phase == "resolve" else "fixture_phase_done"
                    )
                    payload = deepcopy(record.payload)
                    payload["lifecycle_revision"] = payload.get("lifecycle_revision", 0) + 1
                    if phase == "resolve":
                        payload["completed_at"] = datetime.now(UTC).isoformat()
                    payload.setdefault("commands", {})[str(command_index)] = asdict(
                        FulfillmentReceipt(
                            operation_id,
                            "completed" if phase == "resolve" else "running",
                            phase,
                            "fixture_phase_done",
                        )
                    )
                    record.payload = payload
                row.revision += 1
                row.payload = world
            if lost:
                raise LostFixtureResponse
            return FulfillmentReceipt(
                operation_id,
                "completed" if phase == "resolve" else "running",
                phase,
                "fixture_phase_done",
            )
        except ProvisioningBlocked as error:
            with Session(self.engine) as session, session.begin():
                record = session.get(FulfillmentRecord, operation_id, with_for_update=True)
                if record and record.state not in {"completed", "cancelled"}:
                    record.state, record.reason_code = "blocked", str(error)
            return FulfillmentReceipt(operation_id, "blocked", phase, str(error))

    def reconcile(self, session, record, world):
        for step in session.scalars(
            select(FulfillmentStep)
            .where(
                FulfillmentStep.operation_id == record.operation_id,
                FulfillmentStep.state.in_(("claimed", "uncertain")),
            )
            .with_for_update()
        ):
            proof = world["receipts"].get(step.step_id)
            if proof is None:
                continue
            if proof.get("operation_id") != record.operation_id or proof.get("phase") != step.phase:
                raise ProvisioningBlocked("downstream_receipt_mismatch")
            if step.phase in {"user_dm", "staff_dm"}:
                message = session.get(FixtureMessage, proof["delivery_id"])
                if (
                    message is None
                    or message.operation_id != record.operation_id
                    or message.recipient_ref != proof["recipient_ref"]
                    or message.kind != step.phase
                ):
                    raise ProvisioningBlocked("delivery_receipt_unverified")
            if step.phase == "mutation" and "secret_ref" in proof:
                saved = session.get(ProvisioningSecret, proof["secret_ref"])
                if saved is None or saved.operation_id != record.operation_id:
                    raise ProvisioningBlocked("generated_key_material_unavailable")
                try:
                    material = self.cipher.open(proof["secret_ref"], saved.ciphertext)
                except ValueError:
                    raise ProvisioningBlocked("generated_key_material_unavailable") from None
                if material["key_ref"] != proof["key_ref"]:
                    raise ProvisioningBlocked("generated_key_binding_mismatch")
            step.state = "verified"

    def effect(self, session, record, world, event, job, catalog, phase, recipient):
        operation_id = record.operation_id
        if phase == "tool_team":
            target = job.tool_team
            if any(
                t["team_alias"].casefold() == target.alias.casefold()
                for t in world["teams"].values()
            ):
                raise ProvisioningBlocked("tool_team_alias_conflict")
            team_id = self.tool_team_id(job, operation_id)
            world["teams"][team_id] = {
                "team_id": team_id,
                "team_alias": target.alias,
                "kind": "tool",
                "models": list(target.initial_model_ids),
                "max_budget": str(target.initial_budget),
                "spend": "0",
                "budget_duration": target.budget_duration,
                "budget_reset_at": None,
                "metadata": {
                    "operation_ref": operation_id,
                    "terms_digest": record.payload["job_digest"],
                },
            }
            return {"team_id": team_id}
        if phase == "owner_membership":
            owner = self.owner(world, job.owner_email)
            team_id = self.tool_team_id(job, operation_id)
            if world["teams"][team_id]["kind"] != "tool":
                raise ProvisioningBlocked("one_verified_tool_team")
            owner["teams"] = sorted(set(owner["teams"]) | {team_id})
            return {"team_id": team_id, "owner_ref": owner["user_id"]}
        if phase == "mutation":
            if record.payload["skip_mutation"]:
                return {"no_change": True}
            OwnershipLedger.register(session, record, world, job)
            if isinstance(job, CreateApiKey):
                owner = self.owner(world, job.owner_email)
                team_id = self.tool_team_id(job, operation_id)
                raw = "sk-fixture-" + secrets.token_urlsafe(32)
                key_ref = "litellm-key-" + stable_id(raw)
                world["keys"][key_ref] = {
                    "key_ref": key_ref,
                    "user_id": owner["user_id"],
                    "team_id": team_id,
                    "expired": False,
                    "expires": job.expires_at.isoformat() if job.expires_at else None,
                    "max_budget": str(job.budget_limit),
                    "spend": "0",
                    "budget_reset_at": None,
                    "budget_duration": job.budget_duration,
                    "metadata": {
                        "operation_ref": operation_id,
                        "terms_digest": record.payload["job_digest"],
                    },
                }  # There is deliberately no key-level model/ACL field in creation.
                secret_ref = "secret-" + stable_id(operation_id)
                session.add(
                    ProvisioningSecret(
                        secret_ref=secret_ref,
                        operation_id=operation_id,
                        ciphertext=self.cipher.seal(
                            secret_ref,
                            {
                                "key": raw,
                                "key_ref": key_ref,
                                "owner_email": job.owner_email,
                                "team_id": team_id,
                            },
                        ),
                    )
                )
                OwnershipLedger.created_key(session, record, world, job, key_ref)
                return {"key_ref": key_ref, "secret_ref": secret_ref, "team_id": team_id}
            if isinstance(job, AddPersonToNonToolTeam):
                owner = self.owner(world, job.person_email)
                owner["teams"] = sorted(set(owner["teams"]) | {job.team_id})
            elif job.operation == "grant_team_model_access":
                team = world["teams"][job.team_id]
                team["models"] = sorted(set(team["models"]) | set(job.model_ids))
            elif hasattr(job, "reasoning_level"):
                row = (
                    world["keys"][job.key_ref]
                    if hasattr(job, "key_ref")
                    else world["teams"][job.team_id]
                )
                rows = [reasoning(row)]
                if hasattr(job, "key_ref"):
                    rows.append(reasoning(world["teams"][job.tool_team_id]))
                effective = effective_reasoning(rows)
                needed = tuple(
                    m
                    for m in job.model_ids
                    if LEVELS.index(effective.models.get(m.casefold(), effective.all_models))
                    < LEVELS.index(job.reasoning_level)
                )
                row["metadata"] = increase_reasoning(row["metadata"], needed, job.reasoning_level)
            elif hasattr(job, "budget"):
                row = (
                    world["keys"][job.key_ref]
                    if hasattr(job, "key_ref")
                    else (
                        world["teams"][job.team_id]
                        if hasattr(job, "team_id")
                        else self.owner(world, job.person_email)
                    )
                )
                row["max_budget"] = budget_target(row, job.budget)
            else:
                raise ProvisioningBlocked("unsupported_mirza_operation")
            return {"operation": job.operation}
        self.verify(session, record, world, job)
        if phase in {"user_dm", "staff_dm"}:
            delivery_id = self.step_id(operation_id, phase, recipient)
            description = world["descriptions"][event.workflow_id()]
            summary = verified_summary(job, world, record.operation_id)
            if record.payload["completion_explanation_ref"]:
                summary = (
                    "Additional key unnecessary; explanation: "
                    + record.payload["completion_explanation_ref"]
                )
            link = "https://fixture.invalid/tickets/" + event.ticket_id
            body = completion_text(event.ticket_id, link, description, summary)
            if (
                phase == "user_dm"
                and isinstance(job, CreateApiKey)
                and not record.payload["skip_mutation"]
            ):
                secret_ref = "secret-" + stable_id(operation_id)
                saved = session.get(ProvisioningSecret, secret_ref)
                if saved is None:
                    raise ProvisioningBlocked("generated_key_material_unavailable")
                try:
                    secret = self.cipher.open(secret_ref, saved.ciphertext)
                except ValueError:
                    raise ProvisioningBlocked("generated_key_material_unavailable") from None
                if (
                    secret["owner_email"] != job.owner_email
                    or secret["team_id"] != self.tool_team_id(job, operation_id)
                    or "litellm-key-" + stable_id(secret["key"]) != secret["key_ref"]
                ):
                    raise ProvisioningBlocked("generated_key_binding_mismatch")
                body += " API key: " + secret["key"]
            # The simulated private post is encrypted too, never a public projection/body.
            session.add(
                FixtureMessage(
                    delivery_id=delivery_id,
                    operation_id=operation_id,
                    recipient_ref=recipient,
                    kind=phase,
                    ciphertext=self.cipher.seal(delivery_id, {"body": body}),
                )
            )
            return {"delivery_id": delivery_id, "recipient_ref": recipient}
        if phase == "resolve":
            # World row lock serializes status and current-tech checks in this simulator.
            if self.phase(record, event, job, catalog, world)[0] != "resolve":
                raise ProvisioningBlocked("completion_contact_changed")
            world["tickets"][event.workflow_id()] = event.model_copy(
                update={
                    "snapshot": event.snapshot.model_copy(update={"status": "Resolved"}),
                }
            ).model_dump(mode="json")
            return {"status": "Resolved"}
        raise ProvisioningBlocked("unknown_fulfillment_phase")

    def verify(self, session, record, world, job):
        if record.payload["skip_mutation"]:
            return
        if isinstance(job, CreateApiKey):
            rows = [
                k
                for k in world["keys"].values()
                if k["metadata"].get("operation_ref") == record.operation_id
            ]
            if len(rows) != 1:
                raise ProvisioningBlocked("created_key_missing_or_ambiguous")
            key = rows[0]
            owner = self.owner(world, job.owner_email)
            team_id = self.tool_team_id(job, record.operation_id)
            if (
                key["user_id"] != owner["user_id"]
                or key["team_id"] != team_id
                or team_id not in owner["teams"]
                or "models" in key
                or Decimal(key["max_budget"]) != job.budget_limit
                or key["budget_duration"] != job.budget_duration
                or key["expires"] != (job.expires_at.isoformat() if job.expires_at else None)
                or key["metadata"].get("terms_digest") != record.payload["job_digest"]
            ):
                raise ProvisioningBlocked("created_key_scope_changed")
            if isinstance(job.tool_team, NewToolTeam) and (
                set(world["teams"][team_id]["models"]) != set(job.tool_team.initial_model_ids)
            ):
                raise ProvisioningBlocked("created_team_grants_changed")
            if not has_budget(key) or not has_budget(world["teams"][team_id]):
                raise ProvisioningBlocked("effective_budget_exhausted")
        elif isinstance(job, AddPersonToNonToolTeam):
            owner = self.owner(world, job.person_email)
            if job.team_id not in owner["teams"]:
                raise ProvisioningBlocked("membership_not_effective")
            if not has_budget(owner) or not has_budget(world["teams"][job.team_id]):
                raise ProvisioningBlocked("effective_budget_exhausted")
        elif job.operation == "grant_team_model_access":
            if not set(job.model_ids).issubset(world["teams"][job.team_id]["models"]):
                raise ProvisioningBlocked("model_grant_not_effective")
        elif hasattr(job, "reasoning_level"):
            row = (
                world["keys"][job.key_ref]
                if hasattr(job, "key_ref")
                else world["teams"][job.team_id]
            )
            rows = [reasoning(row)]
            if hasattr(job, "key_ref"):
                rows.append(reasoning(world["teams"][job.tool_team_id]))
            effective = effective_reasoning(rows)
            if any(
                LEVELS.index(effective.models.get(m.casefold(), effective.all_models))
                < LEVELS.index(job.reasoning_level)
                for m in job.model_ids
            ):
                raise ProvisioningBlocked("reasoning_grant_not_effective")
        elif hasattr(job, "budget"):
            row = (
                world["keys"][job.key_ref]
                if hasattr(job, "key_ref")
                else (
                    world["teams"][job.team_id]
                    if hasattr(job, "team_id")
                    else self.owner(world, job.person_email)
                )
            )
            if Decimal(row["max_budget"]) < job.budget.desired_limit:
                raise ProvisioningBlocked("budget_grant_not_effective")
            if not has_budget(row):
                raise ProvisioningBlocked("effective_budget_exhausted")

    def projection(self, operation_id):
        with Session(self.engine) as session:
            row = session.get(FulfillmentRecord, operation_id)
            if row is None:
                return None
            messages = session.scalars(
                select(FixtureMessage).where(FixtureMessage.operation_id == operation_id)
            ).all()
            return {
                "operation_id": operation_id,
                "state": row.state,
                "reason_code": row.reason_code,
                "execution_domain": "synthetic",
                "job": row.payload.get("archived_job")
                or row.payload["event"]["proposal"]["operation"],
                "deliveries": [
                    {"delivery_id": m.delivery_id, "recipient_ref": m.recipient_ref, "kind": m.kind}
                    for m in messages
                ],
                "external_calls": 0,
            }


def verified_summary(job, world, operation_id):
    """Summarize verified scope without key material or invented expiry."""
    parts = [job.operation.replace("_", " ") + " verified"]
    if isinstance(job, CreateApiKey):
        parts += [
            "Tool team: " + FixtureFulfillmentService.tool_team_id(job, operation_id),
            "Budget limit: " + str(job.budget_limit),
            "Reset duration: " + job.budget_duration,
        ]
    elif hasattr(job, "budget"):
        collection = (
            "keys" if hasattr(job, "key_ref") else ("teams" if hasattr(job, "team_id") else "users")
        )
        ref = (
            job.key_ref
            if collection == "keys"
            else (
                job.team_id
                if collection == "teams"
                else FixtureFulfillmentService.owner(world, job.person_email)["user_id"]
            )
        )
        parts += [
            "Scope: " + collection + "/" + ref,
            "Verified budget limit: " + str(world[collection][ref]["max_budget"]),
        ]
    else:
        parts += ["Scope: " + getattr(job, "key_ref", getattr(job, "team_id", ""))]
        if hasattr(job, "model_ids"):
            parts += ["Models: " + ", ".join(job.model_ids)]
        if hasattr(job, "requested_model_id"):
            parts += ["Model through team membership: " + job.requested_model_id]
        if hasattr(job, "reasoning_level"):
            parts += ["Reasoning: at least " + job.reasoning_level]
    expiry = getattr(job, "expires_at", None)
    parts += ["Approved expiry: " + (expiry.isoformat() if expiry else "none specified")]
    return "; ".join(parts)
