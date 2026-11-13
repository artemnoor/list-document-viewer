import test from "node:test";
import assert from "node:assert/strict";
import { demoBlueprints } from "../data/demo-blueprints.mjs";
import { selectMissingDemoDocuments } from "../lib/storage-seeding.mjs";

const parserResults = demoBlueprints.map(({ id }) => ({ document_id: id }));

test("demo seeding fills only missing records when D1 already has demo data", () => {
  const missing = selectMissingDemoDocuments(parserResults, ["contract-2026-0315"]);
  assert.equal(missing.length, 5);
  assert.ok(missing.some((result) => result.document_id === "kfz-2026-q1"));
  assert.ok(!missing.some((result) => result.document_id === "contract-2026-0315"));
});

test("demo seeding is idempotent after every prepared record exists", () => {
  const ids = parserResults.map((result) => result.document_id);
  assert.deepEqual(selectMissingDemoDocuments(parserResults, ids), []);
});
