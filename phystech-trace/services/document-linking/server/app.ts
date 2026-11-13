import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { timingSafeEqual } from "node:crypto";
import { parse as parseYaml } from "yaml";
import { Hono } from "hono";
import { serveStatic } from "@hono/node-server/serve-static";
import { linkDocuments } from "../src/linking/link-resolver";
import { GEMMA_MODEL } from "../src/linking/llm-matcher";
import { validateInput } from "../src/contracts/input";
import { linkingOutputSchema } from "../src/contracts/output";
import { OUTPUT_CONTRACT_VERSION } from "../src/contracts/registry";
import type { LinkingResult } from "../src/linking/types";
import type { AnalysisQueue } from "./queue";
import type { PostgresStorage } from "./storage";

export type AppDependencies = {
  storage: PostgresStorage;
  queue: AnalysisQueue;
  config: { apiToken?: string; polzaApiKey?: string; llmEnabled: boolean; requireExternalLlmConsent?: boolean; maxCalls: number; timeoutMs: number; maxInputTokens: number; maxRunMs: number; systemPrompt?: string; maxRequestBytes?: number; maxDocumentBytes?: number; maxDocumentSetBytes?: number; maxDocuments?: number };
};
const MIB = 1024 * 1024;
const DEFAULT_LIMITS = { maxRequestBytes: 32 * MIB, maxDocumentBytes: 16 * MIB, maxDocumentSetBytes: 30 * MIB, maxDocuments: 100 };
function validToken(provided: string, expected?: string): boolean {
  if (!expected) return false;
  const a = Buffer.from(provided), b = Buffer.from(expected);
  return a.length === b.length && timingSafeEqual(a, b);
}
async function jsonBody(request: Request, maxBytes: number): Promise<{ body?: any; error?: string; status?: number }> {
  const contentLength = Number(request.headers.get("content-length"));
  if (Number.isFinite(contentLength) && contentLength > maxBytes) return { error: `Размер HTTP-запроса превышает лимит ${Math.ceil(maxBytes / MIB)} МиБ`, status: 413 };
  const reader = request.body?.getReader(); if (!reader) return { error: "Пустое тело запроса", status: 400 };
  const chunks: Uint8Array[] = []; let total = 0;
  while (true) {
    const { done, value } = await reader.read(); if (done) break;
    total += value.byteLength; if (total > maxBytes) { await reader.cancel(); return { error: `Размер HTTP-запроса превышает лимит ${Math.ceil(maxBytes / MIB)} МиБ`, status: 413 }; }
    chunks.push(value);
  }
  const bytes = new Uint8Array(total); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try { return { body: JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) }; } catch { return { error: "Некорректный JSON тела запроса", status: 400 }; }
}
function documentsFrom(body: any): unknown { return body?.documents ?? body; }
function clientIp(request: Request): string { return request.headers.get("x-real-ip") ?? request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ?? "unknown"; }
function documentSizeError(documents: unknown[], config: AppDependencies["config"]): string | undefined {
  const limits = { ...DEFAULT_LIMITS, ...config };
  let total = 0;
  for (let index = 0; index < documents.length; index++) {
    let size: number;
    try { size = Buffer.byteLength(JSON.stringify(documents[index]), "utf8"); }
    catch { return `Документ ${index + 1} нельзя представить как JSON`; }
    if (size > limits.maxDocumentBytes) return `Документ ${index + 1} превышает лимит ${Math.ceil(limits.maxDocumentBytes / MIB)} МиБ`;
    total += size;
  }
  if (total > limits.maxDocumentSetBytes) return `Общий размер комплекта превышает лимит ${Math.ceil(limits.maxDocumentSetBytes / MIB)} МиБ`;
  return undefined;
}

export function createApp(deps: AppDependencies) {
  const app = new Hono();
  const auth = async (c: any, next: () => Promise<void>) => {
    const header = c.req.header("Authorization") ?? "", token = header.startsWith("Bearer ") ? header.slice(7) : "";
    if (!deps.config.apiToken) return c.json({ error: "Защищённый API не настроен: задайте API_BEARER_TOKEN" }, 503);
    if (!validToken(token, deps.config.apiToken)) return c.json({ error: "Требуется авторизация" }, 401);
    await next();
  };
  const limit = (action: "run" | "read") => async (c: any, next: () => Promise<void>) => {
    const allowed = await deps.storage.rateLimit(`${action}:${clientIp(c.req.raw)}`, action === "run" ? 20 : 120);
    if (!allowed) return c.json({ error: "Слишком много запросов; повторите позже" }, 429);
    await next();
  };
  app.onError((error, c) => {
    const status = Number.isInteger((error as any).status) ? (error as any).status : 500;
    const candidate = status < 500 ? String((error as any).publicMessage ?? error.message ?? "Некорректный запрос") : String((error as any).publicMessage ?? "Внутренняя ошибка сервера");
    const secrets = [deps.config.apiToken, deps.config.polzaApiKey].filter((value): value is string => Boolean(value));
    const message = secrets.reduce((value, secret) => value.split(secret).join("[redacted]"), candidate);
    return c.json({ error: message, ...(status === 422 ? { diagnostics: (error as any).diagnostics ?? [] } : []) }, status as any);
  });

  const health = async (c: any) => {
    try { await deps.storage.health(); await deps.queue.health(); return c.json({ status: "ok", service: "kfz-document-linking", contract_version: OUTPUT_CONTRACT_VERSION, database: "ok", queue: "ok", llm: { provider: "Polza AI", model: GEMMA_MODEL, configured: deps.config.llmEnabled && Boolean(deps.config.polzaApiKey) } }); }
    catch { return c.json({ status: "unavailable", service: "kfz-document-linking", contract_version: OUTPUT_CONTRACT_VERSION, database: "unknown", queue: "unknown", llm: { provider: "Polza AI", model: GEMMA_MODEL, configured: deps.config.llmEnabled && Boolean(deps.config.polzaApiKey) } }, 503); }
  };
  app.get("/health", health);
  app.get("/api/health", health);
  app.get("/docs", c => c.html(`<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Document Linking API</title><link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css"></head><body><div id="swagger-ui"></div><script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script><script>SwaggerUIBundle({url:'/openapi.json',dom_id:'#swagger-ui'});</script></body></html>`));
  app.get("/openapi.json", async c => c.json(parseYaml(await readFile(resolve(process.cwd(), "openapi.yaml"), "utf8"))));
  app.get("/contracts/:name", async c => {
    const name = c.req.param("name");
    if (!['input.schema.json', 'output.schema.json'].includes(name)) return c.json({ error: "Contract not found" }, 404);
    c.header("Content-Type", "application/schema+json; charset=utf-8");
    return c.body(await readFile(resolve(process.cwd(), "contracts", name)));
  });

  app.get("/api/demo", auth, limit("read"), async c => {
    const names = ["act-2026-0424.json", "addendum-2026-04.json", "contract-2026-0315.json", "invoice-2026-0408.json", "kfz-2026-q1.json", "registry-2026-04.json", "receipt-unknown-1.json", "contract-ambiguous-a.json", "contract-ambiguous-b.json", "act-ambiguous-1.json"];
    try { const documents = await Promise.all(names.map(async name => JSON.parse(await readFile(resolve(process.cwd(), "dist/demo", name), "utf8")))); return c.json({ documents }); }
    catch { return c.json({ error: "Не удалось загрузить демонстрационные данные" }, 503); }
  });

  app.use("/api/linking-runs", auth); app.use("/api/linking-runs/*", auth);
  app.post("/api/linking-runs", limit("run"), async c => {
    const parsed = await jsonBody(c.req.raw, deps.config.maxRequestBytes ?? DEFAULT_LIMITS.maxRequestBytes); if (parsed.error) return c.json({ error: parsed.error }, parsed.status as any);
    const body = parsed.body, documents = documentsFrom(body);
    if (deps.config.requireExternalLlmConsent && (body?.allow_external_llm !== true || !["public", "synthetic", "anonymized"].includes(body?.data_classification))) return c.json({ error: "Вызов внешней модели требует явного согласия и публичных, синтетических или обезличенных данных", code: "LLM_EXTERNAL_PROCESSING_DENIED" }, 403);
    if (!Array.isArray(documents)) return c.json({ error: "Ожидается массив документов" }, 422);
    if (documents.length > (deps.config.maxDocuments ?? DEFAULT_LIMITS.maxDocuments)) return c.json({ error: `Количество документов превышает лимит ${deps.config.maxDocuments ?? DEFAULT_LIMITS.maxDocuments}` }, 413);
    const sizeError = documentSizeError(documents, deps.config); if (sizeError) return c.json({ error: sizeError }, 413);
    const payloadHash = await sha256(JSON.stringify(body)), rawKey = c.req.header("Idempotency-Key");
    if (rawKey && (rawKey.length > 128 || !/^[\w.:-]+$/.test(rawKey))) return c.json({ error: "Некорректный Idempotency-Key" }, 400);
    const key = rawKey ? await sha256(rawKey) : payloadHash, existing = await deps.storage.findRunByIdempotency(key);
    if (existing) return existing.payload_hash === payloadHash ? c.json(existing.result_json, 200) : c.json({ error: "Idempotency-Key уже использован для другого содержимого" }, 409);
    const prompt = deps.config.systemPrompt ?? await readFile(resolve(process.cwd(), "prompts/document-linking-system.md"), "utf8");
    const result = await linkDocuments(documents, { llm: { enabled: deps.config.llmEnabled, apiKey: deps.config.polzaApiKey, model: GEMMA_MODEL, maxCalls: deps.config.maxCalls, timeoutMs: deps.config.timeoutMs, maxRunMs: deps.config.maxRunMs, maxInputTokens: deps.config.maxInputTokens, systemPrompt: prompt, resumeProgress: await deps.storage.readProgress(payloadHash), onProgress: state => deps.storage.saveProgress(payloadHash, state) } });
    const valid = linkingOutputSchema.safeParse(result); if (!valid.success) return c.json({ error: "Ошибка внутреннего выходного контракта", diagnostics: valid.error.issues }, 500);
    try { await deps.storage.saveRun(result, key, payloadHash); } catch (error) { const retry = await deps.storage.findRunByIdempotency(key); if (retry?.payload_hash === payloadHash) return c.json(retry.result_json, 200); throw error; }
    return c.json(result, 201);
  });
  app.get("/api/linking-runs/:id", limit("read"), async c => {
    const result = await deps.storage.readRun(c.req.param("id")); return result ? c.json(result) : c.json({ error: "Запуск не найден или повреждён" }, 404);
  });
  app.patch("/api/linking-runs/:runId/links/:linkId", limit("read"), async c => {
    const parsed = await jsonBody(c.req.raw, deps.config.maxRequestBytes ?? DEFAULT_LIMITS.maxRequestBytes); if (parsed.error) return c.json({ error: parsed.error }, parsed.status as any);
    const body = parsed.body; if (!body || !["confirmed", "rejected"].includes(body.status)) return c.json({ error: "status должен быть confirmed или rejected" }, 400);
    const previous = await deps.storage.readRun(c.req.param("runId")); if (!previous) return c.json({ error: "Запуск не найден" }, 404);
    const result = structuredClone(previous) as LinkingResult, link = result.links.find(item => item.link_id === c.req.param("linkId")); if (!link) return c.json({ error: "Связь не найдена" }, 404);
    if (link.verification_status !== "not_reviewed" && link.status !== body.status) return c.json({ error: "Решение уже сохранено и не может быть перезаписано" }, 409);
    link.status = body.status; link.verification_status = body.status === "confirmed" ? "human_confirmed" : "human_rejected";
    result.review_required = result.review_required.filter(item => item.link_id !== link.link_id);
    try { if (!await deps.storage.updateDecision(previous, result, link)) return c.json({ error: "Результат изменён параллельным запросом; перечитайте его" }, 409); }
    catch { return c.json({ error: "Не удалось атомарно сохранить решение" }, 503); }
    return c.json(result);
  });

  app.use("/api/linking-jobs", auth); app.use("/api/linking-jobs/*", auth);
  app.post("/api/linking-jobs", limit("run"), async c => {
    const parsed = await jsonBody(c.req.raw, deps.config.maxRequestBytes ?? DEFAULT_LIMITS.maxRequestBytes); if (parsed.error) return c.json({ error: parsed.error }, parsed.status as any);
    const body = parsed.body, input = documentsFrom(body);
    if (deps.config.requireExternalLlmConsent && (body?.allow_external_llm !== true || !["public", "synthetic", "anonymized"].includes(body?.data_classification))) return c.json({ error: "Вызов внешней модели требует явного согласия и публичных, синтетических или обезличенных данных", code: "LLM_EXTERNAL_PROCESSING_DENIED" }, 403);
    if (!Array.isArray(input)) return c.json({ error: "Ожидается массив документов" }, 422);
    if (input.length > (deps.config.maxDocuments ?? DEFAULT_LIMITS.maxDocuments)) return c.json({ error: `Количество документов превышает лимит ${deps.config.maxDocuments ?? DEFAULT_LIMITS.maxDocuments}` }, 413);
    const sizeError = documentSizeError(input, deps.config); if (sizeError) return c.json({ error: sizeError }, 413);
    if (!deps.config.llmEnabled) return c.json({ error: "LLM-анализ отключён; включите Gemma через Polza AI" }, 503);
    if (!deps.config.polzaApiKey) return c.json({ error: "Задайте POLZA_API_KEY для создания задания анализа" }, 503);
    const checked = validateInput(input); if (!checked.success) return c.json({ error: "Входные данные не соответствуют Structured Extraction 1.2.0", diagnostics: checked.diagnostics }, 422);
    const payload = JSON.stringify({ documents: checked.documents }), payloadHash = await sha256(payload), rawKey = c.req.header("Idempotency-Key");
    if (rawKey && (rawKey.length > 128 || !/^[\w.:-]+$/.test(rawKey))) return c.json({ error: "Некорректный Idempotency-Key" }, 400);
    const key = rawKey ? await sha256(rawKey) : payloadHash, existing = await deps.storage.findJobByIdempotency(key);
    if (existing) return existing.payload_hash === payloadHash ? c.json({ job_id: existing.id, status: existing.status }, 200) : c.json({ error: "Idempotency-Key уже использован для другого содержимого" }, 409);
    const id = crypto.randomUUID();
    try { await deps.storage.createJob({ id, key, payloadHash, payload }); await deps.queue.enqueue(id); return c.json({ job_id: id, status: "queued", status_url: `/api/linking-jobs/${id}` }, 202); }
    catch (error) { const retry = await deps.storage.findJobByIdempotency(key); if (retry?.payload_hash === payloadHash) { if (retry.status === "queued") await deps.queue.enqueue(retry.id); return c.json({ job_id: retry.id, status: retry.status }, 200); } throw error; }
  });
  app.get("/api/linking-jobs/:id", limit("read"), async c => {
    const job = await deps.storage.readJob(c.req.param("id")); if (!job) return c.json({ error: "Задание не найдено" }, 404);
    const progress: any = job.progress_json ?? {};
    return c.json({ job_id: job.id, status: job.status, phase: progress.phase ?? (job.status === "queued" ? "queued" : job.status), progress: { completed_fragments: progress.completed_fragments?.length ?? 0, total_fragments: progress.total_fragments ?? null, model_calls: progress.calls ?? 0, input_tokens: progress.input_tokens ?? 0, output_tokens: progress.output_tokens ?? 0, cost_amount: progress.has_cost ? progress.cost_amount : null, cost_currency: progress.cost_currency ?? null, context_rounds: progress.context_rounds ?? 0 }, model: GEMMA_MODEL, provider: "Polza AI", attempts: job.attempts, last_error: job.last_error, run_id: job.run_id, ...(job.status === "completed" ? { result: job.result_json } : {}), created_at: job.created_at, updated_at: job.updated_at });
  });
  app.post("/api/linking-jobs/:id/resume", limit("run"), async c => {
    if (!deps.config.llmEnabled) return c.json({ error: "LLM-анализ отключён; включите Gemma через Polza AI" }, 503);
    if (!deps.config.polzaApiKey) return c.json({ error: "Задайте POLZA_API_KEY для продолжения задания" }, 503);
    const job = await deps.storage.readJob(c.req.param("id")); if (!job) return c.json({ error: "Задание не найдено" }, 404);
    if (["completed", "queued", "running", "retrying"].includes(job.status)) return c.json({ job_id: job.id, status: job.status }, 200);
    await deps.storage.resetFailedJob(job.id); await deps.queue.enqueue(job.id, true); return c.json({ job_id: job.id, status: "queued" }, 202);
  });

  app.use("/*", serveStatic({ root: "./dist" }));
  app.get("*", async c => {
    if (!c.req.header("Accept")?.includes("text/html")) return c.notFound();
    try { return c.html(await readFile(resolve(process.cwd(), "dist/index.html"), "utf8")); }
    catch { return c.text("Frontend build not found. Run npm run build.", 503); }
  });
  return app;
}

export async function sha256(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value)); return [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, "0")).join("");
}
