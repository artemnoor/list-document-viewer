import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

type Ref = { document_id: string; path: string; raw_value?: unknown };
type Label = { relationship_type: string; source_document_id: string; target_document_id: string; source_row_id?: string | null; target_row_id?: string | null; row_correspondences?: { source_row_id: string; target_row_id: string; decision?: string }[]; evidence: { source: Ref; target: Ref }[] };
type Bundle = { annotations_complete: boolean; scenarios: { id: string; gold_links: Label[]; predictions_file?: string; predictions_files?: string[] }[] };
const args = process.argv.slice(2), annotationFlag = args.indexOf("--annotations"), bundlePath = annotationFlag >= 0 ? args[annotationFlag + 1] : args[0];
if (!bundlePath) throw new Error("Usage: npm run eval:links -- evaluation/annotations.json [--out evaluation/report.json]");
const bundle = JSON.parse(readFileSync(resolve(bundlePath), "utf8")) as Bundle;
if (!bundle.annotations_complete || !Array.isArray(bundle.scenarios) || bundle.scenarios.length === 0 || bundle.scenarios.some(s => !Array.isArray(s.gold_links) || !(s.predictions_file || s.predictions_files?.length))) {
  console.error("Метрики не измерены: независимая экспертная разметка неполная. Скопируйте annotations.template.json, заполните gold_links по исходным документам и установите annotations_complete=true после независимой проверки.");
  process.exit(2);
}
const key = (link: Label) => JSON.stringify([link.relationship_type, link.source_document_id, link.target_document_id]);
const pairKey = (link: Label) => JSON.stringify([link.relationship_type, ...[link.source_document_id, link.target_document_id].sort()]);
const rowKey = (link: Label) => JSON.stringify([link.relationship_type, link.source_document_id, link.target_document_id, link.source_row_id ?? null, link.target_row_id ?? null]);
const evidenceKeys = (link: Label) => new Set((link.evidence ?? []).flatMap(e => [JSON.stringify([e.source.document_id, e.source.path, e.source.raw_value]), JSON.stringify([e.target.document_id, e.target.path, e.target.raw_value])]));
let tp = 0, fp = 0, fn = 0, directionCorrect = 0, directionTotal = 0, rowCorrect = 0, rowTotal = 0, provenanceCorrect = 0, provenanceTotal = 0;
const byScenario: unknown[] = [];
let callsTotal = 0, inputTokensTotal = 0, outputTokensTotal = 0, knownCostRuns = 0, runCount = 0;
const costsByCurrency: Record<string, number> = {};
for (const scenario of bundle.scenarios) {
  const predictionFiles = scenario.predictions_files?.length ? scenario.predictions_files : [scenario.predictions_file!];
  const results = predictionFiles.map(file => { const raw = JSON.parse(readFileSync(resolve(file), "utf8")); return raw.result && typeof raw.result === "object" ? raw.result : raw; });
  runCount += results.length;
  for (const result of results) {
    const llm = result.processing_metadata?.llm ?? result.usage;
    callsTotal += Number(llm?.calls ?? result.calls?.length) || 0; inputTokensTotal += Number(llm?.input_tokens) || 0; outputTokensTotal += Number(llm?.output_tokens) || 0;
    if (typeof llm?.cost_amount === "number") { const currency = typeof llm.cost_currency === "string" ? llm.cost_currency : "unknown"; costsByCurrency[currency] = (costsByCurrency[currency] ?? 0) + llm.cost_amount; knownCostRuns++; }
  }
  const result = results[0], gold: Label[] = scenario.gold_links, predicted: Label[] = result.links ?? [], unmatchedGold = new Set(gold.map((_, i) => i));
  for (const prediction of predicted) {
    const exact = gold.findIndex((label, i) => unmatchedGold.has(i) && key(label) === key(prediction));
    if (exact >= 0) { tp++; unmatchedGold.delete(exact); }
    else fp++;
    const candidate = gold.find(label => pairKey(label) === pairKey(prediction));
    if (candidate) { directionTotal++; if (key(candidate) === key(prediction)) directionCorrect++; }
    const expectedRefs = gold.flatMap(label => label.evidence ?? []).flatMap(e => [JSON.stringify([e.source.document_id, e.source.path, e.source.raw_value]), JSON.stringify([e.target.document_id, e.target.path, e.target.raw_value])]);
    const actualRefs = evidenceKeys(prediction); if (expectedRefs.length) { provenanceTotal += expectedRefs.length; provenanceCorrect += expectedRefs.filter(ref => actualRefs.has(ref)).length; }
  }
  fn += unmatchedGold.size;
  const graphKeys = (item: any) => new Set((item.links ?? []).map((link: Label) => key(link)));
  const pairScores: number[] = [];
  for (let i = 0; i < results.length; i++) for (let j = i + 1; j < results.length; j++) {
    const left = graphKeys(results[i]), right = graphKeys(results[j]), intersection = [...left].filter(value => right.has(value)).length, union = new Set([...left, ...right]).size;
    pairScores.push(union ? intersection / union : 1);
  }
  const goldRows = new Set(gold.flatMap(label => label.row_correspondences?.filter(row => row.decision === undefined || row.decision === "supported").map(row => JSON.stringify([label.relationship_type, label.source_document_id, label.target_document_id, row.source_row_id, row.target_row_id])) ?? (label.source_row_id && label.target_row_id ? [rowKey(label)] : [])));
  const predictedRows = new Set(predicted.filter(link => link.source_row_id && link.target_row_id).map(rowKey));
  const rowTp = [...predictedRows].filter(value => goldRows.has(value)).length;
  rowCorrect += rowTp; rowTotal += goldRows.size;
  byScenario.push({ id: scenario.id, gold: gold.length, predicted: predicted.length, true_positives: gold.length - unmatchedGold.size, false_positives: predicted.length - (gold.length - unmatchedGold.size), false_negatives: unmatchedGold.size, gold_row_correspondences: goldRows.size, predicted_row_correspondences: predictedRows.size, row_true_positives: rowTp, row_false_positives: [...predictedRows].filter(value => !goldRows.has(value)).length, row_false_negatives: [...goldRows].filter(value => !predictedRows.has(value)).length, repeat_runs: results.length, mean_pairwise_graph_jaccard: pairScores.length ? pairScores.reduce((sum, value) => sum + value, 0) / pairScores.length : null });
}
const precision = tp + fp ? tp / (tp + fp) : 0, recall = tp + fn ? tp / (tp + fn) : 0;
const pairwiseStability = byScenario.flatMap((item: any) => item.mean_pairwise_graph_jaccard === null ? [] : [item.mean_pairwise_graph_jaccard]);
const rowPrecision = rowCorrect + byScenario.reduce((sum: number, item: any) => sum + item.row_false_positives, 0) ? rowCorrect / (rowCorrect + byScenario.reduce((sum: number, item: any) => sum + item.row_false_positives, 0)) : 0;
const rowRecall = rowTotal ? rowCorrect / rowTotal : 0;
const report = { annotations_complete: true, scenarios: bundle.scenarios.length, runs: runCount, links: { true_positives: tp, false_positives: fp, false_negatives: fn, precision, recall, f1: precision + recall ? 2 * precision * recall / (precision + recall) : 0 }, direction_accuracy: { correct: directionCorrect, total: directionTotal, value: directionTotal ? directionCorrect / directionTotal : null }, row_matching: { true_positives: rowCorrect, false_positives: byScenario.reduce((sum: number, item: any) => sum + item.row_false_positives, 0), false_negatives: byScenario.reduce((sum: number, item: any) => sum + item.row_false_negatives, 0), precision: rowPrecision, recall: rowRecall, f1: rowPrecision + rowRecall ? 2 * rowPrecision * rowRecall / (rowPrecision + rowRecall) : 0 }, provenance_accuracy: { correct: provenanceCorrect, total: provenanceTotal, value: provenanceTotal ? provenanceCorrect / provenanceTotal : null }, stability: { mean_pairwise_graph_jaccard: pairwiseStability.length ? pairwiseStability.reduce((sum, value) => sum + value, 0) / pairwiseStability.length : null }, model_usage: { calls_total: callsTotal, input_tokens_total: inputTokensTotal, output_tokens_total: outputTokensTotal, cost_total: knownCostRuns === runCount && Object.keys(costsByCurrency).length <= 1 ? Object.values(costsByCurrency)[0] ?? 0 : null, cost_by_currency: costsByCurrency, cost_known_runs: knownCostRuns, cost_unknown_runs: runCount - knownCostRuns }, false_relationships: fp, per_scenario: byScenario };
console.log(JSON.stringify(report, null, 2));
const outFlag = args.indexOf("--out"); if (outFlag >= 0 && args[outFlag + 1]) writeFileSync(resolve(args[outFlag + 1]), `${JSON.stringify(report, null, 2)}\n`);
