"""Report aggregate observation quality from reviewer labels; never invoke a model or write."""

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.settings import Settings  # noqa: E402
from app.storage.database import make_engine  # noqa: E402
from app.storage.observations import ObservationRepository  # noqa: E402


def evaluate_labels(repository, labels):
    if not isinstance(labels, list) or not 1 <= len(labels) <= 2000:
        raise ValueError("Reviewed labels must be a bounded nonempty list")
    matched, observed, missing = 0, 0, 0
    seen = set()
    latency, costs = [], []
    for label in labels:
        if not isinstance(label, dict) or not {"ticket_id", "expected_kind"} <= label.keys():
            raise ValueError("Invalid label shape")
        if label["expected_kind"] not in {
            "correct_support_group",
            "mirza",
            "no_op",
            "manual_review",
        }:
            raise ValueError("Invalid expected kind")
        identity = (label.get("tenant_id", "servicedesk"), label["ticket_id"])
        if identity in seen:
            raise ValueError("Duplicate reviewed ticket")
        seen.add(identity)
        rows = repository.latest(label.get("tenant_id", "servicedesk"), label["ticket_id"])
        completed = [row for row in rows if row["result"]]
        selected = completed
        classified = next((row for row in completed if row["stage"] == "classify"), None)
        if (
            classified
            and classified["result"]["state"] == "proposed"
            and ((classified["result"].get("classification") or {}).get("kind") == "mirza")
        ):
            extracted = [
                row
                for row in completed
                if row["stage"] == "extract"
                and row["result"]["evidence_refs"] == classified["result"]["evidence_refs"]
            ]
            selected = extracted or [classified]
        elif classified:
            selected = [classified]
        if not selected:
            missing += 1
            continue
        result = selected[0]["result"]
        proposal = result.get("proposal") or {}
        classification = result.get("classification") or {}
        kind = (
            "manual_review"
            if result["state"] in {"manual_review", "blocked", "unavailable"}
            else proposal.get(
                "kind",
                "mirza" if classification.get("kind") == "mirza" else "no_op",
            )
        )
        correct = kind == label["expected_kind"]
        if "expected_group_id" in label:
            correct = correct and proposal.get("destination_group_id") == label["expected_group_id"]
        if "expected_operation" in label:
            correct = correct and proposal.get("operation") == label["expected_operation"]
        observed += 1
        matched += correct
        latency.append(result.get("latency_ms", 0))
        for row in completed:
            if row["result"].get("estimated_cost_usd") is not None:
                costs.append(row["result"]["estimated_cost_usd"])
    return {
        "reviewed_cases": len(labels),
        "observed_cases": observed,
        "missing_cases": missing,
        "matched_cases": matched,
        "accuracy": matched / observed if observed else None,
        "median_inference_latency_ms": statistics.median(latency) if latency else None,
        "estimated_cost_usd": sum(costs),
        "external_writes": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, required=True)
    args = parser.parse_args()
    engine = None
    try:
        engine = make_engine(Settings())
        report = evaluate_labels(ObservationRepository(engine), json.loads(args.labels.read_text()))
        print(json.dumps(report))
    except Exception as exc:
        print(json.dumps({"evaluation_available": False, "error_type": type(exc).__name__}))
        raise SystemExit(1)
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    main()
