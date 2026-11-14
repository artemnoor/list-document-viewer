export type StageName = "parser" | "extraction" | "linking" | "reconciliation" | "verification";
export type StageState = { status: string; completed: number; total: number; mode?: string; warning?: string | null; error?: { code?: string; message?: string } | null };
export type TraceDocument = {
  id: string; role: "kfz" | "primary"; file_name: string; document_id: string; parser_state: string;
  parser_error?: { code?: string; message?: string } | null; has_parser_result: boolean;
  extraction_id?: string | null; document_type?: string | null; extraction_error?: { code?: string; message?: string } | null;
  source_url: string;
};
export type EvidenceSide = { document_id: string; path?: string; raw_value?: unknown; normalized_value?: string; provenance?: Provenance | null };
export type Provenance = {
  document_id?: string; source_part_id?: string; source_ref?: string; page_no?: number | null;
  sheet_name?: string | null; cell_address?: string | null; bbox?: { l: number; t: number; r: number; b: number; coord_origin?: string } | null;
  coordinate_origin?: string | null; page_size?: { width: number; height: number; unit?: string } | null;
  table_id?: string; row_id?: string; column_index?: number; source_text?: string;
};
export type LinkEvidence = { source: EvidenceSide; target: EvidenceSide; signal: string; explanation: string };
export type TraceLink = {
  link_id: string; relationship_type: string; source_document_id: string; target_document_id: string;
  source_row_id?: string; target_row_id?: string; evidence: LinkEvidence[]; explanation: string;
  confidence: number; status: string; verification_status: string; conflicts: string[];
};
export type LinkingResult = { linking_run_id: string; links: TraceLink[]; review_required: { link_id: string; reason: string; candidate_document_ids: string[] }[]; unlinked_documents: { document_id: string; reason: string }[]; warnings: string[]; analysis_summary: string };
export type TraceProject = {
  id: string; name: string; data_classification: "confidential" | "public" | "synthetic" | "anonymized";
  allow_external_llm: boolean; status: string; created_at: string; updated_at: string;
  stages: Record<StageName, StageState>; last_error?: { code?: string; message?: string } | null;
  reconciliation_result?: Record<string, any> | null; verification_result?: Record<string, any> | null; linking_job_id?: string | null; linking_result?: LinkingResult | null; documents: TraceDocument[];
};
export type DocumentResult = { parser_result?: Record<string, any> | null; extraction?: Record<string, any> | null; parser_error?: { code?: string; message?: string } | null; extraction_error?: { code?: string; message?: string } | null };
