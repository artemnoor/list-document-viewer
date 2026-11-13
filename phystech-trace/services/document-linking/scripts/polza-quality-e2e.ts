import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile, access } from "node:fs/promises";
import { dirname, relative, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { isDeepStrictEqual } from "node:util";
import { analyzeDocumentSet, GEMMA_MODEL } from "../src/linking/llm-matcher";
import { buildLinkingResult } from "../src/linking/link-resolver";
import { buildEvidenceRegistry, resolveEvidenceReference } from "../src/linking/evidence-registry";
import { pathContainsRowId, rowIdExists } from "../src/linking/evidence-validation";
import { validateInput } from "../src/contracts/input";
import { linkingOutputSchema } from "../src/contracts/output";
import { createQualityTransport, QUALITY_Q1, type QualityLedger } from "./quality-live-budget";

const serviceRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const extractionRoot = resolve(serviceRoot, "../structured-extraction");
const hash = (value: string | Buffer) => createHash("sha256").update(value).digest("hex");
const json = async (path: string) => JSON.parse(await readFile(path, "utf8"));
const exists = async (path: string) => access(path).then(() => true, () => false);
const saveJson = async (path: string, value: unknown) => { await mkdir(dirname(path), { recursive: true }); await writeFile(path, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 }); };
type Config = { live: boolean; resume: boolean; linkingOnly: boolean; manifest: string; out: string; repeats: number; linkingGold?: string; extractionGold?: string };

export function parseQualityArgs(args: string[]): Config {
  const config: Config = { live: false, resume: false, linkingOnly: false, manifest: resolve(serviceRoot, "evaluation/quality-live-full.json"), out: resolve(serviceRoot, "reports/polza-quality-live"), repeats: 5 };
  for (let i = 0; i < args.length; i++) {
    const flag = args[i];
    if (flag === "--live") config.live = true;
    else if (flag === "--resume") config.resume = true;
    else if (flag === "--linking-only") config.linkingOnly = true;
    else {
      const mapping: Record<string, "manifest" | "out" | "repeats" | "linkingGold" | "extractionGold"> = { "--manifest": "manifest", "--out": "out", "--repeats": "repeats", "--linking-gold": "linkingGold", "--extraction-gold": "extractionGold" };
      const key = mapping[flag];
      const value = args[++i];
      if (!key || !value || value.startsWith("--")) throw new Error(`QUALITY_ARGUMENT_INVALID:${flag}`);
      if (key === "repeats") config.repeats = Number(value); else config[key] = resolve(value);
    }
  }
  if (config.linkingOnly && config.extractionGold) throw new Error("QUALITY_EXTRACTION_GOLD_REQUIRES_EXTRACTION");
  if (!Number.isInteger(config.repeats) || config.repeats < 1 || config.repeats > 5) throw new Error("QUALITY_REPEATS_RANGE_1_TO_5");
  return config;
}

export function checkPublishedEvidence(result: any, documents: any[]) {
  const registry = buildEvidenceRegistry(documents), docs = new Map(documents.map(doc => [doc.document_id, doc]));
  const references = new Map(registry.map(ref => [`${ref.document_id}\0${ref.json_path}`, ref]));
  const issues: any[] = []; let sides = 0, rows = 0;
  for (const link of result.links) for (const side of ["source", "target"] as const) {
    const documentId = link[`${side}_document_id`], rowId = link[`${side}_row_id`], document = docs.get(documentId);
    if (rowId) {
      rows++;
      if (!document || !rowIdExists(document, rowId) || !link.evidence.some((item: any) => pathContainsRowId(document, item[side]?.path, rowId))) issues.push({ link_id: link.link_id, side, code: "row_not_cited" });
    }
    for (const item of link.evidence) {
      sides++;
      const citation = item[side], ref = references.get(`${documentId}\0${citation?.path}`);
      const resolved = resolveEvidenceReference(ref, documentId);
      if (!resolved.valid || citation?.document_id !== documentId || !ref || !isDeepStrictEqual(ref.raw_value, citation.raw_value) || !isDeepStrictEqual(ref.provenance, citation.provenance)) issues.push({ link_id: link.link_id, side, code: "unresolved_or_forged_evidence", reasons: resolved.issues });
      if (resolved.warnings.length && link.status !== "review" && link.status !== "rejected") issues.push({ link_id: link.link_id, side, code: "accepted_evidence_warning", reasons: resolved.warnings });
    }
  }
  return { evidence_sides_checked: sides, row_citations_checked: rows, technical_issues: issues, passed: issues.length === 0, semantic_correctness: "not_measured_without_independent_gold" };
}

export function graphStability(results: any[]) {
  const graph = (result: any, row: boolean) => new Set<string>(result.links.filter((link: any) => link.status !== "rejected").map((link: any) => JSON.stringify([link.relationship_type, link.source_document_id, link.target_document_id, ...(row ? [link.source_row_id ?? null, link.target_row_id ?? null] : [])])));
  const calculate = (row: boolean) => {
    const scores: number[] = []; let emptyPairs = 0;
    for (let i = 0; i < results.length; i++) for (let j = i + 1; j < results.length; j++) {
      const a = graph(results[i], row), b = graph(results[j], row), union = new Set([...a, ...b]);
      if (!union.size) { emptyPairs++; continue; }
      scores.push([...a].filter(key => b.has(key)).length / union.size);
    }
    return { pair_count: scores.length, empty_graph_pair_count: emptyPairs, mean_jaccard: scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : null, minimum_jaccard: scores.length ? Math.min(...scores) : null };
  };
  return { document_graphs: calculate(false), row_graphs: calculate(true), note: "Empty graphs have no artificial stability of one; failed repeats remain failed separately." };
}

export async function runQualityE2E(config: Config) {
  const extraction = config.linkingOnly ? null : await import(pathToFileURL(resolve(extractionRoot, "lib/extraction/polza-ai.mjs")).href);
  const structured = config.linkingOnly ? null : await import(pathToFileURL(resolve(extractionRoot, "lib/extraction/structured-extraction.mjs")).href);
  const sourceManifest = await json(config.manifest), manifestRoot = dirname(config.manifest);
  if (sourceManifest.schema_version !== "polza-quality-inputs-v1") throw new Error("QUALITY_MANIFEST_VERSION_INVALID");
  const readInputs = async (paths: unknown) => {
    if (!Array.isArray(paths) || !paths.length || paths.length > 10 || paths.some(path => typeof path !== "string")) throw new Error("QUALITY_MANIFEST_FILES_INVALID");
    const items = await Promise.all(paths.map(async (path: string) => { const absolute = resolve(manifestRoot, path), bytes = await readFile(absolute), parsed = JSON.parse(bytes.toString("utf8")); return { path: absolute, sha256: hash(bytes), input_hash: hash(JSON.stringify(parsed)), document_id: parsed.document_id, parsed }; }));
    if (new Set(items.map(item => item.document_id)).size !== items.length || items.some(item => typeof item.document_id !== "string")) throw new Error("QUALITY_DUPLICATE_OR_MISSING_DOCUMENT_ID");
    return items;
  };
  const [parserInputs, linkingInputs] = await Promise.all([readInputs(sourceManifest.parser_files), readInputs(sourceManifest.linking_fixture_files)]);
  const prompt = await readFile(resolve(serviceRoot, "prompts/document-linking-system.md"), "utf8");
  const extractionContextChars = 25000;
  const manifest = { schema_version: "polza-quality-run-v1", source_manifest_sha256: hash(await readFile(config.manifest)), prompt_sha256: hash(prompt), mode: config.linkingOnly ? "linking_only_frozen_extraction" : "parser_json_extraction_linking", repeats: config.repeats, q1: QUALITY_Q1,
    models: { extraction: "deepseek/deepseek-v4-flash", linking: GEMMA_MODEL }, extraction_context_chars: extractionContextChars,
    parser_inputs: parserInputs.map(({ parsed, ...item }) => item), linking_fixture_inputs: linkingInputs.map(({ parsed, ...item }) => item),
    independent_gold: { linking: config.linkingGold ? hash(await readFile(config.linkingGold)) : null, extraction: config.extractionGold ? hash(await readFile(config.extractionGold)) : null } };
  const manifestHash = hash(JSON.stringify(manifest)), manifestPath = resolve(config.out, "manifest.json");
  if (await exists(manifestPath)) { const previous = await json(manifestPath); if (previous.manifest_hash !== manifestHash) throw new Error("QUALITY_RESUME_INPUT_OR_CONFIG_MISMATCH"); }
  await mkdir(config.out, { recursive: true }); await writeFile(resolve(config.out, ".gitignore"), "*\n!.gitignore\n");
  await saveJson(manifestPath, { ...manifest, manifest_hash: manifestHash });
  const nominalExtractionCalls = config.linkingOnly ? 0 : parserInputs.reduce((sum, item) => sum + extraction!.buildGroundedContexts(item.parsed, extractionContextChars).length, 0);
  // The frozen linking fixtures describe the plan only. Live extraction outputs are never replaced with them.
  const planner = await import("../src/linking/semantic-plan");
  const linkingPlan = planner.planSemanticLinking(linkingInputs.map(item => item.parsed), { maxInputTokens: QUALITY_Q1.inputPerCall - 600, systemPrompt: prompt });
  const dryRun = { live: false, model_calls_made: 0, manifest_hash: manifestHash, extraction_initial_calls: nominalExtractionCalls, linking_on_frozen_fixtures: { minimum_calls: linkingPlan.minimum_calls, source_coverage: linkingPlan.source_coverage },
    combined_minimum_on_frozen_fixtures: nominalExtractionCalls + linkingPlan.minimum_calls, maximum_calls: QUALITY_Q1.calls,
    repeats: config.repeats, maximum_total_calls_across_repeats: config.repeats * QUALITY_Q1.calls,
    budget_status: nominalExtractionCalls + linkingPlan.minimum_calls > QUALITY_Q1.calls ? "minimum_exceeds_q1" : "candidate_dependent_verification_and_repairs_not_yet_known",
    note: "Planning does not predict model output, semantic recall, cost, or real Extraction→Linking verification call count. Default mode makes no network requests. Parser JSON snapshots are reused; OCR/Gateway are not exercised." };
  await saveJson(resolve(config.out, "plan.json"), dryRun);
  if (!config.live) return dryRun;
  const apiKey = String(process.env.POLZA_API_KEY ?? "").trim();
  if (!apiKey) throw new Error("QUALITY_LIVE_API_KEY_MISSING");
  if (dryRun.combined_minimum_on_frozen_fixtures > QUALITY_Q1.calls) throw new Error("QUALITY_INITIAL_PLAN_EXCEEDS_Q1");
  const realFetch = globalThis.fetch; const reports: any[] = [], successful: any[] = [];
  for (let repeat = 1; repeat <= config.repeats; repeat++) {
    const runDir = resolve(config.out, `repeat-${repeat}`), ledgerPath = resolve(runDir, "attempts.json"), resultPath = resolve(runDir, "linking-result.json"), statePath = resolve(runDir, "linking-checkpoint.json");
    if (await exists(resultPath)) {
      if (!config.resume) throw new Error("QUALITY_EXISTING_LIVE_REPEAT_USE_RESUME");
      const old = linkingOutputSchema.parse(await json(resultPath)), oldReport = await json(resolve(runDir, "report.json"));
      if (oldReport.result_sha256 !== hash(await readFile(resultPath))) throw new Error("QUALITY_RESUME_RESULT_HASH_MISMATCH");
      if (!checkPublishedEvidence(old, await json(resolve(runDir, "input-extractions.json"))).passed) throw new Error("QUALITY_RESUME_EVIDENCE_INVALID");
      successful.push(old); reports.push(oldReport); continue;
    }
    if (await exists(ledgerPath) && !config.resume) throw new Error("QUALITY_EXISTING_ATTEMPTS_USE_RESUME");
    const ledger: QualityLedger = await exists(ledgerPath) ? await json(ledgerPath) : { started_at: new Date().toISOString(), attempts: [] };
    let stage = "starting";
    const transport = createQualityTransport({ fetcher: realFetch, ledger, stage: () => stage, save: () => saveJson(ledgerPath, ledger) });
    const extractions: any[] = []; const started = Date.now();
    try {
      if (config.linkingOnly) extractions.push(...linkingInputs.map(item => item.parsed));
      else for (const item of parserInputs) {
        stage = `extraction:${item.document_id}`;
        const outputPath = resolve(runDir, "extraction", `${encodeURIComponent(item.document_id)}.json`);
        if (config.resume && await exists(outputPath)) { const old = await json(outputPath); if (old.input_hash !== item.input_hash || old.mode !== "llm_assisted") throw new Error("QUALITY_RESUME_EXTRACTION_IDENTITY_MISMATCH"); extractions.push(old); continue; }
        const llm = await extraction!.callPolzaForExtraction(item.parsed, { POLZA_API_KEY: apiKey, POLZA_FETCH: transport.fetcher, POLZA_CONTEXT_MAX_CHARS: extractionContextChars, POLZA_MAX_OUTPUT_TOKENS: QUALITY_Q1.outputPerCall,
          POLZA_ON_PROGRESS: async (state: unknown) => saveJson(resolve(runDir, "extraction-checkpoints", `${encodeURIComponent(item.document_id)}.json`), state) });
        const output = structured!.extractStructuredDocument(item.parsed, { mode: "llm_assisted", llm, extractionId: `quality-${item.input_hash.slice(0, 16)}-${repeat}`, extractedAt: ledger.started_at });
        output.input_hash = item.input_hash;
        if (output.mode !== "llm_assisted" || !output.extraction_engine.llm.called || !output.extraction_engine.llm.response_validated) throw new Error("QUALITY_EXTRACTION_LLM_REQUIRED");
        await saveJson(outputPath, output); extractions.push(output);
      }
      const checked = validateInput(extractions); if (!checked.success) throw new Error("QUALITY_EXTRACTION_LINKING_CONTRACT_INVALID");
      stage = "linking"; globalThis.fetch = transport.fetcher;
      const analysis = await analyzeDocumentSet(checked.documents, { apiKey, timeoutMs: 120000, maxRunMs: QUALITY_Q1.runMs - (Date.now() - Date.parse(ledger.started_at)), maxCalls: QUALITY_Q1.calls - ledger.attempts.filter(attempt => attempt.stage.startsWith("extraction:")).length, maxInputTokens: QUALITY_Q1.inputPerCall, systemPrompt: prompt,
        ...(config.resume && await exists(statePath) ? { resumeProgress: await json(statePath) } : {}), onProgress: async state => saveJson(statePath, state) });
      if (!analysis.complete) throw new Error("QUALITY_LINKING_INCOMPLETE");
      const result = buildLinkingResult(checked.documents, analysis), parsed = linkingOutputSchema.safeParse(result); if (!parsed.success) throw new Error("QUALITY_LINKING_RESULT_CONTRACT_INVALID");
      const evidence = checkPublishedEvidence(result, checked.documents); if (!evidence.passed) throw new Error(`QUALITY_PUBLISHED_EVIDENCE_INVALID:${JSON.stringify(evidence.technical_issues)}`);
      const report = { repeat, state: "completed", duration_ms: Date.now() - started, evidence, totals: transport.totals(), linking_diagnostics: result.link_validation_diagnostics,
        extraction_grounding: extractions.map(doc => ({ document_id: doc.document_id, mode: doc.mode, validation_status: doc.extraction_engine.llm.validation_status, review_required: doc.review_required, quality_analysis: doc.extraction_engine.llm.usage?.quality_analysis ?? null })),
        semantic_metrics: { precision: null, recall: null, f1: null, reason: "independent_gold_not_scored_yet" } };
      await saveJson(resolve(runDir, "input-extractions.json"), extractions); await saveJson(resultPath, result); Object.assign(report, { result_sha256: hash(await readFile(resultPath)) }); await saveJson(resolve(runDir, "report.json"), report);
      successful.push(result); reports.push(report);
    } catch (error: any) {
      const report = { repeat, state: "failed", stage, duration_ms: Date.now() - started, error: String(error?.message ?? error), details: error?.details ?? null, totals: transport.totals() };
      await saveJson(resolve(runDir, "report.json"), report); reports.push(report);
    } finally { globalThis.fetch = realFetch; }
  }
  const report: any = { manifest_hash: manifestHash, live: true, reports, complete_repeats: successful.length, failed_repeats: reports.filter(item => item.state === "failed").length, stability: graphStability(successful), independent_quality: { status: "not_measured_without_gold", precision: null, recall: null, f1: null } };
  if (config.linkingGold) {
    const bundle = await json(config.linkingGold);
    if (bundle.scenarios?.length !== 1 || successful.length !== config.repeats) report.independent_quality = { status: "gold_evaluation_unavailable", reason: "one_full_bundle_scenario_and_all_repeats_required" };
    else try {
      bundle.scenarios[0].predictions_files = reports.map(item => relative(serviceRoot, resolve(config.out, `repeat-${item.repeat}/linking-result.json`)).replaceAll("\\", "/")); delete bundle.scenarios[0].predictions_file;
      const evaluator = await import("./evaluate-links"); report.independent_quality = await evaluator.evaluateBundle(bundle, serviceRoot);
    } catch (error: any) { report.independent_quality = { status: "rejected_by_existing_gold_validator", error: String(error.message) }; }
  }
  if (config.extractionGold && !config.linkingOnly) {
    const gold = await json(config.extractionGold), artifacts = new Map(gold.artifacts.map((artifact: any) => [artifact.artifact_id, artifact]));
    const predictionManifest = { schema_version: "mvp-extraction-run-manifest-v1", runs: await Promise.all(reports.map(async item => ({ run_id: `repeat-${item.repeat}`, scenarios: await Promise.all(gold.scenarios.map(async (scenario: any) => { const documentId = (artifacts.get(scenario.source_artifact_id) as any)?.document_id, path = `repeat-${item.repeat}/extraction/${encodeURIComponent(documentId)}.json`; return await exists(resolve(config.out, path)) ? { scenario_id: scenario.scenario_id, status: "completed", path, sha256: hash(await readFile(resolve(config.out, path))) } : { scenario_id: scenario.scenario_id, status: "failed", error_code: "PREDICTION_MISSING" }; })) }))) };
    const manifestPath = resolve(config.out, "extraction-predictions.json"); await saveJson(manifestPath, predictionManifest);
    try { const evaluator = await import(pathToFileURL(resolve(extractionRoot, "scripts/evaluate-mvp-extraction.mjs")).href); report.extraction_quality = (await evaluator.runEvaluation({ gold: config.extractionGold, predictions: manifestPath, out: resolve(config.out, "extraction-quality.json") }, extractionRoot)).output; }
    catch (error: any) { report.extraction_quality = { status: "rejected_by_existing_gold_validator", error: String(error.message) }; }
  }
  const linkingRejected = config.linkingGold && !report.independent_quality?.aggregate;
  const linkingFailed = (report.independent_quality?.aggregate?.failed_repeats?.length ?? 0) > 0;
  const extractionFailed = config.extractionGold && report.extraction_quality?.status !== "pass";
  report.quality_status = !config.linkingGold && !config.extractionGold ? "not_measured" : linkingRejected || linkingFailed || extractionFailed ? "fail" : config.linkingGold && report.independent_quality.aggregate.not_applicable_repeats.length === config.repeats ? "not_applicable" : "pass";
  await saveJson(resolve(config.out, "summary.json"), report); return report;
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try {
    const config = parseQualityArgs(process.argv.slice(2)), result = await runQualityE2E(config);
    const summary = config.live ? { live: true, out: config.out, complete_repeats: (result as any).complete_repeats, failed_repeats: (result as any).failed_repeats, quality_status: (result as any).quality_status, stability: (result as any).stability } : result;
    process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`); if (("failed_repeats" in result && result.failed_repeats) || (result as any).quality_status === "fail") process.exitCode = 1;
  }
  catch (error: any) { process.stderr.write(`${error.message}\n`); process.exitCode = 1; }
}
