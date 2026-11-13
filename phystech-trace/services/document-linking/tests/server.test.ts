import { test } from "node:test";
import assert from "node:assert/strict";
import { createApp } from "../server/app";
import { GEMMA_MODEL } from "../src/linking/llm-matcher";

function setup(options: { token?: string; job?: any; config?: Record<string, unknown>; storageError?: Error } = {}) {
  const storage: any = {
    health: async () => true, rateLimit: async () => true,
    readJob: async () => { if (options.storageError) throw options.storageError; return options.job; },
  };
  const queue: any = { health: async () => undefined, enqueue: async () => undefined, close: async () => undefined };
  return createApp({ storage, queue, config: { apiToken: options.token, llmEnabled: true, maxCalls: 52, timeoutMs: 1000, maxInputTokens: 180000, maxRunMs: 900000, ...options.config } as any });
}

test("health endpoint reports local PostgreSQL and Redis backed service", async () => {
  const response = await setup().request("/api/health");
  assert.equal(response.status, 200);
  const body: any = await response.json();
  assert.equal(body.database, "ok"); assert.equal(body.queue, "ok"); assert.equal(body.llm.model, GEMMA_MODEL);
});

test("protected APIs reject requests with missing or wrong bearer tokens", async () => {
  const app = setup({ token: "server-secret" });
  for (const authorization of [undefined, "Bearer wrong"]) {
    const response = await app.request("/api/linking-runs/id", { headers: authorization ? { Authorization: authorization } : {} });
    assert.equal(response.status, 401);
  }
  assert.equal((await app.request("/api/demo")).status, 401);
});

test("job status exposes checkpoints, usage and the pinned provider/model", async () => {
  const job = { id: "job-1", status: "running", progress_json: { version: 2, completed_fragments: [{}, {}], total_fragments: 5, calls: 3, input_tokens: 1200, output_tokens: 90, context_rounds: 1, has_cost: true, cost_amount: 0.04, cost_currency: "RUB", phase: "reading_documents" }, attempts: 2, last_error: null, run_id: null, result_json: null, created_at: "2026-11-13T10:00:00.000Z", updated_at: "2026-11-13T10:01:00.000Z" };
  const app = setup({ token: "server-secret", job });
  const response = await app.request("/api/linking-jobs/job-1", { headers: { Authorization: "Bearer server-secret" } });
  assert.equal(response.status, 200);
  const body: any = await response.json();
  assert.equal(body.phase, "reading_documents"); assert.equal(body.progress.completed_fragments, 2); assert.equal(body.progress.total_fragments, 5);
  assert.equal(body.progress.input_tokens, 1200); assert.equal(body.progress.output_tokens, 90); assert.equal(body.progress.cost_amount, 0.04);
  assert.equal(body.model, GEMMA_MODEL); assert.equal(body.provider, "Polza AI");
});

test("job creation refuses to enqueue without Polza credentials while health remains available", async () => {
  const app = setup({ token: "server-secret" });
  const response = await app.request("/api/linking-jobs", { method: "POST", headers: { Authorization: "Bearer server-secret", "Content-Type": "application/json" }, body: JSON.stringify({ documents: [{}] }) });
  assert.equal(response.status, 503);
  assert.match((await response.json() as any).error, /POLZA_API_KEY/);
  assert.equal((await app.request("/api/health")).status, 200);
});

test("request, document, set and document-count limits return 413", async () => {
  const token = "server-secret", headers = { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
  const requestLimited = setup({ token, config: { maxRequestBytes: 20 } });
  const tooLargeRequest = await requestLimited.request("/api/linking-jobs", { method: "POST", headers, body: JSON.stringify({ documents: [{ text: "long enough to exceed request cap" }] }) });
  assert.equal(tooLargeRequest.status, 413);

  const docLimited = setup({ token, config: { maxRequestBytes: 1024, maxDocumentBytes: 16, maxDocumentSetBytes: 128 } });
  const tooLargeDocument = await docLimited.request("/api/linking-jobs", { method: "POST", headers, body: JSON.stringify({ documents: [{ value: "x".repeat(40) }] }) });
  assert.equal(tooLargeDocument.status, 413);

  const setLimited = setup({ token, config: { maxRequestBytes: 1024, maxDocumentBytes: 100, maxDocumentSetBytes: 30 } });
  const tooLargeSet = await setLimited.request("/api/linking-jobs", { method: "POST", headers, body: JSON.stringify({ documents: [{ x: "12345678" }, { x: "abcdefgh" }] }) });
  assert.equal(tooLargeSet.status, 413);

  const countLimited = setup({ token, config: { maxDocuments: 1 } });
  const tooMany = await countLimited.request("/api/linking-jobs", { method: "POST", headers, body: JSON.stringify({ documents: [{}, {}] }) });
  assert.equal(tooMany.status, 413);
});

test("internal failures do not leak database, bearer or Polza secrets in API responses", async () => {
  const app = setup({ token: "server-secret", config: { polzaApiKey: "provider-secret-value" }, storageError: new Error("connection failed for server-secret provider-secret-value") });
  const response = await app.request("/api/linking-jobs/job-1", { headers: { Authorization: "Bearer server-secret" } });
  assert.equal(response.status, 500);
  const body = await response.text();
  assert.doesNotMatch(body, /server-secret|provider-secret-value|connection failed/);
});
