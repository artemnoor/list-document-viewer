import { and, eq, sql } from "drizzle-orm";
import { getDb } from "@/db";
import { documents, extractionRuns } from "@/db/schema";
import { getApiIdentity } from "@/app/api/api-auth";
import { getDocument } from "@/lib/storage";
import { env } from "cloudflare:workers";
import { extractStructuredDocument, classifyDocument, compareExtractionResults } from "@/lib/extraction/structured-extraction.mjs";
import { callPolzaForExtraction, POLZA_MODEL, PolzaAiError } from "@/lib/extraction/polza-ai.mjs";
import { consumeRateLimit } from "@/lib/security/rate-limit.mjs";
import { mayRunLlm, readLimitedBody, requestMode } from "@/lib/security/policy.mjs";
import { sha256 } from "@/lib/security/hash.mjs";

type TechnicalDetails = Record<string, unknown> & { provider?: string | null; model?: string | null };

function errorPayload(error: unknown): { error: string; code: string; technical?: TechnicalDetails } {
  if (error instanceof PolzaAiError) return {
    error: error.message,
    code: error.code,
    technical: { ...error.details, status: error.status, model: error.details?.model ?? null },
  };
  return { error: error instanceof Error ? error.message : "Structured Extraction завершился ошибкой", code: "EXTRACTION_FAILED" };
}

export async function POST(request: Request, context: { params: Promise<{ id: string }> }) {
  const user = await getApiIdentity();
  if (!user) return Response.json({ error: "Требуется вход через ChatGPT для запуска и сохранения извлечения" }, { status: 401 });
  let runId: string | null = null;
  let db: ReturnType<typeof getDb> | null = null;
  let reservedVersion: number | null = null;
  let activeMode: string | null = null;
  let activeInputVersion: number | null = null;
  let activeInputHash: string | null = null;
  let activeDocumentId: string | null = null;
  try {
    const { id } = await context.params;
    activeDocumentId = id;
    const document = await getDocument(id, user.userId);
    if (!document) return Response.json({ error: "Документ не найден" }, { status: 404 });
    const rawBody = await readLimitedBody(request, 8192);
    if (rawBody === null) return Response.json({ error: "Параметры извлечения превышают 8 КБ" }, { status: 413 });
    const body = rawBody.trim() ? JSON.parse(rawBody) as { mode?: string } : {};
    const mode = requestMode(body.mode ?? "llm_assisted");
    if (!mode) return Response.json({ error: "Режим должен быть rules_only, llm_assisted или compare" }, { status: 400 });
    activeMode = mode;
    const usesLlm = mode !== "rules_only";
    if (usesLlm && !mayRunLlm({ isDemo: document.is_demo, isSynthetic: document.is_synthetic })) {
      return Response.json({ error: "LLM разрешена только для демо и импортированных данных, явно отмеченных как синтетические или обезличенные", code: "LLM_SYNTHETIC_ONLY" }, { status: 403 });
    }
    db = getDb();
    const userLimit = await consumeRateLimit(db, `user:${user.userId}`, usesLlm ? "llm_extraction" : "rules_extraction", usesLlm ? 5 : 20, 60);
    if (!userLimit.allowed) return Response.json({ error: "Достигнут лимит запросов. Подождите минуту.", code: "RATE_LIMITED", retry_after: userLimit.resets_at - Math.floor(Date.now() / 1000) }, { status: 429 });
    if (usesLlm) {
      const globalLimit = await consumeRateLimit(db, "global", "polza_ai_daily", 12, 86400);
      if (!globalLimit.allowed) return Response.json({ error: "Достигнут дневной лимит Polza AI для демонстрационного контура", code: "AI_DAILY_LIMIT", retry_after: globalLimit.resets_at - Math.floor(Date.now() / 1000) }, { status: 429 });
    }

    const inputHash = document.input_hash ?? await sha256(JSON.stringify(document.parser_json));
    activeInputVersion = document.input_version;
    activeInputHash = inputHash;
    const next = await db.update(documents).set({
      extractionVersion: sql`${documents.extractionVersion} + 1`,
      updatedAt: new Date().toISOString(),
    }).where(and(
      eq(documents.id, id),
      eq(documents.inputVersion, document.input_version),
      document.is_demo ? eq(documents.isDemo, true) : eq(documents.ownerId, user.userId),
    )).returning({ version: documents.extractionVersion });
    if (!next.length) return Response.json({ error: "Исходный JSON был изменён параллельно. Обновите документ и повторите запуск.", code: "INPUT_VERSION_CONFLICT" }, { status: 409 });
    reservedVersion = next[0].version;

    runId = crypto.randomUUID();
    const deterministicClassification = classifyDocument(document.parser_json);
    const schemaVersion = "1.2.0";
    const startedAt = new Date().toISOString();
    await db.insert(extractionRuns).values({
      id: runId,
      documentId: id,
      ownerId: user.userId,
      version: reservedVersion,
      documentType: deterministicClassification.type,
      schemaVersion,
      inputVersion: document.input_version,
      inputHash,
      mode,
      status: "running",
      model: usesLlm ? POLZA_MODEL : null,
      provider: usesLlm ? "pending" : "rules",
      payload: JSON.stringify({ extraction_id: runId, document_id: id, version: reservedVersion, input_version: document.input_version, input_hash: inputHash, mode, status: "running", started_at: startedAt }),
    });

    let llm = null;
    if (usesLlm) llm = await callPolzaForExtraction(document.parser_json, env);
    const rulesResult = mode === "compare" ? extractStructuredDocument(document.parser_json, { extractionId: `${runId}-rules`, version: reservedVersion, mode: "rules_only" }) : null;
    const result = extractStructuredDocument(document.parser_json, { extractionId: runId, version: reservedVersion, mode, llm });
    result.input_version = document.input_version;
    result.input_hash = inputHash;
    result.model_version = llm?.model ?? null;
    result.schema_version = schemaVersion;
    if (mode === "compare") result.comparison = compareExtractionResults(rulesResult, result);

    const current = await getDocument(id, user.userId);
    const currentHash = current?.input_hash ?? null;
    if (!current || current.input_version !== document.input_version || currentHash !== inputHash) {
      const stale = { ...result, status: "stale", failure: { code: "INPUT_CHANGED_DURING_EXTRACTION", reason: "Входной JSON изменился во время обработки" } };
      await db.update(extractionRuns).set({ status: "stale", error: JSON.stringify(stale.failure), payload: JSON.stringify(stale) }).where(eq(extractionRuns.id, runId));
      return Response.json({ error: "Входной JSON изменился во время обработки. Результат сохранён в истории как устаревший.", code: "INPUT_CHANGED_DURING_EXTRACTION" }, { status: 409 });
    }
    await db.update(extractionRuns).set({
      status: "completed",
      provider: llm?.provider ?? "rules",
      model: llm?.model ?? null,
      payload: JSON.stringify(result),
      error: null,
    }).where(eq(extractionRuns.id, runId));
    await db.update(documents).set({ lastExtractionId: runId }).where(and(eq(documents.id, id), eq(documents.inputVersion, document.input_version)));
    return Response.json({ extraction: result, stored: true, status: "completed" }, { status: 201 });
  } catch (error) {
    const payload = errorPayload(error);
    if (runId && db) {
      try {
        const technical = payload.technical ?? null;
        const failed = { extraction_id: runId, document_id: activeDocumentId, version: reservedVersion, mode: activeMode, input_version: activeInputVersion, input_hash: activeInputHash, status: "failed", failed_at: new Date().toISOString(), technical, error: { code: payload.code, message: payload.error } };
        await db.update(extractionRuns).set({ status: "failed", provider: technical?.provider ?? null, model: technical?.model ?? null, error: JSON.stringify({ code: payload.code, message: payload.error, technical }), payload: JSON.stringify(failed) }).where(eq(extractionRuns.id, runId));
      } catch { /* Keep the original extraction error; history insertion may fail only if D1 is unavailable. */ }
    }
    const status = error instanceof PolzaAiError ? error.status : payload.code === "INPUT_VERSION_CONFLICT" ? 409 : 422;
    return Response.json(payload, { status });
  }
}
