import { z } from "zod";

// Mirrors Structured Extraction schema-registry.mjs 1.2.0. .passthrough() permits additive
// upstream fields while all fields used by this service retain their upstream names and types.
export const provenanceSchema = z.object({
  document_id: z.string(), source_part_id: z.string().optional(), source_ref: z.string().optional(),
  page_no: z.number().nullable().optional(), sheet_name: z.string().nullable().optional(),
  cell_address: z.string().nullable().optional(),
  bbox: z.object({ l: z.number(), t: z.number(), r: z.number(), b: z.number(), coord_origin: z.string().optional() }).passthrough().nullable().optional(),
  coordinate_origin: z.string().nullable().optional(),
  page_size: z.object({ width: z.number(), height: z.number(), unit: z.string() }).passthrough().nullable().optional(),
  table_id: z.string().optional(), row_id: z.string().optional(), column_index: z.number().optional(),
  source_text: z.string(), confidence: z.number().min(0).max(1).nullable().optional(), source_available: z.boolean().optional(),
  provenance_alternates: z.array(z.object({ page_no: z.number().nullable().optional(), bbox: z.unknown().nullable().optional(), coordinate_origin: z.string().nullable().optional(), source_ref: z.string().nullable().optional() }).passthrough()).optional(),
}).passthrough();

export const extractionValueSchema = z.object({ label: z.string().optional(), value: z.unknown().nullable(), source_value: z.string().nullable(), status: z.enum(["extracted", "review", "missing"]), confidence: z.number().min(0).max(1).nullable(), provenance: provenanceSchema.nullable(), normalization_note: z.string().nullable().optional(), source_method: z.enum(["rules", "llm", "consensus", "conflict"]).optional(), conflict: z.object({ reason: z.string(), rules: z.unknown(), llm: z.unknown() }).optional(), corroborated_by: z.string().optional() }).passthrough();
const cellSchema = z.object({ header: z.string(), extracted: extractionValueSchema }).passthrough();
export const lineItemSchema = z.object({ row_id: z.string(), line_number: extractionValueSchema, identifier: extractionValueSchema, description: extractionValueSchema, unit: extractionValueSchema, quantity: extractionValueSchema, plan_quantity: extractionValueSchema, actual_quantity: extractionValueSchema, unit_price: extractionValueSchema, amount: extractionValueSchema, source_cells: z.array(cellSchema), row_status: z.enum(["extracted", "review", "missing"]) }).passthrough();
const tableSchema = z.object({ id: z.string(), title: z.string(), role: z.string(), headers: z.array(z.string()), rows: z.array(lineItemSchema), repeated_header_rows: z.array(lineItemSchema).optional(), summary_rows: z.array(lineItemSchema).optional(), empty_rows: z.array(lineItemSchema).optional(), role_source: z.string().optional(), source: z.unknown().optional() }).passthrough();
const changeSchema = z.object({ row_id: z.string(), parameter: extractionValueSchema, old_value: extractionValueSchema, new_value: extractionValueSchema, reason: extractionValueSchema, source_cells: z.array(cellSchema), row_status: z.enum(["extracted", "review", "missing"]) }).passthrough();
const classificationSchema = z.object({ type: z.string(), label: z.string(), confidence: z.number().min(0).max(1).nullable(), status: z.enum(["classified", "review"]) }).passthrough();
const reviewSchema = z.object({ path: z.string(), reason: z.string(), source_value: z.string().nullable(), provenance: provenanceSchema.nullable() }).passthrough();
const modelRunSchema = z.object({ provider: z.string(), model: z.string().nullable(), called: z.boolean(), response_validated: z.boolean(), duration_ms: z.number().nullable().optional(), usage: z.unknown().nullable().optional(), validation_status: z.string().optional(), error: z.unknown().nullable().optional() }).passthrough();
const extractionEngineSchema = z.object({ rules_executed: z.boolean(), llm: modelRunSchema, parser_adapter: z.string() }).passthrough();
const base = { extraction_id: z.string(), document_id: z.string(), version: z.number().int().positive(), schema_version: z.string(), extracted_at: z.string(), classification: classificationSchema, extraction_engine: extractionEngineSchema, mode: z.enum(["rules_only", "llm_assisted", "compare"]), fields: z.record(z.string(), extractionValueSchema), tables: z.array(tableSchema), indicators: z.array(z.object({ key: z.string(), label: z.string(), extracted: extractionValueSchema }).passthrough()), missing_fields: z.array(z.string()), review_required: z.array(reviewSchema) };
export const extractionSchemas = {
  kfz_report: z.object({ ...base, document_type: z.literal("kfz_report"), line_items: z.array(lineItemSchema) }).passthrough(),
  contract: z.object({ ...base, document_type: z.literal("contract"), payment_schedule: z.array(lineItemSchema) }).passthrough(),
  act: z.object({ ...base, document_type: z.literal("act"), line_items: z.array(lineItemSchema) }).passthrough(),
  invoice: z.object({ ...base, document_type: z.literal("invoice"), line_items: z.array(lineItemSchema) }).passthrough(),
  addendum: z.object({ ...base, document_type: z.literal("addendum"), changes: z.array(changeSchema) }).passthrough(),
  registry: z.object({ ...base, document_type: z.literal("registry"), line_items: z.array(lineItemSchema) }).passthrough(),
  unknown: z.object({ ...base, document_type: z.literal("unknown"), line_items: z.array(lineItemSchema) }).passthrough(),
} as const;
export const extractionSchema = z.discriminatedUnion("document_type", Object.values(extractionSchemas) as [typeof extractionSchemas[keyof typeof extractionSchemas], ...typeof extractionSchemas[keyof typeof extractionSchemas][]]);
export const inputBatchSchema = z.array(z.unknown()).min(1, "Передайте хотя бы один результат Structured Extraction");
export type Extraction = z.infer<typeof extractionSchema>;

export function validateInput(raw: unknown) {
  const batch = inputBatchSchema.safeParse(raw);
  if (!batch.success) return { success: false as const, diagnostics: batch.error.issues.map(i => ({ path: i.path.join("."), message: i.message })) };
  const documents: Extraction[] = [], diagnostics: { index: number; document_id?: string; path: string; message: string }[] = [];
  batch.data.forEach((item, index) => {
    const wrapped = item && typeof item === "object" && "extraction" in item ? (item as { extraction: unknown }).extraction : item;
    const result = extractionSchema.safeParse(wrapped);
    if (result.success) {
      const [major, minor] = result.data.schema_version.split(".").map(Number);
      if (major !== 1 || !Number.isFinite(minor) || minor < 2) diagnostics.push({ index, document_id: result.data.document_id, path: "schema_version", message: `Несовместимая версия ${result.data.schema_version}; поддерживается 1.2.x и совместимые добавочные версии 1.x` });
      else documents.push(result.data);
    }
    else result.error.issues.forEach(issue => diagnostics.push({ index, document_id: (wrapped as any)?.document_id, path: issue.path.join("."), message: issue.message }));
  });
  const seen = new Set<string>();
  documents.forEach(d => { if (seen.has(d.document_id)) diagnostics.push({ index: -1, document_id: d.document_id, path: "document_id", message: "В пакете повторяется document_id; передавайте одну версию результата на документ" }); seen.add(d.document_id); });
  return diagnostics.length ? { success: false as const, diagnostics } : { success: true as const, documents };
}
