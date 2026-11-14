"""Export a self-contained Reconciliation Engine request JSON Schema."""

import json
from pathlib import Path

from reconciliation_engine.models import ReconciliationRequest

ROOT = Path(__file__).resolve().parents[1]
schema = ReconciliationRequest.model_json_schema()
schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
schema["$id"] = "urn:phystech-trace:reconciliation-request:1.0.0"
schema["title"] = "Phystech Trace Reconciliation Request 1.0.0"
schema["$defs"]["StructuredExtractionResult1_2_0"] = json.loads((ROOT / "schemas/upstream/structured-extraction-1.2.0.schema.json").read_text(encoding="utf-8"))
schema["$defs"]["DocumentLinkingResult1_2_0"] = json.loads((ROOT / "schemas/upstream/document-linking-1.2.0.schema.json").read_text(encoding="utf-8"))
schema["properties"]["extraction_results"]["items"] = {"$ref": "#/$defs/StructuredExtractionResult1_2_0"}
schema["properties"]["linking_result"] = {"$ref": "#/$defs/DocumentLinkingResult1_2_0"}
(ROOT / "schemas/reconciliation-request-1.0.0.schema.json").write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("Wrote schemas/reconciliation-request-1.0.0.schema.json")
