import assert from "node:assert/strict";

const baseUrl = process.env.BASE_URL ?? "http://127.0.0.1:5173";
const login = await fetch(new URL("/signin-with-chatgpt?return_to=%2F", baseUrl), { redirect: "manual" });
assert.equal(login.status, 302, "start the local app with npm run dev first");
const cookie = login.headers.get("set-cookie")?.split(";")[0];
assert.match(cookie ?? "", /^__sites_local_auth=1$/);
const headers = { cookie };
const json = async (path, init = {}) => {
  const response = await fetch(new URL(path, baseUrl), { ...init, headers: { ...headers, ...init.headers } });
  return { response, body: await response.json() };
};

const health = await json("/api/health");
assert.ok(health.response.ok, JSON.stringify(health.body));
if (!health.body.llm.configured) {
  console.log("SKIP real Polza smoke: the local Worker has no POLZA_API_KEY configured.");
  process.exit(0);
}

const models = await json("/api/llm/models");
assert.ok(models.response.ok, JSON.stringify(models.body));
assert.ok(models.body.models.some((model) => model.id === "deepseek/deepseek-v4-flash"), "requested model must be returned by Polza GET /models");

const documents = await json("/api/documents");
assert.ok(documents.response.ok, JSON.stringify(documents.body));
const kfz = documents.body.documents.find((document) => document.id === "kfz-2026-q1");
assert.ok(kfz, "KФЗ demo document must be seeded in D1");
const run = await json(`/api/documents/${encodeURIComponent(kfz.id)}/extract`, {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({ mode: "compare" }),
});
assert.equal(run.response.status, 201, JSON.stringify(run.body));
assert.equal(run.body.stored, true);
assert.equal(run.body.extraction.extraction_engine.llm.provider, "polza_ai");
assert.equal(run.body.extraction.extraction_engine.llm.model, "deepseek/deepseek-v4-flash");
assert.equal(run.body.extraction.extraction_engine.llm.called, true);
assert.equal(run.body.extraction.extraction_engine.llm.response_validated, true);
assert.ok(run.body.extraction.comparison);

const detail = await json(`/api/documents/${encodeURIComponent(kfz.id)}`);
assert.equal(detail.response.status, 200);
assert.equal(detail.body.document.latest_extraction.extraction_id, run.body.extraction.extraction_id, "result must be persisted and loaded back from D1");
console.log("Polza integration passed: GET /models, one DeepSeek V4 Flash compare extraction, local validation, and D1 persistence.");
