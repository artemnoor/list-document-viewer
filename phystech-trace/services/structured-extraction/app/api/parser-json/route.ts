import { and, eq, sql } from "drizzle-orm";
import { getDb } from "@/db";
import { documents } from "@/db/schema";
import { getApiIdentity } from "@/app/api/api-auth";
import { ensureDemoDocuments } from "@/lib/storage";
import { parserJsonShapeErrors } from "@/lib/extraction/structured-extraction.mjs";
import { adaptDocumentParserResult } from "@/lib/parser/document-parser-adapter.mjs";
import { sha256 } from "@/lib/security/hash.mjs";
import { consumeRateLimit } from "@/lib/security/rate-limit.mjs";
import { MAX_IMPORT_BYTES, readLimitedBody } from "@/lib/security/policy.mjs";

export async function POST(request: Request) {
  const user = await getApiIdentity();
  if (!user) return Response.json({ error: "Требуется вход через ChatGPT для импорта пользовательских документов" }, { status: 401 });
  try {
    const rawBody = await readLimitedBody(request, MAX_IMPORT_BYTES);
    if (rawBody === null) return Response.json({ error: "JSON больше допустимых 5 МБ" }, { status: 413 });
    const db = getDb();
    const limit = await consumeRateLimit(db, `user:${user.userId}`, "parser_import", 5, 60);
    if (!limit.allowed) return Response.json({ error: "Слишком много импортов. Подождите минуту." }, { status: 429 });
    await ensureDemoDocuments();
    const body = JSON.parse(rawBody) as { parser_json?: Record<string, unknown>; layout_json?: Record<string, unknown>; title?: string; file_name?: string; synthetic_acknowledged?: boolean };
    const rawParserJson = (body.parser_json ?? body) as Record<string, unknown>;
    const parserJson = body.layout_json ? { analysis_json: rawParserJson, layout_json: body.layout_json } : rawParserJson;
    const errors = parserJsonShapeErrors(parserJson);
    if (errors.length) return Response.json({ error: "Этот файл не похож на результат Document Parser", details: errors }, { status: 400 });
    const source = adaptDocumentParserResult(parserJson);
    const id = source.document_id;
    const [existing] = await db.select({ id: documents.id, isDemo: documents.isDemo, ownerId: documents.ownerId, parserJson: documents.parserJson, inputVersion: documents.inputVersion })
      .from(documents).where(eq(documents.id, id)).limit(1);
    if (existing && (existing.isDemo || existing.ownerId !== user.userId)) return Response.json({ error: "Документ с таким ID уже существует или недоступен" }, { status: 409 });
    const fileName = String(source.file_name ?? body.file_name ?? `${id}.json`).slice(0, 240);
    const format = String(source.format ?? fileName.split(".").pop() ?? "JSON").replace(/^\./, "").toUpperCase().slice(0, 16);
    const title = String(body.title ?? source.title ?? fileName).slice(0, 240);
    const parserJsonString = JSON.stringify(parserJson);
    const inputHash = await sha256(parserJsonString);
    const isSynthetic = body.synthetic_acknowledged === true;
    const now = new Date().toISOString();
    let inputVersion = 1;
    if (existing) {
      const changed = await sha256(existing.parserJson) !== inputHash;
      inputVersion = existing.inputVersion + (changed ? 1 : 0);
      await db.update(documents).set({
        title, fileName, format, parserJson: parserJsonString, isSynthetic,
        ...(changed ? { inputVersion: sql`${documents.inputVersion} + 1`, lastExtractionId: null } : {}),
        updatedAt: now,
      }).where(and(eq(documents.id, id), eq(documents.ownerId, user.userId), eq(documents.isDemo, false)));
    } else {
      await db.insert(documents).values({
        id, title, fileName, format, isDemo: false, isSynthetic, ownerId: user.userId,
        inputVersion: 1, extractionVersion: 0, parserJson: parserJsonString, updatedAt: now,
      });
    }
    return Response.json({ document: { id, title, file_name: fileName, format, is_demo: false, is_synthetic: isSynthetic, input_version: inputVersion }, message: "Импортирован готовый JSON результата Document Parser без OCR и повторного распознавания" }, { status: existing ? 200 : 201 });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Не удалось импортировать JSON";
    return Response.json({ error: message }, { status: 400 });
  }
}
