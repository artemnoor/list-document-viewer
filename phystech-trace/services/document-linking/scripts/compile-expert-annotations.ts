import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { isDeepStrictEqual } from "node:util";
import { relative, resolve } from "node:path";
import { pathContainsRowId, resolveJsonPath, rowIdExists } from "../src/linking/evidence-validation";

const root = process.cwd(), packetDirectory = resolve(root, "evaluation/annotation-packets"), manifest = JSON.parse(await readFile(resolve(packetDirectory, "manifest.json"), "utf8"));
type Packet = { scenario_id: string; source_bundle_sha256: string; reviewer_id: string; review_status: string; source_documents: { path: string; sha256: string; document_id: string }[]; document_pair_decisions: any[] };
const readPacket = async (file: string): Promise<Packet> => JSON.parse(await readFile(resolve(packetDirectory, file), "utf8"));
const validDecisions = new Set(["supported", "not_supported", "ambiguous"]);
const pairKey = (left: string, right: string) => [left, right].sort().join("\0");
const documents = new Map<string, any>();

function assertSourceReference(reference: any, expectedDocumentId?: string) {
  if (!reference || typeof reference.document_id !== "string" || typeof reference.path !== "string") throw new Error("Evidence must name a document_id and exact JSON path.");
  if (expectedDocumentId && reference.document_id !== expectedDocumentId) throw new Error(`Evidence document ${reference.document_id} does not match expected side ${expectedDocumentId}.`);
  const document = documents.get(reference.document_id);
  if (!document) throw new Error(`Evidence references unknown document ${reference.document_id}.`);
  const actual = resolveJsonPath(document, reference.path);
  if (actual === undefined || !Object.prototype.hasOwnProperty.call(reference, "raw_value") || !isDeepStrictEqual(actual, reference.raw_value)) throw new Error(`Evidence path/raw_value mismatch: ${reference.document_id} ${reference.path}.`);
}
function validateEvidence(items: any[], sourceId: string, targetId: string) {
  if (!Array.isArray(items)) throw new Error("Evidence must be an array.");
  for (const item of items) {
    assertSourceReference(item?.source, sourceId);
    assertSourceReference(item?.target, targetId);
  }
}
function validatePairEvidence(items: any[], leftId: string, rightId: string) {
  if (!Array.isArray(items)) throw new Error("Evidence must be an array.");
  for (const item of items) {
    const ids = [item?.source?.document_id, item?.target?.document_id];
    if (!ids.every((id) => typeof id === "string") || new Set(ids).size !== 2 || ids.some((id) => id !== leftId && id !== rightId)) {
      throw new Error(`Pair evidence must reference exactly ${leftId} and ${rightId}.`);
    }
    assertSourceReference(item.source);
    assertSourceReference(item.target);
  }
}

const outputScenarios: any[] = [], reviewerIds = new Set<string>();
for (const scenario of manifest.scenarios) {
  const reviewers = await Promise.all(scenario.reviewer_packets.map(readPacket)) as Packet[];
  const adjudication = await readPacket(scenario.adjudication_packet);
  if ([...reviewers, adjudication].some(packet => packet.scenario_id !== scenario.scenario_id || packet.source_bundle_sha256 !== scenario.source_bundle_sha256 || packet.review_status !== "complete" || !packet.reviewer_id.trim())) throw new Error(`Scenario ${scenario.scenario_id} still has pending, mismatched, or anonymous packets.`);
  if (new Set([reviewers[0].reviewer_id, reviewers[1].reviewer_id, adjudication.reviewer_id]).size !== 3) throw new Error(`Scenario ${scenario.scenario_id} needs two independent reviewers and a separate adjudicator.`);
  reviewers.forEach(packet => reviewerIds.add(packet.reviewer_id)); reviewerIds.add(adjudication.reviewer_id);

  const packetFiles = adjudication.source_documents;
  const inputDocuments: any[] = [];
  for (const file of packetFiles) {
    const absolute = resolve(root, file.path), rel = relative(root, absolute);
    if (rel === ".." || rel.startsWith(`..${process.platform === "win32" ? "\\" : "/"}`)) throw new Error(`Source path escapes repository: ${file.path}`);
    const bytes = await readFile(absolute);
    if (createHash("sha256").update(bytes).digest("hex") !== file.sha256) throw new Error(`Source file changed since annotation packet generation: ${file.path}`);
    const document = JSON.parse(bytes.toString("utf8"));
    if (document.document_id !== file.document_id) throw new Error(`Source document ID changed: ${file.path}`);
    documents.set(document.document_id, document); inputDocuments.push(document);
  }
  const docIds = packetFiles.map(file => file.document_id), expectedPairs = new Set(docIds.flatMap((left, index) => docIds.slice(index + 1).map(right => pairKey(left, right))));
  for (const packet of [...reviewers, adjudication]) {
    const actualPairs = new Set<string>();
    for (const item of packet.document_pair_decisions) {
      const key = pairKey(item.left_document_id, item.right_document_id);
      if (!expectedPairs.has(key) || actualPairs.has(key) || !validDecisions.has(item.decision)) throw new Error(`Invalid or duplicate pair decision in ${scenario.scenario_id} for ${item.left_document_id}/${item.right_document_id}.`);
      actualPairs.add(key);
    }
    if (actualPairs.size !== expectedPairs.size) throw new Error(`Scenario ${scenario.scenario_id}, reviewer ${packet.reviewer_id} has undecided document pairs.`);
  }
  const pairReviews = adjudication.document_pair_decisions;
  const goldLinks: any[] = [];
  for (const pair of pairReviews) {
    validatePairEvidence(pair.contradicting_evidence ?? [], pair.left_document_id, pair.right_document_id);
    if (pair.decision !== "supported" && pair.relationship_instances?.length) throw new Error(`Non-supported pair ${pair.left_document_id}/${pair.right_document_id} cannot contain gold supported relationships.`);
    if (pair.decision === "supported" && (!Array.isArray(pair.relationship_instances) || pair.relationship_instances.length === 0)) throw new Error(`Supported pair ${pair.left_document_id}/${pair.right_document_id} must list its relationship instances.`);
    if (pair.decision === "supported" && !pair.relationship_instances.some((item: any) => item.decision === "supported")) throw new Error(`Supported pair ${pair.left_document_id}/${pair.right_document_id} needs at least one supported relationship instance.`);
    for (const relationship of pair.relationship_instances ?? []) {
      if (!validDecisions.has(relationship.decision) || !["supported", "ambiguous"].includes(relationship.decision)) throw new Error(`Invalid relationship decision in ${scenario.scenario_id}.`);
      const sourceId = relationship.source_document_id, targetId = relationship.target_document_id;
      if (![pair.left_document_id, pair.right_document_id].includes(sourceId) || ![pair.left_document_id, pair.right_document_id].includes(targetId) || sourceId === targetId) throw new Error("Relationship direction must use the two documents in its pair.");
      if (typeof relationship.relationship_type !== "string" || !relationship.relationship_type.trim()) throw new Error("Every relationship needs an expert-defined relationship_type.");
      validateEvidence(relationship.supporting_evidence ?? [], sourceId, targetId);
      validateEvidence(relationship.contradicting_evidence ?? [], sourceId, targetId);
      const rowCorrespondences = relationship.row_correspondences ?? [];
      for (const row of rowCorrespondences) {
        if (!validDecisions.has(row.decision)) throw new Error("Every row correspondence needs a supported, not_supported, or ambiguous decision.");
        if (row.decision === "supported") {
          if (typeof row.source_row_id !== "string" || typeof row.target_row_id !== "string" || !rowIdExists(documents.get(sourceId), row.source_row_id) || !rowIdExists(documents.get(targetId), row.target_row_id)) throw new Error("Supported row correspondence must cite existing row IDs on both sides.");
          if (!Array.isArray(row.supporting_evidence) || row.supporting_evidence.length === 0) throw new Error("Supported row correspondence must include evidence.");
          if (row.supporting_evidence.some((item: any) => !pathContainsRowId(documents.get(sourceId), item?.source?.path ?? "", row.source_row_id) || !pathContainsRowId(documents.get(targetId), item?.target?.path ?? "", row.target_row_id))) throw new Error("Supported row evidence paths must pass through their cited row IDs.");
        }
        validateEvidence(row.supporting_evidence ?? [], sourceId, targetId);
        validateEvidence(row.contradicting_evidence ?? [], sourceId, targetId);
      }
      if (relationship.decision === "supported") {
        if (pair.decision !== "supported" || !relationship.supporting_evidence?.length) throw new Error("Supported gold relation requires a supported pair and paired source/target evidence.");
        goldLinks.push({ relationship_type: relationship.relationship_type.trim(), source_document_id: sourceId, target_document_id: targetId, ...(typeof relationship.source_row_id === "string" ? { source_row_id: relationship.source_row_id } : {}), ...(typeof relationship.target_row_id === "string" ? { target_row_id: relationship.target_row_id } : {}), evidence: relationship.supporting_evidence.map((item: any) => ({ source: item.source, target: item.target })), row_correspondences: rowCorrespondences, contradicting_evidence: relationship.contradicting_evidence ?? [], ambiguity_notes: relationship.ambiguity_notes ?? "" });
      }
    }
  }
  outputScenarios.push({ id: scenario.scenario_id, source_bundle_sha256: scenario.source_bundle_sha256, source_documents: packetFiles, adjudicated_document_pairs: pairReviews, gold_links: goldLinks });
}

const result = { version: "1.0.0", annotations_complete: true, instructions: "Independent labels adjudicated against original Structured Extraction JSON before predictions were shown.", reviewer_ids: [...reviewerIds], scenarios: outputScenarios };
await writeFile(resolve(root, "evaluation/expert-gold.json"), `${JSON.stringify(result, null, 2)}\n`);
console.log(`Compiled independent labels for ${outputScenarios.length} scenarios into evaluation/expert-gold.json.`);
