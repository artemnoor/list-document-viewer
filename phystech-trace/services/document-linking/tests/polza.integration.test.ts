import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { linkDocuments } from "../src/linking/link-resolver";
import { GEMMA_MODEL } from "../src/linking/llm-matcher";
import { linkingOutputSchema } from "../src/contracts/output";

const apiKey = process.env.POLZA_API_KEY;
const systemPrompt = readFileSync("public/prompts/document-linking-system.md", "utf8");
test("live Polza smoke test calls Gemma 4 26B A4B and validates its output", { skip: !apiKey && "Set POLZA_API_KEY or POLZA_AI_API_KEY in the Windows environment" }, async () => {
  const root = "fixtures/demo-structured-extraction";
  const docs = ["contract-ambiguous-a.json", "act-ambiguous-1.json"].map(name => JSON.parse(readFileSync(`${root}/${name}`, "utf8")));
  const result = await linkDocuments(docs, { llm: { enabled: true, apiKey, model: GEMMA_MODEL, timeoutMs: 120000, maxCalls: 2, maxInputTokens: 180000, systemPrompt } });
  assert.equal(result.processing_metadata.llm.provider, "Polza AI");
  assert.equal(result.processing_metadata.llm.model, GEMMA_MODEL);
  assert.ok(result.processing_metadata.llm.calls >= 1 && result.processing_metadata.llm.calls <= 2);
  assert.equal(result.processing_metadata.llm.errors, 0);
  assert.equal(linkingOutputSchema.safeParse(result).success, true);
  console.log(JSON.stringify({ case: "ambiguous-demo-pair", provider: "Polza AI", model: result.processing_metadata.llm.model, document_count: result.input_documents.length, link_count: result.links.length, review_count: result.review_required.length, diagnostics_count: result.link_validation_diagnostics.length, request_count: result.processing_metadata.llm.calls, input_tokens: result.processing_metadata.llm.input_tokens, output_tokens: result.processing_metadata.llm.output_tokens, cost_amount: result.processing_metadata.llm.cost_amount, cost_currency: result.processing_metadata.llm.cost_currency, output_contract_valid: true, duration_ms: result.processing_metadata.llm.duration_ms }));
});

test("live Polza rechecks an upstream contract and addendum with Gemma", { skip: !apiKey && "Set POLZA_API_KEY or POLZA_AI_API_KEY in the Windows environment" }, async () => {
  const root = "fixtures/upstream-structured-extraction-1.2.0";
  const docs = ["contract-2026-0315.json", "addendum-2026-04.json"].map(name => JSON.parse(readFileSync(`${root}/${name}`, "utf8")));
  const result = await linkDocuments(docs, { llm: { enabled: true, apiKey, model: GEMMA_MODEL, timeoutMs: 120000, maxCalls: 2, maxInputTokens: 180000, systemPrompt } });
  assert.equal(result.processing_metadata.llm.provider, "Polza AI");
  assert.equal(result.processing_metadata.llm.model, GEMMA_MODEL);
  assert.ok(result.processing_metadata.llm.calls >= 1 && result.processing_metadata.llm.calls <= 2);
  assert.equal(result.processing_metadata.llm.errors, 0);
  assert.equal(linkingOutputSchema.safeParse(result).success, true);
  console.log(JSON.stringify({ case: "structured-extraction-contract-and-addendum", provider: "Polza AI", model: result.processing_metadata.llm.model, document_count: result.input_documents.length, link_count: result.links.length, review_count: result.review_required.length, diagnostics_count: result.link_validation_diagnostics.length, diagnostic_codes: result.link_validation_diagnostics.map(item => item.reason_codes), evidence_issue_codes: result.link_validation_diagnostics.flatMap(item => item.evidence_issues.map(issue => issue.reason_codes)), request_count: result.processing_metadata.llm.calls, input_tokens: result.processing_metadata.llm.input_tokens, output_tokens: result.processing_metadata.llm.output_tokens, cost_amount: result.processing_metadata.llm.cost_amount, cost_currency: result.processing_metadata.llm.cost_currency, output_contract_valid: true, duration_ms: result.processing_metadata.llm.duration_ms }));
});

test("live Polza full-set integration covers every upstream fixture", { skip: !apiKey || process.env.POLZA_RUN_FULL_SET !== "true" ? "Set POLZA_RUN_FULL_SET=true to run the longer multi-stage suite" : false }, async () => {
  const root = "fixtures/upstream-structured-extraction-1.2.0";
  const docs = readdirSync(root).filter(name => name.endsWith(".json")).map(name => JSON.parse(readFileSync(`${root}/${name}`, "utf8")));
  const result = await linkDocuments(docs, { llm: { enabled: true, apiKey, model: GEMMA_MODEL, timeoutMs: 120000, maxCalls: 52, maxInputTokens: 180000, systemPrompt } });
  assert.equal(result.processing_metadata.llm.provider, "Polza AI");
  assert.equal(result.processing_metadata.llm.model, GEMMA_MODEL);
  assert.ok(result.processing_metadata.llm.calls > 1);
  assert.equal(result.processing_metadata.llm.errors, 0);
  assert.equal(linkingOutputSchema.safeParse(result).success, true);
  assert.equal(result.input_documents.length, docs.length);
  console.log(JSON.stringify({ provider: "Polza AI", model: result.processing_metadata.llm.model, request_count: result.processing_metadata.llm.calls, input_tokens: result.processing_metadata.llm.input_tokens, output_tokens: result.processing_metadata.llm.output_tokens, cost_amount: result.processing_metadata.llm.cost_amount, cost_currency: result.processing_metadata.llm.cost_currency, output_contract_valid: true, duration_ms: result.processing_metadata.llm.duration_ms }));
});
import "dotenv/config";
