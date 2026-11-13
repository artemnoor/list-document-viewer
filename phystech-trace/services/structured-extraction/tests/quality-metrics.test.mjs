import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { adaptDocumentParserResult } from "../lib/parser/document-parser-adapter.mjs";
import { extractStructuredDocument } from "../lib/extraction/structured-extraction.mjs";

const corpus = [
  ["kfz-2026-q1", 18, { report_number: "КФЗ-01/2026", report_date: "2026-03-31", reported_total: { amount: "5742183.40", currency: "RUB" } }],
  ["contract-2026-0315", 3, { contract_number: "КД-24/03-15", contract_amount: { amount: "4860000.00", currency: "RUB" } }],
  ["act-2026-0424", 5, { act_number: "А-024/26", amount_due: { amount: "1180300.00", currency: "RUB" } }],
  ["invoice-2026-0408", 3, { invoice_date: "2026-04-08", vat_amount: { amount: "53049.68", currency: "RUB" } }],
  ["addendum-2026-04", 3, { previous_amount: { amount: "4860000.00", currency: "RUB" }, new_amount: { amount: "5214600.00", currency: "RUB" } }],
  ["registry-2026-04", 14, { registry_total: { amount: "3882146.40", currency: "RUB" }, reporting_period: { start: "2026-04-01", end: "2026-04-30" } }],
];

test("rules-only golden corpus reports row precision, recall, completeness and source-link correctness", async () => {
  let predictedRows = 0;
  let goldRows = 0;
  let truePositiveRows = 0;
  let sourceCells = 0;
  let correctlyLinkedCells = 0;
  let checkedFields = 0;
  let correctFields = 0;

  for (const [documentId, expectedRowCount, expectedFields] of corpus) {
    const parsed = JSON.parse(await readFile(new URL(`../data/parser-results/${documentId}.json`, import.meta.url), "utf8"));
    const source = adaptDocumentParserResult(parsed);
    const result = extractStructuredDocument(parsed, { extractionId: `quality-${documentId}`, mode: "rules_only" });
    const sourceTables = new Map(source.tables.map((table) => [table.id, table]));
    const expectedIds = new Set(source.tables.filter((table) => ["line_items", "payment_schedule", "amendments"].includes(table.role))
      .flatMap((table) => table.rows.filter((row) => row.cells.some((cell) => cell.text.trim())).map((row) => row.row_id)));
    const outputRows = result.line_items ?? result.payment_schedule ?? result.changes ?? [];
    assert.equal(outputRows.length, expectedRowCount, `${documentId}: every expected checked row must be present`);
    predictedRows += outputRows.length;
    goldRows += expectedIds.size;
    truePositiveRows += outputRows.filter((row) => expectedIds.has(row.row_id)).length;

    for (const [key, expected] of Object.entries(expectedFields)) {
      checkedFields++;
      assert.equal(JSON.stringify(result.fields[key]?.value), JSON.stringify(expected), `${documentId}.${key}`);
      assert.equal(result.fields[key]?.status, "extracted", `${documentId}.${key} status`);
      correctFields++;
    }

    for (const table of result.tables) {
      const sourceTable = sourceTables.get(table.id);
      for (const row of table.rows) {
        const sourceRow = sourceTable?.rows.find((candidate) => candidate.row_id === row.row_id);
        for (let index = 0; index < row.source_cells.length; index++) {
          const extracted = row.source_cells[index].extracted;
          const sourceCell = sourceRow?.cells.find((cell) => cell.column === index);
          sourceCells++;
          if (extracted.source_value === (sourceCell?.text.trim() ? sourceCell.text : null)
            && extracted.provenance?.document_id === parsed.document_id
            && extracted.provenance?.source_part_id === sourceCell?.id
            && extracted.provenance?.source_text === (sourceCell?.text ?? "")) correctlyLinkedCells++;
        }
      }
    }
  }

  const rowPrecision = truePositiveRows / predictedRows;
  const rowRecall = truePositiveRows / goldRows;
  const rowCompleteness = truePositiveRows / goldRows;
  const provenanceCorrectness = correctlyLinkedCells / sourceCells;
  const fieldAssertionAccuracy = correctFields / checkedFields;
  assert.equal(rowPrecision, 1);
  assert.equal(rowRecall, 1);
  assert.equal(rowCompleteness, 1);
  assert.equal(provenanceCorrectness, 1);
  assert.equal(fieldAssertionAccuracy, 1);
  console.log(`Rules Only · synthetic oracle corpus (LLM not measured): rows P=${(rowPrecision * 100).toFixed(1)}% R=${(rowRecall * 100).toFixed(1)}% completeness=${(rowCompleteness * 100).toFixed(1)}% (${truePositiveRows}/${goldRows}); provenance=${(provenanceCorrectness * 100).toFixed(1)}% (${correctlyLinkedCells}/${sourceCells}); field assertions=${correctFields}/${checkedFields}.`);
});
