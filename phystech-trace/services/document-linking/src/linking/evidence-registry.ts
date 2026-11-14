import type { Extraction } from "../contracts/input";
import type { Evidence } from "./types";
import type { EvidenceIssueCode } from "./evidence-validation";

export type EvidenceReference = {
  reference_id: string;
  document_id: string;
  json_path: string;
  raw_value: unknown;
  source_value?: unknown;
  normalized_value: string;
  row_id?: string;
  provenance: Record<string, unknown> | null;
  location: { ancestors: string[]; path: string };
};

function pathJoin(parent: string, key: string | number): string {
  return typeof key === "number" ? `${parent}[${key}]` : parent ? `${parent}.${key}` : key;
}

function normalize(value: unknown): string {
  if (typeof value === "string") return value.normalize("NFKC").replace(/[\u200B-\u200D\u2060\uFEFF]/g, "").replace(/[\u00A0\u202F]/g, " ").replace(/\s+/gu, " ").trim();
  if (value === null) return "null";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function metadataFor(ancestors: { path: string; value: Record<string, unknown> }[]): { provenance: Record<string, unknown> | null; source_value?: unknown; row_id?: string } {
  let provenance: Record<string, unknown> | null = null;
  let source_value: unknown;
  let row_id: string | undefined;
  for (let index = ancestors.length - 1; index >= 0; index--) {
    const value = ancestors[index].value;
    if (!provenance && value.provenance && typeof value.provenance === "object" && !Array.isArray(value.provenance)) provenance = value.provenance as Record<string, unknown>;
    if (source_value === undefined && value.source_value !== undefined) source_value = value.source_value;
    if (!row_id && typeof value.row_id === "string") row_id = value.row_id;
  }
  return { provenance, ...(source_value !== undefined ? { source_value } : {}), ...(row_id ? { row_id } : {}) };
}

/** Build stable, unique references for every JSON scalar without interpreting document semantics. */
export function buildEvidenceRegistry(documents: Extraction[]): EvidenceReference[] {
  const references: EvidenceReference[] = [];
  for (const document of documents) {
    const visit = (value: unknown, path: string, ancestors: { path: string; value: Record<string, unknown> }[]) => {
      if (Array.isArray(value)) {
        value.forEach((item, index) => visit(item, pathJoin(path, index), ancestors));
        return;
      }
      if (value && typeof value === "object") {
        const object = value as Record<string, unknown>;
        const next = [...ancestors, { path, value: object }];
        for (const [key, child] of Object.entries(object)) {
          // Provenance is attached to the cited value below; indexing its internal metadata
          // as separate candidate evidence would create duplicate, misleading references.
          if (key === "provenance") continue;
          visit(child, pathJoin(path, key), next);
        }
        return;
      }
      if (!path) return;
      const reference_id = `r${(references.length + 1).toString(36)}`;
      const metadata = metadataFor(ancestors);
      references.push({
        reference_id,
        document_id: document.document_id,
        json_path: path,
        raw_value: value,
        ...(metadata.source_value !== undefined ? { source_value: metadata.source_value } : {}),
        normalized_value: normalize(value),
        ...(metadata.row_id ? { row_id: metadata.row_id } : {}),
        provenance: metadata.provenance,
        location: { ancestors: ancestors.map(item => item.path).filter(Boolean), path },
      });
    };
    visit(document, "", []);
  }
  return references;
}

function comparableText(value: string): string {
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

export function resolveEvidenceReference(reference: EvidenceReference | undefined, expectedDocumentId: string): { valid: boolean; evidence?: Evidence["source"]; issues: EvidenceIssueCode[]; warnings: EvidenceIssueCode[] } {
  if (!reference) return { valid: false, issues: ["evidence_reference_not_found"], warnings: [] };
  if (reference.document_id !== expectedDocumentId) return { valid: false, issues: ["evidence_reference_document_mismatch"], warnings: [] };
  if (!reference.provenance || reference.provenance.document_id !== expectedDocumentId || reference.provenance.source_available === false || typeof reference.provenance.source_text !== "string" || !reference.provenance.source_text.trim()) {
    return { valid: false, issues: [!reference.provenance ? "provenance_missing" : reference.provenance.document_id !== expectedDocumentId ? "provenance_document_mismatch" : reference.provenance.source_available === false ? "source_unavailable" : "source_text_missing"], warnings: [] };
  }
  const sourceText = comparableText(reference.provenance.source_text);
  const sourceCandidates = [reference.source_value, reference.raw_value]
    .filter((value): value is string => typeof value === "string" && value.length > 0)
    .map(comparableText);
  const warnings: EvidenceIssueCode[] = sourceCandidates.length > 0 && !sourceCandidates.some(value => sourceText.includes(value)) ? ["source_text_value_mismatch"] : [];
  return {
    valid: true,
    evidence: {
      document_id: reference.document_id,
      path: reference.json_path,
      raw_value: reference.raw_value,
      normalized_value: reference.normalized_value,
      provenance: reference.provenance,
    },
    issues: [],
    warnings,
  };
}
