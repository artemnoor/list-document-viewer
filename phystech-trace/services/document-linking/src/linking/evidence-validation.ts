import type { Extraction } from "../contracts/input";
import type { Evidence } from "./types";

export type EvidenceIssueCode = "invalid_document_reference" | "invalid_link_metadata" | "evidence_source_direction_mismatch" | "unsafe_or_invalid_json_path" | "json_path_not_found" | "raw_value_mismatch" | "evidence_reference_not_found" | "evidence_reference_document_mismatch" | "provenance_missing" | "provenance_document_mismatch" | "source_unavailable" | "source_text_missing" | "source_text_value_mismatch" | "row_id_not_found" | "row_id_not_cited_by_path" | "row_provenance_mismatch";
export type InvalidRelationshipDiagnostic = { proposal_index: number; relationship_type?: string; source_document_id?: string; target_document_id?: string; candidate_status?: "review"; reason_codes: EvidenceIssueCode[]; evidence_issues: { evidence_index: number; reason_codes: EvidenceIssueCode[]; source_path?: string; target_path?: string; source_reference_id?: string; target_reference_id?: string }[]; proposal: unknown; resolution?: "corrected" | "withdrawn" | "unresolved" | "review_required"; corrected_proposal?: unknown; current_proposal?: unknown; correction_attempts?: number };
export type EvidenceValidation = { valid: boolean; evidence?: Evidence["source"]; reasons: EvidenceIssueCode[]; warnings: EvidenceIssueCode[] };
type PathSegment = string | number;

function parseJsonPath(path: string): PathSegment[] | null {
  if (!path || path.length > 2048) return null;
  const parts: PathSegment[] = [];
  let index = 0;
  while (index < path.length) {
    if (path[index] === ".") index++;
    if (index >= path.length) return null;
    if (path[index] === "[") {
      const end = path.indexOf("]", index + 1);
      if (end < 0) return null;
      const number = path.slice(index + 1, end);
      if (!/^\d+$/.test(number)) return null;
      parts.push(Number(number)); index = end + 1;
    } else {
      const start = index;
      while (index < path.length && path[index] !== "." && path[index] !== "[") index++;
      if (start === index) return null;
      parts.push(path.slice(start, index));
    }
  }
  if (!parts.length || parts.some(part => typeof part === "string" && ["__proto__", "prototype", "constructor"].includes(part))) return null;
  return parts;
}

function ownGet(value: unknown, segment: PathSegment): unknown {
  if (!value || typeof value !== "object") return undefined;
  if (Array.isArray(value)) return typeof segment === "number" && Object.prototype.hasOwnProperty.call(value, segment) ? value[segment] : undefined;
  if (typeof segment !== "string" || !Object.prototype.hasOwnProperty.call(value, segment)) return undefined;
  return (value as Record<string, unknown>)[segment];
}

export function resolveJsonPath(doc: unknown, path: string): unknown {
  const segments = parseJsonPath(path);
  if (!segments) return undefined;
  let value: unknown = doc;
  for (const segment of segments) {
    value = ownGet(value, segment);
    if (value === undefined) return undefined;
  }
  return value;
}

function entryValue(entry: unknown): unknown {
  if (entry && typeof entry === "object" && (Object.prototype.hasOwnProperty.call(entry, "value") || Object.prototype.hasOwnProperty.call(entry, "source_value"))) {
    const object = entry as Record<string, unknown>;
    return object.value ?? object.source_value ?? null;
  }
  return entry;
}

function provenanceFor(doc: Extraction, path: string, value: unknown): Record<string, any> | null {
  if (value && typeof value === "object" && Object.prototype.hasOwnProperty.call(value, "provenance")) {
    const provenance = ownGet(value, "provenance");
    return provenance && typeof provenance === "object" ? provenance as Record<string, any> : null;
  }
  const parentPath = path.replace(/\.(value|source_value)$/, "");
  if (parentPath === path) return null;
  const parent = resolveJsonPath(doc, parentPath);
  const provenance = parent && typeof parent === "object" ? ownGet(parent, "provenance") : null;
  return provenance && typeof provenance === "object" ? provenance as Record<string, any> : null;
}

function sameJsonValue(left: unknown, right: unknown): boolean {
  if (Object.is(left, right)) return true;
  try { return JSON.stringify(left) === JSON.stringify(right); } catch { return false; }
}

export function pathContainsRowId(doc: Extraction, path: string, rowId: string): boolean {
  const segments = parseJsonPath(path);
  if (!segments) return false;
  let value: unknown = doc;
  for (const segment of segments) {
    value = ownGet(value, segment);
    if (value === undefined) return false;
    if (value && typeof value === "object" && ownGet(value, "row_id") === rowId) return true;
  }
  return false;
}

export function rowIdExists(doc: Extraction, rowId: string): boolean {
  const seen = new Set<object>();
  const visit = (value: unknown): boolean => {
    if (!value || typeof value !== "object" || seen.has(value)) return false;
    seen.add(value);
    if (!Array.isArray(value) && ownGet(value, "row_id") === rowId) return true;
    return Object.keys(value).some(key => visit((value as Record<string, unknown>)[key]));
  };
  return visit(doc);
}

function normalizeSourceText(value: string): string {
  return value.normalize("NFKC")
    .replace(/[\u200B-\u200D\u2060\uFEFF]/g, "")
    .replace(/[‐‑‒–—−]/g, "-")
    .replace(/[“”„]/g, '"').replace(/[‘’]/g, "'")
    .replace(/[\u00A0\u202F]/g, " ")
    .toLocaleLowerCase("und")
    .replace(/\s+/gu, " ")
    .replace(/\s*([\-./,:;])\s*/gu, "$1")
    .trim();
}

export function validateEvidenceSide(args: { document: Extraction; expectedDocumentId: string; reportedDocumentId: unknown; path: unknown; rawValue: unknown; rowId?: string }): EvidenceValidation {
  const reasons: EvidenceIssueCode[] = [];
  const warnings: EvidenceIssueCode[] = [];
  if (args.reportedDocumentId !== args.expectedDocumentId) reasons.push("evidence_source_direction_mismatch");
  if (typeof args.path !== "string" || !parseJsonPath(args.path)) return { valid: false, reasons: [...reasons, "unsafe_or_invalid_json_path"], warnings };
  const value = resolveJsonPath(args.document, args.path);
  if (value === undefined) reasons.push("json_path_not_found");
  const rawValue = entryValue(value);
  if (value !== undefined && !sameJsonValue(rawValue, args.rawValue)) reasons.push("raw_value_mismatch");
  const provenance = value === undefined ? null : provenanceFor(args.document, args.path, value);
  const extractionPath = args.path.replace(/\.(value|source_value)$/, "");
  const extractionEntry = extractionPath !== args.path ? resolveJsonPath(args.document, extractionPath) : value;
  if (!provenance) reasons.push("provenance_missing");
  else {
    if (provenance.document_id !== args.expectedDocumentId) reasons.push("provenance_document_mismatch");
    if (provenance.source_available === false) reasons.push("source_unavailable");
    if (typeof provenance.source_text !== "string" || provenance.source_text.trim().length === 0) reasons.push("source_text_missing");
    const sourceValue = extractionEntry && typeof extractionEntry === "object" ? ownGet(extractionEntry, "source_value") : undefined;
    if (provenance.source_available !== false && typeof sourceValue === "string" && sourceValue.length > 0 && typeof provenance.source_text === "string" && !normalizeSourceText(provenance.source_text).includes(normalizeSourceText(sourceValue))) warnings.push("source_text_value_mismatch");
    if (args.rowId && provenance.row_id && provenance.row_id !== args.rowId) reasons.push("row_provenance_mismatch");
  }
  if (args.rowId) {
    if (!rowIdExists(args.document, args.rowId)) reasons.push("row_id_not_found");
    if (!pathContainsRowId(args.document, args.path, args.rowId)) reasons.push("row_id_not_cited_by_path");
  }
  if (reasons.length) return { valid: false, reasons, warnings };
  const normalized = args.path.endsWith(".value") || args.path.endsWith(".source_value") ? resolveJsonPath(args.document, args.path.replace(/\.(value|source_value)$/, "")) : value;
  const normalizedValue = normalized && typeof normalized === "object" ? (normalized as any).value ?? (normalized as any).source_value ?? rawValue : rawValue;
  return { valid: true, reasons, warnings, evidence: { document_id: args.expectedDocumentId, path: args.path, raw_value: rawValue, normalized_value: typeof normalizedValue === "string" ? normalizedValue : JSON.stringify(normalizedValue), provenance } };
}

export function explainEvidenceIssue(code: EvidenceIssueCode): string {
  const messages: Record<EvidenceIssueCode, string> = {
    invalid_document_reference: "связь ссылается на отсутствующий документ или связывает документ с самим собой",
    invalid_link_metadata: "ответ содержит некорректный тип связи, статус или уверенность",
    evidence_source_direction_mismatch: "доказательство относится не к указанному source/target этой связи",
    unsafe_or_invalid_json_path: "JSON-путь повреждён или содержит небезопасные свойства",
    json_path_not_found: "JSON-путь отсутствует в исходном документе",
    raw_value_mismatch: "raw_value не совпадает со значением по указанному JSON-пути",
    evidence_reference_not_found: "reference_id отсутствует в реестре исходных доказательств",
    evidence_reference_document_mismatch: "reference_id относится к другому документу, чем указанная сторона связи",
    provenance_missing: "для значения отсутствует provenance",
    provenance_document_mismatch: "provenance указывает на другой документ",
    source_unavailable: "исходный фрагмент помечен как недоступный",
    source_text_missing: "в provenance нет доступного исходного текста",
    source_text_value_mismatch: "source_value не удалось технически подтвердить в исходном тексте после нормализации; требуется ручная проверка",
    row_id_not_found: "указанный row_id отсутствует в этом документе",
    row_id_not_cited_by_path: "JSON-путь доказательства не проходит через указанную строку",
    row_provenance_mismatch: "provenance строки указывает на другой row_id",
  };
  return messages[code];
}
