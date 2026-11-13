import { isDeepStrictEqual } from "node:util";
import { resolveJsonPath } from "../src/linking/evidence-validation";

export type EvidenceReference = { document_id: string; path: string; raw_value: unknown };
export type EvidencePair = { source: EvidenceReference; target: EvidenceReference };
export type GoldLink = {
  relationship_type: string;
  source_document_id: string;
  target_document_id: string;
  source_row_id?: string | null;
  target_row_id?: string | null;
  row_correspondences?: {
    source_row_id?: string;
    target_row_id?: string;
    decision?: string;
    supporting_evidence?: EvidencePair[];
    contradicting_evidence?: EvidencePair[];
    ambiguity_notes?: string;
  }[];
  evidence: EvidencePair[];
};
export type ReviewedPair = {
  left_document_id: string;
  right_document_id: string;
  decision: "supported" | "not_supported" | "ambiguous";
  relationship_instances?: unknown[];
  contradicting_evidence?: EvidencePair[];
  ambiguity_notes?: string;
};
export type PredictionLink = {
  relationship_type: string;
  source_document_id: string;
  target_document_id: string;
  source_row_id?: string;
  target_row_id?: string;
  evidence: EvidencePair[];
  status: "confirmed" | "proposed" | "review" | "rejected";
  verification_status: "not_reviewed" | "human_confirmed" | "human_rejected";
};
export type ScoringScenarioInput = {
  id: string;
  goldLinks: GoldLink[];
  reviewedPairs: ReviewedPair[];
  result: {
    linking_run_id?: string;
    links: PredictionLink[];
    processing_metadata?: { llm?: Record<string, unknown> };
    usage?: Record<string, unknown>;
    calls?: unknown[];
  };
  sourceDocumentsById: Map<string, unknown>;
};

type MetricCounts = { true_positives: number; false_positives: number; false_negatives: number; predicted_denominator: number; gold_denominator: number; precision: number | null; recall: number | null; f1: number | null };
type EvidenceStats = { correct_pairs: number; required_pairs: number; missing_pairs: number; accuracy: number | null; paired_completeness: number | null; invalid_pairs: number; predicted_pairs: number };
type UsageStats = { calls: number | null; input_tokens: number | null; output_tokens: number | null; cost: number | null; cost_currency: string | null; model_errors: number | null };

export type ScenarioScore = {
  id: string;
  linking_run_id: string;
  document_relations: MetricCounts;
  direction_accuracy: { correct: number; total: number; value: number | null };
  row_correspondences: MetricCounts;
  evidence: EvidenceStats;
  explicit_negative_pairs: number;
  accepted_links_on_negative_pairs: number;
  ambiguous_pairs: number;
  accepted_links_on_ambiguous_pairs: number;
  usage: UsageStats;
  graphRelations: string[];
};
export type RunScore = {
  repeat: number;
  document_relations: MetricCounts;
  direction_accuracy: { correct: number; total: number; value: number | null };
  row_correspondences: MetricCounts;
  evidence: EvidenceStats;
  explicit_negative_pairs: number;
  accepted_links_on_negative_pairs: number;
  ambiguous_pairs: number;
  accepted_links_on_ambiguous_pairs: number;
  positive_gold_relations: number;
  empty_positive_graph: boolean;
  model_usage: UsageStats;
  quality_gates: Record<string, { status: "pass" | "fail" | "not_applicable"; value: number | null; threshold?: number }>;
  overall_status: "pass" | "fail" | "not_applicable";
  per_scenario: ScenarioScore[];
};

const relationKey = (link: Pick<GoldLink, "relationship_type" | "source_document_id" | "target_document_id">) =>
  JSON.stringify([link.relationship_type, link.source_document_id, link.target_document_id]);
const unorderedPairKey = (left: string, right: string) => JSON.stringify([left, right].sort());
const typeAndPairKey = (link: Pick<GoldLink, "relationship_type" | "source_document_id" | "target_document_id">) =>
  JSON.stringify([link.relationship_type, ...[link.source_document_id, link.target_document_id].sort()]);
const rowKey = (link: GoldLink, sourceRowId: string, targetRowId: string) =>
  JSON.stringify([relationKey(link), sourceRowId, targetRowId]);
const evidencePairKey = (evidence: EvidencePair) => JSON.stringify([
  evidence.source.document_id,
  evidence.source.path,
  evidence.source.raw_value,
  evidence.target.document_id,
  evidence.target.path,
  evidence.target.raw_value,
]);
const pairEvidenceKey = (pair: EvidencePair) => evidencePairKey(pair);

function metricCounts(tp: number, fp: number, fn: number, predictedDenominator = tp + fp, goldDenominator = tp + fn): MetricCounts {
  const precision = predictedDenominator ? tp / predictedDenominator : null;
  const recall = goldDenominator ? tp / goldDenominator : null;
  const f1 = tp === 0 && goldDenominator > 0
    ? 0
    : precision !== null && recall !== null && precision + recall > 0
    ? 2 * precision * recall / (precision + recall)
    : null;
  return {
    true_positives: tp,
    false_positives: fp,
    false_negatives: fn,
    predicted_denominator: predictedDenominator,
    gold_denominator: goldDenominator,
    precision,
    recall,
    f1,
  };
}

function evidenceIsExact(link: PredictionLink, item: EvidencePair, sourceDocumentsById: Map<string, unknown>) {
  if (!item?.source || !item?.target || item.source.document_id !== link.source_document_id || item.target.document_id !== link.target_document_id) return false;
  const source = sourceDocumentsById.get(item.source.document_id), target = sourceDocumentsById.get(item.target.document_id);
  if (!source || !target) return false;
  const sourceValue = resolveJsonPath(source, item.source.path), targetValue = resolveJsonPath(target, item.target.path);
  return sourceValue !== undefined && targetValue !== undefined &&
    isDeepStrictEqual(sourceValue, item.source.raw_value) && isDeepStrictEqual(targetValue, item.target.raw_value);
}

function usageFor(result: ScoringScenarioInput["result"]): UsageStats {
  const llm = result.processing_metadata?.llm ?? result.usage;
  const numberOrNull = (value: unknown) => typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
  return {
    calls: numberOrNull(llm?.calls ?? result.calls?.length),
    input_tokens: numberOrNull(llm?.input_tokens),
    output_tokens: numberOrNull(llm?.output_tokens),
    cost: numberOrNull(llm?.cost_amount),
    cost_currency: typeof llm?.cost_currency === "string" ? llm.cost_currency : null,
    model_errors: numberOrNull(llm?.errors),
  };
}

function isAccepted(link: PredictionLink) {
  return link.status !== "rejected" && link.verification_status !== "human_rejected" &&
    (link.status === "confirmed" || link.verification_status === "human_confirmed");
}

function scoreScenario(scenario: ScoringScenarioInput): ScenarioScore {
  const goldByRelation = new Map<string, { link: GoldLink; rowKeys: Set<string>; evidencePairs: Set<string> }>();
  const ambiguousPairs = new Set<string>();
  const negativePairs = new Set<string>();
  const pairDecisions = new Map<string, string>();
  for (const pair of scenario.reviewedPairs) {
    const key = unorderedPairKey(pair.left_document_id, pair.right_document_id);
    pairDecisions.set(key, pair.decision);
    if (pair.decision === "ambiguous") ambiguousPairs.add(key);
    if (pair.decision === "not_supported") negativePairs.add(key);
  }
  for (const gold of scenario.goldLinks) {
    const key = relationKey(gold);
    const pairKey = unorderedPairKey(gold.source_document_id, gold.target_document_id);
    if (pairDecisions.size && pairDecisions.get(pairKey) !== "supported") {
      throw new Error(`Gold relation for ${scenario.id} is not in a supported reviewed pair.`);
    }
    const relation = goldByRelation.get(key) ?? { link: gold, rowKeys: new Set<string>(), evidencePairs: new Set<string>() };
    for (const row of gold.row_correspondences ?? []) {
      if ((row.decision === undefined || row.decision === "supported") && row.source_row_id && row.target_row_id) {
        relation.rowKeys.add(rowKey(gold, row.source_row_id, row.target_row_id));
      }
    }
    if (!gold.row_correspondences?.length && gold.source_row_id && gold.target_row_id) {
      relation.rowKeys.add(rowKey(gold, gold.source_row_id, gold.target_row_id));
    }
    for (const evidence of gold.evidence ?? []) relation.evidencePairs.add(pairEvidenceKey(evidence));
    goldByRelation.set(key, relation);
  }

  const activeLinks = scenario.result.links.filter((link) => link.status !== "rejected" && link.verification_status !== "human_rejected");
  const linksByRelation = new Map<string, PredictionLink[]>();
  for (const link of activeLinks) {
    const key = relationKey(link);
    const group = linksByRelation.get(key) ?? [];
    group.push(link);
    linksByRelation.set(key, group);
  }

  let linkTp = 0, linkFp = 0, directionCorrect = 0, directionTotal = 0;
  const predictedRelationKeys = new Set<string>();
  const goldRelationKeys = new Set(goldByRelation.keys());
  const positiveTypePairKeys = new Set([...goldByRelation.values()].map(({ link }) => typeAndPairKey(link)));
  for (const [key, links] of linksByRelation) {
    const link = links[0];
    const pairKey = unorderedPairKey(link.source_document_id, link.target_document_id);
    if (ambiguousPairs.has(pairKey)) continue;
    predictedRelationKeys.add(key);
    if (positiveTypePairKeys.has(typeAndPairKey(link))) {
      directionTotal++;
      if (goldRelationKeys.has(key)) directionCorrect++;
    }
    if (goldRelationKeys.has(key)) {
      linkTp++;
    } else {
      linkFp++;
    }
    const rowlessCount = links.filter((item) => !item.source_row_id && !item.target_row_id).length;
    if (rowlessCount > 1) linkFp += rowlessCount - 1;
  }
  const linkFn = [...goldRelationKeys].filter((key) => !predictedRelationKeys.has(key)).length;
  const linkMetrics = metricCounts(linkTp, linkFp, linkFn);

  const goldRows = new Set([...goldByRelation.values()].flatMap((relation) => [...relation.rowKeys]));
  const predictedRowCounts = new Map<string, number>();
  let predictedRowOccurrences = 0;
  for (const link of activeLinks) {
    if (ambiguousPairs.has(unorderedPairKey(link.source_document_id, link.target_document_id))) continue;
    if (!link.source_row_id && !link.target_row_id) continue;
    predictedRowOccurrences++;
    if (!link.source_row_id || !link.target_row_id) continue;
    const key = rowKey(link, link.source_row_id, link.target_row_id);
    predictedRowCounts.set(key, (predictedRowCounts.get(key) ?? 0) + 1);
  }
  const matchedRows = [...predictedRowCounts.keys()].filter((key) => goldRows.has(key)).length;
  const rowFp = predictedRowOccurrences - matchedRows;
  const rowFn = goldRows.size - matchedRows;
  const rowMetrics = metricCounts(matchedRows, rowFp, rowFn, predictedRowOccurrences, goldRows.size);

  let requiredEvidencePairs = 0, correctEvidencePairs = 0, invalidEvidencePairs = 0, predictedEvidencePairs = 0;
  const evidenceCountsByRelation = new Map<string, Set<string>>();
  for (const link of activeLinks) {
    const relation = relationKey(link);
    const set = evidenceCountsByRelation.get(relation) ?? new Set<string>();
    for (const item of link.evidence ?? []) {
      predictedEvidencePairs++;
      if (evidenceIsExact(link, item, scenario.sourceDocumentsById)) {
        set.add(evidencePairKey(item));
      } else {
        invalidEvidencePairs++;
      }
    }
    evidenceCountsByRelation.set(relation, set);
  }
  for (const [key, relation] of goldByRelation) {
    if (!predictedRelationKeys.has(key)) continue;
    const predictedEvidence = evidenceCountsByRelation.get(key) ?? new Set<string>();
    requiredEvidencePairs += relation.evidencePairs.size;
    const matches = [...relation.evidencePairs].filter((item) => predictedEvidence.has(item)).length;
    correctEvidencePairs += matches;
  }

  let acceptedNegativeLinks = 0, acceptedAmbiguousLinks = 0;
  for (const link of activeLinks) {
    if (!isAccepted(link)) continue;
    const pairKey = unorderedPairKey(link.source_document_id, link.target_document_id);
    if (negativePairs.has(pairKey)) acceptedNegativeLinks++;
    if (ambiguousPairs.has(pairKey)) acceptedAmbiguousLinks++;
  }

  const pairedCompleteness = requiredEvidencePairs ? correctEvidencePairs / requiredEvidencePairs : null;
  const evidenceAccuracy = predictedEvidencePairs ? (predictedEvidencePairs - invalidEvidencePairs) / predictedEvidencePairs : null;
  const usage = usageFor(scenario.result);
  const graphRelations = [...new Set([...linksByRelation.entries()]
    .filter(([key, links]) => !ambiguousPairs.has(unorderedPairKey(links[0].source_document_id, links[0].target_document_id)) && links.length > 0)
    .map(([, links]) => JSON.stringify([links[0].relationship_type, ...[links[0].source_document_id, links[0].target_document_id].sort()]))
  )];

  return {
    id: scenario.id,
    linking_run_id: scenario.result.linking_run_id ?? "unknown",
    document_relations: linkMetrics,
    direction_accuracy: { correct: directionCorrect, total: directionTotal, value: directionTotal ? directionCorrect / directionTotal : null },
    row_correspondences: rowMetrics,
    evidence: {
      correct_pairs: correctEvidencePairs,
      required_pairs: requiredEvidencePairs,
      missing_pairs: Math.max(0, requiredEvidencePairs - correctEvidencePairs),
      accuracy: evidenceAccuracy,
      paired_completeness: pairedCompleteness,
      invalid_pairs: invalidEvidencePairs,
      predicted_pairs: predictedEvidencePairs,
    },
    explicit_negative_pairs: negativePairs.size,
    accepted_links_on_negative_pairs: acceptedNegativeLinks,
    ambiguous_pairs: ambiguousPairs.size,
    accepted_links_on_ambiguous_pairs: acceptedAmbiguousLinks,
    usage,
    graphRelations,
  };
}

function sumMetric(scenarios: ScenarioScore[], key: "document_relations" | "row_correspondences"): MetricCounts {
  const values = scenarios.map((scenario) => scenario[key]);
  return metricCounts(
    values.reduce((sum, metric) => sum + metric.true_positives, 0),
    values.reduce((sum, metric) => sum + metric.false_positives, 0),
    values.reduce((sum, metric) => sum + metric.false_negatives, 0),
  );
}

function sumMaybe(values: (number | null)[]) {
  return values.every((value) => value !== null) ? values.reduce<number>((sum, value) => sum + (value ?? 0), 0) : null;
}

function sumUsage(scenarios: ScenarioScore[]): UsageStats {
  const currencies = new Set(scenarios.map((scenario) => scenario.usage.cost_currency).filter((value): value is string => value !== null));
  const costs = scenarios.map((scenario) => scenario.usage.cost);
  return {
    calls: sumMaybe(scenarios.map((scenario) => scenario.usage.calls)),
    input_tokens: sumMaybe(scenarios.map((scenario) => scenario.usage.input_tokens)),
    output_tokens: sumMaybe(scenarios.map((scenario) => scenario.usage.output_tokens)),
    cost: currencies.size <= 1 ? sumMaybe(costs) : null,
    cost_currency: currencies.size === 1 ? [...currencies][0] : null,
    model_errors: sumMaybe(scenarios.map((scenario) => scenario.usage.model_errors)),
  };
}

function thresholdGate(value: number | null, threshold: number, comparator: "min" | "max" = "min") {
  if (value === null) return { status: "not_applicable" as const, value, threshold };
  const passed = comparator === "min" ? value >= threshold : value <= threshold;
  return { status: passed ? "pass" as const : "fail" as const, value, threshold };
}

export function scoreRun(repeat: number, scenarios: ScoringScenarioInput[]): RunScore {
  if (!Number.isInteger(repeat) || repeat < 1) throw new Error("Repeat number must be a positive integer.");
  if (!Array.isArray(scenarios) || scenarios.length === 0) throw new Error("At least one scenario is required for scoring.");
  const scenarioScores = scenarios.map(scoreScenario);
  const documentRelations = sumMetric(scenarioScores, "document_relations");
  const rowCorrespondences = sumMetric(scenarioScores, "row_correspondences");
  const directionCorrect = scenarioScores.reduce((sum, scenario) => sum + scenario.direction_accuracy.correct, 0);
  const directionTotal = scenarioScores.reduce((sum, scenario) => sum + scenario.direction_accuracy.total, 0);
  const correctEvidencePairs = scenarioScores.reduce((sum, scenario) => sum + scenario.evidence.correct_pairs, 0);
  const requiredEvidencePairs = scenarioScores.reduce((sum, scenario) => sum + scenario.evidence.required_pairs, 0);
  const predictedEvidencePairs = scenarioScores.reduce((sum, scenario) => sum + scenario.evidence.predicted_pairs, 0);
  const invalidEvidencePairs = scenarioScores.reduce((sum, scenario) => sum + scenario.evidence.invalid_pairs, 0);
  const evidenceAccuracy = predictedEvidencePairs ? (predictedEvidencePairs - invalidEvidencePairs) / predictedEvidencePairs : null;
  const evidenceCompleteness = requiredEvidencePairs ? correctEvidencePairs / requiredEvidencePairs : null;
  const negativePairs = scenarioScores.reduce((sum, scenario) => sum + scenario.explicit_negative_pairs, 0);
  const acceptedNegativeLinks = scenarioScores.reduce((sum, scenario) => sum + scenario.accepted_links_on_negative_pairs, 0);
  const ambiguousPairs = scenarioScores.reduce((sum, scenario) => sum + scenario.ambiguous_pairs, 0);
  const acceptedAmbiguousLinks = scenarioScores.reduce((sum, scenario) => sum + scenario.accepted_links_on_ambiguous_pairs, 0);
  const positiveGoldRelations = scenarios.reduce((sum, scenario) => sum + new Set(scenario.goldLinks.map(relationKey)).size, 0);
  const gates = {
    link_precision: thresholdGate(documentRelations.precision, 0.95),
    link_recall: thresholdGate(documentRelations.recall, 0.90),
    link_f1: thresholdGate(documentRelations.f1, 0.92),
    row_precision: thresholdGate(rowCorrespondences.precision, 0.90),
    row_recall: thresholdGate(rowCorrespondences.recall, 0.90),
    direction_accuracy: thresholdGate(directionTotal ? directionCorrect / directionTotal : null, 1),
    accepted_evidence_accuracy: thresholdGate(evidenceAccuracy, 1),
    paired_evidence_completeness: thresholdGate(evidenceCompleteness, 1),
    explicit_negative_pairs: thresholdGate(negativePairs ? acceptedNegativeLinks : null, 0, "max"),
    ambiguous_pairs_remain_undetermined: thresholdGate(ambiguousPairs ? acceptedAmbiguousLinks : null, 0, "max"),
  };
  const gateStatuses = Object.values(gates).map((gate) => gate.status);
  const overallStatus = gateStatuses.includes("fail")
    ? "fail"
    : positiveGoldRelations === 0
      ? "not_applicable"
      : "pass";

  return {
    repeat,
    document_relations: documentRelations,
    direction_accuracy: { correct: directionCorrect, total: directionTotal, value: directionTotal ? directionCorrect / directionTotal : null },
    row_correspondences: rowCorrespondences,
    evidence: {
      correct_pairs: correctEvidencePairs,
      required_pairs: requiredEvidencePairs,
      missing_pairs: Math.max(0, requiredEvidencePairs - correctEvidencePairs),
      accuracy: evidenceAccuracy,
      paired_completeness: evidenceCompleteness,
      invalid_pairs: invalidEvidencePairs,
      predicted_pairs: predictedEvidencePairs,
    },
    explicit_negative_pairs: negativePairs,
    accepted_links_on_negative_pairs: acceptedNegativeLinks,
    ambiguous_pairs: ambiguousPairs,
    accepted_links_on_ambiguous_pairs: acceptedAmbiguousLinks,
    positive_gold_relations: positiveGoldRelations,
    empty_positive_graph: positiveGoldRelations === 0 && documentRelations.true_positives === 0 && documentRelations.false_positives === 0,
    model_usage: sumUsage(scenarioScores),
    quality_gates: gates,
    overall_status: overallStatus,
    per_scenario: scenarioScores,
  };
}

function jaccard(left: Set<string>, right: Set<string>) {
  const union = new Set([...left, ...right]);
  if (union.size === 0) return null;
  const intersection = [...left].filter((item) => right.has(item)).length;
  return intersection / union.size;
}

export function aggregate(runScores: RunScore[]) {
  if (!runScores.length) throw new Error("At least one scored repeat is required for aggregation.");
  const metrics = ["link_precision", "link_recall", "link_f1", "row_precision", "row_recall"] as const;
  const worstRepeat: Record<string, number | null> = {};
  for (const metric of metrics) {
    const values = runScores.map((run) => {
      if (metric === "link_precision") return run.document_relations.precision;
      if (metric === "link_recall") return run.document_relations.recall;
      if (metric === "link_f1") return run.document_relations.f1;
      if (metric === "row_precision") return run.row_correspondences.precision;
      return run.row_correspondences.recall;
    }).filter((value): value is number => value !== null);
    worstRepeat[metric] = values.length ? Math.min(...values) : null;
  }
  const scenarioIds = [...new Set(runScores.flatMap((run) => run.per_scenario.map((scenario) => scenario.id)))];
  const stability = { nonempty_gold_graphs: [] as number[], empty_negative_graphs: [] as number[] };
  for (const scenarioId of scenarioIds) {
    const scenarioRuns = runScores.map((run) => run.per_scenario.find((scenario) => scenario.id === scenarioId)).filter((value): value is ScenarioScore => value !== undefined);
    if (!scenarioRuns.length) continue;
    const isPositiveGold = scenarioRuns.some((scenario) => scenario.document_relations.gold_denominator > 0);
    const hasNegativeGold = scenarioRuns.some((scenario) => scenario.explicit_negative_pairs > 0);
    if (!isPositiveGold && !hasNegativeGold) continue;
    for (let leftIndex = 0; leftIndex < scenarioRuns.length; leftIndex++) {
      for (let rightIndex = leftIndex + 1; rightIndex < scenarioRuns.length; rightIndex++) {
        const value = jaccard(new Set(scenarioRuns[leftIndex].graphRelations), new Set(scenarioRuns[rightIndex].graphRelations));
        if (value === null) continue;
        (isPositiveGold ? stability.nonempty_gold_graphs : stability.empty_negative_graphs).push(value);
      }
    }
  }
  const summarize = (values: number[]) => ({
    pairs: values.length,
    mean: values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null,
    minimum: values.length ? Math.min(...values) : null,
  });
  return {
    repeats: runScores.length,
    worst_repeat: worstRepeat,
    stability: {
      nonempty_gold_graphs: summarize(stability.nonempty_gold_graphs),
      empty_negative_graphs: summarize(stability.empty_negative_graphs),
    },
    failed_repeats: runScores.filter((run) => run.overall_status === "fail").map((run) => run.repeat),
    not_applicable_repeats: runScores.filter((run) => run.overall_status === "not_applicable").map((run) => run.repeat),
  };
}
