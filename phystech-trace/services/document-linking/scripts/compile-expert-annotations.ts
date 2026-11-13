import { createHash } from "node:crypto";
import { mkdir, readFile, realpath, writeFile } from "node:fs/promises";
import { isDeepStrictEqual } from "node:util";
import { isAbsolute, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { pathContainsRowId, resolveJsonPath, rowIdExists } from "../src/linking/evidence-validation";
import { validateInput } from "../src/contracts/input";
import { logAnnotationEvent, logAnnotationFailure } from "./annotation-logging";

type ReviewMode = "single" | "expert";
type SourceDocument = {
  path: string;
  sha256: string;
  document_id: string;
  extraction_id?: string;
  schema_version?: string;
};
type Packet = {
  review_mode?: string;
  scenario_id: string;
  source_bundle_sha256: string;
  reviewer_id: string;
  review_status: string;
  source_documents: SourceDocument[];
  document_pair_decisions: any[];
};
type ManifestScenario = {
  scenario_id: string;
  reviewer_packets: string[];
  adjudication_packet?: string;
  document_count: number;
  pair_count: number;
  source_bundle_sha256: string;
};
type Options = { mode: ReviewMode; packetDirectory: string; outputPath: string };

const validPairDecisions = new Set(["supported", "not_supported", "ambiguous"]);
const validRelationshipDecisions = new Set(["supported", "ambiguous"]);
const validRowDecisions = new Set(["supported", "not_supported", "ambiguous"]);
const pairKey = (left: string, right: string) => [left, right].sort().join("\0");

function parseOptions(args: string[]): Options {
  let mode: ReviewMode = "expert";
  let packetDirectory = "evaluation/annotation-packets";
  let outputPath = "evaluation/expert-gold.json";
  let modeWasSet = false;
  let packetDirectoryWasSet = false;
  let outputPathWasSet = false;
  for (let index = 0; index < args.length; index++) {
    const option = args[index];
    const value = args[index + 1];
    if (option === "--mode" && (value === "single" || value === "expert")) {
      mode = value;
      modeWasSet = true;
      index++;
    } else if (option === "--packets" && value && !value.startsWith("--")) {
      packetDirectory = value;
      packetDirectoryWasSet = true;
      index++;
    } else if (option === "--out" && value && !value.startsWith("--")) {
      outputPath = value;
      outputPathWasSet = true;
      index++;
    } else {
      throw new Error("Usage: npm run eval:compile-annotations -- [--mode single|expert] [--packets <packet-directory>] [--out <gold-file>]");
    }
  }
  if (!modeWasSet && packetDirectoryWasSet) {
    throw new Error("Specify --mode single or --mode expert when compiling a custom packet directory.");
  }
  if (mode === "single" && !packetDirectoryWasSet) {
    packetDirectory = "evaluation/mvp-v1/packets";
  }
  if (mode === "single" && !outputPathWasSet) {
    outputPath = "evaluation/mvp-v1/gold.json";
  }
  return { mode, packetDirectory, outputPath };
}

function resolveInsideRoot(root: string, path: string, label: string) {
  const absolute = resolve(root, path);
  const relativePath = relative(root, absolute);
  if (relativePath === ".." || relativePath.startsWith(`..${sep}`) || isAbsolute(relativePath)) {
    throw new Error(`${label} must stay inside the repository: ${path}`);
  }
  return absolute;
}

async function readPacket(packetDirectory: string, file: string): Promise<Packet> {
  if (typeof file !== "string" || file.length === 0 || isAbsolute(file)) throw new Error("Packet manifest contains an invalid packet path.");
  const path = resolveInsideRoot(packetDirectory, file, "Packet path");
  const value = JSON.parse(await readFile(path, "utf8")) as Packet;
  if (!value || typeof value !== "object") throw new Error(`Annotation packet is not an object: ${file}`);
  return value;
}

function validateReviewerIdentity(value: unknown, scenarioId: string) {
  if (typeof value !== "string" || value.length === 0 || value !== value.trim() || value.length > 128 || /[\u0000-\u001f\u007f]/.test(value)) {
    throw new Error(`Scenario ${scenarioId} has an invalid reviewer identity.`);
  }
  if (/^(?:pending|reviewer-\d+-pending|adjudicator-pending|replace_with_reviewer_id|anonymous|unknown)$/i.test(value)) {
    throw new Error(`Scenario ${scenarioId} has an invalid reviewer identity placeholder.`);
  }
  return value;
}

function assertSourceReference(reference: any, expectedDocumentId?: string) {
  if (!reference || typeof reference.document_id !== "string" || typeof reference.path !== "string" || !Object.prototype.hasOwnProperty.call(reference, "raw_value")) {
    throw new Error("Evidence must name a document, exact JSON path, and checked raw value.");
  }
  if (expectedDocumentId && reference.document_id !== expectedDocumentId) {
    throw new Error(`Evidence document ${reference.document_id} does not match expected side ${expectedDocumentId}.`);
  }
  const document = documents.get(reference.document_id);
  if (!document) throw new Error(`Evidence references unknown document ${reference.document_id}.`);
  const actual = resolveJsonPath(document, reference.path);
  if (actual === undefined || !isDeepStrictEqual(actual, reference.raw_value)) {
    throw new Error(`Evidence path/raw_value mismatch: ${reference.document_id} ${reference.path}.`);
  }
}

function validateEvidence(items: any[], sourceId: string, targetId: string) {
  if (!Array.isArray(items)) throw new Error("Evidence must be an array.");
  for (const item of items) {
    if (typeof item?.explanation !== "string" || !item.explanation.trim()) throw new Error("Each evidence pair needs a reviewer explanation.");
    assertSourceReference(item.source, sourceId);
    assertSourceReference(item.target, targetId);
  }
}

function validatePairEvidence(items: any[], leftId: string, rightId: string) {
  if (!Array.isArray(items)) throw new Error("Pair-level evidence must be an array.");
  for (const item of items) {
    const ids = [item?.source?.document_id, item?.target?.document_id];
    if (!ids.every((id) => typeof id === "string") || new Set(ids).size !== 2 || ids.some((id) => id !== leftId && id !== rightId)) {
      throw new Error(`Pair evidence must reference exactly ${leftId} and ${rightId}.`);
    }
    if (typeof item?.explanation !== "string" || !item.explanation.trim()) throw new Error("Each pair-level evidence item needs a reviewer explanation.");
    assertSourceReference(item.source);
    assertSourceReference(item.target);
  }
}

function validatePairCoverage(packet: Packet, expectedPairs: Set<string>) {
  if (!Array.isArray(packet.document_pair_decisions)) throw new Error(`Scenario ${packet.scenario_id} has no complete document-pair decisions.`);
  const actualPairs = new Set<string>();
  for (const item of packet.document_pair_decisions) {
    const left = item?.left_document_id, right = item?.right_document_id;
    if (typeof left !== "string" || typeof right !== "string" || left === right) {
      throw new Error(`Scenario ${packet.scenario_id} contains an invalid document pair.`);
    }
    const key = pairKey(left, right);
    if (!expectedPairs.has(key) || actualPairs.has(key) || !validPairDecisions.has(item.decision)) {
      throw new Error(`Scenario ${packet.scenario_id} has an invalid or duplicate pair decision for ${left}/${right}.`);
    }
    if (!Array.isArray(item.relationship_instances) || !Array.isArray(item.contradicting_evidence) || typeof item.ambiguity_notes !== "string") {
      throw new Error(`Scenario ${packet.scenario_id} has an incomplete pair decision for ${left}/${right}.`);
    }
    if (item.decision === "ambiguous" && !item.ambiguity_notes.trim()) {
      throw new Error(`Ambiguous pair ${left}/${right} needs an uncertainty note.`);
    }
    actualPairs.add(key);
  }
  if (actualPairs.size !== expectedPairs.size) {
    throw new Error(`Scenario ${packet.scenario_id}, reviewer ${packet.reviewer_id} has undecided document pairs.`);
  }
}

function validateRelationship(relationship: any, pair: any, scenarioId: string) {
  if (!relationship || !validRelationshipDecisions.has(relationship.decision)) {
    throw new Error(`Invalid relationship decision in ${scenarioId}.`);
  }
  const sourceId = relationship.source_document_id, targetId = relationship.target_document_id;
  if (![pair.left_document_id, pair.right_document_id].includes(sourceId) || ![pair.left_document_id, pair.right_document_id].includes(targetId) || sourceId === targetId) {
    throw new Error("Relationship direction must use the two documents in its pair.");
  }
  if (typeof relationship.relationship_type !== "string" || !relationship.relationship_type.trim()) {
    throw new Error(`Every relationship in ${scenarioId} needs a reviewer-defined relationship_type.`);
  }
  if (!Array.isArray(relationship.supporting_evidence) || !Array.isArray(relationship.contradicting_evidence) || !Array.isArray(relationship.row_correspondences) || typeof relationship.ambiguity_notes !== "string") {
    throw new Error(`Relationship in ${scenarioId} has incomplete evidence or row review fields.`);
  }
  validateEvidence(relationship.supporting_evidence, sourceId, targetId);
  validateEvidence(relationship.contradicting_evidence, sourceId, targetId);

  for (const row of relationship.row_correspondences) {
    if (!row || !validRowDecisions.has(row.decision) || !Array.isArray(row.supporting_evidence) || !Array.isArray(row.contradicting_evidence) || typeof row.ambiguity_notes !== "string") {
      throw new Error("Every row correspondence needs a decision, evidence arrays, and notes.");
    }
    if (row.decision === "ambiguous" && !row.ambiguity_notes.trim()) throw new Error("An ambiguous row correspondence needs an uncertainty note.");
    if (row.decision === "supported") {
      if (typeof row.source_row_id !== "string" || typeof row.target_row_id !== "string" || !rowIdExists(documents.get(sourceId), row.source_row_id) || !rowIdExists(documents.get(targetId), row.target_row_id)) {
        throw new Error("Supported row correspondence must cite existing row IDs on both sides.");
      }
      if (row.supporting_evidence.length === 0) throw new Error("Supported row correspondence must include evidence.");
      if (row.supporting_evidence.some((item: any) => !pathContainsRowId(documents.get(sourceId), item?.source?.path ?? "", row.source_row_id) || !pathContainsRowId(documents.get(targetId), item?.target?.path ?? "", row.target_row_id))) {
        throw new Error("Supported row evidence paths must pass through their cited row IDs.");
      }
    }
    validateEvidence(row.supporting_evidence, sourceId, targetId);
    validateEvidence(row.contradicting_evidence, sourceId, targetId);
  }

  if (relationship.decision === "ambiguous" && !relationship.ambiguity_notes.trim()) {
    throw new Error(`Ambiguous relationship in ${scenarioId} needs an uncertainty note.`);
  }
  if (relationship.decision === "supported" && (!relationship.supporting_evidence.length || pair.decision !== "supported")) {
    throw new Error("Supported gold relation requires a supported pair and paired source/target evidence.");
  }
}

const documents = new Map<string, any>();

async function validateSourceBundle(root: string, expectedPaths: string[], packetSourceDocuments: SourceDocument[], scenarioId: string) {
  if (!Array.isArray(packetSourceDocuments) || packetSourceDocuments.length !== expectedPaths.length) {
    throw new Error(`Scenario ${scenarioId} source-document coverage does not match the configured bundle.`);
  }
  const canonicalRoot = await realpath(root);
  const inputDocuments: any[] = [];
  const sourceRows: SourceDocument[] = [];
  const seenDocumentIds = new Set<string>();

  for (const [index, configuredPath] of expectedPaths.entries()) {
    const absolutePath = resolve(root, configuredPath);
    const normalizedPath = relative(root, absolutePath).replaceAll("\\", "/");
    const source = packetSourceDocuments[index];
    if (!source || source.path !== normalizedPath || isAbsolute(source.path) || !/^[a-f0-9]{64}$/i.test(source.sha256)) {
      throw new Error(`Scenario ${scenarioId} has an invalid source path or hash entry.`);
    }
    const lexicalRelative = relative(root, absolutePath);
    if (lexicalRelative === ".." || lexicalRelative.startsWith(`..${sep}`) || isAbsolute(lexicalRelative)) {
      throw new Error(`Source path escapes repository: ${source.path}`);
    }
    const actualPath = await realpath(absolutePath);
    const actualRelative = relative(canonicalRoot, actualPath);
    if (actualRelative === ".." || actualRelative.startsWith(`..${sep}`) || isAbsolute(actualRelative)) {
      throw new Error(`Source path escapes repository through a symlink: ${source.path}`);
    }
    const bytes = await readFile(actualPath);
    const actualHash = createHash("sha256").update(bytes).digest("hex");
    if (actualHash !== source.sha256) throw new Error(`Source file hash changed since packet preparation: ${source.path}`);
    const parsed = JSON.parse(bytes.toString("utf8"));
    if (parsed.document_id !== source.document_id || (source.extraction_id && parsed.extraction_id !== source.extraction_id) || (source.schema_version && parsed.schema_version !== source.schema_version)) {
      throw new Error(`Source document identity changed since packet preparation: ${source.path}`);
    }
    if (seenDocumentIds.has(parsed.document_id)) throw new Error(`Scenario ${scenarioId} repeats a source document identity.`);
    seenDocumentIds.add(parsed.document_id);
    inputDocuments.push(parsed);
    sourceRows.push({
      path: normalizedPath,
      sha256: actualHash,
      document_id: parsed.document_id,
      extraction_id: parsed.extraction_id,
      schema_version: parsed.schema_version,
    });
  }

  const checked = validateInput(inputDocuments);
  if (!checked.success) throw new Error(`Scenario ${scenarioId} source documents fail the Extraction contract.`);
  const actualBundleHash = createHash("sha256").update(sourceRows.map((item) => `${item.path}\0${item.sha256}`).join("\n")).digest("hex");
  for (const document of checked.documents) documents.set(document.document_id, document);
  return { sourceDocuments: sourceRows, documents: checked.documents, sourceBundleHash: actualBundleHash };
}

async function compileAnnotations(root: string, options: Options) {
  const packetDirectory = resolveInsideRoot(root, options.packetDirectory, "Packet directory");
  const outputPath = resolveInsideRoot(root, options.outputPath, "Gold output path");
  const manifestPath = resolve(packetDirectory, "manifest.json");
  const manifest = JSON.parse(await readFile(manifestPath, "utf8")) as { review_mode?: string; scenarios: ManifestScenario[] };
  const configuredScenarios = JSON.parse(await readFile(resolve(root, "evaluation/scenarios.json"), "utf8")) as { scenarios: { id: string; documents: string[] }[] };
  if (!Array.isArray(manifest.scenarios) || !Array.isArray(configuredScenarios.scenarios)) throw new Error("Annotation packet manifest or scenario configuration is invalid.");
  const expectedMode = options.mode === "single" ? "single_reviewer" : "independent_adjudication";
  if (manifest.review_mode !== expectedMode && !(options.mode === "expert" && manifest.review_mode === undefined)) {
    throw new Error(`Packet manifest review mode does not match requested mode ${options.mode}.`);
  }
  const configuredById = new Map(configuredScenarios.scenarios.map((scenario) => [scenario.id, scenario]));
  if (configuredById.size !== configuredScenarios.scenarios.length || manifest.scenarios.length !== configuredById.size) {
    throw new Error("Annotation manifest is missing required scenario coverage or contains duplicate scenarios.");
  }
  const manifestIds = new Set(manifest.scenarios.map((scenario) => scenario.scenario_id));
  if (manifestIds.size !== configuredById.size || [...configuredById.keys()].some((id) => !manifestIds.has(id))) {
    throw new Error("Annotation manifest is missing required scenario coverage or contains unknown scenarios.");
  }

  const outputScenarios: any[] = [];
  const reviewerIds = new Set<string>();
  let singleReviewerId: string | undefined;
  let totalPairCount = 0;
  for (const scenario of manifest.scenarios) {
    const configuredScenario = configuredById.get(scenario.scenario_id);
    if (!configuredScenario || !Array.isArray(scenario.reviewer_packets) || !/^[a-f0-9]{64}$/i.test(scenario.source_bundle_sha256)) {
      throw new Error(`Invalid annotation manifest entry for ${scenario.scenario_id}.`);
    }
    const reviewers = await Promise.all(scenario.reviewer_packets.map((file) => readPacket(packetDirectory, file)));
    let packets: Packet[];
    let labels: Packet;
    if (options.mode === "single") {
      if (reviewers.length !== 1 || scenario.adjudication_packet || reviewers[0].review_mode !== "single_reviewer") {
        throw new Error(`Scenario ${scenario.scenario_id} must have exactly one single-reviewer packet and no adjudication packet.`);
      }
      packets = reviewers;
      labels = reviewers[0];
    } else {
      if (reviewers.length !== 2 || !scenario.adjudication_packet) {
        throw new Error(`Scenario ${scenario.scenario_id} must have two independent reviews and a separate adjudication packet.`);
      }
      const adjudication = await readPacket(packetDirectory, scenario.adjudication_packet);
      if (adjudication.review_mode && adjudication.review_mode !== "independent_adjudication") {
        throw new Error(`Scenario ${scenario.scenario_id} has a packet from a different review mode.`);
      }
      packets = [...reviewers, adjudication];
      labels = adjudication;
    }

    if (packets.some((packet) => packet.scenario_id !== scenario.scenario_id || packet.source_bundle_sha256 !== scenario.source_bundle_sha256 || packet.review_status !== "complete")) {
      throw new Error(`Scenario ${scenario.scenario_id} still has pending or mismatched packets.`);
    }
    const ids = packets.map((packet) => validateReviewerIdentity(packet.reviewer_id, scenario.scenario_id));
    if (options.mode === "single") {
      if (singleReviewerId && singleReviewerId !== ids[0]) throw new Error("Single-reviewer MVP packets must use the same human reviewer identity.");
      singleReviewerId = ids[0];
      reviewerIds.add(ids[0]);
    } else {
      if (new Set(ids).size !== 3) throw new Error(`Scenario ${scenario.scenario_id} needs two distinct reviewers and a separate adjudicator.`);
      ids.forEach((id) => reviewerIds.add(id));
    }

    const sourceBundle = await validateSourceBundle(root, configuredScenario.documents, labels.source_documents, scenario.scenario_id);
    if (sourceBundle.sourceBundleHash !== scenario.source_bundle_sha256) throw new Error(`Scenario ${scenario.scenario_id} source bundle hash does not match its current sources.`);
    if (packets.some((packet) => !isDeepStrictEqual(packet.source_documents, labels.source_documents))) {
      throw new Error(`Scenario ${scenario.scenario_id} packets do not share the same source-document snapshot.`);
    }
    if (packets.some((packet) => packet.source_bundle_sha256 !== sourceBundle.sourceBundleHash)) {
      throw new Error(`Scenario ${scenario.scenario_id} packet source hash does not match its source files.`);
    }
    if (sourceBundle.documents.length !== scenario.document_count) throw new Error(`Scenario ${scenario.scenario_id} document count does not match the packet manifest.`);
    documents.clear();
    sourceBundle.documents.forEach((document) => documents.set(document.document_id, document));

    const documentIds = sourceBundle.documents.map((document) => document.document_id);
    const expectedPairs = new Set(documentIds.flatMap((left, index) => documentIds.slice(index + 1).map((right) => pairKey(left, right))));
    if (expectedPairs.size !== scenario.pair_count) throw new Error(`Scenario ${scenario.scenario_id} pair count does not match the packet manifest.`);
    for (const packet of packets) validatePairCoverage(packet, expectedPairs);
    totalPairCount += expectedPairs.size;

    const reviewedPairs = labels.document_pair_decisions;
    const goldLinks: any[] = [];
    for (const pair of reviewedPairs) {
      validatePairEvidence(pair.contradicting_evidence, pair.left_document_id, pair.right_document_id);
      if (pair.decision !== "supported" && pair.relationship_instances.length > 0 && pair.decision !== "ambiguous") {
        throw new Error(`Non-supported pair ${pair.left_document_id}/${pair.right_document_id} cannot contain relationship instances.`);
      }
      if (pair.decision === "ambiguous" && pair.relationship_instances.some((item: any) => item.decision === "supported")) {
        throw new Error(`Ambiguous pair ${pair.left_document_id}/${pair.right_document_id} cannot contain a supported gold relationship.`);
      }
      if (pair.decision === "supported" && (!pair.relationship_instances.length || !pair.relationship_instances.some((item: any) => item.decision === "supported"))) {
        throw new Error(`Supported pair ${pair.left_document_id}/${pair.right_document_id} needs at least one supported relationship instance.`);
      }
      for (const relationship of pair.relationship_instances) {
        validateRelationship(relationship, pair, scenario.scenario_id);
        if (relationship.decision === "supported") {
          goldLinks.push({
            relationship_type: relationship.relationship_type.trim(),
            source_document_id: relationship.source_document_id,
            target_document_id: relationship.target_document_id,
            ...(typeof relationship.source_row_id === "string" ? { source_row_id: relationship.source_row_id } : {}),
            ...(typeof relationship.target_row_id === "string" ? { target_row_id: relationship.target_row_id } : {}),
            evidence: relationship.supporting_evidence.map((item: any) => ({ source: item.source, target: item.target })),
            row_correspondences: relationship.row_correspondences,
            contradicting_evidence: relationship.contradicting_evidence,
            ambiguity_notes: relationship.ambiguity_notes,
          });
        }
      }
    }
    outputScenarios.push({
      id: scenario.scenario_id,
      source_bundle_sha256: scenario.source_bundle_sha256,
      source_documents: labels.source_documents,
      [options.mode === "single" ? "reviewed_document_pairs" : "adjudicated_document_pairs"]: reviewedPairs,
      gold_links: goldLinks,
    });
    logAnnotationEvent("INFO", "annotation_scenario_compiled", {
      mode: options.mode,
      scenarioId: scenario.scenario_id,
      reviewerCount: new Set(ids).size,
      documentCount: documentIds.length,
      pairCount: expectedPairs.size,
      goldLinkCount: goldLinks.length,
    });
  }

  const result = {
    version: "1.0.0",
    review_mode: expectedMode,
    annotations_complete: true,
    instructions: options.mode === "single"
      ? "Single-reviewer MVP labels reviewed against original Structured Extraction JSON before predictions were shown. This is not an independent multi-expert adjudication."
      : "Independent labels adjudicated against original Structured Extraction JSON before predictions were shown.",
    reviewer_ids: [...reviewerIds],
    scenarios: outputScenarios,
  };
  await mkdir(resolve(outputPath, ".."), { recursive: true });
  await writeFile(outputPath, `${JSON.stringify(result, null, 2)}\n`);
  logAnnotationEvent("INFO", "annotation_gold_compiled", {
    mode: options.mode,
    scenarioCount: outputScenarios.length,
    reviewerCount: reviewerIds.size,
    reviewedPairCount: totalPairCount,
    outputPath: relative(root, outputPath).replaceAll("\\", "/"),
  });
}

async function main() {
  let mode: ReviewMode = "expert";
  try {
    const options = parseOptions(process.argv.slice(2));
    mode = options.mode;
    logAnnotationEvent("INFO", "annotation_compile_started", { mode });
    await compileAnnotations(process.cwd(), options);
  } catch (error) {
    logAnnotationFailure("annotation_compile_rejected_or_failed", error, { mode });
    process.exitCode = 1;
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) void main();
