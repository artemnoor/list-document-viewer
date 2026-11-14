import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from reconciliation_engine.contracts import validate_upstream_inputs
from reconciliation_engine.errors import InputContractError

from conftest import UPSTREAM_FIXTURES, load_upstream, make_linking


def test_real_structured_extraction_1_2_fixtures_match_upstream_schema():
    schema = json.loads((Path(__file__).resolve().parents[1] / "schemas/upstream/structured-extraction-1.2.0.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    fixtures = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(UPSTREAM_FIXTURES.glob("*.json"))]
    assert len(fixtures) == 6
    for document in fixtures:
        assert not list(validator.iter_errors(document)), document["document_id"]


def test_matching_extractions_and_contract_valid_link_snapshot_are_accepted():
    extractions = [load_upstream(name) for name in ["act-2026-0424.json", "invoice-2026-0408.json"]]
    validate_upstream_inputs(extractions, make_linking(extractions))


def test_stale_upstream_link_example_is_rejected_with_exact_legacy_version():
    extractions = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(UPSTREAM_FIXTURES.glob("*.json"))]
    legacy = json.loads((Path(__file__).resolve().parents[1] / "fixtures/upstream-linking/linking-result-legacy-1.0.0.json").read_text(encoding="utf-8"))
    with pytest.raises(InputContractError) as error:
        validate_upstream_inputs(extractions, legacy)
    codes = {diagnostic.code for diagnostic in error.value.diagnostics}
    assert "unsupported_linking_contract_version" in codes
    assert any(item.path == "$.linking_result.contract_version" and item.details["actual"] == "1.0.0" for item in error.value.diagnostics)


def test_incompatible_extraction_major_version_is_rejected():
    extraction = load_upstream("act-2026-0424.json")
    extraction["schema_version"] = "2.0.0"
    with pytest.raises(InputContractError) as error:
        validate_upstream_inputs([extraction], make_linking([extraction]))
    assert any(item.code == "unsupported_extraction_schema_version" for item in error.value.diagnostics)


def test_versioned_request_schema_contains_the_exact_upstream_contracts():
    root = Path(__file__).resolve().parents[1]
    request_schema = json.loads((root / "schemas/reconciliation-request-1.0.0.schema.json").read_text(encoding="utf-8"))
    extraction_schema = json.loads((root / "schemas/upstream/structured-extraction-1.2.0.schema.json").read_text(encoding="utf-8"))
    linking_schema = json.loads((root / "schemas/upstream/document-linking-1.2.0.schema.json").read_text(encoding="utf-8"))
    assert request_schema["properties"]["contract_version"]["const"] == "1.0.0"
    assert request_schema["$defs"]["StructuredExtractionResult1_2_0"] == extraction_schema
    assert request_schema["$defs"]["DocumentLinkingResult1_2_0"] == linking_schema

