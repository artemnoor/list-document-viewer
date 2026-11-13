import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, rm, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { createQualityTransport, type QualityLedger } from "../scripts/quality-live-budget";
import { checkPublishedEvidence, graphStability, parseQualityArgs, runQualityE2E } from "../scripts/polza-quality-e2e";

const endpoint = "https://polza.ai/api/v1/chat/completions";
const request = (model = "google/gemma-4-26b-a4b-it", max_tokens = 4000) => ({ method: "POST", body: JSON.stringify({ model, max_tokens, messages: [{ role: "user", content: "source" }] }) });
const response = (content = "{}", usage: any = { prompt_tokens: 10, completion_tokens: 2 }) => new Response(JSON.stringify({ choices: [{ message: { content }, finish_reason: "stop" }], ...(usage ? { usage } : {}) }));

test("one budget counts Extraction and Linking sends together and rejects call 41 before send", async () => {
  const ledger: QualityLedger = { started_at: new Date().toISOString(), attempts: [] }; let sends = 0, stage = "extraction";
  const transport = createQualityTransport({ ledger, stage: () => stage, save: async () => {}, fetcher: async () => { sends++; assert.equal(ledger.attempts.at(-1)?.state, "sending"); return response(); } });
  for (let i = 0; i < 40; i++) { stage = i < 12 ? "extraction" : "linking"; await transport.fetcher(endpoint, request(i < 12 ? "deepseek/deepseek-v4-flash" : undefined)); }
  await assert.rejects(() => transport.fetcher(endpoint, request()), /QUALITY_Q1_RUN_BUDGET_EXCEEDED/);
  assert.equal(sends, 40); assert.equal(ledger.attempts.length, 40); assert.equal(transport.totals().actual_input_tokens, 400); assert.equal(transport.totals().cost_amount, null);
});

test("raw malformed JSON usage is retained before a later repaired response", async () => {
  const ledger: QualityLedger = { started_at: new Date().toISOString(), attempts: [] }; let sends = 0;
  const transport = createQualityTransport({ ledger, stage: () => "repair", save: async () => {}, fetcher: async () => response(++sends === 1 ? '{"links":[' : '{"links":[]}', { prompt_tokens: 7, completion_tokens: 3, cost: 0.2, cost_currency: "RUB" }) });
  await transport.fetcher(endpoint, request()); await transport.fetcher(endpoint, request());
  assert.equal(ledger.attempts[0].raw_output, '{"links":['); assert.equal(transport.totals().actual_input_tokens, 14); assert.equal(transport.totals().cost_amount, 0.4);
});

test("Q1 token, endpoint and uncertain-prior-send guards reject before any send", async () => {
  const ledger: QualityLedger = { started_at: new Date().toISOString(), attempts: [] }; let sends = 0;
  const transport = createQualityTransport({ ledger, stage: () => "linking", save: async () => {}, fetcher: async () => { sends++; return response(); } });
  await assert.rejects(() => transport.fetcher(endpoint, request(undefined, 4096)), /REQUEST_TOKEN_LIMIT/);
  await assert.rejects(() => transport.fetcher("https://example.com/", request()), /ENDPOINT_REJECTED/);
  ledger.attempts.push({ index: 1, stage: "linking", model: "google/gemma-4-26b-a4b-it", estimated_input_tokens: 10, reserved_output_tokens: 4000, started_at: ledger.started_at, state: "sending" });
  await assert.rejects(() => transport.fetcher(endpoint, request()), /UNCERTAIN_PRIOR_SEND/);
  assert.equal(sends, 0);
});

test("missing provider usage reserves output instead of reporting free or zero-cost calls", async () => {
  const ledger: QualityLedger = { started_at: new Date().toISOString(), attempts: [] }; let sends = 0;
  const transport = createQualityTransport({ ledger, stage: () => "linking", save: async () => {}, fetcher: async () => { sends++; return response("{}", null); } });
  for (let i = 0; i < 25; i++) await transport.fetcher(endpoint, request());
  await assert.rejects(() => transport.fetcher(endpoint, request()), /RUN_BUDGET_EXCEEDED/);
  assert.equal(sends, 25); assert.equal(transport.totals().actual_output_tokens, null); assert.equal(transport.totals().accounted_output_tokens, 100000); assert.equal(transport.totals().cost_amount, null);
});

test("authoritative provider usage above Q1 stays a failed recorded attempt", async () => {
  const ledger: QualityLedger = { started_at: new Date().toISOString(), attempts: [] };
  const transport = createQualityTransport({ ledger, stage: () => "linking", save: async () => {}, fetcher: async () => response("{}", { prompt_tokens: 16001, completion_tokens: 2 }) });
  await assert.rejects(() => transport.fetcher(endpoint, request()), /PROVIDER_USAGE_EXCEEDED_Q1/);
  assert.equal(ledger.attempts[0].state, "received"); assert.equal(ledger.attempts[0].usage.prompt_tokens, 16001);
  assert.equal(ledger.attempts[0].error, "QUALITY_PROVIDER_USAGE_EXCEEDED_Q1");
});

test("empty proposal graphs have N/A Jaccard and forged provenance fails evidence verification", () => {
  assert.equal(graphStability([{ links: [] }, { links: [] }]).document_graphs.mean_jaccard, null);
  const documents: any[] = [{ document_id: "a", fields: { number: { value: "A", provenance: { document_id: "a", source_text: "A", source_available: true } } } }, { document_id: "b", fields: { number: { value: "B", provenance: { document_id: "b", source_text: "B", source_available: true } } } }];
  const result = { links: [{ link_id: "x", status: "confirmed", source_document_id: "a", target_document_id: "b", evidence: [{ source: { document_id: "a", path: "fields.number.value", raw_value: "A", provenance: { document_id: "a", source_text: "invented" } }, target: { document_id: "b", path: "fields.number.value", raw_value: "B", provenance: documents[1].fields.number.provenance } }] }] };
  const verified = checkPublishedEvidence(result, documents); assert.equal(verified.passed, false); assert.equal(verified.technical_issues[0].code, "unresolved_or_forged_evidence");
});

test("full-five frozen Linking dry run cannot call a provider and pins source hashes", async (t) => {
  const directory = await mkdtemp(join(tmpdir(), "quality-live-harness-")); t.after(() => rm(directory, { recursive: true, force: true }));
  const original = globalThis.fetch; let sends = 0; globalThis.fetch = async () => { sends++; throw new Error("NO_NETWORK_ALLOWED"); };
  try {
    const config = parseQualityArgs(["--linking-only", "--out", directory, "--repeats", "1"]); assert.equal(config.live, false);
    const plan = await runQualityE2E(config); assert.equal(plan.live, false); assert.equal(sends, 0);
    const manifest = JSON.parse(await readFile(resolve(directory, "manifest.json"), "utf8"));
    assert.equal(manifest.parser_inputs.length, 5); assert.ok(manifest.parser_inputs.every((item: any) => /^[a-f0-9]{64}$/.test(item.sha256)));
    assert.ok(plan.combined_minimum_on_frozen_fixtures <= 40);
    await assert.rejects(() => runQualityE2E({ ...config, repeats: 2 }), /RESUME_INPUT_OR_CONFIG_MISMATCH/);
  } finally { globalThis.fetch = original; }
});
