"""Evaluate saved output against the answer workbook locally; never send it to models."""
import argparse
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path

import openpyxl


def amount(evidence):
    value = evidence.get("normalized_value") if isinstance(evidence, dict) else evidence
    if isinstance(value, dict):
        value = value.get("amount")
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def evaluate(project, workbook):
    local = project.get("financial_audit")
    indicators = (local or project.get("verification_result") or {}).get("indicators", [])
    checks = []
    for row in workbook["Эталон"].iter_rows(values_only=True):
        label, actual, expected, difference, status = row[:5]
        if not isinstance(actual, (int, float)) or not isinstance(expected, (int, float)):
            continue
        expected_status = "matched" if status == "ОК" else "mismatch"
        matches = [item for item in indicators if amount(item.get("actual")) == Decimal(str(actual))]
        passed = any(amount(item.get("expected")) == Decimal(str(expected)) and item.get("status") == expected_status and abs(Decimal(str(item.get("difference") if local else item.get("difference", {}).get("absolute") or "NaN"))) == abs(Decimal(str(difference))) and (item.get("sources") if local else item.get("evidence", {}).get("used_sources")) for item in matches)
        checks.append({"label": label, "expected_actual": str(actual), "expected_value": str(expected), "expected_status": expected_status, "passed": bool(passed), "found_statuses": [item.get("status") for item in matches]})
    categories = {d.get("category") for item in indicators for d in item.get("discrepancies", [])}
    categories.update(item.get("category") for item in project.get("document_findings", []))
    categories.update(item.get("category") for item in (local or {}).get("documents", []))
    additional = {key: key in categories for key in ("duplicate_operation", "wrong_period", "incorrect_document_link")}
    additional["unverified_indicators"] = any(item.get("status") in {"insufficient_data", "needs_review"} for item in indicators)
    return {"project_id": project.get("id"), "pipeline_status": project.get("status"), "passed": project.get("status") == "completed" and len(checks) == 5 and all(c["passed"] for c in checks) and all(additional.values()), "amount_checks": checks, "additional_checks": additional, "last_error": project.get("last_error")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(json.loads(args.result.read_text(encoding="utf-8")), openpyxl.load_workbook(args.gold, data_only=True))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
