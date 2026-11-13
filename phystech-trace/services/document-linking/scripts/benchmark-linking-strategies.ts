import "dotenv/config";
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { relative, resolve } from "node:path";
import { validateInput, type Extraction } from "../src/contracts/input";
import { runLinkingStrategy, STRATEGY_PROMPTS, STRATEGY_PROMPT_VERSION, type ExperimentCall, type LinkingStrategy, type StrategyExperimentResult } from "../src/linking/strategy-experiments";
import { POLZA_MODEL } from "../src/linking/polza-client";

// Official Polza model page lists 7.26 RUB/M input and 39.9 RUB/M output. Reserve 2x
// those rates before each call; actual usage.cost takes precedence after every response.
const RUB_PER_INPUT_TOKEN = 0.00001452, RUB_PER_OUTPUT_TOKEN = 0.0000798;
const planPath = resolve(process.env.LINKING_BENCHMARK_PLAN ?? "evaluation/strategy-pilot.json"), outputDir = resolve(process.env.LINKING_BENCHMARK_OUTPUT ?? "reports/strategy-benchmark-runs"), reportPath = resolve(process.env.LINKING_BENCHMARK_REPORT ?? "reports/linking-strategy-benchmark.md");
const plan = JSON.parse(await readFile(planPath, "utf8")) as { version: string; budget_rub: number; repeats_per_scenario: number; strategies: LinkingStrategy[]; scenarios: { id: string; repeats?: number; description: string; fixture_directory: string; documents: string[] }[] };
const apiKey = process.env.POLZA_API_KEY ?? process.env.POLZA_AI_API_KEY;
if (!apiKey) throw new Error("POLZA_API_KEY не задан; платные тесты не запускались.");
await mkdir(outputDir, { recursive: true });
const systemPrompt = await readFile(resolve("prompts/document-linking-system.md"), "utf8");
const promptHash = createHash("sha256").update(systemPrompt).digest("hex");
const strategyPromptHash = createHash("sha256").update(JSON.stringify(STRATEGY_PROMPTS)).digest("hex");
const strategySourceHash = createHash("sha256").update(await readFile(resolve("src/linking/strategy-experiments.ts"))).digest("hex");
const planHash = createHash("sha256").update(await readFile(planPath)).digest("hex");
const results: { scenario: string; repeat: number; strategy: LinkingStrategy; result?: StrategyExperimentResult; error?: string; file: string; observedCalls?: ExperimentCall[]; attemptedCalls?: number; unpricedReserveRub?: number }[] = [];
const externalCalls: { label: string; calls: number; tokens: string; reported_cost_rub: number; included_in_strategy_rows: false }[] = [];
let actualSpend = 0, reservedSpend = 0, stopForBudget = false, totalCalls = 0, callsWithUsage = 0;
const ledgerPath = resolve(outputDir, "ledger.json");
const writeLedger = async () => writeFile(ledgerPath, `${JSON.stringify({ version: "1.0.0", plan_sha256: planHash, experiment_parameters: { timeout_ms: 120_000, max_run_ms: 600_000, max_calls_per_strategy: 8, max_input_tokens: 180_000, max_evidence_correction_attempts: 2 }, model: POLZA_MODEL, provider: "Polza AI", budget_rub: plan.budget_rub, actual_or_estimated_spend_rub: Number(actualSpend.toFixed(8)), reserved_spend_rub: Number(reservedSpend.toFixed(8)), requests_attempted: totalCalls, responses_with_usage: callsWithUsage, requests_without_usage: totalCalls - callsWithUsage, stopped_for_budget: stopForBudget || results.some(row => row.error?.startsWith("BUDGET_STOP:")), external_live_checks: externalCalls, pricing_source: "https://polza.ai/models/google/gemma-4-26b-a4b-it", input_rate_rub_per_million: 14.52, output_rate_rub_per_million: 79.8, system_prompt_sha256: promptHash, strategy_prompts_version: STRATEGY_PROMPT_VERSION, strategy_prompts_sha256: strategyPromptHash, strategy_source_sha256: strategySourceHash, results: results.map(({ scenario, repeat, strategy, error, file }) => ({ scenario, repeat, strategy, error, file })) }, null, 2)}\n`);

// Resume from persisted spend and retain all earlier raw outputs; never reset the run budget.
try {
  const priorLedger = JSON.parse(await readFile(ledgerPath, "utf8"));
  actualSpend = Number(priorLedger.actual_or_estimated_spend_rub) || 0;
  reservedSpend = Number(priorLedger.reserved_spend_rub) || 0;
  totalCalls = Number(priorLedger.requests_attempted ?? priorLedger.calls) || 0;
  callsWithUsage = Number(priorLedger.responses_with_usage ?? totalCalls) || 0;
  externalCalls.push(...(priorLedger.external_live_checks ?? []));
  for (const prior of priorLedger.results ?? []) {
    const artifact = JSON.parse(await readFile(resolve(outputDir, prior.file), "utf8"));
    results.push({ scenario: prior.scenario, repeat: prior.repeat, strategy: prior.strategy, file: prior.file, observedCalls: artifact.calls ?? [], attemptedCalls: artifact.attempted_calls ?? ((artifact.calls?.length ?? 0) + (artifact.error?.startsWith("BUDGET_STOP:") ? 0 : artifact.error ? 1 : 0)), unpricedReserveRub: artifact.unpriced_reserved_rub ?? 0, ...(artifact.result ? { result: artifact.result as StrategyExperimentResult } : {}), ...(prior.error ? { error: prior.error } : artifact.error ? { error: artifact.error } : {}) });
  }
} catch { /* New pilot; no previous ledger exists. */ }
const alreadyRun = new Set(results.map(row => `${row.scenario}:${row.repeat}:${row.strategy}`));

for (const scenario of plan.scenarios) {
  const raw = await Promise.all(scenario.documents.map(name => readFile(resolve(scenario.fixture_directory, name), "utf8").then(JSON.parse)));
  const checked = validateInput(raw);
  if (!checked.success) throw new Error(`Invalid fixture set ${scenario.id}: ${JSON.stringify(checked.diagnostics)}`);
  const documents: Extraction[] = checked.documents;
  for (let repeat = 1; repeat <= (scenario.repeats ?? plan.repeats_per_scenario) && !stopForBudget; repeat++) for (const strategy of plan.strategies) {
    if (stopForBudget) break;
    if (alreadyRun.has(`${scenario.id}:${repeat}:${strategy}`)) continue;
    const file = `${scenario.id}-repeat-${repeat}-${strategy}.json`, filePath = resolve(outputDir, file);
    const row: typeof results[number] = { scenario: scenario.id, repeat, strategy, file, observedCalls: [], attemptedCalls: 0, unpricedReserveRub: 0 }; results.push(row);
    alreadyRun.add(`${scenario.id}:${repeat}:${strategy}`);
    const reservations = new Map<string, number[]>();
    const updateArtifact = async (status: string) => writeFile(filePath, `${JSON.stringify({ version: "1.0.0", scenario: { id: scenario.id, description: scenario.description, fixture_files: scenario.documents }, repeat, strategy, provider: "Polza AI", model: POLZA_MODEL, prompt_version: "document-linking-system@" + promptHash.slice(0, 12) + "+strategy-prompts@" + STRATEGY_PROMPT_VERSION + "-" + strategyPromptHash.slice(0, 12), system_prompt_sha256: promptHash, strategy_prompts_sha256: strategyPromptHash, strategy_source_sha256: strategySourceHash, started_at: new Date().toISOString(), status, spend_rub_so_far: Number(actualSpend.toFixed(8)), calls: row.observedCalls, attempted_calls: row.attemptedCalls, unpriced_reserved_rub: Number((row.unpricedReserveRub ?? 0).toFixed(8)), result: row.result, error: row.error }, null, 2)}\n`);
    await updateArtifact("running"); await writeLedger();
    const reserve = async ({ label, estimatedInputTokens, maxOutputTokens }: { label: string; estimatedInputTokens: number; maxOutputTokens: number }) => {
      const amount = estimatedInputTokens * RUB_PER_INPUT_TOKEN + maxOutputTokens * RUB_PER_OUTPUT_TOKEN;
      if (actualSpend + reservedSpend + amount > plan.budget_rub) { stopForBudget = true; throw new Error(`BUDGET_STOP: резерв ${amount.toFixed(6)} RUB для ${label} превысит лимит ${plan.budget_rub} RUB (учтено ${actualSpend.toFixed(6)} + резерв ${reservedSpend.toFixed(6)})`); }
      reservedSpend += amount; reservations.set(label, [...(reservations.get(label) ?? []), amount]);
      row.attemptedCalls = (row.attemptedCalls ?? 0) + 1; row.unpricedReserveRub = (row.unpricedReserveRub ?? 0) + amount; totalCalls++;
      await updateArtifact("running");
    };
    const onCall = async (call: ExperimentCall) => {
      const pending = reservations.get(call.label) ?? [], held = pending.shift() ?? 0; reservations.set(call.label, pending); reservedSpend = Math.max(0, reservedSpend - held);
      row.unpricedReserveRub = Math.max(0, (row.unpricedReserveRub ?? 0) - held);
      const measured = typeof call.cost === "number" ? call.cost : call.input_tokens * RUB_PER_INPUT_TOKEN + call.output_tokens * RUB_PER_OUTPUT_TOKEN;
      if (call.currency && call.currency !== "RUB") throw new Error(`Неизвестная валюта стоимости ${call.currency}; эксперимент остановлен для соблюдения рублёвого бюджета.`);
      actualSpend += measured; callsWithUsage++;
      row.observedCalls!.push(call);
      await updateArtifact("running");
      await writeLedger();
      if (actualSpend + reservedSpend > plan.budget_rub) { stopForBudget = true; throw new Error(`BUDGET_STOP: фактический/оценочный расход превысил доступный остаток (${actualSpend.toFixed(6)} RUB)`); }
    };
    try {
      row.result = await runLinkingStrategy(strategy, documents, { apiKey, timeoutMs: 120_000, maxRunMs: 600_000, maxCalls: 8, maxEvidenceCorrectionAttempts: 2, maxInputTokens: 180_000, systemPrompt, beforeCall: reserve, onCall });
      await updateArtifact("complete");
    } catch (error) {
      row.error = error instanceof Error ? error.message : String(error);
      if (row.error.startsWith("BUDGET_STOP:")) stopForBudget = true;
      await updateArtifact(stopForBudget ? "stopped_budget" : "failed");
      if (stopForBudget) break;
    }
    await writeLedger();
  }
}

const generatedAt = new Date().toISOString();
const completed = results.filter(row => row.result);
const graphKey = (link: any) => JSON.stringify([link.relationship_type, link.source_document_id, link.target_document_id, link.source_row_id ?? null, link.target_row_id ?? null]);
const stabilityFor = (scenario: string, strategy: LinkingStrategy) => {
  const repeats = completed.filter(row => row.scenario === scenario && row.strategy === strategy).map(row => {
    const result = row.result!;
    const candidates: any[] = strategy === "A" ? [...result.links, ...result.diagnostics.map(item => (item as any).proposal)] : result.candidates as any[];
    return new Set(candidates.filter(item => item && typeof item === "object").map(graphKey));
  });
  if (repeats.length < 2) return null;
  const scores: number[] = [];
  for (let i = 0; i < repeats.length; i++) for (let j = i + 1; j < repeats.length; j++) {
    const a = repeats[i], b = repeats[j], intersection = [...a].filter(key => b.has(key)).length, union = new Set([...a, ...b]).size;
    scores.push(union ? intersection / union : 1);
  }
  return Number((scores.reduce((sum, score) => sum + score, 0) / scores.length).toFixed(4));
};
const metrics = (result: StrategyExperimentResult) => ({ candidates: result.candidates.length, accepted: result.links.length, confirmed: result.links.filter(link => link.status === "confirmed").length, proposed: result.links.filter(link => link.status === "proposed").length, review: result.links.filter(link => link.status === "review").length, rejected: result.links.filter(link => link.status === "rejected").length, diagnostics: result.diagnostics.length, unverified_candidates: result.candidate_dispositions?.filter(item => item.disposition === "retained_unverified").length ?? result.diagnostics.length, review_candidates: result.candidate_dispositions?.filter(item => item.disposition === "review_link").length ?? result.links.filter(link => link.status === "review" || link.status === "proposed").length, semantic_duplicates_collapsed: result.semantic_deduplication?.collapsed_candidate_indices.length ?? 0, valid_evidence_pairs: result.links.reduce((sum, link) => sum + link.evidence.length, 0), repaired_evidence: result.strategy === "A" ? result.diagnostics.filter(item => (item.proposal as any)?.resolution === "corrected").length : 0, calls: result.calls.length, input_tokens: result.usage.input_tokens, output_tokens: result.usage.output_tokens, cost_rub: result.usage.cost_amount, duration_seconds: Number((result.duration_ms / 1000).toFixed(2)) });
const partialCandidateCount = (row: typeof results[number]) => {
  if (row.result) return row.result.candidates.length;
  const candidates = new Map<string, unknown>();
  for (const call of row.observedCalls ?? []) {
    const value = call.raw_response as any;
    const entries = row.strategy === "A" ? value?.links : value?.candidates;
    if (Array.isArray(entries)) for (const item of entries) if (item && typeof item === "object") candidates.set(JSON.stringify([item.relationship_type, item.source_document_id, item.target_document_id, item.source_row_id ?? null, item.target_row_id ?? null]), item);
  }
  return candidates.size ? candidates.size : "—";
};
const reportRows: Record<string, any>[] = results.map(row => ({ scenario: row.scenario, repeat: row.repeat, strategy: row.strategy, stability_mean_pairwise_jaccard: stabilityFor(row.scenario, row.strategy), ...(row.result ? metrics(row.result) : { candidates: partialCandidateCount(row), semantic_duplicates_collapsed: "—", accepted: "—", confirmed: "—", proposed: "—", review: "—", rejected: "—", diagnostics: "—", unverified_candidates: "—", valid_evidence_pairs: "—", repaired_evidence: "—", calls: row.attemptedCalls ?? row.observedCalls?.length ?? 0, input_tokens: row.observedCalls?.reduce((sum, call) => sum + call.input_tokens, 0) ?? 0, output_tokens: row.observedCalls?.reduce((sum, call) => sum + call.output_tokens, 0) ?? 0, cost_rub: (row.observedCalls ?? []).reduce((sum, call) => sum + (call.cost ?? 0), 0) + (row.unpricedReserveRub ?? 0), duration_seconds: row.observedCalls?.reduce((sum, call) => sum + call.duration_ms, 0) ? Number(((row.observedCalls?.reduce((sum, call) => sum + call.duration_ms, 0) ?? 0) / 1000).toFixed(2)) : "—", error: row.error ?? "not run" }) }));
const budgetWasHit = stopForBudget || results.some(row => row.error?.startsWith("BUDGET_STOP:"));
const nonBenchmarkCost = externalCalls.reduce((sum, call) => sum + call.reported_cost_rub, 0);
const completedByStrategy = (["A", "B", "C"] satisfies LinkingStrategy[]).map(strategy => ({ strategy, complete_runs: completed.filter(row => row.strategy === strategy).length, complete_candidate_count: completed.filter(row => row.strategy === strategy).reduce((sum, row) => sum + (row.result?.candidates.length ?? 0), 0), complete_emitted_links: completed.filter(row => row.strategy === strategy).reduce((sum, row) => sum + (row.result?.links.length ?? 0), 0), complete_unverified_candidates: completed.filter(row => row.strategy === strategy).reduce((sum, row) => sum + (row.result?.candidate_dispositions?.filter(item => item.disposition === "retained_unverified").length ?? row.result?.diagnostics.length ?? 0), 0), complete_requests: completed.filter(row => row.strategy === strategy).reduce((sum, row) => sum + (row.result?.calls.length ?? 0), 0), complete_cost_rub: completed.filter(row => row.strategy === strategy).reduce((sum, row) => sum + (row.result?.calls.reduce((cost, call) => cost + (call.cost ?? 0), 0) ?? 0), 0) }));
const md = [
  "# Document Linking strategy pilot", "", `Generated: ${generatedAt}`, `Model: \`${POLZA_MODEL}\` via Polza AI`, `Plan: \`${relative(process.cwd(), planPath).replaceAll("\\", "/")}\`; raw artifacts: \`${relative(process.cwd(), outputDir).replaceAll("\\", "/")}\`.`, `New-request budget: ${plan.budget_rub} RUB; reported or estimated calls: ${actualSpend.toFixed(6)} RUB; reserved upper bound for requests without returned usage: ${reservedSpend.toFixed(6)} RUB; total budget exposure: ${(actualSpend + reservedSpend).toFixed(6)} RUB.`, `Requests attempted: ${totalCalls}; responses with usage: ${callsWithUsage}; without usage: ${totalCalls - callsWithUsage}.`, `Prompt versions: document-linking-system SHA-256 \`${promptHash}\`; experiment prompts ${STRATEGY_PROMPT_VERSION} SHA-256 \`${strategyPromptHash}\`.`, "",
  "## Runs", "", "| Bundle | Repeat | Approach | Candidates | Semantic duplicates collapsed | Links emitted | Confirmed | Proposed | Review | Rejected | Diagnostics | Unverified candidates | Evidence pairs | Corrected | Calls | Input / output tokens | Cost (RUB) | Duration (s) | Stability Jaccard |", "|---|---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
  ...reportRows.map(row => "| " + [row.scenario, row.repeat, row.strategy, row.candidates ?? "—", row.semantic_duplicates_collapsed ?? "—", row.accepted ?? "—", row.confirmed ?? "—", row.proposed ?? "—", row.review ?? "—", row.rejected ?? "—", row.diagnostics ?? "—", row.unverified_candidates ?? "—", row.valid_evidence_pairs ?? "—", row.repaired_evidence ?? "—", row.calls ?? "—", `${row.input_tokens ?? "—"} / ${row.output_tokens ?? "—"}`, typeof row.cost_rub === "number" ? row.cost_rub.toFixed(6) : "unknown", row.duration_seconds ?? "—", row.stability_mean_pairwise_jaccard ?? "n/a", row.error ? String(row.error).replaceAll("|", "/") : ""].join(" | ") + " |"), "",
  "## Comparison", "", "| Strategy | Complete runs | Candidate records | Emitted links | Unverified candidates | Calls | Known run cost (RUB) |", "|---|---:|---:|---:|---:|---:|---:|", ...completedByStrategy.map(row => `| ${row.strategy} | ${row.complete_runs} | ${row.complete_candidate_count} | ${row.complete_emitted_links} | ${row.complete_unverified_candidates} | ${row.complete_requests} | ${row.complete_cost_rub.toFixed(6)} |`), "", "Counts are model and technical-validation observations, not correctness scores. Precision, recall, F1, direction accuracy, row matching accuracy, false relationships, and missed relationships are reported only after independent adjudication. No predictions are used as gold labels.", "", "Semantic duplicate groups are returned by Gemma; code checks only that candidate indices are well-formed. Original candidates remain in each artifact, and grouped aliases are explicitly recorded. Unsupported statuses are retained as review candidates with their original model status and a diagnostic. Invalid evidence is preserved in diagnostics; a separately valid evidence pair can still support a review-status link.", "", "Repeat stability is a candidate-graph Jaccard and is not a quality metric. Sparse or empty candidate sets can make it uninformative. A strategy is not selected by candidate or link count alone.", "", `Complete-run comparison: ${completedByStrategy.map(row => `${row.strategy}=${row.complete_runs}`).join(", ")}.`, `An independent expert gold set is present: no. ${completedByStrategy.some(row => row.complete_runs === 0) ? "The strategies also lack a complete matched sample." : "Even if every strategy has a run, repeat count and expert adjudication are required for a quality conclusion."} Winner: not determined.`, `A budget guard stopped at least one planned request: ${budgetWasHit ? "yes; the rejected preflight request was not sent" : "no"}.`, "",
  "## Raw artifacts", "", `Raw model outputs, prompts hashes, per-call token/cost/time observations, technical diagnostics, and run state are stored under \`${relative(process.cwd(), outputDir).replaceAll("\\", "/")}\`. Each output file is written as calls complete so a partial strategy remains inspectable. No key is saved.`, "",
  "## Limitations", "", "This is a fixed-fixture pilot, not an independently labelled benchmark. Provider-reported usage/cost is used when available; otherwise the runner conservatively estimates cost and holds the preflight reserve for requests without usage. Requests are pre-reserved before sending; a strategy may remain partial if its next call would exceed the selected budget. No unsupported quality claims can be made without the independent annotation packets being completed.", "",
].join("\n");
await writeFile(reportPath, md);
await writeLedger();
console.log(JSON.stringify({ spend_rub: actualSpend, budget_rub: plan.budget_rub, total_calls: totalCalls, stopped_for_budget: stopForBudget, results: reportRows }, null, 2));
