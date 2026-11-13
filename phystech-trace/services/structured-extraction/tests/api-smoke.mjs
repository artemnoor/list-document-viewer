import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const baseUrl = process.env.BASE_URL ?? "http://127.0.0.1:5173";
const login = await fetch(new URL("/signin-with-chatgpt?return_to=%2F", baseUrl), { redirect: "manual" });
assert.equal(login.status, 302, "local development requires explicit sign-in");
const localCookie = login.headers.get("set-cookie")?.split(";")[0];
assert.match(localCookie ?? "", /^__sites_local_auth=1$/);
const ownerA = { cookie: localCookie };
const spoofedOwner = { ...ownerA, "oai-authenticated-user-id": "forged-user", "oai-authenticated-user-email": "forged@example.test" };
const anonymousSpoof = { "oai-authenticated-user-id": "forged-user", "oai-authenticated-user-email": "forged@example.test" };
const json = async (path, init = {}) => {
  const response = await fetch(new URL(path, baseUrl), init);
  return { response, body: await response.json() };
};

const health = await json("/api/health");
assert.ok(health.response.ok, JSON.stringify(health.body));
assert.equal(health.body.storage, "Cloudflare D1");
assert.equal(typeof health.body.llm.configured, "boolean");
if (!health.body.llm.configured) {
  const providerUnavailable = await json("/api/llm/models", { headers: ownerA });
  assert.equal(providerUnavailable.response.status, 503);
  assert.equal(providerUnavailable.body.code, "POLZA_NOT_CONFIGURED");
}

const listing = await json("/api/documents");
assert.ok(listing.response.ok, JSON.stringify(listing.body));
assert.equal(listing.body.storage, "Cloudflare D1");
assert.ok(listing.body.documents.length >= 6);
assert.ok(listing.body.documents.every((document) => document.is_demo));
const demo = listing.body.documents.find((document) => document.id === "kfz-2026-q1");
assert.ok(demo);
const demoDetail = await json(`/api/documents/${encodeURIComponent(demo.id)}`);
assert.equal(demoDetail.response.status, 200);
assert.equal(demoDetail.body.document.parser_json.document_id, demo.id);

const unauthenticatedExtraction = await json(`/api/documents/${encodeURIComponent(demo.id)}/extract`, { method: "POST" });
assert.equal(unauthenticatedExtraction.response.status, 401);
const unauthenticatedImport = await json("/api/parser-json", { method: "POST", headers: { ...anonymousSpoof, "content-type": "application/json" }, body: "{}" });
assert.equal(unauthenticatedImport.response.status, 401);
const unauthenticatedModels = await json("/api/llm/models", { headers: anonymousSpoof });
assert.equal(unauthenticatedModels.response.status, 401);

const rawFixture = JSON.parse(await readFile(new URL("../data/parser-results/invoice-2026-0408.json", import.meta.url), "utf8"));
const importedId = `api-smoke-${crypto.randomUUID()}`;
function updateDocumentReferences(value) {
  if (!value || typeof value !== "object") return;
  for (const key of Object.keys(value)) {
    if (key === "document_id") value[key] = importedId;
    else updateDocumentReferences(value[key]);
  }
}
updateDocumentReferences(rawFixture);
rawFixture.document_id = importedId;
rawFixture.document.name = importedId;
rawFixture.title = "API smoke · подготовленный счёт";
rawFixture.file_name = `${importedId}.json`;
const importDoc = async (parserJson, headers = ownerA) => json("/api/parser-json", {
  method: "POST",
  headers: { ...headers, "content-type": "application/json" },
  body: JSON.stringify({ parser_json: parserJson, synthetic_acknowledged: true }),
});

const imported = await importDoc(rawFixture);
assert.equal(imported.response.status, 201, JSON.stringify(imported.body));
assert.equal(imported.body.document.input_version, 1);
const saved = await json(`/api/documents/${encodeURIComponent(importedId)}`, { headers: ownerA });
assert.equal(saved.response.status, 200);
assert.equal(saved.body.document.is_synthetic, true);

const extraction = await json(`/api/documents/${encodeURIComponent(importedId)}/extract`, {
  method: "POST", headers: { ...ownerA, "content-type": "application/json" }, body: JSON.stringify({ mode: "rules_only" }),
});
assert.equal(extraction.response.status, 201, JSON.stringify(extraction.body));
assert.equal(extraction.body.extraction.document_type, "invoice");
assert.equal(extraction.body.extraction.extraction_engine.llm.called, false);
assert.equal(extraction.body.extraction.input_version, 1);

const extractionId = extraction.body.extraction.extraction_id;
const outsiderDocument = await json(`/api/documents/${encodeURIComponent(importedId)}`, { headers: anonymousSpoof });
assert.equal(outsiderDocument.response.status, 404);
const outsiderHistory = await json(`/api/documents/${encodeURIComponent(importedId)}/extractions`, { headers: anonymousSpoof });
assert.equal(outsiderHistory.response.status, 404);
const outsiderExtraction = await json(`/api/extractions/${encodeURIComponent(extractionId)}`, { headers: anonymousSpoof });
assert.equal(outsiderExtraction.response.status, 404);
const spoofedImport = await importDoc(rawFixture, anonymousSpoof);
assert.equal(spoofedImport.response.status, 401);

const spoofedIdentity = await json(`/api/documents/${encodeURIComponent(importedId)}`, { headers: spoofedOwner });
assert.equal(spoofedIdentity.response.status, 200, "client-supplied OAI identity headers must not replace the local authenticated session");

const unchangedImport = await importDoc(rawFixture);
assert.equal(unchangedImport.response.status, 200);
assert.equal(unchangedImport.body.document.input_version, 1);

const changedFixture = structuredClone(rawFixture);
changedFixture.parts.push({ kind: "paragraph", id: "new-source", text: "Дополнительный исходный фрагмент" });
const changedImport = await importDoc(changedFixture);
assert.equal(changedImport.response.status, 200);
assert.equal(changedImport.body.document.input_version, 2);
const afterChange = await json(`/api/documents/${encodeURIComponent(importedId)}`, { headers: ownerA });
assert.equal(afterChange.body.document.latest_extraction, null, "old extraction must not be reported as current after source version changes");

const reExtraction = await json(`/api/documents/${encodeURIComponent(importedId)}/extract`, {
  method: "POST", headers: { ...ownerA, "content-type": "application/json" }, body: JSON.stringify({ mode: "rules_only" }),
});
assert.equal(reExtraction.response.status, 201, JSON.stringify(reExtraction.body));
assert.equal(reExtraction.body.extraction.version, extraction.body.extraction.version + 1);
assert.equal(reExtraction.body.extraction.input_version, 2);
const history = await json(`/api/documents/${encodeURIComponent(importedId)}/extractions`, { headers: ownerA });
assert.equal(history.response.status, 200);
assert.ok(history.body.history.some((run) => run.input_version === 1));
assert.ok(history.body.history.some((run) => run.input_version === 2));
const stored = await json(`/api/extractions/${encodeURIComponent(reExtraction.body.extraction.extraction_id)}`, { headers: ownerA });
assert.equal(stored.response.status, 200);
assert.equal(stored.body.extraction.document_id, importedId);

console.log("API smoke passed: D1 persistence, local sign-in, spoofed-header rejection, import versioning, stale-result invalidation, rules-only rerun, history reload, and anonymous write denial. Polza AI configuration reported:", health.body.llm.configured ? "configured" : "not configured");
