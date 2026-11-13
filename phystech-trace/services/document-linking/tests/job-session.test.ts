import { test } from "node:test";
import assert from "node:assert/strict";
import { ACTIVE_JOB_STORAGE_KEY, clearActiveJobId, readActiveJobId, saveActiveJobId } from "../src/ui/job-session";

function memoryStorage() {
  const values = new Map<string, string>();
  return { values, getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => { values.set(key, value); }, removeItem: (key: string) => { values.delete(key); } };
}

test("active job ID survives a UI reload in session storage and clears on completion", () => {
  const storage = memoryStorage();
  saveActiveJobId("job-123", storage);
  assert.equal(readActiveJobId(storage), "job-123");
  assert.equal(storage.values.size, 1);
  assert.equal(storage.values.has("api-token"), false);
  assert.equal(ACTIVE_JOB_STORAGE_KEY.includes("token"), false);
  clearActiveJobId(storage);
  assert.equal(readActiveJobId(storage), null);
});

test("blank and missing active job IDs are treated as absent", () => {
  const storage = memoryStorage();
  storage.setItem(ACTIVE_JOB_STORAGE_KEY, "  ");
  assert.equal(readActiveJobId(storage), null);
});
