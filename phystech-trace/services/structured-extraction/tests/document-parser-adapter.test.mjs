import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { adaptDocumentParserResult, parserInputShapeErrors } from "../lib/parser/document-parser-adapter.mjs";
import { extractStructuredDocument, classifyDocument } from "../lib/extraction/structured-extraction.mjs";
import { buildGroundedContext, callPolzaForExtraction, POLZA_MODEL, PolzaAiError } from "../lib/extraction/polza-ai.mjs";

const fixture = (name) => readFile(new URL(`./fixtures/${name}`, import.meta.url), "utf8").then(JSON.parse);

test("native Document Parser XLSX JSON preserves cell addresses, merges, formulas and empty cells", async () => {
  const parsed = await fixture("document-parser-native-xlsx.analysis.json");
  const view = adaptDocumentParserResult(parsed);
  assert.deepEqual(parserInputShapeErrors(parsed), []);
  assert.equal(view.format, "XLSX");
  assert.ok(view.file_name.endsWith(".xlsx"));
  assert.ok(view.sheet_names.includes("Ведомость"));
  assert.equal(view.tables.length, 1);
  const table = view.tables[0];
  assert.deepEqual(table.headers, ["Код статьи", "Вид начисления", "Сумма, руб.", "Основание"]);
  assert.equal(table.rows.length, 3);
  assert.ok(table.merged_ranges.includes("A1:D1"));
  const row = table.rows.find((item) => item.cells.some((cell) => cell.address === "A6"));
  assert.equal(row.cells.find((cell) => cell.address === "A6").text, "0201");
  assert.equal(row.cells.find((cell) => cell.address === "C6").text, "1,018,750.00");
  const total = table.rows.find((item) => item.cells.some((cell) => cell.address === "C8"));
  const formula = total.cells.find((cell) => cell.address === "C8");
  assert.equal(formula.formula, "=SUM(C6:C7)");
  assert.equal(formula.calculation_status, "missing_cached_result");
  assert.equal(formula.provenance.sheet_name, "Ведомость");
  assert.equal(formula.provenance.cell_address, "C8");
  assert.equal(adaptDocumentParserResult(parsed).tables[0].rows[0].cells[0].id, table.rows[0].cells[0].id);

  // Exercise the parser's actual Docling model_parts shape, without changing the fixture.
  const modelPartsOnly = { ...parsed, parts: [], document: { ...parsed.document, tables: [] } };
  const doclingView = adaptDocumentParserResult(modelPartsOnly);
  assert.ok(doclingView.tables.length > 0);
  assert.ok(doclingView.tables[0].rows.length > 0);
  assert.ok(doclingView.tables[0].headers.some(Boolean));
});

test("authentic Document Parser DOCX JSON preserves paragraphs, table rows and JSON-path provenance", async () => {
  const parsed = await fixture("document-parser-native-docx.analysis.json");
  const view = adaptDocumentParserResult(parsed);
  assert.deepEqual(parserInputShapeErrors(parsed), []);
  assert.equal(view.format, "DOCX");
  assert.ok(view.elements.some((element) => element.text === "Дата: 10.04.2026"));
  const table = view.tables.find((item) => item.headers.includes("Сумма, руб."));
  assert.ok(table);
  assert.deepEqual(table.headers, ["Основание", "Сумма, руб."]);
  assert.equal(table.rows.length, 1);
  const amount = table.rows[0].cells[1];
  assert.equal(amount.text, "270 000,00");
  assert.match(amount.provenance.source_ref, /#\/parts\/6\/rows\/1\/1$/);
  assert.equal(amount.provenance.confidence, null);
  assert.equal(view.elements.find((element) => element.text === "Дата: 10.04.2026").provenance.confidence, null);
});

test("native PDF analysis plus separate visual layout JSON keeps exact provenance and coordinate transforms", async () => {
  const [analysis, layout] = await Promise.all([
    fixture("document-parser-native-pdf.analysis.json"),
    fixture("document-parser-native-pdf.layout.json"),
  ]);
  const input = { analysis_json: analysis, layout_json: layout };
  const view = adaptDocumentParserResult(input);
  assert.deepEqual(parserInputShapeErrors(input), []);
  assert.equal(view.format, "PDF");
  assert.ok(view.file_name.endsWith(".pdf"));
  assert.equal(view.page_count, 1);
  assert.equal(classifyDocument(input).type, "act");
  assert.ok(view.parser_sections.visual_layout_parts > 0);

  const nativeFragment = view.elements.find((item) => item.text === "Дата: 15.05.2026" && item.source_type === "ocr_text");
  assert.ok(nativeFragment);
  assert.equal(nativeFragment.provenance.page_no, 1);
  assert.equal(nativeFragment.provenance.bbox.coord_origin, "TOPLEFT");
  assert.ok(nativeFragment.provenance.bbox.r > nativeFragment.provenance.bbox.l);
  assert.equal(nativeFragment.provenance.source_text, "Дата: 15.05.2026");

  const doclingFragment = view.elements.find((item) => item.text === "Дата: 15.05.2026" && item.provenance.source_ref === "#/texts/0");
  assert.ok(doclingFragment);
  assert.equal(doclingFragment.provenance.coordinate_origin, "BOTTOMLEFT");
  assert.equal(doclingFragment.provenance.bbox_top_left.coord_origin, "TOPLEFT");
  assert.ok(Math.abs(doclingFragment.provenance.bbox_top_left.t - nativeFragment.provenance.bbox.t) < 0.001);
});

test("Docling multi-page tables and merged header spans retain row pages and all header source IDs", () => {
  const parsed = {
    source_extension: ".pdf",
    document: { name: "multi-page-table", pages: { "1": { size: { width: 600, height: 800 } }, "2": { size: { width: 600, height: 800 } }, }, tables: [{
      self_ref: "#/tables/0",
      prov: [{ page_no: 1, bbox: { l: 20, t: 700, r: 580, b: 500, coord_origin: "BOTTOMLEFT" } }, { page_no: 2, bbox: { l: 20, t: 700, r: 580, b: 500, coord_origin: "BOTTOMLEFT" } }],
      data: { num_rows: 4, num_cols: 3, table_cells: [
        { start_row_offset_idx: 0, start_col_offset_idx: 0, row_span: 1, col_span: 2, text: "Показатель", column_header: true, prov: [{ page_no: 1, bbox: { l: 20, t: 780, r: 350, b: 750, coord_origin: "BOTTOMLEFT" } }] },
        { start_row_offset_idx: 0, start_col_offset_idx: 2, text: "Сумма, руб.", column_header: true, prov: [{ page_no: 1, bbox: { l: 360, t: 780, r: 580, b: 750, coord_origin: "BOTTOMLEFT" } }] },
        { start_row_offset_idx: 1, start_col_offset_idx: 0, text: "План", column_header: true, prov: [{ page_no: 1, bbox: { l: 20, t: 745, r: 180, b: 720, coord_origin: "BOTTOMLEFT" } }] },
        { start_row_offset_idx: 1, start_col_offset_idx: 1, text: "Факт", column_header: true, prov: [{ page_no: 1, bbox: { l: 190, t: 745, r: 350, b: 720, coord_origin: "BOTTOMLEFT" } }] },
        { start_row_offset_idx: 2, start_col_offset_idx: 0, text: "Оплата работ", prov: [{ page_no: 1, bbox: { l: 20, t: 745, r: 350, b: 720, coord_origin: "BOTTOMLEFT" } }] },
        { start_row_offset_idx: 2, start_col_offset_idx: 2, text: "1 250,00", prov: [{ page_no: 1, bbox: { l: 360, t: 745, r: 580, b: 720, coord_origin: "BOTTOMLEFT" } }] },
        { start_row_offset_idx: 3, start_col_offset_idx: 0, text: "Дополнительная строка", prov: [{ page_no: 2, bbox: { l: 20, t: 745, r: 350, b: 720, coord_origin: "BOTTOMLEFT" } }] },
        { start_row_offset_idx: 3, start_col_offset_idx: 2, text: "300,00", prov: [{ page_no: 2, bbox: { l: 360, t: 745, r: 580, b: 720, coord_origin: "BOTTOMLEFT" } }] },
      ] },
    }] },
  };
  const table = adaptDocumentParserResult(parsed).tables[0];
  assert.deepEqual(table.headers, ["Показатель · План", "Показатель · Факт", "Сумма, руб."]);
  assert.equal(table.rows.length, 2);
  assert.equal(table.rows[0].page_no, 1);
  assert.equal(table.rows[1].page_no, 2);
  assert.equal(table.rows[1].cells[0].text, "Дополнительная строка");
  assert.ok(table.header_cells[0].source_element_ids.length > 1);
  assert.equal(table.header_cells[0].provenance.bbox_top_left.coord_origin, "TOPLEFT");
  assert.equal(table.page_no, null);
  assert.deepEqual(table.page_numbers, [1, 2]);
});

test("logical tables, fragments and values accept object-valued parser structures", () => {
  const parsed = {
    document_id: "fragments-values",
    source_extension: ".json",
    logical_tables: [{ id: "kv-table", caption: "Финансовые показатели", headers: ["Показатель", "Значение"], values: [[{ value: "Итого" }, { value: "12 400,50 руб." }]] }],
    fragments: [{ ref: "#/fragments/0", fragment: "Период: 01.04.2026 — 30.04.2026", provenance: [{ page_no: 1, bbox: { l: 10, t: 20, r: 300, b: 40, coord_origin: "TOPLEFT" } }] }],
    values: [{ id: "v-1", value: "12 400,50 руб.", provenance: [{ page_no: 1, bbox: { l: 10, t: 50, r: 200, b: 70, coord_origin: "TOPLEFT" } }] }],
  };
  const view = adaptDocumentParserResult(parsed);
  assert.equal(view.tables[0].rows[0].cells[1].text, "12 400,50 руб.");
  assert.ok(view.elements.some((element) => element.text.includes("Период: 01.04.2026")));
  assert.ok(view.elements.some((element) => element.text === "12 400,50 руб."));
  assert.ok(view.elements.find((element) => element.text.includes("Период:")).provenance.bbox);
});

test("logical table fragments preserve multi-page rows, repeated headers and multi-level headers", () => {
  const parsed = {
    document_id: "logical-multipage",
    source_extension: ".pdf",
    parts: [{ kind: "paragraph", text: "Отчёт КФЗ" }],
    logical_tables: [{
      id: "items",
      caption: "Расшифровка показателей",
      headers: [["", "Работа / показатель", "Финансовый показатель"], ["Код", "Наименование", "Сумма, руб."]],
      fragments: [
        { page_no: 1, rows: [{ values: ["01", "Калибровка", "12 000,00"], page_no: 1 }] },
        { page_no: 2, rows: [
          { values: ["Код", "Работа / показатель · Наименование", "Финансовый показатель · Сумма, руб."], page_no: 2 },
          { values: ["02", "Поверка", "8 500,00"], page_no: 2 },
        ] },
      ],
    }],
  };
  const view = adaptDocumentParserResult(parsed);
  assert.deepEqual(view.tables[0].headers, ["Код", "Работа / показатель · Наименование", "Финансовый показатель · Сумма, руб."]);
  assert.equal(view.tables[0].rows.length, 3);
  assert.deepEqual(view.tables[0].rows.map((row) => row.page_no), [1, 2, 2]);
  assert.match(view.tables[0].rows[0].cells[1].provenance.source_ref, /#\/logical_tables\/0\/fragments\/0\/rows\/0\/values\/1$/);
  const extraction = extractStructuredDocument(parsed, { extractionId: "logical-multipage-test", mode: "rules_only" });
  assert.equal(extraction.line_items.length, 2);
  assert.equal(extraction.tables[0].repeated_header_rows.length, 1);
  assert.equal(extraction.line_items[1].identifier.provenance.page_no, 2);
});

test("extraction calls Polza AI, validates JSON Schema and grounds returned IDs to native PDF source", async () => {
  const [analysis, layout] = await Promise.all([
    fixture("document-parser-native-pdf.analysis.json"),
    fixture("document-parser-native-pdf.layout.json"),
  ]);
  const input = { analysis_json: analysis, layout_json: layout };
  const context = buildGroundedContext(input);
  const dateFragment = context.source_elements.find((item) => item.text === "Дата: 15.05.2026");
  const actNumberFragment = context.source_elements.find((item) => item.text === "AKT N ADM-75");
  const contractorFragment = context.source_elements.find((item) => item.text === "Исполнитель: ООО «ДокКонтур Эпсилон»");
  assert.ok(dateFragment && actNumberFragment && contractorFragment);
  let calls = 0;
  let request;
  const mockPolza = {
    POLZA_API_KEY: "unit-test-key",
    async POLZA_FETCH(url, init) {
      calls++;
      request = { url, body: JSON.parse(init.body), authorization: init.headers.authorization };
      return new Response(JSON.stringify({ choices: [{ message: { content: JSON.stringify({
        document_type: "act",
        classification_confidence: 0.99,
        field_candidates: [
          { field_key: "act_number", source_element_id: actNumberFragment.source_element_id, source_value: "ADM-75", confidence: 0.98 },
          { field_key: "act_date", source_element_id: dateFragment.source_element_id, source_value: "15.05.2026", confidence: 0.96 },
          { field_key: "contractor_representative", source_element_id: contractorFragment.source_element_id, source_value: "ООО «ДокКонтур Эпсилон»", confidence: 0.4 },
        ],
        table_mappings: [],
      }) } }] }), { status: 200, headers: { "content-type": "application/json" } });
    },
  };
  const llm = await callPolzaForExtraction(input, mockPolza);
  assert.equal(calls, 1);
  assert.equal(request.url, "https://polza.ai/api/v1/chat/completions");
  assert.equal(request.authorization, "Bearer unit-test-key");
  assert.equal(request.body.model, POLZA_MODEL);
  assert.equal(request.body.response_format.type, "json_schema");
  assert.equal(request.body.response_format.json_schema.strict, true);
  assert.equal(request.body.response_format.json_schema.schema.additionalProperties, false);
  assert.equal(llm.called, true);
  assert.equal(llm.response_validated, true);

  const result = extractStructuredDocument(input, { extractionId: "native-pdf-test", llm });
  assert.equal(result.document_type, "act");
  assert.equal(result.extraction_engine.llm.called, true);
  assert.equal(result.fields.act_number.value, "ADM-75");
  assert.equal(result.fields.act_number.provenance.document_id, analysis.document.name);
  assert.equal(result.fields.act_date.value, "2026-05-15");
  assert.equal(result.fields.act_date.provenance.page_no, 1);
  assert.ok(result.fields.act_date.provenance.bbox);
  assert.equal(result.fields.contractor_representative.source_value, "ООО «ДокКонтур Эпсилон»");
  // Model self-confidence is not evidence; the exact source substring is grounded and the parser confidence is high.
  assert.equal(result.fields.contractor_representative.status, "extracted");
});

test("grounded table mappings can map an unfamiliar native XLSX header and preserve every source column", async () => {
  const parsed = await fixture("document-parser-native-xlsx.analysis.json");
  const view = adaptDocumentParserResult(parsed);
  const table = view.tables[0];
  const context = buildGroundedContext(parsed);
  const headers = context.tables.find((item) => item.table_id === table.id).headers;
  const mockResponse = {
    document_type: "registry",
    classification_confidence: 0.91,
    field_candidates: [],
    table_mappings: [{
      table_id: table.id,
      role: "line_items",
      confidence: 0.91,
      columns: headers.map((header, index) => ({
        source_element_id: header.source_element_id,
        semantic_key: ["identifier", "description", "amount", "unknown"][index],
        label: header.label,
        confidence: 0.91,
      })),
    }],
  };
  const llm = await callPolzaForExtraction(parsed, { POLZA_API_KEY: "unit-test-key", POLZA_FETCH: async () => new Response(JSON.stringify({ choices: [{ message: { content: JSON.stringify(mockResponse) } }] }), { status: 200 }) });
  const result = extractStructuredDocument(parsed, { extractionId: "native-xlsx-test", llm });
  assert.equal(result.document_type, "registry");
  assert.equal(result.line_items.length, 3);
  assert.equal(result.line_items[0].identifier.source_value, "0201");
  assert.equal(result.line_items[0].description.source_value, "Основная заработная плата");
  assert.equal(result.line_items[0].amount.value.amount, "1018750.00");
  assert.equal(result.line_items[0].source_cells.length, 4);
  assert.equal(result.line_items[0].identifier.provenance.cell_address, "A6");
  assert.equal(result.line_items[2].amount.status, "review");
  assert.equal(result.line_items[2].amount.provenance.cell_address, "C8");
});

test("provider absence fails closed and ungrounded candidates are filtered before extraction", async () => {
  const parsed = await fixture("document-parser-native-pdf.analysis.json");
  await assert.rejects(callPolzaForExtraction(parsed, {}), (error) => error instanceof PolzaAiError && error.status === 503 && error.code === "POLZA_NOT_CONFIGURED");
  const invalidBinding = { POLZA_API_KEY: "unit-test-key", POLZA_FETCH: async () => new Response(JSON.stringify({ choices: [{ message: { content: JSON.stringify({
    document_type: "act", classification_confidence: 0.99,
    field_candidates: [{ field_key: "act_number", source_element_id: "invented", source_value: "ADM-75", confidence: 1 }],
    table_mappings: [],
  }) } }] }), { status: 200 }) };
  const filtered = await callPolzaForExtraction(parsed, invalidBinding);
  assert.deepEqual(filtered.field_candidates, []);
  assert.equal(filtered.validation_status, "strict_schema_grounded_candidates_filtered");
});
