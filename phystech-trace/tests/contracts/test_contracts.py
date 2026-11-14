import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"
LINKING = ROOT / "services" / "document-linking"
EXTRACTION = ROOT / "services" / "structured-extraction"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def walk(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)


class SharedContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parser_schema = read_json(CONTRACTS / "parser-to-extraction-v1.schema.json")
        cls.extraction_schema = read_json(CONTRACTS / "structured-extraction-1.2.0.schema.json")
        cls.linking_schema = read_json(CONTRACTS / "document-linking-1.2.0.schema.json")

    def test_all_shared_json_schemas_are_valid_draft_2020_12(self):
        for schema in (self.parser_schema, self.extraction_schema, self.linking_schema):
            Draft202012Validator.check_schema(schema)

    def test_release_contract_schemas_match_imported_linking_sources(self):
        self.assertEqual(
            read_json(CONTRACTS / "structured-extraction-1.2.0.schema.json"),
            read_json(LINKING / "contracts" / "input.schema.json"),
        )
        self.assertEqual(
            read_json(CONTRACTS / "document-linking-1.2.0.schema.json"),
            read_json(LINKING / "contracts" / "output.schema.json"),
        )

    def test_pinned_versions_match_source_registry(self):
        versions = read_json(CONTRACTS / "versions.json")
        self.assertEqual(versions["extraction_to_linking"]["version"], "1.2.0")
        self.assertEqual(versions["linking_output"]["version"], "1.2.0")
        self.assertEqual(len(versions["linking_output"]["source_commit"]), 40)
        registry = (LINKING / "src" / "contracts" / "registry.ts").read_text(encoding="utf-8")
        self.assertIn(versions["extraction_to_linking"]["source_commit"], registry)

    def test_upstream_structured_extraction_120_fixtures_match_linking_input(self):
        fixture_dir = LINKING / "fixtures" / "upstream-structured-extraction-1.2.0"
        fixtures = sorted(fixture_dir.glob("*.json"))
        self.assertEqual(len(fixtures), 6)
        validator = Draft202012Validator(self.extraction_schema)
        for fixture in fixtures:
            with self.subTest(fixture=fixture.name):
                validator.validate(read_json(fixture))

    def test_parser_native_examples_keep_trace_metadata_and_real_fields(self):
        fixture_dir = EXTRACTION / "tests" / "fixtures"
        parser_fixtures = sorted(fixture_dir.glob("document-parser-native-*.analysis.json"))
        self.assertGreaterEqual(len(parser_fixtures), 3)
        validator = Draft202012Validator(self.parser_schema)
        for index, fixture in enumerate(parser_fixtures):
            parser_result = read_json(fixture)
            expected_document_id = f"e2e-fixture-{index}"
            expected_source_file_id = f"{index + 1:032x}"
            parser_result["document_id"] = expected_document_id
            parser_result["source_file_id"] = expected_source_file_id
            parser_result["phystech_trace"] = {
                "contract_version": "1.0.0",
                "project_id": "contract-test",
                "source_file_id": expected_source_file_id,
                "source_file_name": fixture.name,
                "document_role": "primary",
            }
            with self.subTest(fixture=fixture.name):
                validator.validate(parser_result)
                self.assertTrue(parser_result["parts"])
                self.assertEqual(parser_result["document_id"], expected_document_id)
                self.assertEqual(parser_result["phystech_trace"]["source_file_id"], expected_source_file_id)

    def test_xlsx_parser_fixture_retains_sheet_addresses_and_formula(self):
        result = read_json(EXTRACTION / "tests" / "fixtures" / "document-parser-native-xlsx.analysis.json")
        cells = [item for item in walk(result.get("parts", [])) if item.get("kind") == "cell"]
        self.assertTrue(any(item.get("coordinate") or item.get("address") for item in cells))
        self.assertTrue(any(item.get("formula") for item in cells))

    def test_linking_output_example_satisfies_120_schema(self):
        result = {
            "linking_run_id": "contract-test-run",
            "contract_version": "1.2.0",
            "created_at": "2026-01-01T00:00:00Z",
            "input_documents": [],
            "links": [],
            "review_required": [],
            "unlinked_documents": [],
            "warnings": [],
            "link_validation_diagnostics": [],
            "analysis_summary": "No relationships in this contract-only empty set.",
            "processing_metadata": {
                "engine_version": "contract-test",
                "llm": {
                    "enabled": False,
                    "provider": "disabled",
                    "model": "none",
                    "strategy": "full_set",
                    "estimated_input_tokens": 0,
                    "calls": 0,
                    "errors": 0,
                },
                "duration_ms": 0,
            },
        }
        Draft202012Validator(self.linking_schema).validate(result)


if __name__ == "__main__":
    unittest.main()
