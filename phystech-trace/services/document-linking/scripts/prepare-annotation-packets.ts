import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { relative, resolve, sep, isAbsolute } from "node:path";
import { fileURLToPath } from "node:url";
import { validateInput } from "../src/contracts/input";
import { logAnnotationEvent, logAnnotationFailure } from "./annotation-logging";

type ReviewMode = "single" | "expert";
type Scenario = { id: string; documents: string[]; focus?: string };
type SourceDocument = { path: string; sha256: string; document_id: string; extraction_id?: string; schema_version?: string };

function parseOptions(args: string[]) {
  let mode: ReviewMode = "expert";
  let outputPath: string | undefined;
  for (let index = 0; index < args.length; index++) {
    const option = args[index];
    const value = args[index + 1];
    if (option === "--mode" && (value === "single" || value === "expert")) {
      mode = value;
      index++;
    } else if (option === "--out" && value && !value.startsWith("--")) {
      outputPath = value;
      index++;
    } else {
      throw new Error("Usage: npm run eval:prepare-annotations -- [--mode single|expert] [--out <packet-directory>]");
    }
  }
  return { mode, outputPath };
}

function resolveInsideRoot(root: string, path: string) {
  const absolute = resolve(root, path);
  const relativePath = relative(root, absolute);
  if (relativePath === ".." || relativePath.startsWith(`..${sep}`) || isAbsolute(relativePath)) {
    throw new Error(`Output path must stay inside the repository: ${path}`);
  }
  return absolute;
}

function pairTemplate(left: string, right: string) {
  return {
    left_document_id: left,
    right_document_id: right,
    decision: "pending",
    relationship_instances: [],
    contradicting_evidence: [],
    ambiguity_notes: "",
  };
}

function reviewerTemplate(
  scenarioId: string,
  reviewerNumber: number,
  documents: string[],
  digest: string,
  sourceFiles: SourceDocument[],
  mode: ReviewMode,
) {
  const pairs = documents.flatMap((left, index) => documents.slice(index + 1).map((right) => pairTemplate(left, right)));
  const packet = {
    ...(mode === "single" ? { review_mode: "single_reviewer" } : {}),
    packet_version: "1.0.0",
    scenario_id: scenarioId,
    source_bundle_sha256: digest,
    reviewer_id: mode === "single" ? "pending" : `reviewer-${reviewerNumber}-pending`,
    review_status: "pending",
    source_documents: sourceFiles,
    instruction: mode === "single"
      ? "One human reviewer must inspect these original Structured Extraction JSON files without seeing model predictions. Decide every unordered document pair, record supported and unsupported relationships, direction, row matches, exact supporting and contradictory source paths/raw values, and genuine ambiguity. Use the same real reviewer identity across every packet."
      : "Review only these original Structured Extraction JSON files. Do not inspect model predictions. Decide every unordered document pair, record direction for each supported relation, annotate row matches and supporting/contradictory source paths, and mark genuine ambiguity explicitly.",
    document_pair_decisions: pairs,
  };
  return packet;
}

async function preparePackets(root: string, mode: ReviewMode, configuredOutput: string | undefined) {
  const outputPath = configuredOutput ?? (mode === "single" ? "evaluation/mvp-v1/packets" : "evaluation/annotation-packets");
  const output = resolveInsideRoot(root, outputPath);
  const scenarioConfig = JSON.parse(await readFile(resolve(root, "evaluation/scenarios.json"), "utf8")) as { scenarios: Scenario[] };
  if (!Array.isArray(scenarioConfig.scenarios) || scenarioConfig.scenarios.length === 0) {
    throw new Error("Scenario configuration must contain at least one scenario.");
  }

  await mkdir(output, { recursive: true });
  const index: {
    scenario_id: string;
    reviewer_packets: string[];
    adjudication_packet?: string;
    document_count: number;
    pair_count: number;
    source_bundle_sha256: string;
  }[] = [];
  let documentAppearances = 0;

  for (const scenario of scenarioConfig.scenarios) {
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(scenario.id) || !Array.isArray(scenario.documents) || scenario.documents.length < 2) {
      throw new Error(`Invalid annotation scenario configuration: ${scenario.id || "unknown"}`);
    }
    const docs = await Promise.all(scenario.documents.map(async (path) => {
      if (isAbsolute(path)) throw new Error(`Annotation source path must be repository-relative: ${path}`);
      const absolutePath = resolve(root, path);
      const relativePath = relative(root, absolutePath);
      if (relativePath === ".." || relativePath.startsWith(`..${sep}`) || isAbsolute(relativePath)) {
        throw new Error(`Annotation source path escapes the repository: ${path}`);
      }
      const bytes = await readFile(absolutePath);
      const parsed = JSON.parse(bytes.toString("utf8"));
      return {
        path: relativePath.replaceAll("\\", "/"),
        sha256: createHash("sha256").update(bytes).digest("hex"),
        parsed,
      };
    }));
    const checked = validateInput(docs.map((item) => item.parsed));
    if (!checked.success) {
      throw new Error(`Invalid annotation fixture ${scenario.id}: ${JSON.stringify(checked.diagnostics)}`);
    }
    const documentIds = checked.documents.map((document) => document.document_id);
    if (new Set(documentIds).size !== documentIds.length) throw new Error(`Duplicate document IDs in annotation fixture ${scenario.id}`);
    const sourceBundleHash = createHash("sha256").update(docs.map((item) => `${item.path}\0${item.sha256}`).join("\n")).digest("hex");
    const sourceFiles: SourceDocument[] = docs.map(({ path, sha256, parsed }) => ({
      path,
      sha256,
      document_id: parsed.document_id,
      extraction_id: parsed.extraction_id,
      schema_version: parsed.schema_version,
    }));
    const reviewerFiles = mode === "single"
      ? [`${scenario.id}.single-reviewer.json`]
      : [`${scenario.id}.reviewer-1.json`, `${scenario.id}.reviewer-2.json`];

    for (const [index, name] of reviewerFiles.entries()) {
      const packet = reviewerTemplate(scenario.id, index + 1, documentIds, sourceBundleHash, sourceFiles, mode);
      await writeFile(resolve(output, name), `${JSON.stringify(packet, null, 2)}\n`);
    }
    const pairCount = documentIds.length * (documentIds.length - 1) / 2;
    const entry: (typeof index)[number] = {
      scenario_id: scenario.id,
      reviewer_packets: reviewerFiles,
      document_count: documentIds.length,
      pair_count: pairCount,
      source_bundle_sha256: sourceBundleHash,
    };
    if (mode === "expert") {
      const adjudication = reviewerTemplate(scenario.id, 3, documentIds, sourceBundleHash, sourceFiles, mode);
      Object.assign(adjudication, {
        reviewer_id: "adjudicator-pending",
        review_status: "pending",
        instruction: "After both independent reviews are complete, adjudicate every disagreement against the original JSON. Preserve uncertainty; do not consult model outputs until labels are frozen.",
      });
      entry.adjudication_packet = `${scenario.id}.adjudication.json`;
      await writeFile(resolve(output, entry.adjudication_packet), `${JSON.stringify(adjudication, null, 2)}\n`);
    }
    index.push(entry);
    documentAppearances += documentIds.length;
    logAnnotationEvent("DEBUG", "annotation_scenario_prepared", {
      mode,
      scenarioId: scenario.id,
      documentCount: documentIds.length,
      pairCount,
    });
  }

  const modeName = mode === "single" ? "single-reviewer MVP" : "independent expert";
  const instructions = mode === "single"
    ? "These packets contain no model predictions or labels. One human reviewer must complete every unordered document pair, including negative and ambiguous decisions, and record exact row/evidence paths and raw values before predictions are added. Use the same real reviewer identity in every packet. A single reviewer is not an adjudication by multiple experts. Source hashes bind the packets to the reviewed fixture files."
    : "These packets contain no model predictions or labels. Complete both independent reviewer JSON files before the adjudication file. Review all unordered document pairs, including pairs with no relationship. For each supported relation, record direction, row matches, supporting/contradictory source paths, and uncertainty. Evidence paths and raw values must be copied from the original source JSON. The source hashes detect fixture changes.";
  const tableRows = index.map((item) => {
    const packets = item.adjudication_packet
      ? `${item.reviewer_packets.join(", ")}; ${item.adjudication_packet}`
      : item.reviewer_packets.join(", ");
    return `| ${item.scenario_id} | ${item.document_count} | ${item.pair_count} | \`${item.source_bundle_sha256}\` | ${packets} |`;
  });
  const readme = [
    `# ${modeName} annotation packets`,
    "",
    instructions,
    "",
    "| Scenario | Documents | Pairs to decide | Source bundle SHA-256 | Packets |",
    "|---|---:|---:|---|---|",
    ...tableRows,
    "",
    "Use `review_status: \"complete\"` only after every pair is decided. Pair decisions are `supported`, `not_supported`, or `ambiguous`; pending pairs are never negative labels. Evidence paths and raw values must exactly match the original JSON. Do not add or inspect model predictions until the gold is frozen.",
    "",
    mode === "single"
      ? "Compile with `npm run eval:compile-annotations -- --mode single --packets <packet-directory> --out <gold-file>`. The output is explicitly marked `review_mode: \"single_reviewer\"` and is not an adjudicated multi-expert result."
      : "After both reviewers finish, adjudicate all pairs in the third packet. Compile with `npm run eval:compile-annotations -- --mode expert --packets <packet-directory> --out <gold-file>`. The compiler verifies pair coverage, reviewer IDs, source hashes, evidence paths, and raw values.",
    "",
  ].join("\n");
  await writeFile(resolve(output, "README.md"), readme);
  await writeFile(resolve(output, "manifest.json"), `${JSON.stringify({
    version: "1.0.0",
    review_mode: mode === "single" ? "single_reviewer" : "independent_adjudication",
    scenarios: index,
  }, null, 2)}\n`);
  logAnnotationEvent("INFO", "annotation_packets_prepared", {
    mode,
    scenarioCount: index.length,
    documentAppearances,
    outputDirectory: relative(root, output).replaceAll("\\", "/"),
  });
}

async function main() {
  let mode: ReviewMode = "expert";
  try {
    const options = parseOptions(process.argv.slice(2));
    mode = options.mode;
    logAnnotationEvent("INFO", "annotation_prepare_started", { mode });
    await preparePackets(process.cwd(), options.mode, options.outputPath);
  } catch (error) {
    logAnnotationFailure("annotation_prepare_rejected_or_failed", error, { mode });
    process.exitCode = 1;
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) void main();
