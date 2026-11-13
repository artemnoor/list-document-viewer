import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { buildGroundedContext, callPolzaForExtraction, listPolzaModels, PolzaAiError } from "../lib/extraction/polza-ai.mjs";
import { adaptDocumentParserResult } from "../lib/parser/document-parser-adapter.mjs";
import { extractStructuredDocument } from "../lib/extraction/structured-extraction.mjs";

const fixture = (name) => readFile(new URL(`./fixtures/${name}`, import.meta.url), "utf8").then(JSON.parse);
const okResponse = (value) => new Response(JSON.stringify({ choices: [{ message: { content: JSON.stringify(value) } }] }), { status: 200, headers: { "content-type": "application/json" } });
const valid = { document_type: "act", classification_confidence: 0.9, field_candidates: [], table_mappings: [] };

test("Polza JSON object fallback remains locally schema-checked and grounded", async () => {
  const parsed = await fixture("document-parser-native-pdf.analysis.json");
  const requestFormats = [];
  let calls = 0;
  const llm = await callPolzaForExtraction(parsed, {
    POLZA_API_KEY: "unit-test-key",
    POLZA_FETCH: async (_url, init) => {
      calls++;
      const body = JSON.parse(init.body);
      requestFormats.push(body.response_format.type);
      if (calls === 1) return new Response(JSON.stringify({ error: { message: "response_format json_schema is not supported" } }), { status: 400 });
      return okResponse(valid);
    },
  });
  assert.deepEqual(requestFormats, ["json_schema", "json_object"]);
  assert.equal(llm.validation_status, "json_mode_locally_validated_and_grounded");
});

test("Polza JSON parsing accepts fenced output while preserving local schema validation", async () => {
  const parsed = await fixture("document-parser-native-pdf.analysis.json");
  const llm = await callPolzaForExtraction(parsed, {
    POLZA_API_KEY: "unit-test-key",
    POLZA_FETCH: async () => new Response(JSON.stringify({ choices: [{ finish_reason: "stop", message: { content: `Here is the result:\n\n\`\`\`json\n${JSON.stringify(valid)}\n\`\`\`` } }] }), { status: 200 }),
  });
  assert.equal(llm.validation_status, "strict_schema_and_grounded");
  assert.deepEqual(llm.field_candidates, []);
});

test("Polza missing or invalid classification confidence is normalized to null for review", async () => {
  const parsed = await fixture("document-parser-native-pdf.analysis.json");
  for (const response of [
    { document_type: "act", field_candidates: [], table_mappings: [] },
    { document_type: "act", classification_confidence: 1.2, field_candidates: [], table_mappings: [] },
    { document_type: "act", classification_confidence: "0.8", field_candidates: [], table_mappings: [] },
  ]) {
    const llm = await callPolzaForExtraction(parsed, { POLZA_API_KEY: "unit-test-key", POLZA_FETCH: async () => okResponse(response) });
    assert.equal(llm.classification_confidence, null);
  }
});

test("Polza maps authentication, balance, model, rate-limit and server errors", async () => {
  const parsed = await fixture("document-parser-native-pdf.analysis.json");
  const expected = [[401, 401, "POLZA_UNAUTHORIZED"], [402, 402, "POLZA_PAYMENT_REQUIRED"], [404, 404, "POLZA_MODEL_NOT_FOUND"], [429, 429, "POLZA_RATE_LIMITED"], [500, 502, "POLZA_UPSTREAM_ERROR"]];
  for (const [upstream, status, code] of expected) {
    await assert.rejects(callPolzaForExtraction(parsed, {
      POLZA_API_KEY: "unit-test-key",
      POLZA_FETCH: async () => new Response(JSON.stringify({ error: { message: "provider test response" } }), { status: upstream }),
    }), (error) => error instanceof PolzaAiError && error.status === status && error.code === code);
  }
});

test("Polza retries transient network errors only within the configured bound", async () => {
  const parsed = await fixture("document-parser-native-pdf.analysis.json");
  let calls = 0;
  await assert.rejects(callPolzaForExtraction(parsed, {
    POLZA_API_KEY: "unit-test-key",
    POLZA_FETCH: async () => { calls++; throw new TypeError("network unavailable"); },
  }), (error) => error instanceof PolzaAiError && error.code === "POLZA_NETWORK_ERROR");
  assert.equal(calls, 2);
});

test("Polza models endpoint requests the model catalog without exposing the API key", async () => {
  let request;
  const models = await listPolzaModels({
    POLZA_API_KEY: "unit-test-key",
    POLZA_FETCH: async (url, init) => {
      request = { url, method: init.method, authorization: init.headers.authorization };
      return new Response(JSON.stringify({ data: [{ id: "deepseek/deepseek-v4-flash" }] }), { status: 200 });
    },
  });
  assert.deepEqual(request, { url: "https://polza.ai/api/v1/models", method: "GET", authorization: "Bearer unit-test-key" });
  assert.equal(models[0].id, "deepseek/deepseek-v4-flash");
});

test("unavailable source text stays out of Polza context and cannot ground an extracted value", async () => {
  const privateText = "Номер договора: Д-UNAVAILABLE";
  const parsed = {
    document_id: "unavailable-polza-source",
    title: "Документ без доступного первоисточника",
    parts: [
      { kind: "paragraph", id: "private-source-id", text: privateText, source_available: false, provenance: [{ source_ref: "#/parts/0", source_text: privateText }] },
      { kind: "paragraph", id: "synthetic-source-id", text: "Синтетический пример: договор С-1", _synthetic: true, provenance: [{ source_ref: "#/parts/1", source_text: "Синтетический пример: договор С-1" }] },
    ],
    logical_tables: [{
      id: "private-metadata",
      caption: "Реквизиты",
      role: "metadata",
      headers: ["Реквизит", "Значение"],
      rows: [{ row_id: "private-metadata-r001", cells: [
        { id: "private-label", column: 0, text: "Номер договора", source_available: true },
        { id: "private-value", column: 1, text: "Д-UNAVAILABLE", source_available: false, provenance: [{ source_ref: "#/logical_tables/0/rows/0/cells/1", source_text: "Д-UNAVAILABLE" }] },
      ] }],
    }],
  };
  const source = adaptDocumentParserResult(parsed);
  const element = source.elements.find((item) => item.text === privateText);
  assert.ok(element);
  assert.equal(element.source_available, false);
  const unavailableCell = source.tables[0].rows[0].cells[1];
  assert.equal(unavailableCell.source_available, false);
  assert.equal(unavailableCell.provenance.source_available, false);
  assert.equal(source.elements.find((item) => item.text === "Синтетический пример: договор С-1")?.source_available, false);

  const context = buildGroundedContext(parsed);
  const serializedContext = JSON.stringify(context);
  assert.equal(serializedContext.includes(privateText), false);
  assert.equal(serializedContext.includes(element.id), false);
  assert.equal(serializedContext.includes("private-source-id"), false);
  assert.equal(serializedContext.includes("private-value"), false);

  let outboundContent = "";
  const filtered = await callPolzaForExtraction(parsed, {
    POLZA_API_KEY: "unit-test-key",
    POLZA_FETCH: async (_url, init) => {
      outboundContent = JSON.parse(init.body).messages[1].content;
      return okResponse({
        document_type: "contract",
        classification_confidence: 0.99,
        field_candidates: [{ field_key: "contract_number", source_element_id: element.id, source_value: "Д-UNAVAILABLE", confidence: 1 }],
        table_mappings: [],
      });
    },
  });
  assert.deepEqual(filtered.field_candidates, []);
  assert.match(filtered.validation_status, /candidates_filtered$/);
  assert.equal(outboundContent.includes(privateText), false);
  assert.equal(outboundContent.includes(element.id), false);

  const direct = extractStructuredDocument(parsed, {
    mode: "llm_assisted",
    llm: { document_type: "contract", classification_confidence: 0.99, field_candidates: [{ field_key: "contract_number", source_element_id: element.id, source_value: "Д-UNAVAILABLE", confidence: 1 }], table_mappings: [] },
  });
  assert.notEqual(direct.fields.contract_number.status, "extracted");
  assert.equal(direct.fields.contract_number.value, null);
});

test("Polza table context preserves source column indexes when an earlier header is unavailable", async () => {
  const parsed = {
    document_id: "header-index-offset",
    title: "Реестр выполненных работ",
    source_extension: ".json",
    logical_tables: [{
      id: "offset-items",
      caption: "Строки реестра",
      role: "table",
      headers: ["Скрытый заголовок", "Кол-во, шт.", "Наименование работы"],
      header_cells: [
        { id: "hidden-header", text: "Скрытый заголовок", source_available: false },
        { id: "quantity-header", text: "Кол-во, шт.", source_available: true },
        { id: "description-header", text: "Наименование работы", source_available: true },
      ],
      rows: [{ row_id: "offset-items-r001", cells: [
        { id: "hidden-value", column: 0, text: "не использовать", source_available: false },
        { id: "quantity-value", column: 1, text: "3", source_available: true },
        { id: "description-value", column: 2, text: "Монтаж насосного оборудования", source_available: true },
      ] }],
    }],
  };
  const context = buildGroundedContext(parsed);
  const contextTable = context.tables.find((table) => table.table_id === "offset-items");
  assert.deepEqual(contextTable.headers.map(({ column_index, label }) => [column_index, label]), [
    [1, "Кол-во, шт."],
    [2, "Наименование работы"],
  ]);
  assert.equal(JSON.stringify(context).includes("hidden-header"), false);
  assert.equal(JSON.stringify(context).includes("не использовать"), false);

  const mappedColumns = contextTable.headers.map((header) => ({
    source_element_id: header.source_element_id,
    semantic_key: header.column_index === 1 ? "quantity" : "description",
    label: header.label,
    confidence: 0.97,
  }));
  const llm = await callPolzaForExtraction(parsed, {
    POLZA_API_KEY: "unit-test-key",
    POLZA_FETCH: async () => okResponse({
      document_type: "registry",
      classification_confidence: 0.97,
      field_candidates: [],
      table_mappings: [{ table_id: "offset-items", role: "line_items", confidence: 0.97, columns: mappedColumns }],
    }),
  });
  const result = extractStructuredDocument(parsed, { mode: "llm_assisted", llm });
  assert.equal(result.line_items[0].quantity.source_value, "3");
  assert.equal(result.line_items[0].description.source_value, "Монтаж насосного оборудования");
  assert.match(result.line_items[0].quantity.provenance.source_ref, /rows\/0\/cells\/1$/);
  assert.match(result.line_items[0].description.provenance.source_ref, /rows\/0\/cells\/2$/);
});
