from gateway.main import (
    mark_reconciliation_pending,
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
