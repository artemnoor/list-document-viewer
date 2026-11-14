from gateway.main import (
    mark_reconciliation_pending,
    parser_filename_header,
    reconciliation_targets,
    should_resume_linking_job,
    should_reuse_saved_linking_result,
)


def test_reconciliation_invalidation_preserves_other_stages_and_clears_completion():
    stages = {
        "parser": {"status": "completed", "completed": 2, "total": 2},
        "linking": {"status": "completed", "completed": 1, "total": 1},
        "reconciliation": {"status": "completed", "completed": 1, "total": 1, "error": "old"},
    }

    updated = mark_reconciliation_pending(stages)

    assert updated["parser"] == stages["parser"]
    assert updated["linking"] == stages["linking"]
    assert updated["reconciliation"]["status"] == "pending"
    assert updated["reconciliation"]["completed"] == 0
    assert updated["reconciliation"]["error"] is None


def test_completed_linking_job_is_rerun_while_incomplete_job_is_resumed():
    assert not should_resume_linking_job("completed")
    assert should_resume_linking_job("failed")
    assert should_resume_linking_job("paused")
    assert should_resume_linking_job(None)


def test_reconciliation_retry_reuses_saved_linking_result():
    assert should_reuse_saved_linking_result("reconciliation")
    assert not should_reuse_saved_linking_result("linking")


def test_parser_filename_header_encodes_unicode_without_losing_extension():
    header = parser_filename_header("Карточка отчёта.pdf")

    assert header.isascii()
    assert header.endswith(".pdf")
    assert "%D0%9A" in header


def _amount_wrapper(source_ref: str, source_part_id: str):
    return {
        "label": "Reported total",
        "value": {"amount": "10.00", "currency": "RUB"},
        "provenance": {"source_ref": source_ref, "source_part_id": source_part_id},
    }


def test_reconciliation_target_uses_canonical_indicator_pointer_for_duplicate_evidence():
    extraction = {
        "document_id": "kfz-doc",
        "fields": {"reported_total": _amount_wrapper("#/texts/7", "part-7")},
        "indicators": [{
            "key": "reported_total",
            "extracted": _amount_wrapper("#/texts/7", "part-7"),
        }],
    }

    targets = reconciliation_targets(extraction)

    assert len(targets) == 1
    assert targets[0]["kfz_source_path"] == "#/indicators/0/extracted"


def test_reconciliation_target_keeps_field_pointer_when_no_indicator_alias_exists():
    extraction = {
        "document_id": "kfz-doc",
        "fields": {"reported_total": _amount_wrapper("#/texts/7", "part-7")},
        "indicators": [],
    }

    targets = reconciliation_targets(extraction)

    assert len(targets) == 1
    assert targets[0]["kfz_source_path"] == "#/fields/reported_total"


def test_reconciliation_includes_nonmonetary_report_indicators_without_system_counts():
    extraction = {"document_id": "kfz", "fields": {}, "indicators": [
        {"key": "effort", "label": "Трудоемкость", "extracted": {"value": "42", "status": "extracted", "provenance": {"source_part_id": "p1"}}},
        {"key": "extracted_line_count", "extracted": {"value": "5", "provenance": None}},
    ]}
    targets = reconciliation_targets(extraction)
    assert len(targets) == 1
    assert targets[0]["kfz_source_path"] == "#/indicators/0/extracted"
    assert targets[0]["currency"] is None


def test_optional_review_failure_preserves_recognized_content():
    import asyncio
    import httpx
    from gateway import main
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"document_review": {"status": "failed"}}))) as client:
            result = {"parts": [{"text": "Recognized content"}]}
            await main.add_optional_review(client, "doc", "test-model", result)
            assert result["parts"][0]["text"] == "Recognized content"
            assert result["document_review"]["status"] == "failed"
            assert result["warnings"]
    asyncio.run(check())


def test_reconciliation_does_not_hide_monetary_indicator_with_missing_currency():
    targets = reconciliation_targets({"document_id": "kfz", "fields": {}, "indicators": [{"key": "cost", "label": "Cost", "extracted": {"value": {"amount": "12.00", "currency": None}, "status": "review", "provenance": {"source_part_id": "p1"}}}]})
    assert len(targets) == 1
    assert targets[0]["currency"] is None


def test_reconciliation_deduplicates_repeated_indicator_evidence_from_fragments():
    wrapper = _amount_wrapper("#/tables/0/rows/1/cells/2", "cell-2")
    targets = reconciliation_targets({"document_id": "kfz", "fields": {}, "indicators": [{"key": "first", "extracted": wrapper}, {"key": "alias", "extracted": wrapper}]})
    assert len(targets) == 1
    assert targets[0]["kfz_source_path"] == "#/indicators/0/extracted"


def test_report_scope_selects_requested_stage_year_and_rejects_inverted_period():
    from gateway.main import VerificationScope, scope_targets
    import pytest
    scope = VerificationScope(report_row="3 этап, 2026 г.", period_start="2026-01-01", period_end="2026-05-31")
    targets = [{"label": "Оплата труда 3 этап 2026"}, {"label": "Оплата труда 3 этап 2025"}, {"label": "Итого 13 этап 2026"}]
    assert scope_targets(targets, scope.model_dump(mode="json")) == [targets[0]]
    with pytest.raises(ValueError):
        VerificationScope(period_start="2026-05-31", period_end="2026-01-01")
