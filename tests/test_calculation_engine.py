from decimal import Decimal

from reconciliation_engine.engine import execute_plan, validate_plan
from reconciliation_engine.facts import extract_facts
from reconciliation_engine.models import ReconciliationRequest
from reconciliation_engine.plans import CalculationPlan, PlanInclusion, PlanStep
from reconciliation_engine.service import reconcile

from conftest import (
    clone_extraction,
    correspondence_link,
    load_upstream,
    make_linking,
    make_request,
    make_target,
    plan_for,
    set_amount,
)


def _fact(facts, document_id, role, key, row_id=None):
    return next(fact for fact in facts if fact.document_id == document_id and fact.role == role and fact.key == key and (row_id is None or fact.row_id == row_id))


def _codes(result):
    return {item["code"] for item in result["calculations"][0]["diagnostics"]}


def test_one_extracted_document_can_support_a_single_value(settings):
    act = load_upstream("act-2026-0424.json")
    facts = extract_facts([act])
    source = _fact(facts, act["document_id"], "indicator", "amount_due")
    plan = plan_for([act], [source])
    request = make_request([act], plan, period_start="2026-04-01", period_end="2026-04-30")

    result = reconcile(request, settings)["calculations"][0]

    assert result["status"] == "calculated"
    assert result["expected_value"] == "1180300.00"
    assert len(result["included_sources"]) == 1
    assert result["included_sources"][0]["inclusion_reason"]


def test_independent_documents_are_summed_with_decimal(settings):
    first = clone_extraction(load_upstream("act-2026-0424.json"), "independent-a")
    second = clone_extraction(load_upstream("act-2026-0424.json"), "independent-b")
    set_amount(first, 0, "100.10")
    set_amount(second, 0, "50.20")
    extractions = [first, second]
    sources = [_fact(extract_facts([doc]), doc["document_id"], "line_item", "amount", doc["line_items"][0]["row_id"]) for doc in extractions]
    result = reconcile(make_request(extractions, plan_for(extractions, sources)), settings)["calculations"][0]

    assert result["expected_value"] == "150.30"
    assert len(result["included_sources"]) == 2


def test_corresponding_act_and_registry_rows_are_not_summed_twice(settings):
    act = load_upstream("act-2026-0424.json")
    registry = load_upstream("registry-2026-04.json")
    facts = extract_facts([act, registry])
    act_row = act["line_items"][0]["row_id"]
    registry_row = registry["line_items"][0]["row_id"]
    selected = [_fact(facts, act["document_id"], "line_item", "amount", act_row), _fact(facts, registry["document_id"], "line_item", "amount", registry_row)]
    link = correspondence_link(act, act_row, registry, registry_row)
    result = reconcile(make_request([act, registry], plan_for([act, registry], selected), links=[link]), settings)["calculations"][0]

    assert result["expected_value"] is None
    assert result["status"] == "manual_review"
    assert "corresponding_rows_double_counted" in _codes({"calculations": [result]})


def test_act_invoice_and_registry_views_of_one_operation_are_never_triple_counted(settings):
    act = load_upstream("act-2026-0424.json")
    registry = load_upstream("registry-2026-04.json")
    invoice = load_upstream("invoice-2026-0408.json")
    # Contract-valid synthetic row correspondences identify these three rows as
    # alternative records of one economic operation.
    set_amount(invoice, 0, "286500.00")
    docs = [act, registry, invoice]
    facts = extract_facts(docs)
    rows = [doc["line_items"][0]["row_id"] for doc in docs]
    selected = [_fact(facts, doc["document_id"], "line_item", "amount", row) for doc, row in zip(docs, rows)]
    first_link = correspondence_link(act, rows[0], registry, rows[1])
    second_link = correspondence_link(act, rows[0], invoice, rows[2])
    second_link["link_id"] = "test-correspondence-invoice"
    result = reconcile(make_request(docs, plan_for(docs, selected), links=[first_link, second_link]), settings)["calculations"][0]

    assert result["expected_value"] is None
    assert "corresponding_rows_double_counted" in _codes({"calculations": [result]})


def test_negative_adjustment_keeps_its_sign(settings):
    original = clone_extraction(load_upstream("act-2026-0424.json"), "operation-positive")
    correction = clone_extraction(load_upstream("act-2026-0424.json"), "operation-correction")
    set_amount(original, 0, "100.00")
    set_amount(correction, 0, "-20.00")
    docs = [original, correction]
    facts = extract_facts(docs)
    selected = [_fact(facts, doc["document_id"], "line_item", "amount", doc["line_items"][0]["row_id"]) for doc in docs]
    result = reconcile(make_request(docs, plan_for(docs, selected)), settings)["calculations"][0]

    assert result["expected_value"] == "80.00"


def test_source_from_wrong_period_is_excluded(settings):
    kfz = load_upstream("kfz-2026-q1.json")
    registry = load_upstream("registry-2026-04.json")
    facts = extract_facts([kfz, registry])
    source = _fact(facts, registry["document_id"], "line_item", "amount", registry["line_items"][0]["row_id"])
    target = make_target(period_basis="document_period", kfz_document_id=kfz["document_id"], kfz_row_id=kfz["line_items"][0]["row_id"])
    result = reconcile(make_request([kfz, registry], plan_for([kfz, registry], [source]), target, period_start="2026-01-01", period_end="2026-03-31"), settings)["calculations"][0]

    assert result["expected_value"] is None
    assert "period_outside_context" in _codes({"calculations": [result]})
    assert result["target"]["kfz_origin"]["row_id"] == kfz["line_items"][0]["row_id"]


def test_currency_mismatch_blocks_execution(settings):
    act = load_upstream("act-2026-0424.json")
    source = _fact(extract_facts([act]), act["document_id"], "indicator", "amount_due")
    target = make_target(currency="USD")
    result = reconcile(make_request([act], plan_for([act], [source]), target), settings)["calculations"][0]

    assert result["expected_value"] is None
    assert "currency_mismatch" in _codes({"calculations": [result]})


def test_mixed_source_currencies_block_execution_without_an_exchange_rate(settings):
    rub = clone_extraction(load_upstream("act-2026-0424.json"), "rub-source")
    usd = clone_extraction(load_upstream("act-2026-0424.json"), "usd-source")
    set_amount(rub, 0, "100.00", currency="RUB")
    set_amount(usd, 0, "50.00", currency="USD")
    docs = [rub, usd]
    facts = extract_facts(docs)
    selected = [_fact(facts, doc["document_id"], "line_item", "amount", doc["line_items"][0]["row_id"]) for doc in docs]
    target = make_target(currency=None)
    result = reconcile(make_request(docs, plan_for(docs, selected), target), settings)["calculations"][0]

    assert result["expected_value"] is None
    assert "mixed_currencies" in _codes({"calculations": [result]})


def test_incompatible_physical_units_block_execution(settings):
    act = load_upstream("act-2026-0424.json")
    quantity = _fact(extract_facts([act]), act["document_id"], "line_item", "quantity", act["line_items"][0]["row_id"])
    target = make_target(currency=None, unit="hour")
    result = reconcile(make_request([act], plan_for([act], [quantity]), target), settings)["calculations"][0]

    assert result["expected_value"] is None
    assert "unit_mismatch" in _codes({"calculations": [result]})


def test_ambiguous_link_requires_manual_review_even_if_plan_exists(settings):
    left = clone_extraction(load_upstream("act-2026-0424.json"), "left-operation")
    right = clone_extraction(load_upstream("act-2026-0424.json"), "right-operation")
    docs = [left, right]
    facts = extract_facts(docs)
    left_row, right_row = left["line_items"][0]["row_id"], right["line_items"][0]["row_id"]
    selected = [_fact(facts, left["document_id"], "line_item", "amount", left_row)]
    link = correspondence_link(left, left_row, right, right_row, status="review")
    target = make_target(kfz_document_id=left["document_id"], kfz_row_id=left_row)
    result = reconcile(make_request(docs, plan_for(docs, selected), target, links=[link], review=[{"link_id": link["link_id"], "reason": "ambiguous correspondence", "candidate_document_ids": [left["document_id"], right["document_id"]]}]), settings)["calculations"][0]

    assert result["expected_value"] is None
    assert "link_requires_human_review" in _codes({"calculations": [result]})


def test_human_decision_can_confirm_an_extraction_review_value(settings):
    act = load_upstream("act-2026-0424.json")
    set_amount(act, 0, "286500.00", status="review")
    source = _fact(extract_facts([act]), act["document_id"], "line_item", "amount", act["line_items"][0]["row_id"])
    result = reconcile(make_request([act], plan_for([act], [source]), accepted_fact_ids=[source.fact_id]), settings)["calculations"][0]

    assert result["expected_value"] == "286500.00"
    assert result["status"] == "calculated"
    assert result["included_sources"][0]["status"] == "review"
    assert result["included_sources"][0]["human_confirmation"]["reviewer_id"] == "test-reviewer"


def test_human_decision_can_confirm_a_review_link(settings):
    left = clone_extraction(load_upstream("act-2026-0424.json"), "human-left")
    right = clone_extraction(load_upstream("act-2026-0424.json"), "human-right")
    docs = [left, right]
    row = left["line_items"][0]["row_id"]
    other_row = right["line_items"][0]["row_id"]
    source = _fact(extract_facts(docs), left["document_id"], "line_item", "amount", row)
    link = correspondence_link(left, row, right, other_row, status="review")
    target = make_target(kfz_document_id=left["document_id"], kfz_row_id=row)
    result = reconcile(make_request(docs, plan_for(docs, [source]), target, links=[link], accepted_link_ids=[link["link_id"]]), settings)["calculations"][0]

    assert result["expected_value"] == "286500.00"
    assert result["included_sources"][0]["related_links"][0]["human_confirmation"]["decision_id"] == "decision-1"


def test_missing_required_document_is_not_replaced_by_zero(settings):
    act = load_upstream("act-2026-0424.json")
    source = _fact(extract_facts([act]), act["document_id"], "indicator", "amount_due")
    target = make_target(required_document_types=["invoice"])
    result = reconcile(make_request([act], plan_for([act], [source]), target), settings)["calculations"][0]

    assert result["expected_value"] is None
    assert result["status"] == "insufficient_data"
    assert "required_document_missing" in _codes({"calculations": [result]})


def test_review_and_missing_extraction_statuses_do_not_enter_arithmetic(settings):
    for status, amount in [("review", "1180300.00"), ("missing", None)]:
        act = load_upstream("act-2026-0424.json")
        set_amount(act, 0, amount, status=status)
        source = _fact(extract_facts([act]), act["document_id"], "line_item", "amount", act["line_items"][0]["row_id"])
        result = reconcile(make_request([act], plan_for([act], [source])), settings)["calculations"][0]
        assert result["expected_value"] is None
        assert "source_not_usable" in _codes({"calculations": [result]})


def test_vat_can_be_subtracted_only_as_an_explicit_net_plan(settings):
    act = load_upstream("act-2026-0424.json")
    facts = extract_facts([act])
    gross = _fact(facts, act["document_id"], "indicator", "amount_due")
    vat = _fact(facts, act["document_id"], "indicator", "vat_amount")
    steps = [PlanStep(step_id="net", operation="subtract", inputs=[gross.fact_id, vat.fact_id])]
    plan = plan_for([act], [gross, vat], steps=steps, amount_basis="net")
    target = make_target(amount_basis="net")
    result = reconcile(make_request([act], plan, target), settings)["calculations"][0]

    assert result["expected_value"] == "983583.33"
    assert result["amount_basis"] == "net"
    assert " - " in result["formula"]


def test_decimal_fractional_sum_and_half_up_rounding_are_exact(settings):
    docs = [clone_extraction(load_upstream("act-2026-0424.json"), "fraction-a"), clone_extraction(load_upstream("act-2026-0424.json"), "fraction-b")]
    set_amount(docs[0], 0, "0.10")
    set_amount(docs[1], 0, "0.20")
    facts = extract_facts(docs)
    selected = [_fact(facts, doc["document_id"], "line_item", "amount", doc["line_items"][0]["row_id"]) for doc in docs]
    result = reconcile(make_request(docs, plan_for(docs, selected)), settings)["calculations"][0]
    assert result["expected_value"] == "0.30"

    single = clone_extraction(load_upstream("act-2026-0424.json"), "half-cent")
    set_amount(single, 0, "0.005")
    fact = _fact(extract_facts([single]), single["document_id"], "line_item", "amount", single["line_items"][0]["row_id"])
    rounded = reconcile(make_request([single], plan_for([single], [fact])), settings)["calculations"][0]
    assert rounded["exact_value_before_rounding"] == "0.005"
    assert rounded["expected_value"] == "0.01"


def test_available_amounts_with_ambiguous_economic_meaning_do_not_execute(settings):
    act = load_upstream("act-2026-0424.json")
    source = _fact(extract_facts([act]), act["document_id"], "indicator", "amount_due")
    plan = plan_for([act], [source], requires_manual_review=True, information_gaps=["Cannot establish whether the value belongs to the requested economic measure."])
    result = reconcile(make_request([act], plan), settings)["calculations"][0]

    assert result["expected_value"] is None
    assert result["status"] == "manual_review"
    assert "plan_requires_manual_review" in _codes({"calculations": [result]})


def test_absent_link_edges_do_not_create_financial_evidence(settings):
    act = load_upstream("act-2026-0424.json")
    source = _fact(extract_facts([act]), act["document_id"], "indicator", "amount_due")
    # Empty graph + no approved plan stays uncertain; a references_contract link
    # would not silently convert the same fact into an additive source either.
    request = make_request([act], None)
    result = reconcile(request, settings)["calculations"][0]
    assert result["expected_value"] is None
    assert result["status"] == "insufficient_data"
    assert "planner_not_configured" in _codes({"calculations": [result]})
    assert source.fact_id in {item["fact_id"] for item in result["excluded_sources"]}


def test_repeated_run_has_same_numeric_result_and_snapshot_identity(settings):
    act = load_upstream("act-2026-0424.json")
    source = _fact(extract_facts([act]), act["document_id"], "indicator", "amount_due")
    request = make_request([act], plan_for([act], [source]))
    first = reconcile(request, settings)
    second = reconcile(request, settings)

    assert first["calculations"][0]["expected_value"] == second["calculations"][0]["expected_value"]
    assert first["input_snapshot"]["snapshot_sha256"] == second["input_snapshot"]["snapshot_sha256"]
    assert first["reconciliation_id"] == second["reconciliation_id"]


def test_provenance_is_preserved_from_kfz_target_to_xlsx_source(settings):
    kfz = load_upstream("kfz-2026-q1.json")
    registry = load_upstream("registry-2026-04.json")
    facts = extract_facts([kfz, registry])
    target_source = _fact(facts, kfz["document_id"], "line_item", "amount", kfz["line_items"][0]["row_id"])
    source = _fact(facts, registry["document_id"], "line_item", "amount", registry["line_items"][0]["row_id"])
    target = make_target(target_fact_id=target_source.fact_id, period_basis="none")
    result = reconcile(make_request([kfz, registry], plan_for([kfz, registry], [source]), target), settings)["calculations"][0]
    included = result["included_sources"][0]

    assert result["target"]["kfz_origin"]["row_id"] == target_source.row_id
    assert included["document_id"] == registry["document_id"]
    assert included["row_id"] == registry["line_items"][0]["row_id"]
    assert included["source_value"]
    assert included["value"]["amount"] == "286500.00"
    assert included["provenance"]["sheet_name"] == "Реестр"
    assert included["provenance"]["cell_address"] == "H7"
    assert included["provenance"]["source_ref"] == "Реестр!H7"
    assert included["input_hash"]


def test_link_status_confirmed_without_human_confirmation_is_not_treated_as_human(settings):
    act = load_upstream("act-2026-0424.json")
    other = clone_extraction(load_upstream("act-2026-0424.json"), "other-act")
    facts = extract_facts([act, other])
    act_row, other_row = act["line_items"][0]["row_id"], other["line_items"][0]["row_id"]
    source = _fact(facts, act["document_id"], "line_item", "amount", act_row)
    link = correspondence_link(act, act_row, other, other_row, status="confirmed")
    target = make_target(kfz_document_id=act["document_id"], kfz_row_id=act_row)
    result = reconcile(make_request([act, other], plan_for([act, other], [source]), target, links=[link]), settings)["calculations"][0]
    assert result["expected_value"] is None
    assert "link_requires_human_review" in _codes({"calculations": [result]})


def test_summary_and_its_line_items_are_not_added_together(settings):
    act = load_upstream("act-2026-0424.json")
    facts = extract_facts([act])
    header = _fact(facts, act["document_id"], "indicator", "amount_due")
    row = _fact(facts, act["document_id"], "line_item", "amount", act["line_items"][0]["row_id"])
    result = reconcile(make_request([act], plan_for([act], [header, row])), settings)["calculations"][0]

    assert result["expected_value"] is None
    assert "header_and_rows_overlap" in _codes({"calculations": [result]})


def test_partial_calculation_does_not_publish_a_value_as_expected(settings):
    act = load_upstream("act-2026-0424.json")
    source = _fact(extract_facts([act]), act["document_id"], "line_item", "amount", act["line_items"][0]["row_id"])
    plan = plan_for([act], [source], information_gaps=["One expected operation document has not been supplied."])
    result = reconcile(make_request([act], plan), settings)["calculations"][0]

    assert result["expected_value"] is None
    assert result["exact_value_before_rounding"] is None
    assert result["status"] == "manual_review"
    assert result["data_sufficiency"] == "partial"
    assert result["uncertainty_status"] == "present"
    assert result["formula_status"] == "proposed"
    assert result["used_sources"] == []
    assert result["steps"] == []
    assert result["manual_review_required"] is True

