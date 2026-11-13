import { test } from "node:test";
import assert from "node:assert/strict";
import { ConfigurationError, readConfig, validateProductionSecrets } from "../server/config";

const password = "r9GjF6vPz3D7n4Qx2Lm8cV5wB1sK0aHt";
const token = "T3m7qL1vN8xC4pK9dB2hR6sW0aF5jZ8u";

test("production secrets reject missing, sample, short, weak and repeated defaults", () => {
  for (const env of [
    { POSTGRES_PASSWORD: "", API_BEARER_TOKEN: token },
    { POSTGRES_PASSWORD: "replace-with-a-long-random-password", API_BEARER_TOKEN: token },
    { POSTGRES_PASSWORD: password, API_BEARER_TOKEN: "local-development-token-change-me" },
    { POSTGRES_PASSWORD: "x".repeat(32), API_BEARER_TOKEN: token },
    { POSTGRES_PASSWORD: `${password}:`, API_BEARER_TOKEN: token },
    { POSTGRES_PASSWORD: password, API_BEARER_TOKEN: password },
  ]) assert.throws(() => validateProductionSecrets(env), ConfigurationError);
});

test("production config accepts strong distinct secrets and keeps Gemma optional for UI-only startup", () => {
  const config = readConfig({ NODE_ENV: "production", POSTGRES_PASSWORD: password, API_BEARER_TOKEN: token, DATABASE_URL: `postgres://app:${password}@db:5432/app`, REDIS_URL: "redis://redis:6379" });
  assert.equal(config.production, true);
  assert.equal(config.polzaApiKey, undefined);
  assert.equal(config.maxRequestBytes, 32 * 1024 * 1024);
  assert.equal(config.maxDocumentBytes, 16 * 1024 * 1024);
  assert.equal(config.maxDocumentSetBytes, 30 * 1024 * 1024);
  assert.equal(config.maxDocuments, 100);
  const runtimeConfig = readConfig({ NODE_ENV: "production", API_BEARER_TOKEN: token, DATABASE_URL: `postgres://app:${password}@db:5432/app`, REDIS_URL: "redis://redis:6379" });
  assert.equal(runtimeConfig.production, true, "API and Worker do not need a separate POSTGRES_PASSWORD env var when DATABASE_URL is already validated");
});

test("invalid size configuration and production database URLs fail with variable names only", () => {
  const base = { NODE_ENV: "production", POSTGRES_PASSWORD: password, API_BEARER_TOKEN: token, DATABASE_URL: `postgres://app:${password}@db:5432/app`, REDIS_URL: "redis://redis:6379" };
  assert.throws(() => readConfig({ ...base, MAX_REQUEST_SIZE_MB: "2", MAX_DOCUMENT_SET_SIZE_MB: "3" }), /MAX_DOCUMENT_SIZE_MB/);
  assert.throws(() => readConfig({ ...base, DATABASE_URL: "mysql://user:password@db/app" }), /DATABASE_URL/);
});
