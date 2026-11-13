import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { createHash, randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import postgres from "postgres";
import Ajv2020 from "ajv/dist/2020.js";
import { adaptDocumentParserResult } from "../lib/parser/document-parser-adapter.mjs";
import { extractStructuredDocument, compareExtractionResults, parserJsonShapeErrors } from "../lib/extraction/structured-extraction.mjs";
import { callPolzaForExtraction, polzaAiReadiness } from "../lib/extraction/polza-ai.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const contractDir = resolve(here, "../contracts");
const swaggerHtml = `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Structured Extraction API</title><link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css"></head><body><div id="swagger-ui"></div><script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script><script>SwaggerUIBundle({url:'/openapi.json',dom_id:'#swagger-ui'});</script></body></html>`;
const sql = postgres(process.env.DATABASE_URL ?? "postgres://trace:trace@postgres:5432/phystech_trace", { max: 5, idle_timeout: 20, connect_timeout: 5 });
const ajv = new Ajv2020({ allErrors: true, strict: false });
const parserContract = JSON.parse(await readFile(resolve(contractDir, "parser-to-extraction-v1.schema.json"), "utf8"));
const extractionContract = JSON.parse(await readFile(resolve(contractDir, "structured-extraction-1.2.0.schema.json"), "utf8"));
const validateParserContract = ajv.compile(parserContract);
const validateExtractionContract = ajv.compile(extractionContract);

await sql`CREATE TABLE IF NOT EXISTS trace_extractions (
  extraction_id text PRIMARY KEY,
  document_id text NOT NULL,
  version integer NOT NULL,
  schema_version text NOT NULL,
  mode text NOT NULL,
  input_hash text NOT NULL,
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (document_id, version)
)`;
await sql`CREATE INDEX IF NOT EXISTS trace_extractions_document_idx ON trace_extractions(document_id, created_at DESC)`;

const json = (res, status, body) => {
  const data = Buffer.from(JSON.stringify(body));
  res.writeHead(status, { "content-type": "application/json; charset=utf-8", "content-length": data.length, "x-content-type-options": "nosniff" });
  res.end(data);
};
async function bodyJson(req, limit = 12 * 1024 * 1024) {
  const chunks = []; let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > limit) throw Object.assign(new Error("Request body exceeds the configured size limit"), { status: 413, code: "REQUEST_TOO_LARGE" });
    chunks.push(chunk);
  }
  try { return JSON.parse(Buffer.concat(chunks).toString("utf8")); }
  catch { throw Object.assign(new Error("Request body must be valid UTF-8 JSON"), { status: 400, code: "INVALID_JSON" }); }
}
function errorIssues(errors) {
  return (errors ?? []).map((item) => ({ path: item.instancePath || item.dataPath || "/", message: item.message ?? "Invalid value", keyword: item.keyword }));
}
function safeMessage(error) {
  let message = String(error?.message ?? "Unexpected service error");
  if (process.env.POLZA_API_KEY) message = message.split(process.env.POLZA_API_KEY).join("[redacted]");
  return message.slice(0, 1000);
}
function allowedForExternalModel(classification) {
  return ["public", "synthetic", "anonymized"].includes(classification);
}
async function storeExtraction(result, inputHash, mode) {
  const existing = await sql`SELECT payload FROM trace_extractions WHERE document_id=${result.document_id} AND input_hash=${inputHash} AND mode=${mode} ORDER BY version DESC LIMIT 1`;
  if (existing.length) return existing[0].payload;
  const rows = await sql`SELECT COALESCE(MAX(version),0)::int AS version FROM trace_extractions WHERE document_id=${result.document_id}`;
  const version = rows[0].version + 1;
  const stored = { ...result, version };
  await sql`INSERT INTO trace_extractions(extraction_id,document_id,version,schema_version,mode,input_hash,payload) VALUES(${stored.extraction_id},${stored.document_id},${version},${stored.schema_version},${mode},${inputHash},${sql.json(stored)})`;
  return stored;
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url ?? "/", `http://${req.headers.host ?? "localhost"}`);
  try {
    if (req.method === "GET" && url.pathname === "/health") {
      await sql`SELECT 1`;
      return json(res, 200, { status: "ok", service: "structured-extraction", storage: "postgresql", input_contract: "Document Parser v1", output_contract: "Structured Extraction 1.2.0", extraction: "existing adapter, rules and Polza-grounded extraction", llm: polzaAiReadiness(process.env) });
    }
    if (req.method === "GET" && url.pathname === "/docs") {
      res.writeHead(200, { "content-type": "text/html; charset=utf-8", "content-length": Buffer.byteLength(swaggerHtml) }); res.end(swaggerHtml); return;
    }
    if (req.method === "GET" && url.pathname === "/openapi.json") {
      const spec = await readFile(resolve(here, "openapi.json")); res.writeHead(200, { "content-type": "application/json; charset=utf-8", "content-length": spec.length }); res.end(spec); return;
    }
    const contractMatch = req.method === "GET" && url.pathname.match(/^\/contracts\/(parser-to-extraction-v1\.schema\.json|structured-extraction-1\.2\.0\.schema\.json|document-linking-1\.2\.0\.schema\.json)$/);
    if (contractMatch) {
      const spec = await readFile(resolve(contractDir, contractMatch[1])); res.writeHead(200, { "content-type": "application/schema+json", "content-length": spec.length }); res.end(spec); return;
    }
    if (req.method === "POST" && url.pathname === "/api/extractions") {
      const input = await bodyJson(req);
      const parserResult = input?.parser_result ?? input?.analysis ?? input;
      const mode = input?.mode ?? "rules_only";
      const dataClassification = input?.data_classification ?? "confidential";
      const allowExternalLlm = input?.allow_external_llm === true;
      if (!["rules_only", "llm_assisted", "compare"].includes(mode)) return json(res, 400, { code: "INVALID_MODE", error: "mode must be rules_only, llm_assisted or compare" });
      if (!parserResult || typeof parserResult !== "object" || Array.isArray(parserResult)) return json(res, 422, { code: "PARSER_RESULT_REQUIRED", error: "parser_result must be a JSON object" });
      if (!validateParserContract(parserResult)) return json(res, 422, { code: "PARSER_CONTRACT_INVALID", error: "Parser result does not match parser-to-extraction v1", diagnostics: errorIssues(validateParserContract.errors) });
      const parserErrors = parserJsonShapeErrors(parserResult);
      if (parserErrors.length) return json(res, 422, { code: "PARSER_RESULT_INVALID", error: "Parser adapter rejected the input", diagnostics: parserErrors });
      if (mode !== "rules_only" && (!allowExternalLlm || !allowedForExternalModel(dataClassification))) return json(res, 403, { code: "LLM_EXTERNAL_PROCESSING_DENIED", error: "External model calls require explicit consent and public, synthetic or anonymized project data" });
      if (mode !== "rules_only" && !process.env.POLZA_API_KEY) return json(res, 503, { code: "POLZA_NOT_CONFIGURED", error: "Polza API key is not configured; rules_only mode remains available" });

      const adapted = adaptDocumentParserResult(parserResult);
      const documentId = adapted.document_id;
      if (parserResult.document_id !== documentId) return json(res, 422, { code: "DOCUMENT_ID_MISMATCH", error: "Parser adapter changed document_id", diagnostics: [{ path: "document_id", expected: parserResult.document_id, actual: documentId }] });
      const inputHash = createHash("sha256").update(JSON.stringify(parserResult)).digest("hex");
      let llm = null;
      if (mode !== "rules_only") llm = await callPolzaForExtraction(parserResult, process.env);
      const rulesResult = mode === "compare" ? extractStructuredDocument(parserResult, { extractionId: randomUUID(), mode: "rules_only" }) : null;
      const result = extractStructuredDocument(parserResult, { extractionId: randomUUID(), mode, llm });
      result.input_hash = inputHash;
      result.input_version = 1;
      result.model_version = llm?.model ?? null;
      if (mode === "compare") result.comparison = compareExtractionResults(rulesResult, result);
      if (!validateExtractionContract(result)) return json(res, 500, { code: "EXTRACTION_OUTPUT_CONTRACT_INVALID", error: "Extraction output failed Structured Extraction 1.2.0 contract validation", diagnostics: errorIssues(validateExtractionContract.errors) });
      const stored = await storeExtraction(result, inputHash, mode);
      return json(res, 201, { extraction: stored, stored: true, status: "completed" });
    }
    const extractionMatch = url.pathname.match(/^\/api\/extractions\/([^/]+)$/);
    if (req.method === "GET" && extractionMatch) {
      const rows = await sql`SELECT payload FROM trace_extractions WHERE extraction_id=${extractionMatch[1]}`;
      return rows.length ? json(res, 200, { extraction: rows[0].payload }) : json(res, 404, { code: "EXTRACTION_NOT_FOUND", error: "Extraction result was not found" });
    }
    if (req.method === "GET" && url.pathname === "/api/extractions") {
      const documentId = url.searchParams.get("document_id");
      if (documentId) {
        const rows = await sql`SELECT payload FROM trace_extractions WHERE document_id=${documentId} ORDER BY version DESC`;
        return json(res, 200, { history: rows.map((row) => row.payload) });
      }
      const rows = await sql`SELECT DISTINCT ON(document_id) document_id,payload FROM trace_extractions ORDER BY document_id,version DESC`;
      return json(res, 200, { extractions: rows.map((row) => row.payload) });
    }
    if (req.method === "GET" && url.pathname === "/api/documents") {
      const rows = await sql`SELECT DISTINCT ON(document_id) document_id,payload,created_at FROM trace_extractions ORDER BY document_id,version DESC`;
      return json(res, 200, { documents: rows.map(({ document_id, payload, created_at }) => ({ document_id, document_type: payload.document_type, classification: payload.classification, extraction_id: payload.extraction_id, extracted_at: payload.extracted_at, created_at })) });
    }
    const documentMatch = url.pathname.match(/^\/api\/documents\/([^/]+)$/);
    if (req.method === "GET" && documentMatch) {
      const rows = await sql`SELECT payload FROM trace_extractions WHERE document_id=${documentMatch[1]} ORDER BY version DESC LIMIT 1`;
      return rows.length ? json(res, 200, { extraction: rows[0].payload }) : json(res, 404, { code: "DOCUMENT_NOT_FOUND", error: "Document extraction was not found" });
    }
    return json(res, 404, { code: "NOT_FOUND", error: "Endpoint not found" });
  } catch (error) {
    const status = Number.isInteger(error?.status) ? error.status : Number.isInteger(error?.statusCode) ? error.statusCode : Number.isInteger(error?.status) ? error.status : 500;
    const code = error?.code ?? (error?.name === "PolzaAiError" ? "POLZA_REQUEST_FAILED" : "INTERNAL_ERROR");
    const diagnostics = Array.isArray(error?.issues) ? error.issues.map((issue) => ({ path: issue.path?.join("."), message: issue.message })) : undefined;
    return json(res, status, { code, error: safeMessage(error), ...(diagnostics ? { diagnostics } : {}) });
  }
});

const port = Number(process.env.PORT ?? 8082);
server.listen(port, "0.0.0.0", () => process.stdout.write(`Structured Extraction API listening on ${port}\n`));
const shutdown = async () => { server.close(); await sql.end({ timeout: 5 }); };
process.on("SIGTERM", shutdown); process.on("SIGINT", shutdown);
