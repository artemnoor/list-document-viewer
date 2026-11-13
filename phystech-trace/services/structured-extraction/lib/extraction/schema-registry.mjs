import { z } from "zod";

export const extractionValueSchema = z.object({
  label: z.string().optional(),
  value: z.unknown().nullable(),
  source_value: z.string().nullable(),
  status: z.enum(["extracted", "review", "missing"]),
  confidence: z.number().min(0).max(1).nullable(),
  provenance: z.object({
    document_id: z.string(),
    source_part_id: z.string().optional(),
    source_ref: z.string().optional(),
    page_no: z.number().nullable().optional(),
    sheet_name: z.string().nullable().optional(),
    cell_address: z.string().nullable().optional(),
    bbox: z.object({ l: z.number(), t: z.number(), r: z.number(), b: z.number(), coord_origin: z.string().optional() }).nullable().optional(),
    coordinate_origin: z.string().nullable().optional(),
    page_size: z.object({ width: z.number(), height: z.number(), unit: z.string() }).nullable().optional(),
    table_id: z.string().optional(),
    row_id: z.string().optional(),
    column_index: z.number().optional(),
    source_text: z.string(),
    confidence: z.number().min(0).max(1).nullable().optional(),
    source_available: z.boolean().optional(),
    provenance_alternates: z.array(z.object({ page_no: z.number().nullable().optional(), bbox: z.unknown().nullable().optional(), coordinate_origin: z.string().nullable().optional(), source_ref: z.string().nullable().optional() })).optional(),
  }).nullable(),
  normalization_note: z.string().nullable().optional(),
  source_method: z.enum(["rules", "llm", "consensus", "conflict"]).optional(),
  conflict: z.object({ reason: z.string(), rules: z.unknown(), llm: z.unknown() }).optional(),
  corroborated_by: z.string().optional(),
});

const cellSchema = z.object({ header: z.string(), extracted: extractionValueSchema });
const lineItemSchema = z.object({
  row_id: z.string(),
  line_number: extractionValueSchema,
  identifier: extractionValueSchema,
  description: extractionValueSchema,
  unit: extractionValueSchema,
  quantity: extractionValueSchema,
  plan_quantity: extractionValueSchema,
  actual_quantity: extractionValueSchema,
  unit_price: extractionValueSchema,
  amount: extractionValueSchema,
  source_cells: z.array(cellSchema),
  row_status: z.enum(["extracted", "review", "missing"]),
});
const extractedTableSchema = z.object({
  id: z.string(),
  title: z.string(),
  role: z.string(),
  headers: z.array(z.string()),
  rows: z.array(lineItemSchema),
  repeated_header_rows: z.array(lineItemSchema).optional(),
  summary_rows: z.array(lineItemSchema).optional(),
  empty_rows: z.array(lineItemSchema).optional(),
  role_source: z.string().optional(),
  source: z.unknown().optional(),
});

const amendmentSchema = z.object({
  row_id: z.string(),
  parameter: extractionValueSchema,
  old_value: extractionValueSchema,
  new_value: extractionValueSchema,
  reason: extractionValueSchema,
  source_cells: z.array(cellSchema),
  row_status: z.enum(["extracted", "review", "missing"]),
});

const fieldRecord = z.record(z.string(), extractionValueSchema);
const baseShape = {
  extraction_id: z.string(),
  document_id: z.string(),
  version: z.number().int().positive(),
  schema_version: z.string(),
  extracted_at: z.string(),
  classification: z.object({ type: z.string(), label: z.string(), confidence: z.number().min(0).max(1).nullable(), status: z.enum(["classified", "review"]) }),
  extraction_engine: z.object({
    rules_executed: z.boolean(),
    llm: z.object({ provider: z.string(), model: z.string().nullable(), called: z.boolean(), response_validated: z.boolean(), duration_ms: z.number().nullable().optional(), usage: z.unknown().nullable().optional(), validation_status: z.string().optional(), error: z.unknown().nullable().optional() }),
    parser_adapter: z.string(),
  }),
  mode: z.enum(["rules_only", "llm_assisted", "compare"]),
  fields: fieldRecord,
  tables: z.array(extractedTableSchema),
  indicators: z.array(z.object({ key: z.string(), label: z.string(), extracted: extractionValueSchema })),
  missing_fields: z.array(z.string()),
  review_required: z.array(z.object({ path: z.string(), reason: z.string(), source_value: z.string().nullable(), provenance: extractionValueSchema.shape.provenance })),
};

export const documentSchemas = {
  kfz_report: z.object({ ...baseShape, document_type: z.literal("kfz_report"), line_items: z.array(lineItemSchema) }),
  contract: z.object({ ...baseShape, document_type: z.literal("contract"), payment_schedule: z.array(lineItemSchema) }),
  act: z.object({ ...baseShape, document_type: z.literal("act"), line_items: z.array(lineItemSchema) }),
  invoice: z.object({ ...baseShape, document_type: z.literal("invoice"), line_items: z.array(lineItemSchema) }),
  addendum: z.object({ ...baseShape, document_type: z.literal("addendum"), changes: z.array(amendmentSchema) }),
  registry: z.object({ ...baseShape, document_type: z.literal("registry"), line_items: z.array(lineItemSchema) }),
  unknown: z.object({ ...baseShape, document_type: z.literal("unknown"), line_items: z.array(lineItemSchema) }),
};

export const schemaRegistry = Object.freeze({
  kfz_report: { label: "Отчёт КФЗ", version: "1.2.0", schema: documentSchemas.kfz_report },
  contract: { label: "Договор", version: "1.2.0", schema: documentSchemas.contract },
  act: { label: "Акт", version: "1.2.0", schema: documentSchemas.act },
  invoice: { label: "Счёт", version: "1.2.0", schema: documentSchemas.invoice },
  addendum: { label: "Дополнительное соглашение", version: "1.2.0", schema: documentSchemas.addendum },
  registry: { label: "Реестр", version: "1.2.0", schema: documentSchemas.registry },
  unknown: { label: "Тип не определён", version: "1.2.0", schema: documentSchemas.unknown },
});

export function validateExtraction(type, value) {
  const registered = schemaRegistry[type];
  if (!registered) throw new Error(`No extraction schema registered for ${type}`);
  return registered.schema.parse(value);
}
