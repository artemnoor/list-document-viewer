import { createHash } from "node:crypto";
import { mkdir, readFile, realpath, writeFile } from "node:fs/promises";
import { isDeepStrictEqual } from "node:util";
import { fileURLToPath } from "node:url";
import { isAbsolute, relative, resolve, sep } from "node:path";
import { linkingOutputSchema } from "../src/contracts/output";
import { validateInput } from "../src/contracts/input";
import { pathContainsRowId, resolveJsonPath, rowIdExists } from "../src/linking/evidence-validation";
import { aggregate, scoreRun, type EvidencePair, type GoldLink, type ReviewedPair, type RunScore, type ScoringScenarioInput } from "./evaluation-metrics";
import { logAnnotationEvent, logAnnotationFailure } from "./annotation-logging";

type ReviewMode = "single_reviewer" | "independent_adjudication";
type SourceDocument = { path: string; sha256: string; document_id: string; extraction_id?: string; schema_version?: string };
type AnnotationScenario = {
  id: string;
  source_bundle_sha256: string;
  source_documents: SourceDocument[];
  gold_links: GoldLink[];
  reviewed_document_pairs?: ReviewedPair[];
  adjudicated_document_pairs?: ReviewedPair[];
  predictions_file?: string;
  predictions_files?: string[];
};
type AnnotationBundle = {
  version: string;
  review_mode: ReviewMode;
  annotations_complete: boolean;
  reviewer_ids: string[];
  scenarios: AnnotationScenario[];
};
type LoadedScenario = ScoringScenarioInput & {
  predictionFiles: { path: string; sha256: string; linkingRunId: string; inputHashChecks: number; inputHashUnknown: number }[];
};

const sha256Pattern = /^[a-f0-9]{64}$/;
const pairKey = (left: string, right: string) => JSON.stringify([left, right].sort());

function resolveInsideRoot(root: string, path: string, label: string) {
  if (typeof path !== "string" || !path || isAbsolute(path)) throw new Error(`${label} must be a non-empty repository-relative path.`);
  const absolutePath = resolve(root, path);
  const relativePath = relative(root, absolutePath);
  if (relativePath === ".." || relativePath.startsWith(`..${sep}`) || isAbsolute(relativePath)) {
    throw new Error(`${label} escapes the repository.`);
  }
  return absolutePath;
}

async function assertInsideRoot(root: string, path: string, label: string) {
  const canonicalRoot = await realpath(root);
  const canonicalPath = await realpath(path);
  const relativePath = relative(canonicalRoot, canonicalPath);
  if (relativePath === ".." || relativePath.startsWith(`..${sep}`) || isAbsolute(relativePath)) {
    throw new Error(`${label} escapes the repository through a symlink.`);
  }
  return canonicalPath;
}

function assertReference(reference: any, expectedDocumentId: string, documents: Map<string, any>, label: string) {
  if (!reference || reference.document_id !== expectedDocumentId || typeof reference.path !== "string" || !Object.prototype.hasOwnProperty.call(reference, "raw_value")) {
    throw new Error(`${label} must match its expected document and include an exact path/raw value.`);
  }
  const document = documents.get(expectedDocumentId);
  const actual = document ? resolveJsonPath(document, reference.path) : undefined;
  if (actual === undefined || !isDeepStrictEqual(actual, reference.raw_value)) throw new Error(`${label} path or raw value does not match the frozen source.`);
}

function validateGold(scenario: AnnotationScenario, mode: ReviewMode, documents: Map<string, any>) {
  if (!Array.isArray(scenario.gold_links)) throw new Error(`Scenario ${scenario.id} has invalid gold links.`);
  const reviews = mode === "single_reviewer" ? scenario.reviewed_document_pairs : scenario.adjudicated_document_pairs;
  if (!Array.isArray(reviews)) throw new Error(`Scenario ${scenario.id} is missing its completed pair review.`);
  const documentIds = scenario.source_documents.map((source) => source.document_id);
  const expectedPairs = new Set(documentIds.flatMap((left, index) => documentIds.slice(index + 1).map((right) => pairKey(left, right))));
  const decisions = new Map<string, string>();
  for (const review of reviews) {
    if (!review || typeof review.left_document_id !== "string" || typeof review.right_document_id !== "string" || review.left_document_id === review.right_document_id) {
      throw new Error(`Scenario ${scenario.id} has an invalid reviewed pair.`);
    }
    const key = pairKey(review.left_document_id, review.right_document_id);
    if (!expectedPairs.has(key) || decisions.has(key) || !["supported", "not_supported", "ambiguous"].includes(review.decision)) {
      throw new Error(`Scenario ${scenario.id} has an invalid or duplicate reviewed pair.`);
    }
    if (!Array.isArray(review.relationship_instances) || !Array.isArray(review.contradicting_evidence) || typeof review.ambiguity_notes !== "string") {
      throw new Error(`Scenario ${scenario.id} has an incomplete reviewed pair.`);
    }
    if (review.decision === "ambiguous" && !review.ambiguity_notes.trim()) throw new Error(`Scenario ${scenario.id} has an ambiguous pair without an uncertainty note.`);
    if (review.decision === "not_supported" && review.relationship_instances.length > 0) throw new Error(`Scenario ${scenario.id} has relationships on a negative pair.`);
    for (const evidence of review.contradicting_evidence) {
      const ids = [evidence?.source?.document_id, evidence?.target?.document_id];
      if (new Set(ids).size !== 2 || ids.some((id) => id !== review.left_document_id && id !== review.right_document_id)) {
        throw new Error(`Scenario ${scenario.id} pair evidence does not refer to its two reviewed documents.`);
      }
      assertReference(evidence.source, evidence.source.document_id, documents, "Pair source evidence");
      assertReference(evidence.target, evidence.target.document_id, documents, "Pair target evidence");
    }
    decisions.set(key, review.decision);
  }
  if (decisions.size !== expectedPairs.size) throw new Error(`Scenario ${scenario.id} is missing required pair coverage.`);

  for (const link of scenario.gold_links) {
    if (!link || typeof link.relationship_type !== "string" || !link.relationship_type.trim() || !Array.isArray(link.evidence) || link.evidence.length === 0) {
      throw new Error(`Scenario ${scenario.id} contains incomplete positive gold.`);
    }
    const { source_document_id: sourceId, target_document_id: targetId } = link;
    if (!documents.has(sourceId) || !documents.has(targetId) || sourceId === targetId) throw new Error(`Scenario ${scenario.id} gold references an unknown document.`);
    if (decisions.get(pairKey(sourceId, targetId)) !== "supported") throw new Error(`Scenario ${scenario.id} gold link is not attached to a supported pair.`);
    for (const evidence of link.evidence) {
      assertReference(evidence?.source, sourceId, documents, "Gold source evidence");
      assertReference(evidence?.target, targetId, documents, "Gold target evidence");
    }
    for (const row of link.row_correspondences ?? []) {
      if (!["supported", "not_supported", "ambiguous", undefined].includes(row.decision)) throw new Error(`Scenario ${scenario.id} has an invalid row decision.`);
      for (const evidence of [...(row.supporting_evidence ?? []), ...(row.contradicting_evidence ?? [])]) {
        assertReference(evidence?.source, sourceId, documents, "Row source evidence");
        assertReference(evidence?.target, targetId, documents, "Row target evidence");
      }
      if (row.decision === "supported") {
        const sourceRowId = row.source_row_id, targetRowId = row.target_row_id;
        if (typeof sourceRowId !== "string" || typeof targetRowId !== "string" || !rowIdExists(documents.get(sourceId), sourceRowId) || !rowIdExists(documents.get(targetId), targetRowId)) {
          throw new Error(`Scenario ${scenario.id} contains a supported row with missing row IDs.`);
        }
        if (!Array.isArray(row.supporting_evidence) || row.supporting_evidence.length === 0) throw new Error(`Scenario ${scenario.id} supported rows require evidence.`);
        if (row.supporting_evidence.some((item: any) => !pathContainsRowId(documents.get(sourceId), item?.source?.path ?? "", sourceRowId) || !pathContainsRowId(documents.get(targetId), item?.target?.path ?? "", targetRowId))) {
          throw new Error(`Scenario ${scenario.id} row evidence does not pass through its cited rows.`);
        }
      }
    }
  }
  for (const review of reviews) {
    if (review.decision === "supported" && !scenario.gold_links.some((link) => pairKey(link.source_document_id, link.target_document_id) === pairKey(review.left_document_id, review.right_document_id))) {
      throw new Error(`Scenario ${scenario.id} has a supported pair without a supported gold relation.`);
    }
    if (review.decision !== "supported" && scenario.gold_links.some((link) => pairKey(link.source_document_id, link.target_document_id) === pairKey(review.left_document_id, review.right_document_id))) {
      throw new Error(`Scenario ${scenario.id} has gold relations on a negative or ambiguous pair.`);
    }
  }
}

export async function verifySourceHashes(root: string, scenario: Pick<AnnotationScenario, "id" | "source_bundle_sha256" | "source_documents">) {
  if (!Array.isArray(scenario.source_documents) || scenario.source_documents.length < 2 || !sha256Pattern.test(scenario.source_bundle_sha256)) {
    throw new Error(`Scenario ${scenario.id} has invalid source hash metadata.`);
  }
  const sourceRows: SourceDocument[] = [];
  const documentsById = new Map<string, any>();
  for (const source of scenario.source_documents) {
    if (!source || typeof source.document_id !== "string" || !sha256Pattern.test(source.sha256)) throw new Error(`Scenario ${scenario.id} has invalid source-document metadata.`);
    const filePath = resolveInsideRoot(root, source.path, "Source document path");
    const normalizedPath = relative(root, filePath).replaceAll("\\", "/");
    if (source.path !== normalizedPath) throw new Error(`Scenario ${scenario.id} source paths must be normalized repository-relative paths.`);
    const canonicalPath = await assertInsideRoot(root, filePath, "Source document path");
    const bytes = await readFile(canonicalPath);
    const hash = createHash("sha256").update(bytes).digest("hex");
    if (hash !== source.sha256) throw new Error(`Scenario ${scenario.id} source file hash does not match its frozen annotation.`);
    const document = JSON.parse(bytes.toString("utf8"));
    if (document.document_id !== source.document_id || (source.extraction_id && document.extraction_id !== source.extraction_id) || (source.schema_version && document.schema_version !== source.schema_version)) {
      throw new Error(`Scenario ${scenario.id} source document identity changed.`);
    }
    if (documentsById.has(document.document_id)) throw new Error(`Scenario ${scenario.id} contains duplicate source document IDs.`);
    documentsById.set(document.document_id, document);
    sourceRows.push({ path: normalizedPath, sha256: hash, document_id: document.document_id });
  }
  const checked = validateInput([...documentsById.values()]);
  if (!checked.success) throw new Error(`Scenario ${scenario.id} source documents fail the Structured Extraction contract.`);
  const bundleHash = createHash("sha256").update(sourceRows.map((source) => `${source.path}\0${source.sha256}`).join("\n")).digest("hex");
  if (bundleHash !== scenario.source_bundle_sha256) throw new Error(`Scenario ${scenario.id} source bundle hash does not match its source files.`);
  return { documentsById, documentCount: sourceRows.length, sourceBundleHash: bundleHash };
}

export function validatePredictionResult(raw: unknown, expectedDocuments: Map<string, any>) {
  const payload = raw && typeof raw === "object" && "result" in raw && (raw as any).result && typeof (raw as any).result === "object"
    ? (raw as any).result
    : raw;
  const parsed = linkingOutputSchema.safeParse(payload);
  if (!parsed.success) throw new Error("Prediction file does not satisfy the pinned Document Linking output schema.");
  const result = parsed.data;
  if (result.input_documents.length !== expectedDocuments.size) throw new Error("Prediction input-document coverage does not match frozen gold.");
  const inputById = new Map<string, (typeof result.input_documents)[number]>();
  for (const input of result.input_documents) {
    if (inputById.has(input.document_id)) throw new Error("Prediction input documents contain duplicate document IDs.");
    inputById.set(input.document_id, input);
  }
  let inputHashChecks = 0, inputHashUnknown = 0;
  for (const [documentId, document] of expectedDocuments) {
    const input = inputById.get(documentId);
    if (!input || input.extraction_id !== document.extraction_id || input.document_type !== document.document_type || input.version !== document.version || input.schema_version !== document.schema_version) {
      throw new Error("Prediction input-document identity does not match frozen gold.");
    }
    if (typeof document.input_version === "number") {
      if (input.input_version !== document.input_version) throw new Error("Prediction input version does not match frozen gold.");
    }
    if (typeof document.input_hash === "string") {
      if (!sha256Pattern.test(document.input_hash) || input.input_hash !== document.input_hash) throw new Error("Prediction input hash does not match frozen gold.");
      inputHashChecks++;
    } else {
      inputHashUnknown++;
    }
  }
  for (const link of result.links) {
    if (!expectedDocuments.has(link.source_document_id) || !expectedDocuments.has(link.target_document_id) || link.source_document_id === link.target_document_id) {
      throw new Error("Prediction link references a document outside frozen gold.");
    }
  }
  return { result, inputHashChecks, inputHashUnknown };
}

async function readJson(path: string) {
  return JSON.parse(await readFile(path, "utf8"));
}

function predictionPaths(scenario: AnnotationScenario) {
  if (scenario.predictions_file && scenario.predictions_files) throw new Error(`Scenario ${scenario.id} must use one prediction-path representation.`);
  const paths = scenario.predictions_files ?? (scenario.predictions_file ? [scenario.predictions_file] : []);
  if (!Array.isArray(paths) || paths.length === 0 || paths.some((path) => typeof path !== "string" || !path)) {
    throw new Error(`Scenario ${scenario.id} has no prediction files.`);
  }
  const normalized = paths.map((path) => path.replaceAll("\\", "/"));
  if (new Set(normalized).size !== normalized.length) throw new Error(`Scenario ${scenario.id} repeats a prediction file.`);
  return paths;
}

async function loadScenario(root: string, scenario: AnnotationScenario, mode: ReviewMode): Promise<LoadedScenario> {
  if (!scenario || typeof scenario.id !== "string" || !scenario.id.trim() || !sha256Pattern.test(scenario.source_bundle_sha256)) {
    throw new Error("Annotation bundle contains an invalid scenario entry.");
  }
  const source = await verifySourceHashes(root, scenario);
  validateGold(scenario, mode, source.documentsById);
  const files = predictionPaths(scenario);
  const predictionFiles: LoadedScenario["predictionFiles"] = [];
  const results: any[] = [];
  const runIds = new Set<string>();
  for (const path of files) {
    const filePath = resolveInsideRoot(root, path, "Prediction path");
    const canonicalPath = await assertInsideRoot(root, filePath, "Prediction path");
    const bytes = await readFile(canonicalPath);
    const raw = JSON.parse(bytes.toString("utf8"));
    const validated = validatePredictionResult(raw, source.documentsById);
    if (runIds.has(validated.result.linking_run_id)) throw new Error(`Scenario ${scenario.id} repeats a linking_run_id; cached replay is not an independent repeat.`);
    runIds.add(validated.result.linking_run_id);
    results.push(validated.result);
    predictionFiles.push({
      path: relative(root, canonicalPath).replaceAll("\\", "/"),
      sha256: createHash("sha256").update(bytes).digest("hex"),
      linkingRunId: validated.result.linking_run_id,
      inputHashChecks: validated.inputHashChecks,
      inputHashUnknown: validated.inputHashUnknown,
    });
  }
  const reviewedPairs = (mode === "single_reviewer" ? scenario.reviewed_document_pairs : scenario.adjudicated_document_pairs) as ReviewedPair[];
  return {
    id: scenario.id,
    goldLinks: scenario.gold_links,
    reviewedPairs,
    result: results[0],
    sourceDocumentsById: source.documentsById,
    predictionFiles,
    // The loader keeps all repeats separately; evaluateBundle selects the corresponding one.
    allResults: results,
  } as LoadedScenario & { allResults: any[] };
}

function parseArguments(args: string[]) {
  let bundlePath: string | undefined;
  let outputPath: string | undefined;
  for (let index = 0; index < args.length; index++) {
    const option = args[index];
    const value = args[index + 1];
    if (option === "--annotations" && value && !value.startsWith("--")) {
      bundlePath = value;
      index++;
    } else if (option === "--out" && value && !value.startsWith("--")) {
      outputPath = value;
      index++;
    } else if (!option.startsWith("--") && !bundlePath) {
      bundlePath = option;
    } else {
      throw new Error("Usage: npm run eval:links -- [--annotations] <annotations.json> [--out <report.json>]");
    }
  }
  if (!bundlePath) throw new Error("Usage: npm run eval:links -- [--annotations] <annotations.json> [--out <report.json>]");
  return { bundlePath, outputPath };
}

export async function evaluateBundle(bundle: AnnotationBundle, root: string) {
  if (!bundle || typeof bundle !== "object" || bundle.annotations_complete !== true || !Array.isArray(bundle.scenarios) || bundle.scenarios.length === 0) {
    throw new Error("Annotations are incomplete; scoring requires a frozen, human-reviewed gold set.");
  }
  if (bundle.review_mode !== "single_reviewer" && bundle.review_mode !== "independent_adjudication") {
    throw new Error("Annotations must declare a supported human review mode.");
  }
  if (!Array.isArray(bundle.reviewer_ids) || new Set(bundle.reviewer_ids).size !== bundle.reviewer_ids.length ||
    (bundle.review_mode === "single_reviewer" ? bundle.reviewer_ids.length !== 1 : bundle.reviewer_ids.length < 3) ||
    bundle.reviewer_ids.some((id) => typeof id !== "string" || !id.trim() || /pending|anonymous|unknown/i.test(id))) {
    throw new Error("Annotations have invalid reviewer identities for their declared review mode.");
  }
  const scenarioIds = new Set(bundle.scenarios.map((scenario) => scenario?.id));
  if (scenarioIds.size !== bundle.scenarios.length || bundle.scenarios.some((scenario) => !Array.isArray(scenario?.gold_links))) {
    throw new Error("Annotations contain duplicate or malformed scenarios.");
  }
  const loaded = await Promise.all(bundle.scenarios.map((scenario) => loadScenario(root, scenario, bundle.review_mode)));
  const repeatCounts = new Set(loaded.map((scenario) => scenario.predictionFiles.length));
  if (repeatCounts.size !== 1) throw new Error("Every scenario must provide the same number of independent prediction repeats.");
  const repeatCount = [...repeatCounts][0];
  const runScores: RunScore[] = [];
  for (let repeatIndex = 0; repeatIndex < repeatCount; repeatIndex++) {
    const inputs = loaded.map((scenario) => ({
      id: scenario.id,
      goldLinks: scenario.goldLinks,
      reviewedPairs: scenario.reviewedPairs,
      result: (scenario as LoadedScenario & { allResults: any[] }).allResults[repeatIndex],
      sourceDocumentsById: scenario.sourceDocumentsById,
    }));
    const runScore = scoreRun(repeatIndex + 1, inputs);
    runScores.push(runScore);
    for (const scenario of runScore.per_scenario) {
      const loadedScenario = loaded.find((item) => item.id === scenario.id)!;
      const file = loadedScenario.predictionFiles[repeatIndex];
      logAnnotationEvent("INFO", "evaluation_repeat_scored", {
        scenarioId: scenario.id,
        repeat: repeatIndex + 1,
        linkingRunId: file.linkingRunId,
        goldRelations: scenario.document_relations.gold_denominator,
        predictedDenominator: scenario.document_relations.predicted_denominator,
        truePositives: scenario.document_relations.true_positives,
        falsePositives: scenario.document_relations.false_positives,
        falseNegatives: scenario.document_relations.false_negatives,
      });
    }
  }
  return {
    annotations_complete: true,
    review_mode: bundle.review_mode,
    scenarios: bundle.scenarios.length,
    repeats: repeatCount,
    per_run: runScores,
    aggregate: aggregate(runScores),
    source_validation: {
      status: "passed",
      source_files: loaded.reduce((sum, scenario) => sum + scenario.sourceDocumentsById.size, 0),
      scenario_hashes: bundle.scenarios.map((scenario) => ({ id: scenario.id, sha256: scenario.source_bundle_sha256 })),
    },
    prediction_validation: loaded.map((scenario) => ({ id: scenario.id, files: scenario.predictionFiles })),
  };
}

async function main() {
  try {
    const args = parseArguments(process.argv.slice(2));
    const root = process.cwd();
    const bundlePath = resolveInsideRoot(root, args.bundlePath, "Annotation path");
    const canonicalBundlePath = await assertInsideRoot(root, bundlePath, "Annotation path");
    const bundle = await readJson(canonicalBundlePath) as AnnotationBundle;
    logAnnotationEvent("INFO", "evaluation_started", {
      annotationFile: relative(root, canonicalBundlePath).replaceAll("\\", "/"),
      scenarioCount: Array.isArray(bundle.scenarios) ? bundle.scenarios.length : 0,
      reviewMode: bundle.review_mode,
    });
    const report = await evaluateBundle(bundle, root);
    const reportText = `${JSON.stringify(report, null, 2)}\n`;
    if (args.outputPath) {
      const outputPath = resolveInsideRoot(root, args.outputPath, "Report output path");
      await mkdir(resolve(outputPath, ".."), { recursive: true });
      await writeFile(outputPath, reportText);
    }
    console.log(reportText);
  } catch (error) {
    logAnnotationFailure("evaluation_rejected_or_failed", error);
    process.exitCode = 1;
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) void main();
