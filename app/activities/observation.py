"""I/O and model calls live here; only opaque receipts enter workflow history."""

import asyncio
import json
from decimal import Decimal

from temporalio import activity
from temporalio.exceptions import ApplicationError

from app.agents.observation import Inference, Scope
from app.connectors.http import ReadFailure
from app.connectors.observation import ObservationSource
from app.contracts.observation import (
    ClarificationDraft,
    GroupPreflightStart,
    ObservationReceipt,
    ObservationResult,
    ObservationStart,
    PollBatch,
    PollStart,
)
from app.contracts.tickets import (
    Catalog,
    GroupCorrection,
    MirzaRequest,
    NoOp,
    ProcessContext,
    TicketEvent,
    TicketSnapshot,
    Tracking,
    stable_id,
)
from app.policies.group_correction import draft_issue
from app.policies.tickets import POLICY_VERSION, evaluate


class ObservationActivities:
    def __init__(self, repository, connectors, settings, inference=None):
        self.repository, self.settings = repository, settings
        self.source = ObservationSource(connectors, settings)
        self.inference = inference or Inference(settings)

    async def store_call(self, function, *args):
        try:
            return await asyncio.to_thread(function, *args)
        except Exception:
            raise ApplicationError("Observation storage unavailable", type="ObservationStorage")

    @activity.defn(name="prepare_group_correction_review")
    async def preflight(self, request: GroupPreflightStart) -> ObservationReceipt:
        versions = self.inference.versions()
        packet = None
        result = self.base(request, "manual_review", "group_proposal_unverified")
        identity = await self.store_call(self.repository.source_identity, request.observation_id)
        if identity == ("servicedesk", request.ticket_id, "classify") and (
            request.tenant_id == "servicedesk"
        ):
            prior = await self.store_call(self.repository.get, request.observation_id)
            if prior:
                try:
                    packet = await self.source.collect(request.ticket_id)
                    state, reason = draft_issue(prior, packet, versions)
                    result = self.base(request, state, reason, packet)
                    if reason == "native_atomic_group_update_unverified":
                        if await self.source.current(packet):
                            result = result.model_copy(update={
                                "proposal": prior.proposal, "policy_reason": reason,
                            })
                        else:
                            result = self.base(
                                request, "manual_review", "group_context_changed", packet
                            )
                except Exception as error:
                    reason = (error.reason if isinstance(error, ReadFailure)
                              else "group_preflight_source_invalid")
                    result = self.base(request, "manual_review", reason, packet)
        # This is an observation record, never executable intake or action staging.
        fingerprint = stable_id(
            request.observation_id, packet.input_digest if packet else "unavailable",
            result.reason_code, json.dumps(packet.groups, sort_keys=True) if packet else "{}",
        )
        result = result.model_copy(update={
            "versions": {**versions, "group_preflight": "group-only-review-v1"}
        })
        observation_id = stable_id(
            request.tenant_id, request.ticket_id, "group_preflight", fingerprint,
            json.dumps(result.versions, sort_keys=True),
        )
        claimed = await self.store_call(
            self.repository.claim, observation_id, request, "group_preflight", fingerprint,
            result, Decimal(0), self.settings.inference_daily_budget_usd,
        )
        if claimed:
            return await self.store_call(self.repository.finish, observation_id, result)
        return await self.store_call(self.repository.receipt, observation_id)

    @activity.defn(name="poll_observation_candidates")
    async def poll(self, request: PollStart) -> PollBatch:
        if not self.settings.observation_listener_enabled:
            return PollBatch([], request.cursor, "disabled")
        try:
            candidates = await self.source.candidates()
            tracked = await self.store_call(self.repository.tracked_handoffs)
            candidates = sorted(set(candidates).union(tracked), key=int)
            if not candidates:
                return PollBatch([], 0, "ok")
            start = request.cursor % len(candidates)
            count = min(request.batch_size, len(candidates))
            selected = [candidates[(start + offset) % len(candidates)] for offset in range(count)]
            return PollBatch(selected, (start + count) % len(candidates), "ok")
        except Exception:
            return PollBatch([], request.cursor, "unavailable")

    def base(self, request, state, reason, packet=None):
        refs = (
            packet.evidence_refs if packet else (stable_id(request.tenant_id, request.ticket_id),)
        )
        return ObservationResult(
            state=state, reason_code=reason, evidence_refs=refs, versions=self.inference.versions()
        )

    def gate(self, request, packet):
        if packet.relationships.process_association == "lifecycle":
            return self.base(request, "no_op", "excluded_lifecycle_process", packet)
        if packet.ticket.status_name.casefold() in {"resolved", "closed", "cancelled"}:
            return self.base(request, "no_op", "ticket_terminal", packet)
        if (
            packet.ticket.template_id not in {"11401", "11702"}
            and (packet.ticket.group_id != packet.groups["Helpdesk"])
            and not packet.tracked_handoff
        ):
            return self.base(request, "no_op", "outside_helpdesk_scope", packet)
        return None

    def classify_proposal(self, result, packet):
        classified = result.classification
        if classified.kind == "ordinary":
            if packet.ticket.group_id != packet.groups["Helpdesk"]:
                reason = "ordinary_outside_helpdesk"
            elif packet.ticket.technician is not None:
                reason = "human_assignment_preserved"
            elif classified.group == "Helpdesk":
                reason = "helpdesk_already_correct"
            else:
                return result.model_copy(
                    update={
                        "proposal": GroupCorrection(
                            kind="correct_support_group",
                            destination_group_id=packet.groups[classified.group],
                        ),
                        "reason_code": "support_group_proposal_only",
                    }
                )
            return result.model_copy(
                update={
                    "state": "no_op",
                    "reason_code": reason,
                    "proposal": NoOp(kind="no_op", reason_code=reason),
                }
            )
        if classified.kind in {"unsupported_mirza", "ambiguous"}:
            reason = (
                "unsupported_mirza_operation"
                if classified.kind == "unsupported_mirza"
                else "ambiguous_request"
            )
            return result.model_copy(
                update={
                    "state": "no_op" if classified.kind == "unsupported_mirza" else "manual_review",
                    "reason_code": reason,
                    "proposal": NoOp(kind="no_op", reason_code=reason),
                }
            )
        return result

    def policy_reason(self, result, packet, catalog):
        if result.proposal is None:
            return result
        if (isinstance(result.proposal, MirzaRequest)
                and packet.ticket.template_id not in {"11401", "11702"}
                and packet.ticket.group_id != packet.groups["DWE"]
                and packet.ticket.technician is not None):
            return result.model_copy(update={"policy_reason": "human_assignment_preserved"})
        status = {"Open": "Open", "Onhold": "On Hold", "On Hold": "On Hold"}.get(
            packet.ticket.status_name
        )
        if status is None:
            return result.model_copy(update={"policy_reason": "unverified_ticket_status"})
        requester = next(
            (p.person_id for p in catalog.people if p.email == packet.ticket.requester.email),
            packet.ticket.requester.person_id,
        )
        email = getattr(getattr(result.proposal, "job", None), "owner_email", None)
        email = email or getattr(getattr(result.proposal, "job", None), "person_email", None)
        person = next((p.person_id for p in catalog.people if p.email == email), None)
        event = TicketEvent(
            tenant_id="servicedesk",
            ticket_id=packet.ticket.ticket_id,
            event_id="observation-" + packet.input_digest,
            data_kind="servicedesk",
            catalog_version=catalog.version,
            policy_version=POLICY_VERSION,
            model_version=result.versions["model"],
            prompt_version=result.versions["prompt"],
            evidence_refs=packet.evidence_refs,
            snapshot=TicketSnapshot(
                revision_id=packet.ticket.revision_digest,
                source_sequence=None,
                source_order_verified=False,
                requester_ref=requester,
                intended_person_ref=person,
                support_group_id=packet.ticket.group_id,
                technician_ref=packet.ticket.technician.person_id
                if packet.ticket.technician
                else None,
                template_id=packet.ticket.template_id,
                category_id=packet.ticket.category_id,
                status=status,
                source="unknown",
                source_updated_at=packet.ticket.updated_at,
                content_ref="content-" + packet.ticket.content_digest,
                content_digest=packet.ticket.content_digest,
                process=ProcessContext(association=packet.relationships.process_association),
            ),
            proposal=result.proposal,
        )
        decision = evaluate(event, Tracking(), catalog)
        # No TicketRepository.accept(), action staging, synthetic execution or write connector.
        return result.model_copy(update={"policy_reason": decision.reason_code})

    async def observe(self, request, stage, previous_id=None):
        packet, scope, gate = None, None, None
        try:
            packet = await self.source.collect(request.ticket_id)
            tracked = await self.store_call(self.repository.tracked_handoffs)
            if request.ticket_id in tracked and packet.ticket.group_id == packet.groups["DWE"]:
                packet.tracked_handoff = True
                packet.dwe_contact = tracked[request.ticket_id]
                packet.input_digest = stable_id(packet.input_digest, packet.dwe_contact)
            gate = self.gate(request, packet)
            scope = Scope(packet)
            if stage == "extract" and gate is None:
                prior = await self.store_call(self.repository.get, previous_id)
                if (
                    not prior
                    or prior.state != "proposed"
                    or not prior.classification
                    or prior.classification.kind != "mirza"
                ):
                    gate = self.base(
                        request, "blocked", "classification_receipt_unverified", packet
                    )
                elif prior.evidence_refs != packet.evidence_refs:
                    gate = self.base(request, "blocked", "classification_snapshot_changed", packet)
                else:
                    scope.operation = prior.classification.operation
                    (
                        scope.catalog,
                        scope.projection,
                        scope.baselines,
                    ) = await self.source.mirza_scope(packet)
        except Exception as exc:
            reason = exc.reason if isinstance(exc, ReadFailure) else "observation_source_invalid"
            gate = self.base(request, "manual_review", reason, packet)
        fingerprint = stable_id(
            packet.input_digest if packet else "unavailable",
            gate.reason_code if gate else "ready",
            scope.projection if scope else "{}",
            str(scope.operation) if scope else "none",
        )
        observation_id = stable_id(
            request.tenant_id,
            request.ticket_id,
            stage,
            fingerprint,
            json.dumps(self.inference.versions(), sort_keys=True),
        )
        base = gate or self.base(request, "blocked", "inference_outcome_uncertain", packet)
        reserve = (
            Decimal(str(self.settings.inference_max_cost_usd))
            if (
                gate is None
                and self.inference.ready(stage)
                and self.inference.cost_bound(stage)
                <= Decimal(str(self.settings.inference_max_cost_usd))
            )
            else Decimal(0)
        )
        claimed = await self.store_call(
            self.repository.claim,
            observation_id,
            request,
            stage,
            fingerprint,
            base,
            reserve,
            self.settings.inference_daily_budget_usd,
        )
        if not claimed:
            return await self.store_call(self.repository.receipt, observation_id)
        result = gate or await self.inference.run(stage, scope)
        if result.state == "proposed":
            if not await self.source.current(packet):
                result = result.model_copy(
                    update={
                        "state": "blocked",
                        "proposal": None,
                        "reason_code": "context_changed_during_inference",
                    }
                )
            elif stage == "classify":
                result = self.classify_proposal(result, packet)
                if result.proposal is not None:
                    catalog = Catalog(
                        version="observation-scoped-v1",
                        environment="production",
                        support_groups=packet.groups,
                        dedicated_templates={
                            "Mirza Access Request": "11702",
                            "Mirza API Key": "11401",
                        },
                        people=(),
                        teams=(),
                        keys=(),
                        model_ids=(),
                        reasoning_levels=(),
                        department_tool_teams={},
                        dwe_incharge_ref=packet.dwe_contact,
                    )
                    result = self.policy_reason(result, packet, catalog)
            else:
                result = self.policy_reason(result, packet, scope.catalog)
                if isinstance(result.proposal, MirzaRequest) and result.proposal.job is None:
                    result = result.model_copy(
                        update={
                            "clarification": ClarificationDraft(
                                contact_ref=(
                                    packet.ticket.technician.person_id
                                    if packet.ticket.technician
                                    else packet.dwe_contact
                                ),
                                missing_fields=result.proposal.missing_fields,
                            )
                        }
                    )
        return await self.store_call(self.repository.finish, observation_id, result)

    @activity.defn(name="classify_observation_ticket")
    async def classify(self, request: ObservationStart) -> ObservationReceipt:
        return await self.observe(request, "classify")

    @activity.defn(name="extract_observation_ticket")
    async def extract(self, request: ObservationStart, previous_id: str) -> ObservationReceipt:
        return await self.observe(request, "extract", previous_id)
