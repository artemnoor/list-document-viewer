import { appendFile, mkdir, readFile, writeFile, access } from "node:fs/promises";
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createHash } from "node:crypto";
import { isDeepStrictEqual } from "node:util";
import { config as loadEnv } from "dotenv";
import { analyzeDocumentSet, GEMMA_MODEL } from "../src/linking/llm-matcher";
import { buildEvidenceRegistry, resolveEvidenceReference } from "../src/linking/evidence-registry";
import { pathContainsRowId, resolveJsonPath, rowIdExists } from "../src/linking/evidence-validation";
import { planSemanticLinking } from "../src/linking/semantic-plan";
import { documents, gold, systemPrompt } from "../evaluation/synthetic-routing-fixture";
import { createQualityTransport, estimateRequestInputTokens, QUALITY_Q1, type QualityLedger } from "./quality-live-budget";

const serviceRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
loadEnv({ path: resolve(serviceRoot, ".env.local"), quiet: true });

// Conservative visible Polza model-card rates checked 2026-11-14; refresh these before a later live run.
const RUB_PER_MILLION: Record<string, { input: number; output: number }> = {
  "deepseek/deepseek-v4-flash": { input: 16.47, output: 32.94 },
  "google/gemma-4-26b-a4b-it": { input: 7.26, output: 39.9 },
};
const PRICE_SOURCES = [
  "https://polza.ai/models/deepseek/deepseek-v4-flash",
  "https://polza.ai/models/google/gemma-4-26b-a4b-it",
];
const hash = (value: string | Buffer) => createHash("sha256").update(value).digest("hex");
const exists = (path: string) => access(path).then(() => true, () => false);
const writeJson = async (path: string, value: unknown) => { await mkdir(dirname(path), { recursive: true, mode: 0o700 }); await writeFile(path, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 }); };
const scrub = (value: unknown, secret: string) => JSON.parse(JSON.stringify(value, (_key, item) => typeof item === "string" ? item.replaceAll(secret, "[REDACTED]").replace(/Bearer\s+[^\s"']+/gi, "Bearer [REDACTED]") : item));
const appendJsonl = async (path: string, value: unknown, secret: string) => { await mkdir(dirname(path), { recursive: true, mode: 0o700 }); await appendFile(path, `${JSON.stringify(scrub(value, secret))}\n`, { encoding: "utf8", mode: 0o600 }); };

type Config = { live: boolean; out: string; fullAttempts?: string };
export function parseSyntheticRoutingArgs(args: string[]): Config {
  const config: Config = { live: false, out: resolve(serviceRoot, "reports/synthetic-routing-live") };
  for (let i = 0; i < args.length; i++) {
    const flag = args[i];
    if (flag === "--live") config.live = true;
    else if (flag === "--out" || flag === "--full-attempts") {
      const value = args[++i];
      if (!value || value.startsWith("--")) throw new Error(`QUALITY_ARGUMENT_INVALID:${flag}`);
      if (flag === "--out") config.out = resolve(value); else config.fullAttempts = resolve(value);
    } else throw new Error(`QUALITY_ARGUMENT_INVALID:${flag}`);
  }
  if (config.live && !config.fullAttempts) throw new Error("SYNTHETIC_LINKING_REQUIRES_FULL_E2E_ATTEMPTS");
  return config;
}

function attemptCostRub(attempt: any) {
  const rate = RUB_PER_MILLION[attempt.model];
  if (!rate) throw new Error(`QUALITY_PRICE_MODEL_UNKNOWN:${attempt.model}`);
  const input = Number.isFinite(attempt.usage?.prompt_tokens) ? attempt.usage.prompt_tokens : attempt.estimated_input_tokens;
  const output = Number.isFinite(attempt.usage?.completion_tokens) ? attempt.usage.completion_tokens : attempt.reserved_output_tokens;
  const tokenEstimate = (input * rate.input + output * rate.output) / 1_000_000;
  const reportedRub = Number.isFinite(attempt.usage?.cost) && ["RUB", "RUR"].includes(String(attempt.usage?.cost_currency ?? "").toUpperCase()) ? attempt.usage.cost : 0;
  return Math.max(tokenEstimate, reportedRub);
}

function scoreResult(result: any, progress: any) {
  const registry = buildEvidenceRegistry(documents);
  const refByDocPath = new Map(registry.map(ref => [`${ref.document_id}\0${ref.json_path}`, ref]));
  const plan = planSemanticLinking(documents, { maxInputTokens: QUALITY_Q1.inputPerCall - 600, systemPrompt });
  const canonicalId = (id: string) => Object.entries(plan.alias_map).find(([canonical, aliases]) => canonical === id || aliases.includes(id))?.[0] ?? id;
  const positives = gold.positive_relations.map((edge: any) => {
    const source = refByDocPath.get(`${edge.source_document_id}\0${edge.source_path}`), target = refByDocPath.get(`${edge.target_document_id}\0${edge.target_path}`);
    if (!source || !target) throw new Error(`SYNTHETIC_GOLD_REFERENCE_MISSING:${edge.source_document_id}->${edge.target_document_id}`);
    return { ...edge, source_reference_id: canonicalId(source.reference_id), target_reference_id: canonicalId(target.reference_id) };
  });
  const key = (edge: any) => JSON.stringify([edge.source_document_id, edge.target_document_id, edge.relationship_type, edge.source_row_id ?? null, edge.target_row_id ?? null]);
  const actual = result.links.filter((link: any) => link.status !== "rejected");
  const expectedKeys = new Set(positives.map(key)), actualKeys = new Set(actual.map(key));
  const tp = [...actualKeys].filter(item => expectedKeys.has(item)).length;
  const fp = [...actualKeys].filter(item => !expectedKeys.has(item)).length;
  const fn = [...expectedKeys].filter(item => !actualKeys.has(item)).length;
  const precision = tp / Math.max(1, tp + fp), recall = tp / positives.length, f1 = 2 * precision * recall / Math.max(1e-9, precision + recall);
  const pairKey = (ids: string[]) => JSON.stringify([...ids].sort());
  const goldPairs = new Set(positives.map((edge: any) => pairKey([edge.source_document_id, edge.target_document_id])));
  const routeDecisions = (progress.semantic?.routing ?? []).flatMap((task: any) => task.response?.decisions ?? []);
  const candidatePairs = new Set(routeDecisions.filter((item: any) => item.state === "candidate").map((item: any) => pairKey(item.document_ids)));
  const routingTp = [...goldPairs].filter(pair => candidatePairs.has(pair)).length;
  const routeStates = new Map(routeDecisions.map((item: any) => [pairKey(item.document_ids), item.state]));
  const routingMissedAsNoRelation = [...goldPairs].filter(pair => routeStates.get(pair) === "no_relation").length;
  const pairOutcomes = result.analysisCoverage?.semantic?.pair_decisions ?? [];
  const outcomesByPair = new Map(pairOutcomes.map((item: any) => [pairKey(item.document_ids), item.state]));
  const evidenceSides = actual.reduce((sum: number, link: any) => sum + link.evidence.length * 2, 0);
  let evidenceSidesValid = 0, evidenceRowsChecked = 0, evidenceRowsValid = 0;
  for (const link of actual) for (const item of link.evidence) for (const side of ["source", "target"] as const) {
    const docId = link[`${side}_document_id`], citation = item[side], ref = refByDocPath.get(`${docId}\0${citation?.path}`);
    const resolved = resolveEvidenceReference(ref, docId);
    const exact = Boolean(ref && resolved.valid && citation?.document_id === docId && isDeepStrictEqual(ref.raw_value, citation.raw_value) && isDeepStrictEqual(ref.provenance, citation.provenance) && isDeepStrictEqual(resolveJsonPath(documents.find(doc => doc.document_id === docId), ref.json_path), ref.raw_value));
    if (exact) evidenceSidesValid++;
    const rowId = link[`${side}_row_id`];
    if (rowId) { evidenceRowsChecked++; if (rowIdExists(documents.find(doc => doc.document_id === docId), rowId) && exact && pathContainsRowId(documents.find(doc => doc.document_id === docId), citation.path, rowId)) evidenceRowsValid++; }
  }
  const rowGold = positives.filter((edge: any) => edge.source_row_id || edge.target_row_id);
  const rowPred = actual.filter((edge: any) => edge.source_row_id || edge.target_row_id);
  const rowTp = rowPred.filter((edge: any) => expectedKeys.has(key(edge))).length;
  return {
    synthetic_closed_world_gold: { positive_relations: positives.length, negative_document_pairs: gold.explicit_negative_pairs.length, all_document_pairs_labeled: goldPairs.size + gold.explicit_negative_pairs.length === 10 },
    graph: { tp, fp, fn, precision, recall, f1, predicted_relations: actual.length, missed_relations: positives.filter((edge: any) => !actualKeys.has(key(edge))) },
    routing: { gold_positive_pairs: goldPairs.size, candidate_recall: routingTp / Math.max(1, goldPairs.size), candidate_pairs_found: routingTp, positive_pairs_sent_as_no_relation: routingMissedAsNoRelation, positive_pairs_with_insufficient_context: [...goldPairs].filter(pair => routeStates.get(pair) === "insufficient_context").length },
    direction: { correct_positive_directions: tp, gold_relations: positives.length, direction_errors: actual.filter((edge: any) => positives.some((expected: any) => expected.source_document_id === edge.target_document_id && expected.target_document_id === edge.source_document_id)).length },
    row_matching: { tp: rowTp, fp: Math.max(0, rowPred.length - rowTp), fn: Math.max(0, rowGold.length - rowTp), precision: rowTp / Math.max(1, rowPred.length), recall: rowTp / Math.max(1, rowGold.length) },
    evidence: { citation_sides_checked: evidenceSides, citation_sides_exact_value_and_provenance: evidenceSidesValid, valid_share: evidenceSides ? evidenceSidesValid / evidenceSides : null, row_citations_checked: evidenceRowsChecked, row_citations_valid: evidenceRowsValid, invalid_relationship_diagnostics: result.invalidRelationshipDiagnostics.length },
    negative_and_uncertain_pairs: { explicit_negative_pairs: gold.explicit_negative_pairs.map((pair: string[]) => ({ documents: pair, predicted_relations: actual.filter((link: any) => pair.includes(link.source_document_id) && pair.includes(link.target_document_id)).length, final_state: outcomesByPair.get(pairKey(pair)) ?? null })), no_link_found: pairOutcomes.filter((item: any) => item.state === "no_link_found").length, insufficient_evidence: pairOutcomes.filter((item: any) => item.state === "insufficient_evidence").length },
    source_coverage: { processed_references: result.analysisCoverage?.processed_references ?? null, total_references: result.analysisCoverage?.total_references ?? null, complete: result.analysisCoverage?.processed_references === result.analysisCoverage?.total_references },
  };
}

export async function runSyntheticRoutingLive(config: Config) {
  const plan = planSemanticLinking(documents, { maxInputTokens: QUALITY_Q1.inputPerCall - 600, systemPrompt });
  const fullMaxCostRub = (QUALITY_Q1.inputTotal * RUB_PER_MILLION["deepseek/deepseek-v4-flash"].input + QUALITY_Q1.outputTotal * RUB_PER_MILLION["google/gemma-4-26b-a4b-it"].output) / 1_000_000;
  const linkingMaxCostRub = (Math.min(20 * QUALITY_Q1.inputPerCall, QUALITY_Q1.inputTotal) * RUB_PER_MILLION["google/gemma-4-26b-a4b-it"].input + Math.min(20 * QUALITY_Q1.outputPerCall, QUALITY_Q1.outputTotal) * RUB_PER_MILLION["google/gemma-4-26b-a4b-it"].output) / 1_000_000;
  const output = { mode: config.live ? "live" : "preflight_only", model: GEMMA_MODEL, synthetic_documents: documents.map((doc: any) => doc.document_id), gold_sha256: hash(JSON.stringify(gold)), input_sha256: hash(JSON.stringify(documents)), positive_relations: gold.positive_relations.length, negative_pairs: gold.explicit_negative_pairs.length, linking_minimum_calls: plan.minimum_calls, linking_call_limit: 20, q1_per_request: { input: QUALITY_Q1.inputPerCall, output: QUALITY_Q1.outputPerCall }, q1_per_run: { input: QUALITY_Q1.inputTotal, output: QUALITY_Q1.outputTotal, wall_ms: QUALITY_Q1.runMs }, model_prices_checked_on: "2026-11-14", rub_per_million_tokens: RUB_PER_MILLION, price_sources: PRICE_SOURCES, total_cost_budget_rub_approximate: 30, cost_forecast: { full_e2e_worst_case_rub: fullMaxCostRub, synthetic_linking_worst_case_rub: linkingMaxCostRub, combined_worst_case_rub: fullMaxCostRub + linkingMaxCostRub, approximate_budget_headroom_rub: 30 - fullMaxCostRub - linkingMaxCostRub, caveat: "Token-cap estimate using visible model-card rates, not a guaranteed billing ceiling; provider rates may change and actual billing metadata is retained." } };
  if (!config.live) return { ...output, model_calls_made: 0, note: "Preflight only; no network or model call was made." };
  const apiKey = String(process.env.POLZA_API_KEY ?? "").trim();
  if (!apiKey) throw new Error("QUALITY_LIVE_API_KEY_MISSING");
  if (plan.minimum_calls > 20) throw new Error(`SYNTHETIC_LINKING_MINIMUM_EXCEEDS_20:${plan.minimum_calls}`);
  if (await exists(resolve(config.out, "report.json")) || await exists(resolve(config.out, "attempts.json"))) throw new Error("SYNTHETIC_LINKING_OUTPUT_ALREADY_EXISTS_USE_NEW_DIR");
  const prior = JSON.parse(await readFile(config.fullAttempts!, "utf8"));
  if (!Array.isArray(prior.attempts) || prior.attempts.length > 40 || prior.attempts.some((item: any) => item.state === "sending")) throw new Error("FULL_E2E_ATTEMPT_LEDGER_INVALID_OR_UNCERTAIN");
  const fullRunDirectory = dirname(dirname(config.fullAttempts!));
  const fullManifest = JSON.parse(await readFile(resolve(fullRunDirectory, "manifest.json"), "utf8"));
  if (fullManifest.repeats !== 1 || fullManifest.mode !== "parser_json_extraction_linking" || fullManifest.models?.extraction !== "deepseek/deepseek-v4-flash" || fullManifest.models?.linking !== GEMMA_MODEL || fullManifest.parser_inputs?.length !== 5) throw new Error("FULL_E2E_MANIFEST_DOES_NOT_MATCH_APPROVED_SINGLE_RUN");
  if (fullManifest.source_manifest_sha256 !== hash(await readFile(resolve(serviceRoot, "evaluation/quality-live-full.json")))) throw new Error("FULL_E2E_SOURCE_MANIFEST_MISMATCH");
  if (prior.attempts.length + 20 > 60) throw new Error("TOTAL_POLZA_CALL_LIMIT_WOULD_BE_EXCEEDED");
  const currentWorst = (500_000 * 16.47 + 100_000 * 39.9) / 1_000_000;
  const gemmaRates = RUB_PER_MILLION[GEMMA_MODEL];
  const linkingWorst = (Math.min(20 * QUALITY_Q1.inputPerCall, QUALITY_Q1.inputTotal) * gemmaRates.input + Math.min(20 * QUALITY_Q1.outputPerCall, QUALITY_Q1.outputTotal) * gemmaRates.output) / 1_000_000;
  const priorCost = prior.attempts.reduce((sum: number, item: any) => sum + attemptCostRub(item), 0);
  const budgetForecast = priorCost + linkingWorst;
  if (budgetForecast > 30) throw new Error(`COST_FORECAST_EXCEEDS_APPROX_BUDGET_RUB:${budgetForecast.toFixed(4)}`);
  await mkdir(config.out, { recursive: true, mode: 0o700 });
  await writeJson(resolve(config.out, "manifest.json"), { ...output, ...plan.source_coverage, full_e2e_manifest_sha256: hash(JSON.stringify(fullManifest)), full_e2e_attempts: prior.attempts.length, prior_full_e2e_estimated_cost_rub: priorCost, full_e2e_max_cost_estimate_rub: currentWorst, total_worst_case_cost_estimate_rub: priorCost + linkingWorst, total_call_limit: 60, source_hash: hash(JSON.stringify(documents)), created_at: new Date().toISOString() });
  await writeJson(resolve(config.out, "input-documents.json"), documents);
  await writeJson(resolve(config.out, "gold.json"), gold);
  const ledger: QualityLedger = { started_at: new Date().toISOString(), attempts: [] };
  const ledgerPath = resolve(config.out, "attempts.json"), requestPath = resolve(config.out, "requests.jsonl"), responsePath = resolve(config.out, "responses.jsonl"), checkpointPath = resolve(config.out, "checkpoint.json");
  let stage = "linking";
  const realFetch = globalThis.fetch;
  const auditedFetch: typeof fetch = async (url, init) => {
    if (prior.attempts.length + ledger.attempts.length > 60) throw new Error("TOTAL_POLZA_CALL_LIMIT_REACHED");
    const projectedCost = priorCost + ledger.attempts.reduce((sum, item) => sum + attemptCostRub(item), 0);
    if (projectedCost > 30) throw new Error(`COST_FORECAST_EXCEEDS_APPROX_BUDGET_RUB:${projectedCost.toFixed(4)}`);
    const body = JSON.parse(String(init?.body));
    if (body.model !== GEMMA_MODEL) throw new Error("SYNTHETIC_LINKING_MODEL_REJECTED");
    await appendJsonl(requestPath, { timestamp: new Date().toISOString(), stage, model: body.model, max_tokens: body.max_tokens, messages: body.messages }, apiKey);
    const response = await realFetch(url, init);
    const payload = await response.clone().json().catch(async () => ({ raw_text: await response.clone().text().catch(() => "[unreadable response]") }));
    await appendJsonl(responsePath, { timestamp: new Date().toISOString(), status: response.status, ok: response.ok, body: payload }, apiKey);
    return response;
  };
  const transport = createQualityTransport({ fetcher: auditedFetch, ledger, stage: () => stage, save: () => writeJson(ledgerPath, scrub(ledger, apiKey)) });
  let progress: any = null, result: any = null, error: any = null;
  const started = Date.now();
  try {
    globalThis.fetch = transport.fetcher;
    result = await analyzeDocumentSet(documents, { apiKey, timeoutMs: 120_000, maxRunMs: QUALITY_Q1.runMs, maxCalls: Math.min(20, 60 - prior.attempts.length), maxInputTokens: QUALITY_Q1.inputPerCall, systemPrompt,
      onProgress: async state => { progress = state; await writeJson(checkpointPath, scrub(state, apiKey)); },
    });
  } catch (caught: any) { error = { name: caught?.name ?? "Error", message: String(caught?.message ?? caught), status: caught?.status ?? null }; }
  finally { globalThis.fetch = realFetch; await writeJson(ledgerPath, scrub(ledger, apiKey)); }
  const report = { ...output, started_at: ledger.started_at, finished_at: new Date().toISOString(), duration_ms: Date.now() - started, prior_full_e2e_attempts: prior.attempts.length, linking_calls: ledger.attempts.length, total_calls: prior.attempts.length + ledger.attempts.length, totals: transport.totals(), cost_estimate_rub: priorCost + ledger.attempts.reduce((sum, item) => sum + attemptCostRub(item), 0), complete: Boolean(result?.complete), error, metrics: result ? scoreResult(result, progress ?? {}) : null, model_summary: result ? { phase: result.phase, calls: result.calls, errors: result.errors, input_tokens: result.inputTokens ?? null, output_tokens: result.outputTokens ?? null, cost_amount: result.costAmount ?? null, cost_currency: result.costCurrency ?? null, analysis_summary: result.analysisSummary } : null, result: result ? scrub(result, apiKey) : null };
  await writeJson(resolve(config.out, "report.json"), scrub(report, apiKey));
  return { live: true, out: config.out, linking_calls: ledger.attempts.length, total_calls: prior.attempts.length + ledger.attempts.length, complete: Boolean(result?.complete), precision: report.metrics?.graph.precision ?? null, recall: report.metrics?.graph.recall ?? null, f1: report.metrics?.graph.f1 ?? null, cost_estimate_rub: report.cost_estimate_rub, duration_ms: report.duration_ms };
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try {
    const config = parseSyntheticRoutingArgs(process.argv.slice(2));
    const summary = await runSyntheticRoutingLive(config);
    process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`);
    if ("complete" in summary && !summary.complete) process.exitCode = 1;
  } catch (error: any) { process.stderr.write(`${String(error?.message ?? error)}\n`); process.exitCode = 1; }
}
