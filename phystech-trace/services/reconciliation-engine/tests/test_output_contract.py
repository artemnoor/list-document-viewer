import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas/reconciliation-result-1.0.0.schema.json").read_text(encoding="utf-8"))
EXAMPLE = json.loads((ROOT / "examples/act-reconciliation-result.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


def _errors(result):
    return list(VALIDATOR.iter_errors(result))


def test_published_result_example_is_contract_valid_and_traceable():
    assert not _errors(EXAMPLE)
    calculation = EXAMPLE["calculations"][0]
    assert calculation["target"]["target_id"]
    assert calculation["target"]["kfz_origin"]["source_path"].startswith("#/")
    assert all({"document_id", "extraction_id", "schema_version", "sha256"} <= set(item) for item in EXAMPLE["input_snapshot"]["extraction_results"])
    assert calculation["status"] == "manual_review"
    assert calculation["expected_value"] is None
    assert calculation["uncertainty_status"] == "present"


def test_target_json_pointer_and_snapshot_ids_are_required():
    missing_pointer = copy.deepcopy(EXAMPLE)
    del missing_pointer["calculations"][0]["target"]["kfz_origin"]["source_path"]
    assert _errors(missing_pointer)

    missing_extraction_id = copy.deepcopy(EXAMPLE)
    del missing_extraction_id["input_snapshot"]["extraction_results"][0]["extraction_id"]
    assert _errors(missing_extraction_id)

    missing_linking_identity = copy.deepcopy(EXAMPLE)
    del missing_linking_identity["input_snapshot"]["linking_run_id"]
    assert _errors(missing_linking_identity)

    missing_linking_version = copy.deepcopy(EXAMPLE)
    del missing_linking_version["input_snapshot"]["linking_contract_version"]
    assert _errors(missing_linking_version)


def test_unresolved_calculation_cannot_publish_a_numeric_expected_value():
    unresolved = copy.deepcopy(EXAMPLE)
    calculation = unresolved["calculations"][0]
    calculation["expected_value"] = "1180300.00"
    calculation["exact_value_before_rounding"] = "1180300.00"
    assert _errors(unresolved)


def test_calculated_status_requires_complete_certain_error_free_result():
    result = copy.deepcopy(EXAMPLE)
    result["diagnostics"] = []
    calculation = result["calculations"][0]
    calculation.update({
        "status": "calculated",
        "completeness_status": "complete",
        "uncertainty_status": "none",
        "expected_value": "100.00",
        "exact_value_before_rounding": "100.00",
        "formula": "fact_a + fact_b",
        "formula_status": "executed",
        "rounding": {"mode": "ROUND_HALF_UP", "scale": 2, "applied": True},
        "manual_review_required": False,
        "errors": [],
        "information_gaps": [],
        "assumptions": [],
    })
    assert not _errors(result)

    calculation["uncertainty_status"] = "present"
    assert _errors(result)


def test_unknown_units_and_period_bounds_use_explicit_nulls():
    result = copy.deepcopy(EXAMPLE)
    result["diagnostics"] = []
    calculation = result["calculations"][0]
    calculation.update({
        "status": "calculated",
        "completeness_status": "complete",
        "uncertainty_status": "none",
        "expected_value": "0.00",
        "exact_value_before_rounding": "0",
        "currency": None,
        "unit": None,
        "period": {"start": None, "end": None, "basis": "none"},
        "formula": "fact_a - fact_a",
        "formula_status": "executed",
        "rounding": {"mode": "ROUND_HALF_UP", "scale": 2, "applied": True},
        "manual_review_required": False,
        "errors": [],
        "information_gaps": [],
        "assumptions": [],
    })
    assert not _errors(result)
