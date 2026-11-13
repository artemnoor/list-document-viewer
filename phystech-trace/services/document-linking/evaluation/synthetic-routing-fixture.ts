import { readFileSync } from "node:fs";

export const gold: any = JSON.parse(readFileSync("evaluation/synthetic-routing-gold.json", "utf8"));
const value = (documentId: string, rowId: string | undefined, text: string, tableId?: string, columnIndex?: number) => ({
  value: text, source_value: text, status: "extracted", confidence: 0.99,
  provenance: { document_id: documentId, source_ref: `#/source/${rowId ?? "fields"}`, source_text: text, source_available: true, ...(rowId ? { row_id: rowId } : {}), ...(tableId ? { table_id: tableId } : {}), ...(columnIndex !== undefined ? { column_index: columnIndex } : {}) },
});
const line = (documentId: string, rowId: string, description: string) => {
  const item = (text: string, column: number) => value(documentId, rowId, text, "lines", column);
  return { row_id: rowId, line_number: item(rowId, 0), identifier: item("", 1), description: item(description, 2), unit: item("шт.", 3), quantity: item("1", 4), plan_quantity: item("1", 5), actual_quantity: item("1", 6), unit_price: item("1250000", 7), amount: item("1250000", 8), row_status: "extracted", source_cells: [{ header: "Описание", extracted: item(description, 2) }] };
};
const longContext = "Дополнительные условия и сведения о страницах исходного документа. ".repeat(40);
const document = (id: string, type: string, fields: Record<string, any>, rows: any[] = []) => ({
  extraction_id: `${id}-extraction`, document_id: id, version: 1, schema_version: "1.2.0", extracted_at: "2026-11-13T00:00:00.000Z",
  classification: { type, label: type, confidence: 0.99, status: "classified" },
  extraction_engine: { rules_executed: true, llm: { provider: "not_called", model: null, called: false, response_validated: false, duration_ms: null, usage: null, validation_status: "not_run", error: null }, parser_adapter: "synthetic-test" },
  mode: "rules_only", fields: Object.fromEntries(Object.entries({ ...fields, context_note: longContext }).map(([key, text]) => [key, { label: key, ...value(id, undefined, String(text)) }])),
  tables: rows.length ? [{ id: "lines", title: "Строки", role: "line_items", headers: ["Описание"], rows }] : [], indicators: [], missing_fields: [], review_required: [],
});

export const documents: any[] = [
  document("contract-A", "contract", { subject: "Договор A: поставка оптического стенда", amount: "1 250 000 рублей" }),
  document("contract-B", "contract", { subject: "Договор B: поставка криостата", amount: "1 250 000 рублей" }),
  document("invoice-A", "invoice", { basis: "Счет INV-A по договору A, оптический стенд", amount: "1 250 000 рублей", invoice_number: "INV-A" }, [line("invoice-A", "invoice-line-A", "Оптический стенд по договору A")]),
  document("invoice-B", "invoice", { basis: "Счет INV-B по договору B, криостат", amount: "1 250 000 рублей", invoice_number: "INV-B" }, [line("invoice-B", "invoice-line-B", "Криостат по договору B")]),
  document("registry", "registry", { title: "Реестр двух отдельных оплат" }, [line("registry", "registry-payment-A", "Оплата INV-A по договору A за оптический стенд"), line("registry", "registry-payment-B", "Оплата INV-B по договору B за криостат")]),
];

export const systemPrompt = "Определи фактические связи между оригинальными документами и строками. Ссылайся только на исходные reference_id.";
