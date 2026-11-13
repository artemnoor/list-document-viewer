import { and, asc, desc, eq, isNull, or } from "drizzle-orm";
import { getDb } from "@/db";
import { documents, extractionRuns } from "@/db/schema";
import { demoDocumentRecord, demoParserResults } from "@/lib/parser/mock-document-parser";
import { sha256 } from "@/lib/security/hash.mjs";
import { adaptDocumentParserResult } from "@/lib/parser/document-parser-adapter.mjs";
import { selectMissingDemoDocuments } from "@/lib/storage-seeding.mjs";

export async function ensureDemoDocuments() {
  const db = getDb();
  const existing = await db.select({ id: documents.id }).from(documents).where(eq(documents.isDemo, true));
  const missing = selectMissingDemoDocuments(demoParserResults, existing.map((row) => row.id));
  for (const parserJson of missing) {
    const record = demoDocumentRecord(parserJson);
    await db.insert(documents).values(record).onConflictDoNothing();
  }
  await db.update(documents).set({ isSynthetic: true }).where(and(eq(documents.isDemo, true), eq(documents.isSynthetic, false)));
}

export async function listDocuments(ownerId?: string | null) {
  const db = getDb();
  const visibility = ownerId ? or(eq(documents.isDemo, true), eq(documents.ownerId, ownerId)) : eq(documents.isDemo, true);
  const rows = await db.select().from(documents).where(visibility).orderBy(asc(documents.isDemo), desc(documents.updatedAt), asc(documents.title));
  return Promise.all(rows.map(async (row) => {
    const parser = JSON.parse(row.parserJson);
    const inputHash = await sha256(row.parserJson);
    const runOwnerScope = ownerId ? or(isNull(extractionRuns.ownerId), eq(extractionRuns.ownerId, ownerId)) : isNull(extractionRuns.ownerId);
    const [[latest], [currentRun]] = await Promise.all([
      db.select().from(extractionRuns).where(and(eq(extractionRuns.documentId, row.id), runOwnerScope)).orderBy(desc(extractionRuns.version)).limit(1),
      db.select().from(extractionRuns).where(and(eq(extractionRuns.documentId, row.id), runOwnerScope, eq(extractionRuns.status, "completed"), eq(extractionRuns.inputHash, inputHash), eq(extractionRuns.inputVersion, row.inputVersion))).orderBy(desc(extractionRuns.version)).limit(1),
    ]);
    const parserView = adaptDocumentParserResult(parser);
    return {
      id: row.id,
      title: row.title,
      file_name: row.fileName,
      format: row.format,
      is_demo: Boolean(row.isDemo),
      parser_version: parser.parser_output_version ?? parser.analysis_version ?? "Document Parser",
      page_count: parserView.page_count,
      latest_extraction: currentRun ? { id: currentRun.id, version: currentRun.version, document_type: currentRun.documentType, created_at: currentRun.createdAt, mode: currentRun.mode } : null,
      latest_run_status: latest?.status ?? null,
      input_version: row.inputVersion,
      is_synthetic: Boolean(row.isSynthetic),
      updated_at: row.updatedAt,
    };
  }));
}

export async function getDocument(id: string, ownerId?: string | null) {
  const db = getDb();
  const visibility = ownerId ? or(eq(documents.isDemo, true), eq(documents.ownerId, ownerId)) : eq(documents.isDemo, true);
  const [row] = await db.select().from(documents).where(and(eq(documents.id, id), visibility)).limit(1);
  if (!row) return null;
  const parserJson = JSON.parse(row.parserJson);
  const inputHash = await sha256(row.parserJson);
  const [[latest], [currentRun]] = await Promise.all([
    db.select().from(extractionRuns).where(and(eq(extractionRuns.documentId, id), ownerId ? or(isNull(extractionRuns.ownerId), eq(extractionRuns.ownerId, ownerId)) : isNull(extractionRuns.ownerId))).orderBy(desc(extractionRuns.version)).limit(1),
    db.select().from(extractionRuns).where(and(eq(extractionRuns.documentId, id), ownerId ? or(isNull(extractionRuns.ownerId), eq(extractionRuns.ownerId, ownerId)) : isNull(extractionRuns.ownerId), eq(extractionRuns.status, "completed"), eq(extractionRuns.inputHash, inputHash), eq(extractionRuns.inputVersion, row.inputVersion))).orderBy(desc(extractionRuns.version)).limit(1),
  ]);
  return {
    id: row.id,
    title: row.title,
    file_name: row.fileName,
    format: row.format,
    is_demo: Boolean(row.isDemo),
    is_synthetic: Boolean(row.isSynthetic),
    owner_id: row.ownerId,
    parser_json: parserJson,
    parser_view: adaptDocumentParserResult(parserJson),
    latest_extraction: currentRun ? JSON.parse(currentRun.payload) : null,
    latest_run_status: latest?.status ?? null,
    latest_run_error: latest?.error ? JSON.parse(latest.error) : null,
    extraction_version: row.extractionVersion,
    input_version: row.inputVersion,
    input_hash: inputHash,
  };
}

export async function getExtractionHistory(documentId: string, ownerId?: string | null) {
  const db = getDb();
  const runOwnerScope = ownerId ? or(isNull(extractionRuns.ownerId), eq(extractionRuns.ownerId, ownerId)) : isNull(extractionRuns.ownerId);
  const rows = await db.select({ id: extractionRuns.id, version: extractionRuns.version, documentType: extractionRuns.documentType, schemaVersion: extractionRuns.schemaVersion, inputVersion: extractionRuns.inputVersion, inputHash: extractionRuns.inputHash, mode: extractionRuns.mode, status: extractionRuns.status, model: extractionRuns.model, provider: extractionRuns.provider, error: extractionRuns.error, createdAt: extractionRuns.createdAt })
    .from(extractionRuns).where(and(eq(extractionRuns.documentId, documentId), runOwnerScope)).orderBy(desc(extractionRuns.version));
  return rows.map((row) => ({ id: row.id, version: row.version, document_type: row.documentType, schema_version: row.schemaVersion, input_version: row.inputVersion, input_hash: row.inputHash, mode: row.mode, status: row.status, model: row.model, provider: row.provider, error: row.error ? JSON.parse(row.error) : null, created_at: row.createdAt }));
}

export async function getExtraction(extractionId: string, ownerId?: string | null) {
  const db = getDb();
  const visibility = ownerId ? or(eq(documents.isDemo, true), eq(documents.ownerId, ownerId)) : eq(documents.isDemo, true);
  const runOwnerScope = ownerId ? or(isNull(extractionRuns.ownerId), eq(extractionRuns.ownerId, ownerId)) : isNull(extractionRuns.ownerId);
  const [row] = await db.select({ payload: extractionRuns.payload }).from(extractionRuns)
    .innerJoin(documents, eq(extractionRuns.documentId, documents.id))
    .where(and(eq(extractionRuns.id, extractionId), visibility, runOwnerScope)).limit(1);
  return row ? JSON.parse(row.payload) : null;
}

