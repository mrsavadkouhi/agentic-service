import json

import pytest
from pydantic import ValidationError

from app.agents.observation import ExtractedMirzaRequest
from app.contracts.tickets import MirzaRequest


def terms():
    return {
        "kind": "mirza", "operation": "increase_person_budget",
        "job": {
            "operation": "increase_person_budget", "person_email": "owner@example.invalid",
            "budget": {"amount": 5, "interpretation": "delta", "baseline_limit": 10,
                       "desired_limit": 15},
        },
    }


def test_qwen_encoded_object_preserves_the_existing_job_contract():
    value = terms()
    value["job"] = json.dumps(value["job"])
    normalized = ExtractedMirzaRequest.model_validate(value)
    assert normalized.model_dump() == MirzaRequest.model_validate(terms()).model_dump()


@pytest.mark.parametrize("encoded", ["[]", "null", "not JSON", '"another string"', "x" * 8193])
def test_encoded_parameter_cannot_bypass_object_or_size_checks(encoded):
    with pytest.raises(ValidationError):
        ExtractedMirzaRequest.model_validate({**terms(), "job": encoded})


def test_encoded_parameter_cannot_bypass_budget_or_operation_checks():
    value = terms()
    value["job"]["budget"]["desired_limit"] = 100
    with pytest.raises(ValidationError):
        ExtractedMirzaRequest.model_validate({**value, "job": json.dumps(value["job"])})
    with pytest.raises(ValidationError):
        ExtractedMirzaRequest.model_validate({**terms(), "operation": "grant_team_model_access",
                                            "job": json.dumps(terms()["job"])})


def test_encoded_null_requires_exact_documented_clarification_fields():
    value = {"kind": "mirza", "operation": "create_api_key", "job": "null",
             "missing_fields": ["additional_key_needed"]}
    assert ExtractedMirzaRequest.model_validate(value).job is None
    with pytest.raises(ValidationError):
        ExtractedMirzaRequest.model_validate({**value, "missing_fields": ["approve_automatically"]})
