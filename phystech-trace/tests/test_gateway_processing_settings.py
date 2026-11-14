import pytest
from fastapi import HTTPException
from gateway import main


@pytest.mark.parametrize("classification", ["confidential", "public"])
def test_processing_settings_accepts_model_choice_and_resets_results(monkeypatch, classification):
    from contextlib import contextmanager
    queries = []
    class Connection:
        def execute(self, query, params):
            queries.append((query, params))
            return self
        def fetchone(self):
            return {"data_classification": "synthetic", "allow_external_llm": False}
        def commit(self): pass
    @contextmanager
    def database(): yield Connection()
    monkeypatch.setattr(main, 'project_row', lambda _: {'id': 'p'})
    monkeypatch.setattr(main, 'db', database)
    monkeypatch.setattr(main, 'project_payload', lambda _: {"id": "p"})
    main.update_processing_settings('p', main.ProjectProcessingSettings(data_classification=classification, allow_external_llm=True))
    assert any("extraction_result=NULL" in query for query, _ in queries)
    assert any("linking_result=NULL" in query and "verification_result=NULL" in query for query, _ in queries)
    assert any(params == (classification, True, "p") for _, params in queries)


def test_processing_settings_cannot_change_while_running(monkeypatch):
    monkeypatch.setattr(main, 'project_row', lambda _: {'id': 'p'})
    class Task:
        def done(self): return False
    monkeypatch.setitem(main.ACTIVE_TASKS, 'p', Task())
    with pytest.raises(HTTPException) as exc:
        main.update_processing_settings('p', main.ProjectProcessingSettings(data_classification='synthetic', allow_external_llm=True))
    assert exc.value.status_code == 409
