import { test } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { aggregate, scoreRun, type GoldLink, type PredictionLink, type ReviewedPair, type ScoringScenarioInput } from "../scripts/evaluation-metrics";
import { validatePredictionResult, verifySourceHashes } from "../scripts/evaluate-links";

const sourceA = { document_id: "doc-a", fields: { alpha: "A-raw", beta: "A-other" }, tables: [] };
const sourceB = { document_id: "doc-b", fields: { alpha: "B-raw", beta: "B-other" }, tables: [] };
const sourceC = { document_id: "doc-c", fields: { alpha: "C-raw", beta: "C-other" }, tables: [] };
const documents = new Map<string, unknown>([["doc-a", sourceA], ["doc-b", sourceB], ["doc-c", sourceC]]);

function evidence(sourceId = "doc-a", targetId = "doc-b", sourcePath = "fields.alpha", targetPath = "fields.alpha"): any {
  const values: Record<string, any> = { "doc-a": sourceA, "doc-b": sourceB, "doc-c": sourceC };
  return {
    source: { document_id: sourceId, path: sourcePath, raw_value: sourcePath.endsWith("beta") ? values[sourceId].fields.beta : values[sourceId].fields.alpha },
    target: { document_id: targetId, path: targetPath, raw_value: targetPath.endsWith("beta") ? values[targetId].fields.beta : values[targetId].fields.alpha },
  };
}

function gold(type = "relates_to", sourceId = "doc-a", targetId = "doc-b", rows?: [string, string][]): GoldLink {
  return {
    relationship_type: type,
    source_document_id: sourceId,
    target_document_id: targetId,
    evidence: [evidence(sourceId, targetId)],
    ...(rows ? { row_correspondences: rows.map(([source_row_id, target_row_id]) => ({ source_row_id, target_row_id, decision: "supported" })) } : {}),
  };
}

function prediction(type = "relates_to", sourceId = "doc-a", targetId = "doc-b", options: { rows?: [string, string]; evidence?: any[]; status?: PredictionLink["status"] } = {}): PredictionLink {
  return {
    relationship_type: type,
    source_document_id: sourceId,
    target_document_id: targetId,
    ...(options.rows ? { source_row_id: options.rows[0], target_row_id: options.rows[1] } : {}),
    evidence: options.evidence ?? [evidence(sourceId, targetId)],
    status: options.status ?? "proposed",
    verification_status: "not_reviewed",
  };
}

function pair(left: string, right: string, decision: ReviewedPair["decision"]): any {
  return {
    left_document_id: left,
    right_document_id: right,
    decision,
    relationship_instances: [],
    contradicting_evidence: [],
    ambiguity_notes: decision === "ambiguous" ? "Synthetic ambiguity for scorer mechanics." : "",
  };
}

function scenario(goldLinks: GoldLink[], reviewedPairs: any[], links: PredictionLink[]): ScoringScenarioInput {
  return {
    id: "synthetic-score-case",
    goldLinks,
    reviewedPairs,
    result: {
      linking_run_id: "run-test-1",
      links,
      processing_metadata: { llm: { calls: 1, input_tokens: 12, output_tokens: 5, errors: 0 } },
    },
    sourceDocumentsById: documents,
  };
}

test("each repeat is scored separately and the worst repeat remains visible", () => {
  const goldLinks = [gold()];
  const reviewedPairs = [pair("doc-a", "doc-b", "supported")];
  const first = scoreRun(1, [scenario(goldLinks, reviewedPairs, [prediction()])]);
  const second = scoreRun(2, [scenario(goldLinks, reviewedPairs, [])]);
  const combined = aggregate([first, second]);

  assert.equal(first.document_relations.true_positives, 1);
  assert.equal(first.document_relations.f1, 1);
  assert.equal(second.document_relations.false_negatives, 1);
  assert.equal(second.document_relations.recall, 0);
  assert.equal(second.document_relations.f1, 0);
  assert.equal(combined.worst_repeat.link_f1, 0);
  assert.deepEqual(combined.failed_repeats, [2]);
});

test("reverse direction is a false positive and false negative", () => {
  const result = scoreRun(1, [scenario(
    [gold()],
    [pair("doc-a", "doc-b", "supported")],
    [prediction("relates_to", "doc-b", "doc-a", { evidence: [evidence("doc-b", "doc-a")] })],
  )]);

  assert.deepEqual(
    [result.document_relations.true_positives, result.document_relations.false_positives, result.document_relations.false_negatives],
    [0, 1, 1],
  );
  assert.deepEqual(result.direction_accuracy, { correct: 0, total: 1, value: 0 });
});

test("multiple row matches on one document relation count once for links and separately for rows", () => {
  const result = scoreRun(1, [scenario(
    [gold("relates_to", "doc-a", "doc-b", [["a-row-1", "b-row-1"], ["a-row-2", "b-row-2"]])],
    [pair("doc-a", "doc-b", "supported")],
    [
      prediction("relates_to", "doc-a", "doc-b", { rows: ["a-row-1", "b-row-1"] }),
      prediction("relates_to", "doc-a", "doc-b", { rows: ["a-row-2", "b-row-2"] }),
    ],
  )]);

  assert.equal(result.document_relations.true_positives, 1);
  assert.equal(result.document_relations.false_positives, 0);
  assert.equal(result.row_correspondences.true_positives, 2);
  assert.equal(result.row_correspondences.false_positives, 0);
});

test("evidence is paired to its own true positive and crossed references do not match", () => {
  const firstGold = { ...gold("relation-a"), evidence: [evidence("doc-a", "doc-b", "fields.alpha", "fields.alpha")] };
  const secondGold = { ...gold("relation-b"), evidence: [evidence("doc-a", "doc-b", "fields.beta", "fields.beta")] };
  const firstPrediction = prediction("relation-a", "doc-a", "doc-b", { evidence: [evidence("doc-a", "doc-b", "fields.alpha", "fields.beta")] });
  const secondPrediction = prediction("relation-b", "doc-a", "doc-b", { evidence: [evidence("doc-a", "doc-b", "fields.beta", "fields.alpha")] });
  const result = scoreRun(1, [scenario(
    [firstGold, secondGold],
    [pair("doc-a", "doc-b", "supported")],
    [firstPrediction, secondPrediction],
  )]);

  assert.equal(result.document_relations.true_positives, 2);
  assert.equal(result.evidence.accuracy, 1);
  assert.equal(result.evidence.correct_pairs, 0);
  assert.equal(result.evidence.required_pairs, 2);
  assert.equal(result.evidence.paired_completeness, 0);
});

test("missing, extra, and duplicate document relations retain exact denominators", () => {
  const result = scoreRun(1, [scenario(
    [gold("relation-a"), gold("relation-b")],
    [pair("doc-a", "doc-b", "supported")],
    [prediction("relation-a"), prediction("relation-a"), prediction("relation-extra")],
  )]);

  assert.deepEqual(
    [result.document_relations.true_positives, result.document_relations.false_positives, result.document_relations.false_negatives],
    [1, 2, 1],
  );
  assert.equal(result.document_relations.predicted_denominator, 3);
  assert.equal(result.document_relations.gold_denominator, 2);
});

test("negative and ambiguous pairs have separate gates, and an empty negative graph stays N/A", () => {
  const reviews = [pair("doc-a", "doc-b", "not_supported"), pair("doc-a", "doc-c", "ambiguous")];
  const result = scoreRun(1, [scenario(
    [],
    reviews,
    [prediction("false-link", "doc-a", "doc-b", { status: "confirmed" }), prediction("uncertain-link", "doc-a", "doc-c", { status: "review" })],
  )]);
  assert.equal(result.document_relations.precision, 0);
  assert.equal(result.accepted_links_on_negative_pairs, 1);
  assert.equal(result.accepted_links_on_ambiguous_pairs, 0);
  assert.equal(result.quality_gates.explicit_negative_pairs.status, "fail");
  assert.equal(result.quality_gates.ambiguous_pairs_remain_undetermined.status, "pass");

  const empty = scoreRun(1, [scenario([], [pair("doc-a", "doc-b", "not_supported")], [])]);
  assert.equal(empty.empty_positive_graph, true);
  assert.equal(empty.document_relations.precision, null);
  assert.equal(empty.document_relations.recall, null);
  assert.equal(empty.document_relations.f1, null);
  assert.equal(empty.quality_gates.explicit_negative_pairs.status, "pass");
});

test("malformed prediction results are rejected instead of becoming empty graphs", () => {
  assert.throws(() => validatePredictionResult({}, documents), /pinned Document Linking output schema/);
});

test("source bundle hashes are checked again before scoring", async (t) => {
  const root = mkdtempSync(resolve(tmpdir(), "phystech-trace-scorer-hash-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  mkdirSync(resolve(root, "evaluation/sources"), { recursive: true });
  const fixturePaths = [
    "fixtures/upstream-structured-extraction-1.2.0/contract-2026-0315.json",
    "fixtures/upstream-structured-extraction-1.2.0/invoice-2026-0408.json",
  ];
  const sources = fixturePaths.map((fixture, index) => {
    const bytes = readFileSync(resolve(fixture));
    const path = `evaluation/sources/document-${index + 1}.json`;
    writeFileSync(resolve(root, path), bytes);
    const document = JSON.parse(bytes.toString("utf8"));
    return { path, sha256: createHash("sha256").update(bytes).digest("hex"), document_id: document.document_id, extraction_id: document.extraction_id, schema_version: document.schema_version };
  });
  const sourceBundleHash = createHash("sha256").update(sources.map((source) => `${source.path}\0${source.sha256}`).join("\n")).digest("hex");
  const scenario = { id: "hash-check", source_bundle_sha256: sourceBundleHash, source_documents: sources };
  const valid = await verifySourceHashes(root, scenario);
  assert.equal(valid.documentCount, 2);

  writeFileSync(resolve(root, sources[0].path), `${readFileSync(resolve(root, sources[0].path), "utf8")}\n`);
  await assert.rejects(verifySourceHashes(root, scenario), /source file hash does not match/);
});
