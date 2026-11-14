import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { validateEvidenceSide, pathContainsRowId, rowIdExists } from "../src/linking/evidence-validation";
import { buildEvidenceRegistry, resolveEvidenceReference } from "../src/linking/evidence-registry";
import type { Extraction } from "../src/contracts/input";

const dir = resolve("fixtures/upstream-structured-extraction-1.2.0");
function document(name: string): any { return JSON.parse(readFileSync(resolve(dir, name.endsWith(".json") ? name : `${name}.json`), "utf8")); }

test("evidence checks a real upstream value, direction, provenance owner and source availability", () => {
  const source = document("contract-2026-0315") as Extraction;
  const path = "fields.contract_number.value";
  const valid = validateEvidenceSide({ document: source, expectedDocumentId: source.document_id, reportedDocumentId: source.document_id, path, rawValue: "КД-24/03-15" });
  assert.equal(valid.valid, true);
  assert.equal((valid.evidence?.provenance as any).document_id, source.document_id);
  assert.equal(validateEvidenceSide({ document: source, expectedDocumentId: source.document_id, reportedDocumentId: "another-document", path, rawValue: "КД-24/03-15" }).reasons.includes("evidence_source_direction_mismatch"), true);

  const entry = (source as any).fields.contract_number;
  entry.provenance.document_id = "another-document";
  assert.equal(validateEvidenceSide({ document: source, expectedDocumentId: source.document_id, reportedDocumentId: source.document_id, path, rawValue: entry.value }).reasons.includes("provenance_document_mismatch"), true);
  entry.provenance.document_id = source.document_id;
  entry.provenance.source_available = false;
  assert.equal(validateEvidenceSide({ document: source, expectedDocumentId: source.document_id, reportedDocumentId: source.document_id, path, rawValue: entry.value }).reasons.includes("source_unavailable"), true);
  entry.provenance.source_available = true;
  entry.provenance.source_text = "  ";
  assert.equal(validateEvidenceSide({ document: source, expectedDocumentId: source.document_id, reportedDocumentId: source.document_id, path, rawValue: entry.value }).reasons.includes("source_text_missing"), true);
});

test("evidence rejects missing paths, mismatched raw values and prototype access", () => {
  const source = document("contract-2026-0315") as Extraction;
  for (const [path, rawValue, expected] of [
    ["fields.absent.value", "x", "json_path_not_found"],
    ["fields.contract_number.value", "not-the-number", "raw_value_mismatch"],
    ["fields.__proto__.constructor", "Object", "unsafe_or_invalid_json_path"],
  ] as const) {
    const result = validateEvidenceSide({ document: source, expectedDocumentId: source.document_id, reportedDocumentId: source.document_id, path, rawValue });
    assert.equal(result.valid, false);
    assert.ok(result.reasons.includes(expected), `${path} should fail with ${expected}`);
  }
});

test("source text normalization handles OCR formatting and reports uncertain OCR without invalidating paths", () => {
  const source = document("contract-2026-0315") as Extraction, entry = (source as any).fields.contract_number;
  const path = "fields.contract_number.value";
  entry.provenance.source_text = "КД — 24/03–15";
  const checked = validateEvidenceSide({ document: source, expectedDocumentId: source.document_id, reportedDocumentId: source.document_id, path, rawValue: entry.value });
  assert.equal(checked.valid, true);
  assert.deepEqual(checked.warnings, []);

  entry.provenance.source_text = "КД-24/03-1S";
  const uncertain = validateEvidenceSide({ document: source, expectedDocumentId: source.document_id, reportedDocumentId: source.document_id, path, rawValue: entry.value });
  assert.equal(uncertain.valid, true, "the path and provenance are real even when OCR text differs");
  assert.ok(uncertain.warnings.includes("source_text_value_mismatch"));
  entry.provenance.source_text = entry.source_value;
  const supported = validateEvidenceSide({ document: source, expectedDocumentId: source.document_id, reportedDocumentId: source.document_id, path, rawValue: entry.value });
  assert.equal(supported.valid, true);
  assert.deepEqual(supported.warnings, []);
});

test("numeric amount evidence uses its wrapper source_value to validate formatted source text", () => {
  const extraction = {
    document_id: "synthetic-kfz",
    document_type: "kfz_report",
    fields: {
      reported_total: {
        value: { amount: "1180300.00", currency: "RUB" },
        source_value: "1 180 300,00 руб.",
        provenance: {
          document_id: "synthetic-kfz",
          source_available: true,
          source_text: "Общая сумма по отчёту: 1 180 300,00 руб.",
        },
      },
    },
  } as any as Extraction;
  const reference = buildEvidenceRegistry([extraction]).find(item => item.json_path === "fields.reported_total.value.amount");

  assert.equal(reference?.raw_value, "1180300.00");
  assert.equal(reference?.source_value, "1 180 300,00 руб.");
  assert.deepEqual(resolveEvidenceReference(reference, extraction.document_id).warnings, []);
});

test("row evidence requires an existing row and a path that crosses that row", () => {
  const source = document("contract-2026-0315") as Extraction;
  const tableIndex = source.tables.findIndex(table => table.rows.length), row: any = source.tables[tableIndex]?.rows[0];
  assert.ok(row?.row_id);
  const path = `tables[${tableIndex}].rows[0].source_cells[1].extracted.value`;
  assert.equal(rowIdExists(source, row.row_id), true);
  assert.equal(pathContainsRowId(source, path, row.row_id), true);
  const valid = validateEvidenceSide({ document: source, expectedDocumentId: source.document_id, reportedDocumentId: source.document_id, path, rawValue: row.source_cells[1].extracted.value, rowId: row.row_id });
  assert.equal(valid.valid, true, valid.reasons.join(","));
  const mismatch = validateEvidenceSide({ document: source, expectedDocumentId: source.document_id, reportedDocumentId: source.document_id, path, rawValue: row.source_cells[1].extracted.value, rowId: "missing-row" });
  assert.ok(mismatch.reasons.includes("row_id_not_found"));
  assert.ok(mismatch.reasons.includes("row_id_not_cited_by_path"));
});
