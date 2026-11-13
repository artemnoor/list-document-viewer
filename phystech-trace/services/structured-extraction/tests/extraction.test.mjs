import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { demoBlueprints } from "../data/demo-blueprints.mjs";
import { classifyDocument, compareExtractionResults, extractStructuredDocument, normalizeDate, normalizeMoney, normalizeUnit, parserJsonShapeErrors } from "../lib/extraction/structured-extraction.mjs";
import { adaptDocumentParserResult } from "../lib/parser/document-parser-adapter.mjs";

async function parserResult(id) {
  return JSON.parse(await readFile(new URL(`../data/parser-results/${id}.json`, import.meta.url), "utf8"));
}

test("all six parser fixtures are classified from their parsed content", async () => {
  const expected = { "kfz-2026-q1": "kfz_report", "contract-2026-0315": "contract", "act-2026-0424": "act", "invoice-2026-0408": "invoice", "addendum-2026-04": "addendum", "registry-2026-04": "registry" };
  for (const [id, type] of Object.entries(expected)) {
    const parsed = await parserResult(id);
    assert.equal(classifyDocument(parsed).type, type, id);
    assert.equal(extractStructuredDocument(parsed, { extractionId: `test-${id}` }).document_type, type, id);
  }
  assert.equal(demoBlueprints.length, 6);
});

test("LLM-only classification preserves only valid model confidence and always requests review", () => {
  const parsed = { document_id: "llm-only-classification", title: "Финансовый документ без явного типа", parts: [{ kind: "paragraph", text: "Стороны подтверждают условия" }] };
  const valid = classifyDocument(parsed, { document_type: "contract", confidence: 0.83 });
  assert.equal(valid.confidence, 0.83);
  assert.equal(valid.method, "llm_only");
  assert.equal(valid.status, "review");
  for (const confidence of [undefined, null, "0.8", -0.01, 1.01, Number.NaN, Number.POSITIVE_INFINITY]) {
    const result = classifyDocument(parsed, { document_type: "contract", confidence });
    assert.equal(result.confidence, null, String(confidence));
    assert.equal(result.status, "review", String(confidence));
  }
});

test("LLM-only classification with missing or invalid confidence passes the extraction schema as review", async () => {
  const parsed = { document_id: "missing-llm-confidence", title: "Документ без распознанного типа", parts: [{ kind: "paragraph", text: "Стороны подтвердили взаимные обязательства" }] };
  for (const confidence of [undefined, null, "0.84", -0.1, 1.01, Number.NaN]) {
    const result = extractStructuredDocument(parsed, {
      mode: "llm_assisted",
      llm: { document_type: "contract", classification_confidence: confidence, field_candidates: [], table_mappings: [] },
    });
    assert.equal(result.classification.type, "contract");
    assert.equal(result.classification.confidence, null);
    assert.equal(result.classification.status, "review");
    assert.equal(result.document_type, "contract");
  }
});

test("date, currency and unit normalization keeps exact decimal strings", () => {
  assert.deepEqual(normalizeDate("31 марта 2026 г."), { value: "2026-03-31", status: "extracted", note: null });
  assert.deepEqual(normalizeDate("04/05/2026"), { value: null, status: "review", note: "Порядок дня и месяца неоднозначен" });
  assert.deepEqual(normalizeMoney("5 742 183,40 руб."), { value: { amount: "5742183.40", currency: "RUB" }, status: "extracted", note: null });
  assert.equal(normalizeMoney("1,234 руб.").status, "review");
  assert.equal(normalizeMoney("56 4?0,00 руб.").status, "review");
  assert.equal(normalizeUnit("чел.-ч").value, "person_hour");
  assert.equal(normalizeUnit("м³").value, "cubic_meter");
  assert.equal(normalizeDate("31.02.2026").status, "review");
  assert.equal(normalizeMoney("1234,56").status, "review");
  assert.equal(normalizeMoney("1234,56").value.currency, null);
  assert.equal(normalizeMoney("1234,56", "Сумма, руб.").value.currency, "RUB");
  assert.equal(normalizeUnit("неизвестная единица").status, "review");
});

test("grounded rules and LLM candidates reconcile to review when evidence conflicts", async () => {
  const parsed = await parserResult("kfz-2026-q1");
  parsed.parts.push({ kind: "paragraph", id: "alternate-report-number", text: "КФЗ-02/2026" });
  const source = (await import("../lib/parser/document-parser-adapter.mjs")).adaptDocumentParserResult(parsed);
  const alternate = source.elements.find((element) => element.text === "КФЗ-02/2026");
  const llm = {
    document_type: "kfz_report",
    field_candidates: [{ field_key: "report_number", source_element_id: alternate.id, source_value: "КФЗ-02/2026", confidence: 1 }],
    table_mappings: [],
  };
  const rules = extractStructuredDocument(parsed, { extractionId: "rules", mode: "rules_only" });
  const hybrid = extractStructuredDocument(parsed, { extractionId: "hybrid", mode: "llm_assisted", llm });
  assert.equal(hybrid.fields.report_number.status, "review");
  assert.equal(hybrid.fields.report_number.value, null);
  assert.equal(hybrid.fields.report_number.conflict.rules.source_value, "КФЗ-01/2026");
  assert.equal(hybrid.fields.report_number.conflict.llm.source_value, "КФЗ-02/2026");
  assert.ok(hybrid.fields.report_number.conflict.rules.provenance);
  assert.ok(hybrid.fields.report_number.conflict.llm.provenance);
  const comparison = compareExtractionResults(rules, hybrid);
  assert.ok(comparison.discrepancies.some((item) => item.path === "fields.report_number"));
});

test("LLM cannot turn a key-value metadata table into checked line items", async () => {
  const parsed = await parserResult("kfz-2026-q1");
  const source = (await import("../lib/parser/document-parser-adapter.mjs")).adaptDocumentParserResult(parsed);
  const table = source.tables.find((item) => item.id === "document-metadata");
  const mapping = {
    table_id: table.id,
    role: "line_items",
    columns: table.header_cells.map((cell, index) => ({ source_element_id: cell.id, semantic_key: index === 0 ? "identifier" : "amount", label: table.headers[index], confidence: 1 })),
  };
  const result = extractStructuredDocument(parsed, { mode: "llm_assisted", llm: { document_type: "kfz_report", field_candidates: [], table_mappings: [mapping] } });
  const metadata = result.tables.find((item) => item.id === table.id);
  assert.equal(metadata.role, "metadata");
  assert.equal(metadata.role_source, "rules_or_parser");
  assert.equal(result.line_items.length, 18);
});

test("every KFS source row and all quantitative indicators are retained with provenance", async () => {
  const parsed = await parserResult("kfz-2026-q1");
  const result = extractStructuredDocument(parsed, { extractionId: "test-kfz", extractedAt: "2026-11-12T00:00:00.000Z" });
  assert.equal(result.line_items.length, 18);
  assert.equal(result.tables.find((table) => table.id === "kfz-items").rows.length, 18);
  for (const row of result.line_items) {
    assert.ok(row.identifier.source_value, `Missing identifier for ${row.row_id}`);
    assert.ok(row.description.source_value, `Missing description for ${row.row_id}`);
    assert.ok(row.identifier.provenance?.document_id === parsed.document_id);
    assert.ok([2, 3].includes(row.identifier.provenance.page_no));
    assert.ok(row.identifier.provenance.bbox.r > row.identifier.provenance.bbox.l);
    assert.ok(row.source_cells.length === 9, `Not all source columns retained for ${row.row_id}`);
  }
  assert.equal(result.line_items[13].actual_quantity.value, null);
  assert.equal(result.line_items[13].actual_quantity.status, "missing");
  assert.equal(result.line_items[17].amount.value, null);
  assert.equal(result.line_items[17].amount.status, "review");
  assert.equal(result.fields.reported_total.source_value, "5 742 183,40 руб.");
  assert.equal(result.fields.reported_total.value.amount, "5742183.40");
  assert.equal(result.fields.customer_inn.value, "7728406195");
  assert.equal(result.fields.customer_signatory.value, null);
  assert.equal(result.fields.customer_signatory.status, "missing");
});

test("XLSX provenance uses stable sheet names and cell addresses", async () => {
  const parsed = await parserResult("registry-2026-04");
  const result = extractStructuredDocument(parsed, { extractionId: "test-registry" });
  const first = result.line_items[0];
  assert.equal(result.line_items.length, 14);
  assert.equal(first.identifier.provenance.sheet_name, "Реестр");
  assert.equal(first.identifier.provenance.cell_address, "B7");
  assert.equal(first.identifier.source_value, "Р-110");
  assert.equal(first.amount.value.amount, "286500.00");
  assert.equal(result.line_items[13].amount.status, "review");
});

test("empty fields remain null and ambiguous dates are flagged", async () => {
  const parsed = await parserResult("addendum-2026-04");
  const result = extractStructuredDocument(parsed, { extractionId: "test-addendum" });
  assert.equal(result.fields.signing_date.value, null);
  assert.equal(result.fields.signing_date.source_value, "04/05/2026");
  assert.equal(result.fields.signing_date.status, "review");
  assert.equal(result.fields.effective_date.value, null);
  assert.equal(result.fields.effective_date.status, "missing");
  assert.ok(result.review_required.some((item) => item.path === "fields.signing_date"));
  assert.ok(result.missing_fields.includes("effective_date"));
});

test("addendum rows expose parameter, old and new values, reason and each source locator", async () => {
  const parsed = await parserResult("addendum-2026-04");
  const result = extractStructuredDocument(parsed, { extractionId: "test-addendum-rows" });
  assert.equal(result.changes.length, 3);
  const first = result.changes[0];
  assert.equal(first.parameter.source_value, "п. 2.1");
  assert.equal(first.old_value.source_value, "4 860 000,00 руб.");
  assert.equal(first.new_value.source_value, "5 214 600,00 руб.");
  assert.equal(first.reason.source_value, "Дополнительный объём по приложению 1");
  for (const key of ["parameter", "old_value", "new_value", "reason"]) {
    assert.equal(first[key].status, "extracted", key);
    assert.match(first[key].provenance.source_ref, /#\/tables\/1\/cells\//, key);
    assert.equal(first[key].provenance.source_text, first[key].source_value);
  }
  assert.equal(first.source_cells.length, 4);
  assert.equal(first.row_status, "extracted");
  assert.ok(first.source_cells.every((cell) => cell.extracted.provenance?.source_ref));
});

test("partially populated addendum preserves all source cells and marks only absent values missing", async () => {
  const parsed = await parserResult("addendum-2026-04");
  const firstRow = parsed.logical_tables.find((table) => table.id === "addendum-changes").rows[0];
  firstRow.cells[1].text = "";
  firstRow.cells[1].provenance.source_text = "";
  const llm = { document_type: "addendum", classification_confidence: 0.96, field_candidates: [], table_mappings: [] };
  const rulesResult = extractStructuredDocument(parsed, { extractionId: "test-addendum-partial-rules", mode: "rules_only" });
  const assistedResult = extractStructuredDocument(parsed, { extractionId: "test-addendum-partial-assisted", mode: "llm_assisted", llm });
  const compareResult = extractStructuredDocument(parsed, { extractionId: "test-addendum-partial-compare", mode: "compare", llm });

  for (const result of [rulesResult, assistedResult, compareResult]) {
    const row = result.changes[0];
    assert.equal(row.old_value.value, null);
    assert.equal(row.old_value.source_value, null, "no value may be filled from model confidence or inference");
    assert.equal(row.old_value.status, "missing");
    assert.equal(row.parameter.source_value, "п. 2.1");
    assert.equal(row.new_value.source_value, "5 214 600,00 руб.");
    assert.equal(row.reason.source_value, "Дополнительный объём по приложению 1");
    assert.equal(row.source_cells.length, 4);
    assert.equal(row.source_cells[1].extracted.status, "missing");
    assert.ok(row.source_cells.every((cell) => cell.extracted.provenance?.source_ref));
    assert.equal(row.row_status, "review", `${result.mode} must not treat a partial amendment as fully extracted`);
    assert.ok(result.missing_fields.includes(`changes.${row.row_id}.old_value`));
    assert.ok(result.review_required.some((item) => item.path === `changes.${row.row_id}.old_value`));
  }
  const comparison = compareExtractionResults(rulesResult, compareResult);
  assert.equal(comparison.matches.filter((item) => item.path === "changes.addendum-changes-r001").length, 1);
  assert.deepEqual(comparison.counts, { matches: 11, discrepancies: 0, rules_only: 0, llm_only: 0 });

  const allUnmappedInput = await parserResult("addendum-2026-04");
  const allUnmappedTable = allUnmappedInput.logical_tables.find((table) => table.id === "addendum-changes");
  allUnmappedTable.headers = ["Колонка А", "Колонка Б", "Колонка В", "Колонка Г"];
  const allMissing = extractStructuredDocument(allUnmappedInput, { extractionId: "test-addendum-unmapped-row", mode: "rules_only" });
  assert.equal(allMissing.changes[0].row_status, "review", "unmapped values are incomplete while original row data exists");
  for (const key of ["parameter", "old_value", "new_value", "reason"]) {
    assert.equal(allMissing.changes[0][key].status, "missing");
    assert.ok(allMissing.missing_fields.includes(`changes.${allMissing.changes[0].row_id}.${key}`));
    assert.ok(allMissing.review_required.some((item) => item.path === `changes.${allMissing.changes[0].row_id}.${key}`));
  }
});

test("provenance gaps, unavailable sources and low OCR confidence force review", async () => {
  const parsed = {
    document_id: "provenance-audit", title: "Договор", source_extension: ".txt",
    parts: [
      { kind: "paragraph", id: "contract-type", text: "Договор поставки № Д-1", provenance: [{ source_ref: "#/parts/0", source_text: "Договор поставки № Д-1" }] },
      { kind: "paragraph", id: "unlocated", text: "Номер договора: Д-1", _synthetic: true },
      { kind: "paragraph", id: "unavailable", text: "Дата договора: 01.03.2026", source_available: false, provenance: [{ source_ref: "#/parts/1", source_text: "Дата договора: 01.03.2026" }] },
      { kind: "paragraph", id: "low-ocr", text: "Цена договора: 10 000 руб.", confidence: 0.4, provenance: [{ source_ref: "#/parts/2", source_text: "Цена договора: 10 000 руб.", confidence: 0.4 }] },
    ],
  };
  const result = extractStructuredDocument(parsed, { extractionId: "provenance-check" });
  assert.equal(result.fields.contract_number.status, "review");
  assert.equal(result.fields.contract_date.status, "review");
  assert.equal(result.fields.contract_date.provenance.source_available, false);
  assert.equal(result.fields.contract_amount.status, "review");
  assert.equal(result.fields.contract_amount.value, null);
});

test("compare reports addendum value changes, missing data and changed provenance", async () => {
  const parsed = await parserResult("addendum-2026-04");
  const rules = extractStructuredDocument(parsed, { extractionId: "compare-rules" });
  const candidate = structuredClone(rules);
  candidate.changes[0].new_value = { ...candidate.changes[0].new_value, source_value: "5 400 000,00 руб.", value: "5400000.00" };
  const changed = compareExtractionResults(rules, candidate);
  assert.ok(changed.discrepancies.some((item) => item.path === "changes.addendum-changes-r001" && item.differing_fields.includes("new_value")));
  const missing = structuredClone(rules);
  missing.changes[0].old_value = { ...missing.changes[0].old_value, value: null, status: "missing", source_value: null, provenance: null };
  const missingCompare = compareExtractionResults(rules, missing);
  assert.ok(missingCompare.discrepancies.some((item) => item.path === "changes.addendum-changes-r001" && item.missing_fields.includes("old_value")));
  const provenance = structuredClone(rules);
  provenance.changes[0].reason = { ...provenance.changes[0].reason, provenance: { ...provenance.changes[0].reason.provenance, source_ref: "#/parts/404" } };
  const provenanceCompare = compareExtractionResults(rules, provenance);
  assert.ok(provenanceCompare.discrepancies.some((item) => item.path === "changes.addendum-changes-r001" && item.differing_fields.includes("reason")));
});

test("Compare counts each addendum change once and reports its value, missing data and provenance differences", async () => {
  const parsed = await parserResult("addendum-2026-04");
  const rules = extractStructuredDocument(parsed, { extractionId: "compare-addendum-rules" });
  const same = compareExtractionResults(rules, structuredClone(rules));
  assert.deepEqual(same.counts, { matches: 11, discrepancies: 0, rules_only: 0, llm_only: 0 });
  assert.equal(same.matches.filter((item) => item.path === "changes.addendum-changes-r001").length, 1);
  assert.equal(same.matches.some((item) => item.path === "rows.addendum-changes-r001"), false);

  const changed = structuredClone(rules);
  changed.changes[0].new_value = { ...changed.changes[0].new_value, source_value: "5 400 000,00 руб.", value: "5400000.00" };
  const valueCompare = compareExtractionResults(rules, changed);
  assert.deepEqual(valueCompare.counts, { matches: 10, discrepancies: 1, rules_only: 0, llm_only: 0 });
  assert.deepEqual(valueCompare.discrepancies.map((item) => item.path), ["changes.addendum-changes-r001"]);

  const missing = structuredClone(rules);
  missing.changes[0].old_value = { ...missing.changes[0].old_value, value: null, source_value: null, status: "missing", provenance: null };
  const missingCompare = compareExtractionResults(rules, missing);
  assert.deepEqual(missingCompare.counts, { matches: 10, discrepancies: 1, rules_only: 0, llm_only: 0 });
  assert.deepEqual(missingCompare.discrepancies[0].missing_fields, ["old_value"]);

  const provenance = structuredClone(rules);
  provenance.changes[0].reason = { ...provenance.changes[0].reason, provenance: { ...provenance.changes[0].reason.provenance, source_ref: "#/parts/404" } };
  const provenanceCompare = compareExtractionResults(rules, provenance);
  assert.deepEqual(provenanceCompare.counts, { matches: 10, discrepancies: 1, rules_only: 0, llm_only: 0 });
  assert.deepEqual(provenanceCompare.discrepancies.map((item) => item.path), ["changes.addendum-changes-r001"]);
});

test("unavailable source elements are not deterministic extraction candidates", () => {
  const parsed = {
    document_id: "unavailable-candidate",
    parts: [{ kind: "paragraph", id: "unavailable-contract", text: "Номер договора: Д-123", source_available: false, provenance: [{ source_ref: "#/parts/0", source_text: "Номер договора: Д-123" }] }],
  };
  const source = adaptDocumentParserResult(parsed);
  assert.equal(source.elements[0].source_available, false);
  const result = extractStructuredDocument(parsed, {
    mode: "llm_assisted",
    llm: { document_type: "contract", classification_confidence: 0.8, field_candidates: [{ field_key: "contract_number", source_element_id: source.elements[0].id, source_value: "Д-123", confidence: 1 }], table_mappings: [] },
  });
  assert.notEqual(result.fields.contract_number.status, "extracted");
  assert.equal(result.fields.contract_number.value, null);
});

test("parser JSON importer shape checks distinguish parsed JSON from source files", async () => {
  const parsed = await parserResult("invoice-2026-0408");
  assert.deepEqual(parserJsonShapeErrors(parsed), []);
  assert.ok(parserJsonShapeErrors({ filename: "scan.pdf", bytes: "..." }).length > 0);
  assert.deepEqual(parserJsonShapeErrors({ document_id: "text-only", parts: [{ kind: "paragraph", text: "Текст документа без таблиц" }] }), []);
});
