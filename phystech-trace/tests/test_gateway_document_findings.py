from gateway import main


def test_wrong_agreement_and_period_are_document_findings_with_exact_source_paths():
    wrapper = lambda value: {"value": value, "status": "extracted", "provenance": {"source_ref": "#/parts/1"}}
    docs = [{"role": "kfz", "parser_document_id": "report", "file_name": "report.pdf", "extraction_result": {"fields": {"contract_reference": wrapper("A-17")}}}, {"role": "primary", "parser_document_id": "act", "file_name": "act.pdf", "extraction_result": {"fields": {"contract_reference": wrapper("B-18"), "act_date": wrapper("2026-06-03")}}}]
    findings = main.document_findings({"id": "p", "verification_scope": {"period_start": "2026-01-01", "period_end": "2026-05-31"}}, docs)
    assert {item["category"] for item in findings} == {"incorrect_document_link", "wrong_period"}
    assert all(item["document_id"] == "act" and item["source_path"].startswith("#/fields/") for item in findings)
