import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { validateInput } from "../src/contracts/input";
const dir = resolve("fixtures/upstream-structured-extraction-1.2.0");
const demoDir = resolve("fixtures/demo-structured-extraction");
test("published JSON Schemas describe full input and output objects", () => {
  const input = JSON.parse(readFileSync(resolve("contracts/input.schema.json"), "utf8"));
  const output = JSON.parse(readFileSync(resolve("contracts/output.schema.json"), "utf8"));
  assert.ok(input.oneOf?.length >= 6);
  assert.ok(input.$defs && Object.keys(input.$defs).length > 0);
  for (const key of ["linking_run_id", "input_documents", "links", "review_required", "unlinked_documents", "warnings", "processing_metadata"]) assert.ok(output.properties[key], `Missing output property: ${key}`);
});
test("actual rules-mode Structured Extraction 1.2.0 outputs satisfy input contract", () => {
  const fixtures = readdirSync(dir).filter(name => name.endsWith(".json")).map(name => JSON.parse(readFileSync(resolve(dir, name), "utf8")));
  assert.equal(fixtures.length, 6);
  const result = validateInput(fixtures);
  assert.equal(result.success, true, result.success ? "" : JSON.stringify(result.diagnostics, null, 2));
});
test("API extraction envelope is accepted without changing payload keys", () => {
  const extraction = JSON.parse(readFileSync(resolve(dir, "act-2026-0424.json"), "utf8"));
  const result = validateInput([{ extraction }]);
  assert.equal(result.success, true);
});
test("incompatible input returns field-level diagnostics", () => {
  const result = validateInput([{ document_id: "x", document_type: "act", fields: {} }]);
  assert.equal(result.success, false);
  if (!result.success) assert.ok(result.diagnostics.some(item => item.path.includes("extraction_id")));
});
test("additive fields and newer schema version are backward compatible", () => {
  const extraction = JSON.parse(readFileSync(resolve(dir, "act-2026-0424.json"), "utf8"));
  extraction.schema_version = "1.3.0"; extraction.future_metadata = { preserved: true };
  const result = validateInput([extraction]);
  assert.equal(result.success, true);
  if (result.success) assert.equal((result.documents[0] as any).future_metadata.preserved, true);
});
test("unknown fields survive at nested provenance, extraction-engine and table-row levels", () => {
  const extraction = JSON.parse(readFileSync(resolve(dir, "act-2026-0424.json"), "utf8"));
  extraction.schema_version = "1.9.0";
  const field = Object.values(extraction.fields).find((item: any) => item?.provenance)?.valueOf() as any;
  field.provenance.future_trace = { provider: "upstream-next" };
  extraction.extraction_engine.llm.future_usage = { cached_tokens: 13 };
  const table = extraction.tables.find((item: any) => item.rows?.length);
  if (table?.rows?.[0]) table.rows[0].future_row_value = { preserved: true };
  extraction.classification.future_label = "future classification";
  const result = validateInput([extraction]);
  assert.equal(result.success, true, result.success ? "" : JSON.stringify(result.diagnostics));
  if (result.success) {
    const output: any = result.documents[0];
    assert.deepEqual(output.extraction_engine.llm.future_usage, { cached_tokens: 13 });
    assert.equal(output.classification.future_label, "future classification");
    const outputField: any = Object.values(output.fields).find((item: any) => item?.provenance);
    assert.deepEqual(outputField.provenance.future_trace, { provider: "upstream-next" });
    const outputTable = output.tables.find((item: any) => item.rows?.length);
    if (table?.rows?.[0]) assert.deepEqual(outputTable.rows[0].future_row_value, { preserved: true });
  }
});
test("unsupported upstream major versions are rejected with a schema_version diagnostic", () => {
  const extraction = JSON.parse(readFileSync(resolve(dir, "act-2026-0424.json"), "utf8"));
  extraction.schema_version = "2.0.0";
  const result = validateInput([extraction]);
  assert.equal(result.success, false);
  if (!result.success) assert.ok(result.diagnostics.some(item => item.path === "schema_version"));
});
test("independent demo examples use the same input contract", () => {
  const fixtures = readdirSync(demoDir).filter(name => name.endsWith(".json")).map(name => JSON.parse(readFileSync(resolve(demoDir, name), "utf8")));
  const result = validateInput(fixtures);
  assert.equal(result.success, true, result.success ? "" : JSON.stringify(result.diagnostics, null, 2));
});
