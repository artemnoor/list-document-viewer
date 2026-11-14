import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.engine import run_verification
from app.models import VerificationRequest


def read_fixture(name: str):
    return json.loads((ROOT / "tests" / "fixtures" / "synthetic" / name).read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


primary = read_fixture("extraction-kfz.json")
support = read_fixture("extraction-support.json")
reconciliation = read_fixture("reconciliation-matched.json")

for label in ("matched", "mismatch"):
    current_support = copy.deepcopy(support)
    current_reconciliation = copy.deepcopy(reconciliation)
    if label == "mismatch":
        current_support["fields"]["source_amount"]["value"]["amount"] = "110.25"
        current_support["fields"]["source_amount"]["source_value"] = "110.25 RUB"
        current_support["fields"]["source_amount"]["provenance"]["source_text"] = "110.25 RUB"
        current_reconciliation["targets"][0]["result"]["expected_value"]["amount"] = "110.25"
        current_reconciliation["targets"][0]["result"]["operations"][0]["output_value"] = "110.25"
    request = {
        "project_id": "synthetic-project",
        "extraction": primary,
        "supporting_extractions": [current_support],
        "reconciliation_result": current_reconciliation,
        "linking_result": None,
        "context": {"period": None, "tolerance": {"absolute": None, "absolute_unit": None, "relative": None, "rounding_scale": None, "rounding_mode": "HALF_UP"}, "notes": []},
    }
    write_json(ROOT / "examples" / f"request-{label}.json", request)
    result = run_verification(VerificationRequest.model_validate(request), created_at="2026-11-13T10:00:00Z")
    write_json(ROOT / "examples" / f"response-{label}.json", result.model_dump(mode="json"))
