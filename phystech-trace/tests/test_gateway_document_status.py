from gateway.main import document_extraction_state


def test_running_extraction_uses_document_id_even_when_names_match():
    stage = {"extraction": {"status": "running", "current_document_id": "a", "current_file": "scan.pdf"}}
    assert document_extraction_state({"id": "a", "file_name": "scan.pdf", "extraction_error": {"message": "previous attempt"}}, stage) == "running"
    assert document_extraction_state({"id": "b", "file_name": "scan.pdf"}, stage) == "pending"


def test_completed_failed_and_waiting_documents_are_distinct():
    doc = {"id": "a", "file_name": "scan.pdf"}
    assert document_extraction_state(doc, {}) == "pending"
    assert document_extraction_state({**doc, "extraction_error": {"message": "failed"}}, {}) == "error"
    assert document_extraction_state({**doc, "extraction_result": {}}, {}) == "ready"
    assert document_extraction_state(doc, {"extraction": {"status": "failed", "current_document_id": "a"}}) == "pending"


def test_older_running_stage_with_filename_remains_visible():
    assert document_extraction_state({"id": "a", "file_name": "scan.pdf"}, {"extraction": {"status": "running", "current_file": "scan.pdf"}}) == "running"
