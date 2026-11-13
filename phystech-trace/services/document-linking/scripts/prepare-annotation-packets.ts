import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { relative, resolve } from "node:path";
import { validateInput } from "../src/contracts/input";

type Scenario = { id: string; documents: string[] };
const root = process.cwd();
const source = JSON.parse(await readFile(resolve(root, "evaluation/scenarios.json"), "utf8")) as { scenarios: Scenario[] };
const output = resolve(root, "evaluation/annotation-packets");
await mkdir(output, { recursive: true });
const index: { scenario_id: string; reviewer_packets: string[]; adjudication_packet: string; document_count: number; pair_count: number; source_bundle_sha256: string }[] = [];

function pairTemplate(left: string, right: string) {
  return { left_document_id: left, right_document_id: right, decision: "pending", relationship_instances: [], contradicting_evidence: [], ambiguity_notes: "" };
}
function reviewerTemplate(scenarioId: string, reviewerNumber: number, documents: string[], digest: string, sourceFiles: unknown[]) {
  const pairs = documents.flatMap((left, index) => documents.slice(index + 1).map(right => pairTemplate(left, right)));
  return { packet_version: "1.0.0", scenario_id: scenarioId, source_bundle_sha256: digest, reviewer_id: `reviewer-${reviewerNumber}-pending`, review_status: "pending", source_documents: sourceFiles, instruction: "Review only these original Structured Extraction JSON files. Do not inspect model predictions. Decide every unordered document pair, record direction for each supported relation, annotate row matches and supporting/contradictory source paths, and mark genuine ambiguity explicitly.", document_pair_decisions: pairs };
}

for (const scenario of source.scenarios) {
  const docs = await Promise.all(scenario.documents.map(async path => {
    const bytes = await readFile(resolve(root, path));
    const parsed = JSON.parse(bytes.toString("utf8"));
    return { path: relative(root, resolve(root, path)).replaceAll("\\", "/"), sha256: createHash("sha256").update(bytes).digest("hex"), parsed };
  }));
  const checked = validateInput(docs.map(item => item.parsed));
  if (!checked.success) throw new Error(`Invalid annotation fixture ${scenario.id}: ${JSON.stringify(checked.diagnostics)}`);
  const documentIds = checked.documents.map(document => document.document_id);
  if (new Set(documentIds).size !== documentIds.length) throw new Error(`Duplicate document IDs in annotation fixture ${scenario.id}`);
  const sourceBundleHash = createHash("sha256").update(docs.map(item => `${item.path}\0${item.sha256}`).join("\n")).digest("hex");
  const source = { files: docs.map(({ path, sha256, parsed }) => ({ path, sha256, document_id: parsed.document_id, extraction_id: parsed.extraction_id, schema_version: parsed.schema_version })) };
  const reviewerFiles = [1, 2].map(number => `${scenario.id}.reviewer-${number}.json`);
  for (const [index, name] of reviewerFiles.entries()) {
    const packet = reviewerTemplate(scenario.id, index + 1, documentIds, sourceBundleHash, source.files);
    await writeFile(resolve(output, name), `${JSON.stringify(packet, null, 2)}\n`);
  }
  const adjudication = reviewerTemplate(scenario.id, 3, documentIds, sourceBundleHash, source.files);
  Object.assign(adjudication, { reviewer_id: "adjudicator-pending", review_status: "pending", instruction: "After both independent reviews are complete, adjudicate every disagreement against the original JSON. Preserve uncertainty; do not consult model outputs until labels are frozen." });
  await writeFile(resolve(output, `${scenario.id}.adjudication.json`), `${JSON.stringify(adjudication, null, 2)}\n`);
  const pairCount = documentIds.length * (documentIds.length - 1) / 2;
  index.push({ scenario_id: scenario.id, reviewer_packets: reviewerFiles, adjudication_packet: `${scenario.id}.adjudication.json`, document_count: documentIds.length, pair_count: pairCount, source_bundle_sha256: sourceBundleHash });
}

const indexText = [
  "# Independent annotation packets", "",
  "These packets contain no model predictions or labels. Complete both independent reviewer JSON files before the adjudication file. Review all unordered document pairs, including pairs with no relationship. For each supported relation, record direction, row matches, supporting/contradictory source paths, and uncertainty. Evidence paths and raw values must be copied from the original source JSON. The source hashes detect fixture changes.", "",
  "| Scenario | Documents | Pairs to decide | Source bundle SHA-256 | Packets |", "|---|---:|---:|---|---|",
  ...index.map(item => `| ${item.scenario_id} | ${item.document_count} | ${item.pair_count} | \`${item.source_bundle_sha256}\` | ${item.reviewer_packets.join(", ")}; ${item.adjudication_packet} |`), "",
  "Use `review_status: \"complete\"` only after every pair is decided. Pair decisions are `supported`, `not_supported`, or `ambiguous`. A supported pair must contain one or more relationship instances. Each relationship instance has a `decision` (`supported` or `ambiguous`), `relationship_type`, directed source/target document IDs, optional source/target row IDs, `supporting_evidence`, `contradicting_evidence`, `row_correspondences`, and `ambiguity_notes`. Evidence entries use `{source:{document_id,path,raw_value},target:{document_id,path,raw_value},explanation}`. Each row correspondence carries source/target row IDs, a `supported`/`not_supported`/`ambiguous` decision, evidence, contrary evidence, and notes. Pair-level contrary evidence uses the same evidence-entry shape. Do not use a blank `relationship_instances` array to mean an unreviewed pair.", "",
  "After both reviewers finish, adjudicate all pairs in the third packet. `npm run eval:compile-annotations` verifies pair coverage, reviewer IDs, and source hashes, then writes independent gold labels to `evaluation/expert-gold.json`. It refuses pending or mismatched packets. Add prediction files only after the gold is frozen.", "",
].join("\n");
await writeFile(resolve(output, "README.md"), indexText);
await writeFile(resolve(output, "manifest.json"), `${JSON.stringify({ version: "1.0.0", scenarios: index }, null, 2)}\n`);
console.log(`Prepared ${index.length} independent review packets (${index.reduce((sum, item) => sum + item.document_count, 0)} document appearances; source fixtures validated).`);
