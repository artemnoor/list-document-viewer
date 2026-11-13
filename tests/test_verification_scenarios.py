from __future__ import annotations

import copy
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st
from jsonschema import Draft202012Validator

from app.contracts import ContractValidationError, load_schema, validate_request_contracts, validate_result_contract
from app.engine import run_verification
from app.explanations import HypothesisProposal
from app.models import DiscrepancyCategory
from app.reconciliation_adapter import ProvisionalReconciliationAdapter
from app.models import VerificationRequest
from tests.helpers import FIXTURES, base_payload, confirmed_linking_payload, indicator, make_request, read_json, set_actual, set_expected, set_source_amount, verify


EXPECTED = read_json(FIXTURES / "expected-statuses.json")
ROOT = FIXTURES.parents[2]


def test_exact_financial_value_is_matched_with_full_trace():
    result = verify()
    value = indicator(result)
    assert value.status.value == EXPECTED["exact_financial_value"]
    assert value.actual.normalized_value == {"amount": "100.00", "currency": "RUB"}
    assert value.expected.normalized_value == {"amount": "100.00", "currency": "RUB"}
    assert value.difference.absolute == "0.00"
    assert value.difference.formula == "actual - expected"
    assert value.expected.json_pointer == "/targets/0/result/expected_value"
    assert value.evidence.used_sources[0]["json_pointer"] == "/fields/source_amount/value"
    assert value.evidence.provenance_chain[0]["provenance"]["source_ref"] == "#/synthetic/kfz/page-1/total"
    assert value.evidence.reconciliation_reference["json_pointer"] == "/targets/0/result"
    assert result.input_metadata["reconciliation"]["contract_version"] == "1.0.0"


def test_proven_amount_difference_is_reproducible():
    payload = base_payload()
    set_actual(payload, {"amount": "100.00", "currency": "RUB"}, source_value="100.00 RUB")
    set_source_amount(payload, {"amount": "110.25", "currency": "RUB"}, "110.25 RUB")
    set_expected(payload, "110.25")
    result = verify(payload)
    value = indicator(result)
    assert value.status.value == EXPECTED["reproducible_amount_difference"]
    assert value.difference.absolute == "-10.25"
    assert value.difference.relative == "-0.09297052154195011337868480726"
    assert any(item.category.value == "amount_difference" and item.established for item in value.discrepancies)
    assert any(item.category.value == "unsubstantiated_cause" and item.hypothesis for item in value.discrepancies)


def test_explicit_absolute_tolerance_accepts_boundary_and_is_recorded():
    payload = base_payload()
    set_source_amount(payload, {"amount": "110.25", "currency": "RUB"}, "110.25 RUB")
    set_expected(payload, "110.25")
    payload["context"]["tolerance"]["absolute"] = "10.25"
    payload["context"]["tolerance"]["absolute_unit"] = "RUB"
    result = verify(payload)
    value = indicator(result)
    assert value.status.value == "matched"
    assert value.difference.accepted_by == "absolute_tolerance"
    assert value.difference.absolute == "-10.25"


def test_tolerance_acceptance_never_claims_a_proven_amount_difference():
    payload = base_payload()
    set_source_amount(payload, {"amount": "110.25", "currency": "RUB"}, "110.25 RUB")
    set_expected(payload, "110.25")
    payload["context"]["tolerance"]["absolute"] = "10.25"
    payload["context"]["tolerance"]["absolute_unit"] = "RUB"
    value = indicator(verify(payload))
    assert value.status.value == "matched"
    assert value.difference.absolute == "-10.25"
    assert value.difference.accepted_by == "absolute_tolerance"
    assert not any(item.category.value == "amount_difference" and item.established for item in value.discrepancies)


def test_aggregate_status_exposes_not_applicable_coverage_instead_of_matched():
    payload = base_payload()
    payload["reconciliation_result"]["targets"][1]["result"]["calculation_status"] = "not_applicable"
    result = verify(payload)
    assert indicator(result).status.value == "matched"
    assert result.overall_status.value == "not_applicable"
    assert result.completeness.complete is False
    assert result.completeness.not_applicable_indicators == 1
    assert result.completeness.verified_indicators == 1


def test_actual_period_comes_from_extraction_not_reconciliation_or_context():
    payload = base_payload()
    value = {"start": "2025-10-01", "end": "2025-12-31"}
    wrapper = payload["extraction"]["fields"]["reporting_period"]
    wrapper["value"] = value
    wrapper["source_value"] = "2025 Q4"
    wrapper["provenance"]["source_text"] = "2025 Q4"
    period_indicator = payload["extraction"]["indicators"][1]["extracted"]
    period_indicator["value"] = copy.deepcopy(value)
    period_indicator["source_value"] = "2025 Q4"
    period_indicator["provenance"]["source_text"] = "2025 Q4"
    payload["reconciliation_result"]["targets"][0]["target"]["period"] = {"start": "2026-01-01", "end": "2026-03-31"}
    payload["context"]["period"] = {"start": "2026-01-01", "end": "2026-03-31"}
    value_result = indicator(verify(payload))
    assert value_result.actual.period.start == "2025-10-01"
    assert value_result.status.value == "mismatch"
    assert any(item["code"] == "period_mismatch" for item in value_result.diagnostics)


def test_reconciliation_input_hash_mismatch_blocks_final_status():
    payload = base_payload()
    payload["reconciliation_result"]["run_metadata"]["input_data"]["extraction_hash"] = "0" * 64
    value = indicator(verify(payload))
    assert value.status.value == "insufficient_data"
    assert value.trust.calculation_trust == "invalid"
    assert any(item["code"] == "extraction_hash_mismatch" for item in value.diagnostics)


def test_missing_reconciliation_input_hash_is_not_treated_as_verified():
    payload = base_payload()
    payload["reconciliation_result"]["run_metadata"]["input_data"]["extraction_hash"] = None
    value = indicator(verify(payload))
    assert value.status.value == "insufficient_data"
    assert any(item["code"] == "extraction_hash_missing" for item in value.diagnostics)


def test_incompatible_reconciliation_extraction_version_blocks_final_status():
    payload = base_payload()
    payload["reconciliation_result"]["run_metadata"]["input_data"]["extraction_schema_version"] = "1.1.0"
    value = indicator(verify(payload))
    assert value.status.value == "insufficient_data"
    assert any(item["code"] == "extraction_version_mismatch" for item in value.diagnostics)


def test_operation_output_must_match_reconciliation_expected_value():
    payload = base_payload()
    payload["reconciliation_result"]["targets"][0]["result"]["operations"][0]["output_value"] = "999.00"
    value = indicator(verify(payload))
    assert value.status.value == "insufficient_data"
    assert value.trust.calculation_trust == "invalid"
    assert any(item["code"] == "calculation_output_mismatch" for item in value.diagnostics)


def test_operation_formula_must_reference_the_declared_inputs():
    payload = base_payload()
    payload["reconciliation_result"]["targets"][0]["result"]["operations"][0]["input_source_ids"] = []
    value = indicator(verify(payload))
    assert value.status.value == "insufficient_data"
    assert any(item["code"] == "calculation_formula_input_mismatch" for item in value.diagnostics)


def test_missing_calculation_operations_remains_unproven():
    payload = base_payload()
    payload["reconciliation_result"]["targets"][0]["result"]["operations"] = []
    value = indicator(verify(payload))
    assert value.status.value == "needs_review"
    assert value.trust.calculation_trust == "unproven"
    assert any(item["code"] == "calculation_proof_unverified" for item in value.diagnostics)


def test_system_validated_source_can_support_automatic_result():
    payload = base_payload()
    payload["reconciliation_result"]["targets"][0]["result"]["used_sources"][0]["evidence_status"] = "system_validated"
    value = indicator(verify(payload))
    assert value.status.value == "matched"
    assert value.trust.technical_validity == "valid"
    assert value.trust.human_confirmation == "unconfirmed"
    assert value.trust.calculation_trust == "proven"


def test_difference_above_explicit_tolerance_remains_mismatch():
    payload = base_payload()
    set_source_amount(payload, {"amount": "110.25", "currency": "RUB"}, "110.25 RUB")
    set_expected(payload, "110.25")
    payload["context"]["tolerance"]["absolute"] = "10.24"
    payload["context"]["tolerance"]["absolute_unit"] = "RUB"
    assert indicator(verify(payload)).status.value == "mismatch"


def test_null_expected_is_missing_not_zero():
    payload = base_payload()
    payload["reconciliation_result"]["targets"][0]["result"]["expected_value"] = None
    result = verify(payload)
    value = indicator(result)
    assert value.status.value == "insufficient_data"
    assert value.expected is None
    assert value.difference.absolute is None
    assert any(item["code"] == "expected_value_missing" for item in value.diagnostics)


def test_missing_actual_value_is_insufficient_data():
    payload = base_payload()
    set_actual(payload, None, status="missing", source_value=None)
    value = indicator(verify(payload))
    assert value.status.value == "insufficient_data"
    assert value.actual.normalized_value is None
    assert any(item["code"] == "actual_value_missing" for item in value.diagnostics)


def test_partial_multi_document_calculation_cannot_be_a_mismatch():
    payload = base_payload()
    set_expected(payload, "80.00")
    target_result = payload["reconciliation_result"]["targets"][0]["result"]
    target_result["calculation_status"] = "incomplete"
    target_result["used_sources"].append({
        "source_id": "src-missing-document", "document_id": "missing-document", "extraction_id": "missing-extraction",
        "row_id": None, "json_pointer": "/fields/amount/value", "evidence_status": "human_confirmed",
        "operation_ids": ["operation-sum-1"],
    })
    value = indicator(verify(payload))
    assert value.status.value == "insufficient_data"
    assert value.difference.absolute == "20.00"
    assert not any(item.category.value == "amount_difference" and item.established for item in value.discrepancies)


def test_confirmed_duplicate_requires_two_resolved_sources_and_repeated_operation():
    payload = base_payload()
    target_result = payload["reconciliation_result"]["targets"][0]["result"]
    target_result["used_sources"].append({
        **copy.deepcopy(target_result["used_sources"][0]),
        "source_id": "src-invoice-duplicate",
    })
    target_result["expected_value"] = {"amount": "200.00", "currency": "RUB"}
    target_result["operations"][0]["output_value"] = "200.00"
    target_result["operations"][0]["input_source_ids"] = ["src-invoice-total", "src-invoice-duplicate"]
    target_result["formula"] = "SUM(src-invoice-total, src-invoice-duplicate)"
    target_result["operations"][0]["formula"] = target_result["formula"]
    target_result["diagnostics"] = [{
        "code": "duplicate_confirmed", "message": "The same source operation was included twice.", "confirmed": True,
        "source_ids": ["src-invoice-total", "src-invoice-duplicate"],
        "evidence_references": ["src-invoice-total", "src-invoice-duplicate"],
    }]
    value = indicator(verify(payload))
    assert value.status.value == "mismatch"
    assert any(item.category.value == "duplicate_operation" and item.established for item in value.discrepancies)


def test_suspected_duplicate_is_a_hypothesis_and_needs_review():
    payload = base_payload()
    payload["reconciliation_result"]["targets"][0]["result"]["diagnostics"] = [{
        "code": "duplicate_suspected", "message": "Two entries may be duplicates.", "confirmed": False,
        "source_ids": ["src-invoice-total"], "evidence_references": [],
    }]
    value = indicator(verify(payload))
    assert value.status.value == "needs_review"
    assert any(item.category.value == "duplicate_operation" and item.hypothesis and not item.established for item in value.discrepancies)


def test_different_periods_are_classified_as_wrong_period():
    payload = base_payload()
    payload["reconciliation_result"]["targets"][0]["result"]["period"] = {"start": "2025-10-01", "end": "2025-12-31"}
    value = indicator(verify(payload))
    assert value.status.value == EXPECTED["period_mismatch_with_confirmed_source"]
    assert any(item.category.value == "wrong_period" and item.established for item in value.discrepancies)


def test_currency_mismatch_is_not_compared_as_an_amount_error():
    payload = base_payload()
    payload["reconciliation_result"]["targets"][0]["result"]["expected_value"] = {"amount": "100.00", "currency": "USD"}
    payload["reconciliation_result"]["targets"][0]["result"]["currency"] = "USD"
    value = indicator(verify(payload))
    assert value.status.value == "not_applicable"
    assert any(item.category.value == "incompatible_unit" and item.established for item in value.discrepancies)
    assert value.difference.absolute is None


def test_unit_mismatch_is_not_compared_as_a_quantity():
    payload = base_payload()
    target = payload["reconciliation_result"]["targets"][0]
    target["target"].update({"value_type": "quantity", "unit": "item", "currency": None, "vat_basis": "not_applicable"})
    target["result"].update({"value_type": "quantity", "semantic_key": "reported_total", "unit": "hour", "currency": None, "vat_basis": "not_applicable", "expected_value": "3"})
    set_actual(payload, "3", source_value="3")
    value = indicator(verify(payload))
    assert value.status.value == EXPECTED["incompatible_units"]
    assert any(item.category.value == "incompatible_unit" for item in value.discrepancies)


def test_explicit_rounding_rule_is_applied_and_reported():
    payload = base_payload()
    set_actual(payload, {"amount": "100.04", "currency": "RUB"}, "extracted", "100.04 RUB")
    set_source_amount(payload, {"amount": "100.00", "currency": "RUB"}, "100.00 RUB")
    set_expected(payload, "100.00")
    payload["context"]["tolerance"]["rounding_scale"] = 1
    value = indicator(verify(payload))
    assert value.status.value == "matched"
    assert value.difference.absolute == "0.04"
    assert value.difference.accepted_by == "rounding"
    assert any(item.category.value == "rounding_problem" and item.established for item in value.discrepancies)


def test_rounding_difference_without_policy_is_not_silently_tolerated():
    payload = base_payload()
    set_actual(payload, {"amount": "100.04", "currency": "RUB"}, "extracted", "100.04 RUB")
    value = indicator(verify(payload))
    assert value.status.value == "mismatch"
    assert "no_rounding_rule_or_tolerance_was_supplied" in value.uncertainty.reasons
    assert not value.uncertainty.manual_review_required
    assert value.trust.calculation_trust == "proven"


def test_explicit_tolerance_for_another_unit_is_not_applied():
    payload = base_payload()
    set_expected(payload, "110.25")
    set_source_amount(payload, {"amount": "110.25", "currency": "RUB"}, "110.25 RUB")
    payload["context"]["tolerance"]["absolute"] = "10.25"
    payload["context"]["tolerance"]["absolute_unit"] = "USD"
    value = indicator(verify(payload))
    assert value.status.value == "mismatch"
    assert "absolute_tolerance_unit_does_not_match_measure" in value.uncertainty.reasons


def test_relative_difference_for_zero_expected_is_undefined():
    payload = base_payload()
    set_actual(payload, {"amount": "0.00", "currency": "RUB"}, "extracted", "0.00 RUB")
    set_source_amount(payload, {"amount": "0.00", "currency": "RUB"}, "0.00 RUB")
    set_expected(payload, "0.00")
    value = indicator(verify(payload))
    assert value.status.value == "matched"
    assert value.difference.relative is None
    assert "relative_difference_undefined_for_zero_expected_value" in value.uncertainty.reasons


def test_negative_amount_adjustment_preserves_signed_difference():
    payload = base_payload()
    set_actual(payload, {"amount": "-10.50", "currency": "RUB"}, "extracted", "-10.50 RUB")
    set_source_amount(payload, {"amount": "-10.00", "currency": "RUB"}, "-10.00 RUB")
    set_expected(payload, "-10.00")
    value = indicator(verify(payload))
    assert value.status.value == "mismatch"
    assert value.difference.absolute == "-0.50"
    assert value.difference.relative == "-0.05"


def test_equal_numbers_with_unconfirmed_source_need_review():
    payload = base_payload()
    payload["reconciliation_result"]["targets"][0]["result"]["used_sources"][0]["evidence_status"] = "unconfirmed"
    value = indicator(verify(payload))
    assert value.status.value == EXPECTED["unconfirmed_calculation_evidence"]
    assert value.difference.absolute == "0.00"
    assert not any(item.category.value == "amount_difference" and item.established for item in value.discrepancies)


def test_extraction_review_required_flag_blocks_matched():
    payload = base_payload()
    payload["extraction"]["review_required"] = [{
        "path": "fields.reported_total", "reason": "Reviewer must confirm the printed amount.",
        "source_value": "100.00 RUB", "provenance": payload["extraction"]["fields"]["reported_total"]["provenance"],
    }]
    value = indicator(verify(payload))
    assert value.status.value == "needs_review"
    assert any(item["code"] == "actual_review_required" for item in value.diagnostics)


@pytest.mark.parametrize("invalid_locator", ["missing", "unavailable"])
def test_invalid_actual_provenance_prevents_confirmation(invalid_locator: str):
    payload = base_payload()
    provenance = payload["extraction"]["fields"]["reported_total"]["provenance"]
    if invalid_locator == "missing":
        provenance.pop("source_ref")
        provenance.pop("page_no")
    else:
        provenance["source_available"] = False
    value = indicator(verify(payload))
    assert value.status.value == "insufficient_data"
    assert value.uncertainty.manual_review_required


def test_unresolved_actual_json_pointer_is_diagnostic_not_a_success():
    payload = base_payload()
    payload["reconciliation_result"]["targets"][0]["target"]["json_pointer"] = "/fields/not_present/value"
    value = indicator(verify(payload))
    assert value.status.value == "insufficient_data"
    assert any(item["code"] == "actual_reference_unresolved" for item in value.diagnostics)


def test_invalid_upstream_json_is_rejected_with_contract_path():
    payload = base_payload()
    payload["extraction"].pop("document_id")
    with pytest.raises(ContractValidationError) as caught:
        verify(payload)
    assert any(issue["path"].endswith("document_id") for issue in caught.value.as_list())


def test_incompatible_upstream_major_version_is_rejected():
    payload = base_payload()
    payload["extraction"]["schema_version"] = "2.0.0"
    with pytest.raises(ContractValidationError) as caught:
        verify(payload)
    assert any("Only additive Extraction contract 1.x" in issue["message"] for issue in caught.value.as_list())


def test_repeated_request_is_idempotent_and_retrievable(tmp_path: Path):
    from app.storage import SQLiteVerificationStore

    store = SQLiteVerificationStore(tmp_path / "runs.sqlite3")
    payload = make_request()
    first = store.create(payload)
    second = store.create(payload)
    assert first.verification_id == second.verification_id
    assert first.created_at == second.created_at
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert store.get(first.verification_id).model_dump(mode="json") == first.model_dump(mode="json")
    assert store.history(project_id="synthetic-project").items[0].verification_id == first.verification_id
    store.close()


def test_parallel_identical_requests_store_one_idempotent_run(tmp_path: Path):
    from app.storage import SQLiteVerificationStore

    store = SQLiteVerificationStore(tmp_path / "parallel-runs.sqlite3")
    request = make_request()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: store.create(request), range(16)))
    assert len({result.verification_id for result in results}) == 1
    assert len({result.created_at for result in results}) == 1
    assert store._db.execute("SELECT COUNT(*) FROM verification_runs").fetchone()[0] == 1
    store.close()


def test_optional_llm_call_runs_outside_sqlite_transaction(tmp_path: Path):
    from app.storage import SQLiteVerificationStore

    store = None

    class Provider:
        def suggest(self, _case):
            assert store is not None and not store._db.in_transaction
            time.sleep(0.02)
            return []

    store = SQLiteVerificationStore(tmp_path / "polza-transaction.sqlite3", explanation_provider=Provider())
    payload = base_payload()
    set_expected(payload, "110.25")
    set_source_amount(payload, {"amount": "110.25", "currency": "RUB"}, "110.25 RUB")
    result = store.create(make_request(payload))
    assert result.overall_status.value == "mismatch"
    store.close()


def test_multiple_problems_are_reported_without_claiming_a_full_calculation():
    payload = base_payload()
    target_result = payload["reconciliation_result"]["targets"][0]["result"]
    target_result["expected_value"] = {"amount": "90.00", "currency": "RUB"}
    target_result["period"] = {"start": "2025-10-01", "end": "2025-12-31"}
    target_result["diagnostics"] = [{
        "code": "missing_document", "message": "A required source document was not supplied.", "confirmed": True,
        "document_ids": ["missing-doc"], "source_ids": ["src-invoice-total"], "evidence_references": ["src-invoice-total"],
    }]
    target_result["excluded_sources"] = [{
        "source_id": "excluded-missing", "document_id": "missing-doc", "extraction_id": "missing-extraction",
        "row_id": None, "json_pointer": None, "evidence_status": "unknown", "reason": "Document not received",
    }]
    value = indicator(verify(payload))
    assert value.status.value == "insufficient_data"
    categories = {item.category.value for item in value.discrepancies}
    assert "wrong_period" in categories
    assert "missing_supporting_document" in categories
    excluded = value.evidence.excluded_sources[0]
    assert excluded["document_id"] == "missing-doc"
    assert excluded["reason"] == "Document not received"


def test_semantic_and_comparison_basis_conflict_is_not_a_numeric_mismatch():
    payload = base_payload()
    payload["reconciliation_result"]["targets"][0]["result"]["comparison_basis"] = "plan"
    value = indicator(verify(payload))
    assert value.status.value == "not_applicable"
    assert any(item.category.value == "economic_meaning_mismatch" for item in value.discrepancies)


def test_non_numeric_string_indicator_is_supported():
    payload = base_payload()
    set_actual(payload, "Approved", source_value="Approved")
    target = payload["reconciliation_result"]["targets"][0]
    target["target"].update({"value_type": "string", "vat_basis": "not_applicable", "currency": None})
    target["result"].update({"value_type": "string", "vat_basis": "not_applicable", "currency": None, "expected_value": "Approved"})
    target["result"]["operations"][0]["output_value"] = "Approved"
    value = indicator(verify(payload))
    assert value.status.value == EXPECTED["text_value_equal"]
    assert value.difference.accepted_by == "exact"
    assert value.difference.absolute is None


def test_human_confirmed_linking_evidence_is_resolved_and_preserved():
    payload = confirmed_linking_payload()
    result = verify(payload)
    value = indicator(result)
    assert value.status.value == "matched"
    assert value.evidence.linking_references[0]["verification_status"] == "human_confirmed"
    assert value.evidence.linking_references[0]["evidence"][0]["endpoint"] == "source"


def test_complete_machine_validated_link_does_not_require_human_review():
    payload = confirmed_linking_payload()
    payload["linking_result"]["links"][0]["verification_status"] = "not_reviewed"
    value = indicator(verify(payload))
    assert value.status.value == "matched"
    assert value.trust.automatic_link_confirmation == "confirmed"
    assert value.trust.human_confirmation == "unconfirmed"


def test_confirmed_link_status_without_matching_evidence_is_not_accepted():
    payload = confirmed_linking_payload()
    payload["linking_result"]["links"][0]["evidence"][0]["source"]["raw_value"] = "forged value"
    value = indicator(verify(payload))
    assert value.status.value == "insufficient_data"
    assert value.trust.automatic_link_confirmation == "unconfirmed"
    assert any(item["code"] == "link_evidence_value_mismatch" for item in value.diagnostics)


def test_confirmed_link_does_not_accept_forged_target_endpoint():
    payload = confirmed_linking_payload()
    payload["linking_result"]["links"][0]["evidence"][0]["target"]["raw_value"] = "forged value"
    value = indicator(verify(payload))
    assert value.status.value == "insufficient_data"
    assert value.trust.automatic_link_confirmation == "unconfirmed"
    assert any(item["code"] == "link_evidence_value_mismatch" for item in value.diagnostics)


def test_link_input_hash_mismatch_blocks_automatic_link_confirmation():
    payload = confirmed_linking_payload()
    payload["linking_result"]["input_documents"][1]["input_hash"] = "f" * 64
    value = indicator(verify(payload))
    assert value.status.value == "insufficient_data"
    assert value.trust.automatic_link_confirmation == "unconfirmed"
    assert any(item["code"] == "link_input_hash_mismatch" for item in value.diagnostics)


def test_link_evidence_that_does_not_resolve_is_insufficient():
    payload = confirmed_linking_payload()
    payload["linking_result"]["links"][0]["evidence"][0]["source"]["path"] = "fields/wrong"
    value = indicator(verify(payload))
    assert value.status.value == "insufficient_data"
    assert any(item["code"] == "link_evidence_unresolved" for item in value.diagnostics)


def test_synthetic_linking_12_contract_and_real_extraction_12_fixtures_validate():
    extraction_schema = load_schema("upstream/structured-extraction-1.2.0.schema.json")
    linking_schema = load_schema("upstream/document-linking-1.2.0.schema.json")
    for path in (ROOT / "tests" / "fixtures" / "upstream" / "extraction").glob("*.json"):
        payload = read_json(path)
        assert list(Draft202012Validator(extraction_schema).iter_errors(payload)) == []
    synthetic_linking = read_json(FIXTURES / "linking-confirmed.json")
    assert list(Draft202012Validator(linking_schema).iter_errors(synthetic_linking)) == []


def test_upstream_source_commits_and_schema_hashes_are_pinned():
    manifest = read_json(ROOT / "contracts" / "upstream-sources.json")
    assert len(manifest["integration_repository"]["commit"]) == 40
    assert len(manifest["structured_extraction"]["commit"]) == 40
    assert len(manifest["document_linking"]["commit"]) == 40
    for relative_path, expected_hash in (
        ("contracts/upstream/structured-extraction-1.2.0.schema.json", manifest["structured_extraction"]["schema_sha256"]),
        ("contracts/upstream/document-linking-1.2.0.schema.json", manifest["document_linking"]["schema_sha256"]),
        ("tests/fixtures/upstream/extraction/kfz-2026-q1.json", manifest["upstream_fixtures"]["kfz_extraction_fixture_sha256"]),
        ("tests/fixtures/upstream/linking/linking-result.json", manifest["upstream_fixtures"]["linking_result_fixture_sha256"]),
    ):
        actual = hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest()
        assert actual == expected_hash


def test_provisional_reconciliation_adapter_only_projects_fields_without_recalculation():
    payload = read_json(FIXTURES / "reconciliation-matched.json")
    adapted = ProvisionalReconciliationAdapter().adapt(payload)
    assert adapted[0].result is payload["targets"][0]["result"]
    assert adapted[0].result["expected_value"] == {"amount": "100.00", "currency": "RUB"}


def test_upstream_linking_example_is_detected_as_incompatible_with_declared_12_schema():
    linking_schema = load_schema("upstream/document-linking-1.2.0.schema.json")
    fixture = read_json(ROOT / "tests" / "fixtures" / "upstream" / "linking" / "linking-result.json")
    errors = list(Draft202012Validator(linking_schema).iter_errors(fixture))
    assert fixture["contract_version"] == "1.0.0"
    assert errors
    assert any("detection_method" in error.json_path for error in errors)


def test_output_schema_file_matches_pydantic_contract():
    output_schema = load_schema("verification-result-1.1.0.schema.json")
    Draft202012Validator.check_schema(output_schema)
    result = verify()
    validate_result_contract(result)
    Draft202012Validator(output_schema).validate(result.model_dump(mode="json"))
    assert output_schema["$id"].endswith("verification-result-1.1.0.schema.json")


def test_optional_explanation_provider_receives_deidentified_data_and_only_adds_hypotheses():
    class Provider:
        case = None

        def suggest(self, case):
            self.case = case
            return [HypothesisProposal(
                category=DiscrepancyCategory.UNSUBSTANTIATED_CAUSE,
                description="Possible timing difference; verify supporting period documents.",
                evidence_tokens=[case.evidence_tokens[0]],
                confidence="low",
            )]

    payload = base_payload()
    set_expected(payload, "110.25")
    set_source_amount(payload, {"amount": "110.25", "currency": "RUB"}, "110.25 RUB")
    provider = Provider()
    request = make_request(payload)
    result = run_verification(request, explanation_provider=provider)
    value = indicator(result)
    assert value.status.value == "mismatch"
    assert value.difference.absolute == "-10.25"
    suggestion = [item for item in value.discrepancies if item.description.startswith("Possible timing")][0]
    assert suggestion.hypothesis and not suggestion.established
    assert provider.case is not None
    safe_input = provider.case.model_dump_json()
    assert "100.00" not in safe_input and "110.25" not in safe_input
    assert "synthetic-invoice-001" not in safe_input


def test_invalid_optional_llm_evidence_reference_is_rejected_without_affecting_status():
    class Provider:
        def suggest(self, case):
            return [{
                "category": "amount_difference", "description": "Unsupported proposal", "evidence_tokens": ["not-a-token"], "confidence": "medium",
            }]

    payload = base_payload()
    set_expected(payload, "110.25")
    set_source_amount(payload, {"amount": "110.25", "currency": "RUB"}, "110.25 RUB")
    result = run_verification(make_request(payload), explanation_provider=Provider())
    value = indicator(result)
    assert value.status.value == "mismatch"
    assert value.difference.absolute == "-10.25"
    assert any(item["code"] == "llm_suggestion_rejected" for item in value.diagnostics)


@given(
    actual=st.decimals(min_value=Decimal("-100000"), max_value=Decimal("100000"), places=2, allow_nan=False, allow_infinity=False),
    expected=st.decimals(min_value=Decimal("-100000"), max_value=Decimal("100000"), places=2, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=60, deadline=None)
def test_decimal_difference_property_is_signed_exact_and_not_float_based(actual: Decimal, expected: Decimal):
    payload = base_payload()
    set_actual(payload, {"amount": format(actual, "f"), "currency": "RUB"}, source_value=f"{actual} RUB")
    set_source_amount(payload, {"amount": format(expected, "f"), "currency": "RUB"}, f"{expected} RUB")
    set_expected(payload, expected)
    value = indicator(verify(payload))
    assert Decimal(value.difference.absolute) == actual - expected
    assert value.status.value == ("matched" if actual == expected else "mismatch")
