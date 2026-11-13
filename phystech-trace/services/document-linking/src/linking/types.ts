import type { Extraction } from "../contracts/input";
import type { InvalidRelationshipDiagnostic } from "./evidence-validation";
export type LinkStatus = "confirmed" | "proposed" | "review" | "rejected";
export type RelationshipType = string;
export type Evidence = { source: { document_id: string; path: string; raw_value: unknown; normalized_value: string; provenance: unknown }; target: { document_id: string; path: string; raw_value: unknown; normalized_value: string; provenance: unknown }; signal: string; explanation: string };
export type Link = { link_id: string; relationship_type: RelationshipType; source_document_id: string; target_document_id: string; source_row_id?: string; target_row_id?: string; evidence: Evidence[]; explanation: string; confidence: number; status: LinkStatus; verification_status: "not_reviewed" | "human_confirmed" | "human_rejected"; detection_method: "llm"; conflicts: string[]; alternatives?: string[] };
export type AnalysisProgressState = { version: 1 | 2; started_at: string; fragment_budget_tokens: number; phase?: "reading_documents" | "resolving_relationships" | "reviewing_requested_source"; total_fragments?: number; completed_fragments: { document_id: string; chunk_index: number; summary: unknown }[]; requested_source_fragments?: { document_id: string; chunk_index: number; reason: string; paths: string[]; fragment: unknown }[]; context_rounds?: number; calls: number; input_tokens: number; output_tokens: number; cost_amount: number; cost_currency?: string | null; has_cost: boolean };
export type LinkingResult = {
  linking_run_id: string;
  contract_version: string;
  created_at: string;
  input_documents: { document_id: string; extraction_id: string; document_type: string; version: number; schema_version: string; input_version?: number; input_hash?: string }[];
  links: Link[];
  review_required: { link_id: string; reason: string; candidate_document_ids: string[] }[];
  unlinked_documents: { document_id: string; reason: string }[];
  warnings: string[];
  link_validation_diagnostics: Array<Omit<InvalidRelationshipDiagnostic, "evidence_issues"> & {
    reasons: { code: string; message: string }[];
    evidence_issues: { evidence_index: number; reason_codes: string[]; reasons: string[]; source_path?: string; target_path?: string }[];
  }>;
  analysis_summary: string;
  processing_metadata: {
    engine_version: string;
    llm: { enabled: boolean; provider: string; model: string; strategy: "full_set" | "document_fragments_then_full_set"; estimated_input_tokens: number; calls: number; errors: number; input_tokens?: number; output_tokens?: number; cost_amount?: number | null; cost_currency?: string | null; duration_ms?: number };
    duration_ms: number;
  };
};
export type MatcherOptions = { llm?: { enabled: boolean; apiKey?: string; maxCalls?: number; maxEvidenceCorrectionAttempts?: number; timeoutMs?: number; maxRunMs?: number; model?: string; maxInputTokens?: number; systemPrompt?: string; resumeProgress?: AnalysisProgressState; onProgress?: (state: AnalysisProgressState) => Promise<void> } };
export type IndexedDocument = { extraction: Extraction; values: Record<string, any>; rows: { row: any; path: string; role: string; aliases: string[] }[] };
