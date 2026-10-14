"""Bounded local-Qwen evaluation with synthetic data and Temporal's activity harness.

Native workflow replay/recovery is checked separately by check_observations.sh.
The persistent local SQLite ledger retains uncertain spend reservations.
"""

import argparse
import asyncio
import getpass
import json
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic_ai import capture_run_messages  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from temporalio.testing import ActivityEnvironment  # noqa: E402

from app.activities.observation import ObservationActivities  # noqa: E402
from app.agents.observation import Inference  # noqa: E402
from app.contracts.context import DeskPerson  # noqa: E402
from app.contracts.observation import Classification, ObservationStart  # noqa: E402
from app.contracts.tickets import MirzaRequest, stable_id  # noqa: E402
from app.settings import Settings  # noqa: E402
from app.storage.models import Base  # noqa: E402
from app.storage.observations import ObservationRecord, ObservationRepository  # noqa: E402
from scripts.verify_observations import FixtureSource  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = "https://mirza.tapsi.tech/api/v1"


class EvaluationSource(FixtureSource):
    def __init__(self, case):
        super().__init__()
        self.case = case
        if case.get("id") == "create_api_key":
            self.catalog = self.catalog.model_copy(update={"keys": ()})

    async def collect(self, ticket_id):
        packet = await super().collect(ticket_id)
        digest = stable_id(json.dumps(self.case, sort_keys=True))
        packet.text = self.case["text"]
        packet.input_digest = digest
        packet.evidence_refs = (digest,)
        packet.ticket = packet.ticket.model_copy(update={
            "content_digest": "a" * 64,
            "revision_digest": digest,
            "template_id": (
                "11702" if "operation" in self.case.get("classification", {}) else "other"
            ),
            "group_id": self.case.get("group", "sd-helpdesk"),
            "technician": DeskPerson(person_id="technician", email="technician@example.invalid")
            if self.case.get("technician") else None,
        })
        if self.case.get("lifecycle"):
            packet.relationships = packet.relationships.model_copy(update={
                "process_association": "lifecycle", "process_kind": "onboarding"
            })
        return packet

    async def mirza_scope(self, packet):
        baselines = {ref: Decimal(10) for ref in (
            "owner@example.invalid", "tool-team", "ui-team", "key-metadata-1"
        )}
        projection = {
            "people": [{"email": "owner@example.invalid", "department": "Synthetic Department",
                        "mapped_tool_team": "tool-team", "mapping": "mapped"}],
            "teams": [team.model_dump(mode="json") for team in self.catalog.teams],
            "keys": [key.model_dump(mode="json") for key in self.catalog.keys],
            "served_models": self.catalog.model_ids,
            "budget_baselines": {ref: str(value) for ref, value in baselines.items()},
            "purpose_ref": "purpose-" + packet.ticket.content_digest,
        }
        return self.catalog, json.dumps(projection), baselines


def matches(case, classified, extracted):
    if case.get("reason"):
        return classified.reason_code == case["reason"]
    if classified.classification != Classification.model_validate(case["classification"]):
        return False
    if "job" in case:
        expected = MirzaRequest(kind="mirza", operation=case["job"]["operation"], job=case["job"])
        return extracted is not None and extracted.proposal == expected
    if "missing" in case:
        return (extracted is not None and isinstance(extracted.proposal, MirzaRequest)
                and extracted.proposal.job is None
                and case["missing"] in extracted.proposal.missing_fields)
    return True


async def evaluate(args, token):
    settings = Settings(
        _env_file=None, database_url="postgresql+psycopg://unused:unused@localhost/unused",
        inference_enabled=True, inference_url=ENDPOINT, inference_token=token,
        inference_model="local-qwen3.8", inference_max_cost_usd=0.008,
        inference_daily_budget_usd=0.4,
        inference_input_usd_per_million=0.02, inference_output_usd_per_million=0.10,
    )
    cases = json.loads((ROOT / "tests/fixtures/step_5/model_cases.json").read_text())
    if args.case:
        cases = [case for case in cases if case["id"] == args.case]
    if args.skip_routing:
        cases = [case for case in cases if not case["id"].endswith(("-en", "-fa"))]
    if not cases:
        raise ValueError("Unknown evaluation case")
    if args.extract_only and (not args.case or len(cases) != 1):
        raise ValueError("Extraction-only check requires one existing synthetic case")
    args.ledger.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine("sqlite:///" + str(args.ledger.resolve()))
    Base.metadata.create_all(engine)
    repository, inference = ObservationRepository(engine), Inference(settings)
    activities = ObservationActivities(
        repository, SimpleNamespace(reader=None), settings, inference
    )
    harness, results = ActivityEnvironment(), []
    try:
        for index, case in enumerate(cases, 1):
            activities.source = EvaluationSource(case)
            request = ObservationStart("local-qwen-evaluation", str(index), "dispatch", "mirza")
            if args.extract_only:
                packet = await activities.source.collect(request.ticket_id)
                fingerprint = stable_id(packet.input_digest, "ready", "{}", "None")
                with Session(engine) as session:
                    prior = session.scalar(select(ObservationRecord).where(
                        ObservationRecord.tenant_id == request.tenant_id,
                        ObservationRecord.stage == "classify",
                        ObservationRecord.input_digest == fingerprint,
                    ).order_by(ObservationRecord.created_at.desc()))
                    if prior is None or prior.result is None:
                        raise ValueError("Completed classification unavailable")
                    request.ticket_id = prior.ticket_id
                    receipt = repository.receipt(prior.observation_id)
                    result = repository.get(prior.observation_id)
                    if (result.state != "proposed" or result.classification
                            != Classification.model_validate(case["classification"])):
                        raise ValueError("Classification does not match this reviewed case")
            else:
                receipt = await harness.run(activities.classify, request)
            classified, extracted = repository.get(receipt.observation_id), None
            diagnostics = []
            if (classified.state == "proposed" and classified.classification
                    and classified.classification.kind == "mirza"):
                with capture_run_messages() as messages:
                    receipt = await harness.run(activities.extract, request, receipt.observation_id)
                extracted = repository.get(receipt.observation_id)
                if args.diagnostics:
                    for message in messages:
                        for part in message.parts:
                            if part.part_kind == "retry-prompt":
                                diagnostics.append([
                                    {"type": error["type"], "path": error["loc"]}
                                    for error in part.content
                                ] if isinstance(part.content, list) else "validation_retry")
            observations = [r for r in (classified, extracted) if r is not None]
            row = {
                "case": case["id"], "passed": matches(case, classified, extracted),
                "classification_reused": args.extract_only,
                "reason_codes": [r.reason_code for r in observations],
                "model_requests": sum(r.model_requests for r in observations),
                "input_tokens": sum(r.input_tokens for r in observations),
                "output_tokens": sum(r.output_tokens for r in observations),
                "estimated_cost_usd": sum(r.estimated_cost_usd or 0 for r in observations),
                "latency_ms": sum(r.latency_ms for r in observations),
                "authorized": any(r.authorized for r in observations),
                "observed_classification": classified.classification.model_dump(mode="json")
                if classified.classification else None,
                "observed_proposal": extracted.proposal.model_dump(mode="json")
                if extracted and extracted.proposal else None,
                "schema_diagnostics": diagnostics,
            }
            results.append(row)
            print(json.dumps(row), flush=True)
        report = {"model": settings.inference_model, "endpoint": ENDPOINT,
                  "data": "synthetic; labels derive from operator-confirmed rules",
                  "runtime": "Temporal ActivityEnvironment; native recovery checked separately",
                  "usage": "Recorded receipts include reused classifications; not provider billing",
                  "per_stage_reservation_cap": settings.inference_max_cost_usd,
                  "daily_reservation_cap": settings.inference_daily_budget_usd,
                  "external_changes": 0, "results": results}
        if args.report:
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        return 0 if all(r["passed"] and not r["authorized"] for r in results) else 1
    finally:
        await inference.close()
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=ROOT / ".local/qwen-evaluation.db")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--case")
    parser.add_argument("--diagnostics", action="store_true")
    parser.add_argument("--skip-routing", action="store_true")
    parser.add_argument("--extract-only", action="store_true")
    args = parser.parse_args()
    try:
        token = getpass.getpass("Inference token (not stored): ")
        if not token:
            raise ValueError("Token unavailable")
        raise SystemExit(asyncio.run(evaluate(args, token)))
    except KeyboardInterrupt:
        print(json.dumps({"evaluation_available": False, "reason": "interrupted"}))
        raise SystemExit(1) from None
    except Exception as error:
        print(json.dumps({"evaluation_available": False, "error_type": type(error).__name__}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
