import { test } from "node:test";
import assert from "node:assert/strict";
import { POLZA_MODEL, PolzaRequestError, requestPolzaJson } from "../src/linking/polza-client";
import { analysisBackoff, isRetryableAnalysisError } from "../server/worker";

const args = { apiKey: "test-key", model: POLZA_MODEL, timeoutMs: 1000, maxTokens: 100, systemPrompt: "json", userContent: "data" };
const response = (status: number, headers?: HeadersInit) => new Response("provider body is never surfaced", { status, headers });

test("Polza 401, 403, 402 and invalid request errors are permanent", async () => {
  const original = globalThis.fetch;
  try {
    for (const status of [400, 401, 403, 402]) {
      globalThis.fetch = async () => response(status);
      await assert.rejects(requestPolzaJson(args), (error: any) => error instanceof PolzaRequestError && error.status === status && !error.retryable);
    }
  } finally { globalThis.fetch = original; }
});

test("Polza 429 honors bounded Retry-After and 5xx retries", async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => response(429, { "Retry-After": "17" });
    await assert.rejects(requestPolzaJson(args), (error: any) => error.status === 429 && error.retryable && error.retryAfterMs === 17_000);
    globalThis.fetch = async () => response(503);
    await assert.rejects(requestPolzaJson(args), (error: any) => error.status === 503 && error.retryable);
  } finally { globalThis.fetch = original; }
});

test("network errors are retryable, and model mismatch is permanent without leaking provider body", async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => { throw new TypeError("socket failure with secret test-key"); };
    await assert.rejects(requestPolzaJson(args), (error: any) => error.status === 503 && error.retryable && !error.message.includes("test-key"));
    globalThis.fetch = async () => response(200);
    await assert.rejects(requestPolzaJson({ ...args, model: "another-model" }), (error: any) => error.status === 400 && !error.retryable);
  } finally { globalThis.fetch = original; }
});

test("invalid JSON response is retained through an explicit observer without exposing credentials", async () => {
  const original = globalThis.fetch; let retained: any;
  globalThis.fetch = async () => new Response(JSON.stringify({ model: POLZA_MODEL, choices: [{ message: { content: "{broken" } }], usage: { prompt_tokens: 17, completion_tokens: 5 }, cost: 0.002 }), { status: 200 });
  try {
    await assert.rejects(requestPolzaJson({ ...args, onInvalidJsonResponse: response => { retained = response; } }), (error: any) => error.status === 502 && error.retryable);
    assert.deepEqual(retained, { rawText: "{broken", model: POLZA_MODEL, promptTokens: 17, completionTokens: 5, cost: 0.002 });
  } finally { globalThis.fetch = original; }
});

test("BullMQ retries only transient Polza errors with exponential delay and respects Retry-After", () => {
  assert.equal(isRetryableAnalysisError(new PolzaRequestError("unauthorized", 401, false)), false);
  assert.equal(isRetryableAnalysisError(new PolzaRequestError("balance", 402, false)), false);
  assert.equal(isRetryableAnalysisError(new PolzaRequestError("limited", 429, true, 17_000)), true);
  assert.equal(isRetryableAnalysisError(new PolzaRequestError("unavailable", 503, true)), true);
  assert.equal(analysisBackoff(1, "polza-exponential", new PolzaRequestError("temporary", 503, true)), 3_000);
  assert.equal(analysisBackoff(3, "polza-exponential", new PolzaRequestError("limited", 429, true, 17_000)), 17_000);
});
