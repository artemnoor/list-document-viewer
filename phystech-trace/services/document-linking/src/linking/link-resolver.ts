import type { LinkingResult, MatcherOptions } from "./types";
import { analyzeDocumentSet, GEMMA_MODEL } from "./llm-matcher";
import { validateInput } from "../contracts/input";
import { OUTPUT_CONTRACT_VERSION } from "../contracts/registry";
import { explainEvidenceIssue } from "./evidence-validation";

export async function linkDocuments(raw: unknown, options: MatcherOptions = {}): Promise<LinkingResult> {
  const started = Date.now(), checked = validateInput(raw);
  if (!checked.success) throw Object.assign(new Error("Входные данные не соответствуют контракту Structured Extraction 1.2.0"), { status: 422, diagnostics: checked.diagnostics });
  if (!options.llm?.enabled || !options.llm.apiKey) throw Object.assign(new Error("LLM-анализ не настроен: задайте POLZA_API_KEY. Локальные правила и fallback отключены."), { status: 503 });
  const docs = checked.documents;
  const analysis = await analyzeDocumentSet(docs, { apiKey: options.llm.apiKey, timeoutMs: options.llm.timeoutMs ?? 90_000, maxRunMs: options.llm.maxRunMs ?? 900_000, maxCalls: options.llm.maxCalls ?? 52, maxEvidenceCorrectionAttempts: options.llm.maxEvidenceCorrectionAttempts, model: options.llm.model ?? GEMMA_MODEL, maxInputTokens: options.llm.maxInputTokens, systemPrompt: options.llm.systemPrompt, resumeProgress: options.llm.resumeProgress, onProgress: options.llm.onProgress });
  if (!analysis.complete) throw Object.assign(new Error("Анализ не завершён; частичный результат нельзя сохранять как граф. Продолжите фоновое задание."), { status: 409 });
  return buildLinkingResult(docs, analysis, started);
}

export function buildLinkingResult(docs: import("../contracts/input").Extraction[], analysis: Awaited<ReturnType<typeof analyzeDocumentSet>>, started = Date.now()): LinkingResult {
  const included = new Set(docs.map(doc => doc.document_id));
  const links = analysis.links.filter(link => included.has(link.source_document_id) && included.has(link.target_document_id));
  const reviewRequired = links.filter(link => link.status === "review" || link.status === "proposed").map(link => ({ link_id: link.link_id, reason: link.explanation || "Модель обозначила связь как требующую проверки", candidate_document_ids: [link.source_document_id, link.target_document_id] }));
  const modelUnlinked = new Set<string>(analysis.unlinkedDocumentIds);
  const unlinkedDocuments = docs.filter(doc => modelUnlinked.has(doc.document_id)).map(doc => ({ document_id: doc.document_id, reason: "Модель не обнаружила подтверждённой связи" }));
  const diagnostics = analysis.invalidRelationshipDiagnostics.map(item => ({ ...item, reasons: item.reason_codes.map(code => ({ code, message: explainEvidenceIssue(code) })), evidence_issues: item.evidence_issues.map(issue => ({ ...issue, reasons: issue.reason_codes.map(code => explainEvidenceIssue(code)) })) }));
  const warnings = diagnostics.length ? [`Для ${diagnostics.length} предложения сохранены исходные evidence-диагностики и результат проверки/исправления; подробности доступны в link_validation_diagnostics.`] : [];
  return { linking_run_id: crypto.randomUUID(), contract_version: OUTPUT_CONTRACT_VERSION, created_at: new Date().toISOString(), input_documents: docs.map(doc => ({ document_id: doc.document_id, extraction_id: doc.extraction_id, document_type: doc.document_type, version: doc.version, schema_version: doc.schema_version, ...(typeof (doc as any).input_version === "number" ? { input_version: (doc as any).input_version } : {}), ...(typeof (doc as any).input_hash === "string" ? { input_hash: (doc as any).input_hash } : {}) })), links, review_required: reviewRequired, unlinked_documents: unlinkedDocuments, warnings, link_validation_diagnostics: diagnostics, analysis_summary: analysis.analysisSummary, processing_metadata: { engine_version: "0.3.0", llm: { enabled: true, provider: analysis.provider, model: analysis.model, strategy: analysis.strategy, estimated_input_tokens: analysis.estimatedInputTokens, calls: analysis.calls, errors: analysis.errors, ...(analysis.inputTokens !== undefined ? { input_tokens: analysis.inputTokens } : {}), ...(analysis.outputTokens !== undefined ? { output_tokens: analysis.outputTokens } : {}), cost_amount: analysis.costAmount ?? null, cost_currency: analysis.costCurrency ?? null, duration_ms: analysis.durationMs }, duration_ms: Date.now() - started } } as LinkingResult;
}
