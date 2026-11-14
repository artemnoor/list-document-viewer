import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.models import VerificationResult


schema = VerificationResult.model_json_schema()
schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
schema["$id"] = "https://phystech-trace.local/contracts/verification-result-1.0.0.schema.json"
schema["title"] = "Phystech Trace Verification Result 1.0.0"
destination = ROOT / "contracts" / "verification-result-1.0.0.schema.json"
destination.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(destination)
