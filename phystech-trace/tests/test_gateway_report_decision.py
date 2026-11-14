from contextlib import contextmanager

import pytest
from fastapi import HTTPException

from gateway import main


@pytest.fixture
def report_db(monkeypatch):
    project = {"id": "review-test", "status": "completed", "financial_audit": {"indicators": [{"actual": "100", "expected": "90"}]}, "verification_scope": {"period_start": "2026-01-01"}}
    writes = []

    class Connection:
        def execute(self, query, params):
            if query.startswith("UPDATE"):
                project["report_decision"] = params[0].obj
                writes.append(params)
            return self

        def fetchone(self):
            return project

        def commit(self):
            pass

    @contextmanager
    def database():
        yield Connection()

    monkeypatch.setattr(main, "db", database)
    return project, writes


@pytest.mark.parametrize("status", ["accepted", "rejected"])
def test_decision_persists_against_report_version(report_db, status):
    project, writes = report_db
    payload = main.ReportDecision(status=status, comment="  Review comment  ", report_fingerprint=main.report_fingerprint(project))
    result = main.decide_report(project["id"], payload)["report_decision"]
    assert len(writes) == 1
    assert result["status"] == status
    assert result["comment"] == "Review comment"
    assert result["decided_at"]
    assert main.report_decision_payload(project) == result
    project["financial_audit"]["indicators"][0]["actual"] = "101"
    assert main.report_decision_payload(project)["outdated"] is True


@pytest.mark.parametrize("change", ["report", "scope", "running", "empty"])
def test_stale_or_unfinished_report_cannot_be_accepted(report_db, change):
    project, writes = report_db
    payload = main.ReportDecision(status="accepted", report_fingerprint=main.report_fingerprint(project))
    if change == "report":
        project["financial_audit"]["indicators"][0]["expected"] = "100"
    elif change == "scope":
        project["verification_scope"]["period_start"] = "2026-02-01"
    elif change == "running":
        project["status"] = "running"
    else:
        project["financial_audit"] = None
    with pytest.raises(HTTPException) as error:
        main.decide_report(project["id"], payload)
    assert error.value.status_code == 409
    assert not writes


def test_report_version_is_independent_of_decision_and_key_order(report_db):
    project, _ = report_db
    original = main.report_fingerprint(project)
    project["report_decision"] = {"status": "accepted"}
    project["financial_audit"] = {"indicators": [{"expected": "90", "actual": "100"}]}
    assert main.report_fingerprint(project) == original
