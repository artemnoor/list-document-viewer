import "dotenv/config";
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import postgres from "postgres";
import { Queue, Worker } from "bullmq";
import IORedis from "ioredis";
import { createApp } from "../server/app";
import { createAnalysisQueue } from "../server/queue";
import { PostgresStorage } from "../server/storage";
import { runMigrations } from "../server/migrate";
import { recoverPendingJobs, startAnalysisWorker } from "../server/worker";
import { GEMMA_MODEL } from "../src/linking/llm-matcher";

const databaseUrl = process.env.TEST_DATABASE_URL ?? process.env.DATABASE_URL;
const redisUrl = process.env.TEST_REDIS_URL ?? process.env.REDIS_URL;
test("API job creation, idempotency, PostgreSQL result persistence, exclusive claim and BullMQ retry", { skip: !databaseUrl || !redisUrl ? "Set DATABASE_URL and REDIS_URL to run infrastructure integration" : false }, async () => {
  const queueName = `document-linking-test-${randomUUID()}`;
  const pool = postgres(databaseUrl!, { max: 5 }), storage = new PostgresStorage(pool), queue = createAnalysisQueue(redisUrl!, queueName);
  const worker = startAnalysisWorker(redisUrl!, { storage, apiKey: "test-key", maxCalls: 52, maxInputTokens: 180_000, timeoutMs: 5000, maxRunMs: 90_000, systemPrompt: "Analyze the provided documents. Return JSON with links, unlinked_document_ids, analysis_summary and context_requests." }, queueName);
  const lockId = randomUUID(), key = `integration:${randomUUID()}`, payloadHash = `hash:${key}`;
  let id = "";
  const documents = ["contract-2026-0315.json", "addendum-2026-04.json"].map(name => JSON.parse(readFileSync(`fixtures/upstream-structured-extraction-1.2.0/${name}`, "utf8")));
  let modelCalls = 0; const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => {
    modelCalls++;
    if (modelCalls === 1) return new Response("temporary provider failure", { status: 503 });
    return new Response(JSON.stringify({ model: GEMMA_MODEL, choices: [{ finish_reason: "stop", message: { content: JSON.stringify({ links: [], unlinked_document_ids: documents.map(doc => doc.document_id), analysis_summary: "All documents reviewed.", context_requests: [] }) } }], usage: { prompt_tokens: 420, completion_tokens: 40, cost: 0.01, cost_currency: "RUB" } }), { status: 200 });
  };
  try {
    await runMigrations(pool);
    await storage.createJob({ id: lockId, key: `${key}:lock`, payloadHash: `${payloadHash}:lock`, payload: JSON.stringify({ documents }) });
    const claims = await Promise.all([storage.claimJob(lockId, 30_000), storage.claimJob(lockId, 30_000)]);
    assert.equal(claims.filter(Boolean).length, 1, "one job must not be claimed twice concurrently");
    const app = createApp({ storage, queue, config: { apiToken: "integration-api-token", polzaApiKey: "integration-polza-key", llmEnabled: true, maxCalls: 52, timeoutMs: 5000, maxInputTokens: 180_000, maxRunMs: 90_000, systemPrompt: "Analyze the provided documents. Return JSON with links, unlinked_document_ids, analysis_summary and context_requests." } });
    const requestOptions = { method: "POST", headers: { Authorization: "Bearer integration-api-token", "Content-Type": "application/json", "Idempotency-Key": key }, body: JSON.stringify({ documents }) };
    const created = await app.request("/api/linking-jobs", requestOptions);
    assert.equal(created.status, 202);
    const createdBody = await created.json() as { job_id: string; status: string };
    assert.equal(createdBody.status, "queued");
    id = createdBody.job_id;
    const duplicate = await app.request("/api/linking-jobs", requestOptions);
    assert.equal(duplicate.status, 200);
    assert.equal((await duplicate.json() as { job_id: string }).job_id, id, "idempotent API retries return the existing analysis job");
    const deadline = Date.now() + 30_000; let saved = await storage.readJob(id);
    while (saved?.status !== "completed" && saved?.status !== "failed" && Date.now() < deadline) { await new Promise(resolve => setTimeout(resolve, 250)); saved = await storage.readJob(id); }
    assert.equal(saved?.status, "completed", saved?.last_error ?? "BullMQ job did not complete");
    assert.equal(saved?.attempts, 2, JSON.stringify(saved));
    assert.equal(saved?.progress_json?.calls, 2, JSON.stringify(saved));
    assert.equal(saved?.progress_json?.input_tokens, 420, JSON.stringify(saved));
    assert.equal(saved?.result_json?.processing_metadata.llm.model, GEMMA_MODEL);
    assert.equal(saved?.result_json?.processing_metadata.llm.calls, 2);
    assert.equal(modelCalls, 2, "one transient provider error should trigger one retry");
    const fetched = await app.request(`/api/linking-jobs/${id}`, { headers: { Authorization: "Bearer integration-api-token" } });
    assert.equal(fetched.status, 200);
    const fetchedBody = await fetched.json() as { status: string; result?: { linking_run_id: string } };
    assert.equal(fetchedBody.status, "completed"); assert.equal(fetchedBody.result?.linking_run_id, saved?.run_id, "completed API retrieval returns the persisted analysis result");
  } finally {
    globalThis.fetch = originalFetch;
    await worker.worker.close(); await worker.connection.quit(); await queue.close();
    await pool`DELETE FROM analysis_jobs WHERE id=${lockId} OR (${id} <> '' AND id=${id})`;
    await pool.end({ timeout: 5 });
  }
});

test("startup recovery atomically requeues unfinished database jobs with stale completed or failed BullMQ entries", { skip: !databaseUrl || !redisUrl ? "Set DATABASE_URL and REDIS_URL to run infrastructure integration" : false }, async () => {
  const queueName = `document-linking-recovery-${randomUUID()}`;
  const pool = postgres(databaseUrl!, { max: 5 }), storage = new PostgresStorage(pool), recoveryQueue = createAnalysisQueue(redisUrl!, queueName);
  const queueConnection = new IORedis(redisUrl!, { maxRetriesPerRequest: null }), workerConnection = new IORedis(redisUrl!, { maxRetriesPerRequest: null });
  const queue = new Queue(queueName, { connection: queueConnection });
  const id = randomUUID(), failedId = randomUUID();
  let worker: Worker | undefined = new Worker(queueName, async job => {
    if (job.data.job_id === failedId) throw new Error("synthetic terminal queue failure");
    return { skipped: true };
  }, { connection: workerConnection, concurrency: 1 });
  try {
    await runMigrations(pool);
    await storage.createJob({ id, key: `recovery:${id}`, payloadHash: `recovery-hash:${id}`, payload: JSON.stringify({ documents: [] }) });
    await storage.createJob({ id: failedId, key: `recovery:${failedId}`, payloadHash: `recovery-hash:${failedId}`, payload: JSON.stringify({ documents: [] }) });
    await storage.claimJob(id, -1_000);
    await storage.claimJob(failedId, -1_000);
    await recoveryQueue.enqueue(id);
    await queue.add("analyze-document-set", { job_id: failedId }, { jobId: failedId, attempts: 1 });
    const deadline = Date.now() + 10_000;
    let queued = await queue.getJob(id);
    while ((!queued || await queued.getState() !== "completed") && Date.now() < deadline) { await new Promise(resolve => setTimeout(resolve, 100)); queued = await queue.getJob(id); }
    assert.ok(queued); assert.equal(await queued.getState(), "completed");
    let failed = await queue.getJob(failedId);
    while ((!failed || await failed.getState() !== "failed") && Date.now() < deadline) { await new Promise(resolve => setTimeout(resolve, 100)); failed = await queue.getJob(failedId); }
    assert.ok(failed); assert.equal(await failed.getState(), "failed");
    await worker.pause(true);
    await worker.close();
    worker = undefined;
    assert.equal(await recoverPendingJobs(storage, recoveryQueue), 2);
    for (const recoveredId of [id, failedId]) {
      const recovered = await queue.getJob(recoveredId);
      assert.ok(recovered); assert.equal(await recovered.getState(), "waiting", `recovery must atomically requeue the obsolete terminal entry ${recoveredId}`);
      assert.equal(recovered.attemptsMade, 0, "recovered jobs start with a fresh BullMQ retry budget while PostgreSQL retains analysis checkpoints");
    }
  } finally {
    if (worker) await worker.close(); await queue.close(); await recoveryQueue.close();
    await queueConnection.quit(); await workerConnection.quit();
    await pool`DELETE FROM analysis_jobs WHERE id=${id} OR id=${failedId}`;
    await pool.end({ timeout: 5 });
  }
});
