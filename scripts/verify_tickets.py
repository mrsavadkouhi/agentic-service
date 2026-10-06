"""Local synthetic verification. Contains no production URLs or credentials."""

import argparse
import asyncio
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from temporalio.client import Client
from temporalio.worker import Replayer

from app.contracts.execution import ActionCommand, CommitTransition, ReminderCommand
from app.contracts.tickets import (
    Budget,
    ClarificationResponse,
    FallbackApproval,
    GroupCorrection,
    MirzaRequest,
    NoOp,
    Tracking,
    digest,
    stable_id,
)
from app.policies.reminders import TEHRAN
from app.policies.synthetic_events import catalog, event
from app.policies.tickets import evaluate
from app.settings import Settings, WorkerRole
from app.storage.database import make_engine
from app.storage.ticket_repository import TicketRepository
from app.storage.tickets import FixtureEffect, TicketAction, TicketInbox, TicketWorkflowRecord
from app.workflows.tickets import TicketWorkflow


def changed(original, sequence, **snapshot):
    return original.model_copy(
        update={
            "event_id": f"revision-{sequence}",
            "snapshot": original.snapshot.model_copy(
                update={
                    "source_sequence": sequence,
                    "revision_id": f"revision-{sequence}",
                    **snapshot,
                }
            ),
        }
    )


class Verification:
    def __init__(self):
        self.settings = Settings()
        if not self.settings.enable_fixture_execution:
            raise RuntimeError("Verification requires the local synthetic override")
        self.engine = make_engine(self.settings)
        self.repository = TicketRepository(self.engine)
        self.http = httpx.Client(base_url="http://127.0.0.1:8080", timeout=10)
        self.intake = {"Authorization": "Bearer " + self.settings.intake_token.get_secret_value()}
        self.operator = {
            "Authorization": "Bearer " + self.settings.operator_token.get_secret_value()
        }

    def close(self):
        self.http.close()
        self.engine.dispose()

    def submit(self, normalized):
        response = self.http.post(
            "/v1/events", headers=self.intake, json=normalized.model_dump(mode="json")
        )
        assert response.status_code == 202, response.status_code
        assert response.json()["workflow_id"] == normalized.workflow_id()
        return response.json()

    def wait(self, workflow_id, state, sequence=None):
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            response = self.http.get(f"/v1/workflows/{workflow_id}", headers=self.operator)
            assert response.status_code == 200
            view = response.json()
            if view["state"] == state and (sequence is None or view["latest_sequence"] == sequence):
                return view
            time.sleep(0.2)
        raise AssertionError(f"Workflow did not reach {state}: {view['state']}")

    def clean_cancel(self, normalized):
        view = self.repository.projection(normalized.workflow_id())
        response = self.http.post(
            f"/v1/workflows/{normalized.workflow_id()}/cancel",
            headers=self.operator,
            json={"request_id": str(uuid4()), "expected_sequence": view["latest_sequence"]},
        )
        assert response.status_code == 202
        self.wait(normalized.workflow_id(), "cancelled")

    def start(self, role, state_file):
        normalized = event(str(uuid4()), dedicated=(role == "mirza"))
        if role == "dispatch":
            normalized = normalized.model_copy(
                update={
                    "proposal": GroupCorrection(
                        kind="correct_support_group", destination_group_id="sd-network"
                    )
                }
            )
            # Start with a protected human assignment, then remove it in the finish phase.
            normalized = changed(normalized, 1, technician_ref="technician")
            target = "completed"
        else:
            target = "awaiting_approval"
        self.submit(normalized)
        assert self.submit(normalized)["duplicate"]
        self.wait(normalized.workflow_id(), target, 1)
        assert self.repository.counts(normalized.workflow_id())["events"] == 1
        assert self.repository.counts(normalized.workflow_id())["synthetic_effects"] == 0
        Path(state_file).write_text(normalized.model_dump_json())
        print(f"PASS {role}: durable waiting/protected state and duplicate intake")

    async def finish(self, role, state_file):
        from app.contracts.tickets import TicketEvent

        normalized = TicketEvent.model_validate_json(Path(state_file).read_text())
        current = await Client.connect(
            self.settings.temporal_address, namespace=self.settings.temporal_namespace
        )
        handle = current.get_workflow_handle(normalized.workflow_id())
        state = await handle.query("status")
        assert state["latest_sequence"] == 1
        updated = changed(normalized, 2, technician_ref=None)
        if role == "mirza":
            updated = updated.model_copy(
                update={
                    "native_approval": normalized.native_approval.model_copy(
                        update={
                            "final_state": "approved",
                            "required_stages_complete": True,
                            "source_sequence": 2,
                        }
                    )
                }
            )
        self.submit(updated)
        self.wait(updated.workflow_id(), "completed", 2)
        counts = self.repository.counts(updated.workflow_id())
        assert counts["events"] == 2 and counts["actions"] == 1 and counts["synthetic_effects"] == 1
        with Session(self.engine) as session:
            receipt = session.scalar(
                select(FixtureEffect)
                .join(TicketAction)
                .where(TicketAction.workflow_id == updated.workflow_id())
            )
            assert receipt.fail_once_triggered
        self.submit(updated)
        assert self.repository.counts(updated.workflow_id()) == counts
        history = await handle.fetch_history()
        await Replayer(workflows=[TicketWorkflow]).replay_workflow(history)
        self.clean_cancel(updated)
        print(
            f"PASS {role}: worker restart, lost response reconciliation, one effect, history replay"
        )

    def gates(self):
        normalized = event(str(uuid4()), dedicated=False)
        assert self.http.post("/v1/events", json={}).status_code == 401
        assert self.http.post("/v1/events", headers=self.operator, json={}).status_code == 401
        assert self.http.get("/v1/workflows/unknown", headers=self.intake).status_code == 401
        assert (
            self.http.post(
                "/v1/events", headers=self.intake, json={"secret": "sk-do-not-echo"}
            ).text
            == '{"detail":"Invalid normalized event"}'
        )
        assert (
            self.http.post("/v1/events", headers=self.intake, content=b"x" * 65537).status_code
            == 413
        )
        self.submit(normalized)
        assert self.submit(normalized)["duplicate"]
        self.wait(normalized.workflow_id(), "awaiting_approval", 1)
        conflict = changed(normalized, 1, status="Closed")
        assert (
            self.http.post(
                "/v1/events", headers=self.intake, json=conflict.model_dump(mode="json")
            ).status_code
            == 409
        )
        proof = FallbackApproval(
            terms_digest=digest(normalized.proposal.job),
            group_id="sd-dwe",
            held_event_ref="held-2",
            held_sequence=2,
            open_event_ref="open-3",
            open_sequence=3,
            actor_ref="requester",
            history_verified=True,
        )
        wrong = changed(normalized, 3, support_group_id="sd-dwe").model_copy(
            update={"fallback_approval": proof}
        )
        self.submit(wrong)
        self.wait(wrong.workflow_id(), "awaiting_approval", 3)
        assert self.repository.counts(wrong.workflow_id())["synthetic_effects"] == 0
        # A changed amount with old approval must remain blocked.
        new_job = normalized.proposal.job.model_copy(
            update={
                "budget": Budget(
                    amount=10, interpretation="delta", baseline_limit=10, desired_limit=20
                )
            }
        )
        stale = changed(wrong, 4).model_copy(
            update={
                "proposal": wrong.proposal.model_copy(update={"job": new_job}),
                "fallback_approval": proof.model_copy(update={"actor_ref": "incharge"}),
            }
        )
        self.submit(stale)
        pending = self.wait(stale.workflow_id(), "awaiting_approval", 4)
        assert pending["tracking"]["original_dwe_incharge_ref"] == "incharge"
        assert self.repository.counts(stale.workflow_id())["synthetic_effects"] == 0
        reminders = ReminderCommand(
            stale.workflow_id(),
            pending["tracking"]["wait"]["cycle_id"],
            datetime(2026, 10, 9, 10, tzinfo=TEHRAN).isoformat(),
        )
        morning = datetime.fromisoformat(reminders.now_iso)
        assert self.repository.reminders(reminders, morning.replace(hour=9)) == 0
        assert self.repository.reminders(reminders, morning.replace(day=10)) == 0
        assert self.repository.reminders(reminders, morning) == 1
        assert self.repository.reminders(reminders, morning) == 0
        # Older already delivered updates do not regress the current projection.
        older = changed(normalized, 2)
        self.submit(older)
        time.sleep(0.5)
        assert self.repository.projection(older.workflow_id())["latest_sequence"] == 4
        approved = changed(stale, 6).model_copy(
            update={
                "fallback_approval": proof.model_copy(
                    update={
                        "actor_ref": "incharge",
                        "held_sequence": 5,
                        "open_sequence": 6,
                        "terms_digest": digest(new_job),
                    }
                )
            }
        )
        self.submit(approved)
        self.wait(approved.workflow_id(), "completed", 6)
        assert self.repository.counts(approved.workflow_id())["synthetic_effects"] == 1
        assert self.repository.reminders(reminders, morning) == 0
        response = self.http.post(
            f"/v1/workflows/{approved.workflow_id()}/cancel",
            headers=self.operator,
            json={"request_id": "stale-cancel", "expected_sequence": 4},
        )
        assert response.status_code == 409
        self.clean_cancel(approved)
        self.submit(changed(approved, 7))
        self.wait(approved.workflow_id(), "cancelled")
        assert self.repository.counts(approved.workflow_id())["synthetic_effects"] == 1

        incomplete = event(str(uuid4()), approved=True).model_copy(
            update={
                "proposal": MirzaRequest(
                    kind="mirza",
                    operation="increase_person_budget",
                    job=None,
                    missing_fields=("budget",),
                )
            }
        )
        self.submit(incomplete)
        waiting = self.wait(incomplete.workflow_id(), "awaiting_clarification", 1)
        complete = event(incomplete.ticket_id, sequence=3, approved=True)
        response = ClarificationResponse(
            cycle_id=waiting["tracking"]["wait"]["cycle_id"],
            note_ref="note-2",
            note_author_ref="requester",
            note_sequence=2,
            open_event_ref="open-3",
            open_actor_ref="requester",
            open_sequence=3,
            supplied_terms_digest=digest(complete.proposal.job),
            history_verified=True,
        )
        self.submit(complete.model_copy(update={"clarification": response}))
        self.wait(complete.workflow_id(), "awaiting_clarification", 3)
        assert self.repository.counts(complete.workflow_id())["synthetic_effects"] == 0
        # The new cycle starts at the changed complete terms; respond after that baseline.
        view = self.repository.projection(complete.workflow_id())
        complete = changed(complete, 5).model_copy(
            update={
                "clarification": response.model_copy(
                    update={
                        "cycle_id": view["tracking"]["wait"]["cycle_id"],
                        "note_author_ref": "incharge",
                        "open_actor_ref": "incharge",
                        "note_sequence": 4,
                        "open_sequence": 5,
                    }
                )
            }
        )
        self.submit(complete)
        self.wait(complete.workflow_id(), "completed", 5)
        assert self.repository.counts(complete.workflow_id())["synthetic_effects"] == 1
        self.clean_cancel(complete)
        print(
            "PASS authenticated roles, conflicting IDs, stale terms/actors/revisions, "
            "clarification, reminders, cancellation"
        )

    def repository_boundaries(self):
        # Isolate transaction-boundary checks from the outbox-driven actors.
        normalized = event(str(uuid4()), approved=True)
        self.stage_without_delivery(normalized)
        queued = self.repository.next_event(normalized.workflow_id())
        self.repository.mark_notified(queued.event_key)
        decision = evaluate(normalized, Tracking(), catalog())
        command = CommitTransition(
            normalized.workflow_id(), queued.event_key, decision.model_dump_json(), -1
        )
        first = self.repository.commit(command)
        assert self.repository.commit(command) == first
        action = ActionCommand(normalized.workflow_id(), decision.action_id)
        newer = changed(normalized, 2, status="Cancelled")
        self.stage_without_delivery(newer)
        queued = self.repository.next_event(normalized.workflow_id())
        self.repository.mark_notified(queued.event_key)
        result = self.repository.run_fixture_action(action, self.settings, WorkerRole.MIRZA)
        assert result["state"] == "superseded"
        assert self.repository.counts(normalized.workflow_id())["synthetic_effects"] == 0
        self.repository.commit(
            CommitTransition(
                normalized.workflow_id(),
                queued.event_key,
                evaluate(newer, Tracking.model_validate_json(first), catalog()).model_dump_json(),
                1,
            )
        )

        unknown = event(str(uuid4()), approved=True)
        self.stage_without_delivery(unknown)
        queued = self.repository.next_event(unknown.workflow_id())
        self.repository.mark_notified(queued.event_key)
        authorized = evaluate(unknown, Tracking(), catalog())
        self.repository.commit(
            CommitTransition(
                unknown.workflow_id(), queued.event_key, authorized.model_dump_json(), -1
            )
        )
        with Session(self.engine) as session, session.begin():
            session.get(TicketAction, authorized.action_id).state = "uncertain"
        action = ActionCommand(unknown.workflow_id(), authorized.action_id)
        result = self.repository.run_fixture_action(action, self.settings, WorkerRole.MIRZA)
        assert result == {"state": "manual_review", "reason": "unreconciled_result"}
        assert self.repository.counts(unknown.workflow_id())["synthetic_effects"] == 0
        self.repository.finish_action(action, result)
        print(
            "PASS transaction retry receipt, new input before write, "
            "uncertain result without receipt stops"
        )

    def stage_without_delivery(self, normalized):
        # Transaction tests do not start an actor. Mark notified atomically to avoid
        # racing the API outbox; HTTP intake/deduplication is exercised separately.
        with Session(self.engine) as session, session.begin():
            workflow_id = normalized.workflow_id()
            if session.get(TicketWorkflowRecord, workflow_id) is None:
                session.add(
                    TicketWorkflowRecord(
                        workflow_id=workflow_id,
                        tenant_id=normalized.tenant_id,
                        ticket_id=normalized.ticket_id,
                        worker_role="mirza",
                        correlation_id=str(uuid4()),
                        tracking=Tracking().model_dump(mode="json"),
                        latest_sequence=-1,
                        state="received",
                    )
                )
                session.flush()
            session.add(
                TicketInbox(
                    event_key=stable_id(workflow_id, normalized.event_id),
                    workflow_id=workflow_id,
                    external_event_id=normalized.event_id,
                    kind="ticket",
                    sequence=normalized.snapshot.source_sequence,
                    payload_digest=digest(normalized),
                    payload=normalized.model_dump(mode="json"),
                    notified=True,
                )
            )

    async def rollover(self):
        normalized = event(str(uuid4())).model_copy(
            update={"proposal": NoOp(kind="no_op", reason_code="synthetic_no_op")}
        )
        self.submit(normalized)
        self.wait(normalized.workflow_id(), "completed", 1)
        temporal = await Client.connect(
            self.settings.temporal_address, namespace=self.settings.temporal_namespace
        )
        handle = temporal.get_workflow_handle(normalized.workflow_id())
        original_run = (await handle.describe()).run_id
        for sequence in range(2, 103):
            self.submit(changed(normalized, sequence))
        self.wait(normalized.workflow_id(), "completed", 102)
        assert (await handle.describe()).run_id != original_run
        tracking = await handle.query("status")
        assert tracking["latest_sequence"] == 102
        counts = self.repository.counts(normalized.workflow_id())
        assert counts["events"] == 102 and counts["synthetic_effects"] == 0
        await Replayer(workflows=[TicketWorkflow]).replay_workflow(await handle.fetch_history())
        self.clean_cancel(normalized)
        print("PASS continue-as-new preserves revisions and replays after 102 deliveries")


async def run(args):
    verifier = Verification()
    try:
        if args.phase == "start":
            verifier.start(args.role, args.state_file)
        elif args.phase == "finish":
            await verifier.finish(args.role, args.state_file)
        else:
            verifier.gates()
            verifier.repository_boundaries()
            await verifier.rollover()
    finally:
        verifier.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("start", "finish", "gates"))
    parser.add_argument("--role", choices=("dispatch", "mirza"), default="mirza")
    parser.add_argument("--state-file", default="/tmp/agentic-ticket-verification.json")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception as exc:
        print(f"FAIL local ticket verification: {type(exc).__name__}")
        raise  # Fixtures only; never run this script with production settings.


if __name__ == "__main__":
    main()
