import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { isDeepStrictEqual } from "node:util";
import { isAbsolute, relative, resolve, sep } from "node:path";
import { schemaRegistry, validateExtraction } from "../extraction/schema-registry.mjs";

export const MVP_EXTRACTION_THRESHOLDS = Object.freeze({
  critical_field_recall: 1,
  noncritical_field_recall: 0.95,
  accepted_value_source_correctness: 1,
  row_recall: 0.95,
});

const SHA256 = /^[a-f0-9]{64}$/;
const REVIEWER_PLACEHOLDERS = new Set(["", "unknown", "anonymous", "reviewer", "todo", "tbd", "pending", "test", "placeholder", "n/a"]);
const KNOWN_DOCUMENT_TYPES = new Set(Object.keys(schemaRegistry));

function fail(code) {
  const error = new Error(code);
  error.code = code;
  throw error;
}

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function nonEmpty(value) {
  return typeof value === "string" && value.trim().length > 0;
}

function hasOnlyKeys(value, allowed) {
  return Object.keys(value).every((key) => allowed.has(key));
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function safeResolve(base, value) {
  if (!nonEmpty(value) || isAbsolute(value)) fail("PATH_INVALID");
  const basePath = resolve(base);
  const fullPath = resolve(basePath, value);
  const relativePath = relative(basePath, fullPath);
  if (relativePath === ".." || relativePath.startsWith(`..${sep}`) || isAbsolute(relativePath)) fail("PATH_OUTSIDE_ROOT");
  return fullPath;
}

function resolveSourcePath(source, sourcePath) {
  if (sourcePath.startsWith("#/")) {
    let pointer;
    try {
      pointer = decodeURIComponent(sourcePath.slice(1));
    } catch {
      fail("GOLD_SOURCE_PATH_INVALID");
    }
    let current = source;
    for (const token of pointer.slice(1).split("/")) {
      const key = token.replace(/~1/g, "/").replace(/~0/g, "~");
      if (Array.isArray(current) && /^(0|[1-9]\d*)$/.test(key)) current = current[Number(key)];
      else if (isRecord(current)) current = current[key];
      else current = undefined;
      if (current === undefined) fail("GOLD_SOURCE_PATH_NOT_FOUND");
    }
    return current;
  }
  const matches = [];
  const visit = (value) => {
    if (Array.isArray(value)) {
      for (const item of value) visit(item);
    } else if (isRecord(value)) {
      if (["id", "self_ref", "source_ref", "ref"].some((key) => value[key] === sourcePath)) matches.push(value);
      for (const item of Object.values(value)) visit(item);
    }
  };
  visit(source);
  if (!matches.length) fail("GOLD_SOURCE_PATH_NOT_FOUND");
  return matches[0];
}

function stringValues(value, output = []) {
  if (typeof value === "string") output.push(value);
  else if (Array.isArray(value)) for (const item of value) stringValues(item, output);
  else if (isRecord(value)) for (const item of Object.values(value)) stringValues(item, output);
  return output;
}

function checkProvenanceSubset(actual, expected) {
  if (!isRecord(actual) || !isRecord(expected)) return false;
  return Object.entries(expected).every(([key, value]) => isDeepStrictEqual(actual[key], value));
}

function ratio(numerator, denominator) {
  return denominator === 0 ? null : numerator / denominator;
}

function countsFor(expected, predicted, truePositive) {
  return {
    tp: truePositive,
    fp: Math.max(0, predicted - truePositive),
    fn: Math.max(0, expected - truePositive),
    expected,
    predicted,
    precision: ratio(truePositive, predicted),
    recall: ratio(truePositive, expected),
  };
}

function recallCounts(expected, truePositive) {
  return { tp: truePositive, fn: Math.max(0, expected - truePositive), expected, recall: ratio(truePositive, expected) };
}

function thresholdGate(rate, threshold) {
  if (rate === null) return "not_applicable";
  return rate >= threshold ? "pass" : "fail";
}

export function validateGold(gold) {
  if (!isRecord(gold) || !hasOnlyKeys(gold, new Set(["schema_version", "review_mode", "reviewer_id", "artifacts", "scenarios"]))
    || gold.schema_version !== "mvp-extraction-gold-v1" || gold.review_mode !== "single_reviewer") fail("GOLD_SCHEMA_INVALID");
  if (!nonEmpty(gold.reviewer_id) || REVIEWER_PLACEHOLDERS.has(gold.reviewer_id.trim().toLocaleLowerCase("en-US"))) fail("GOLD_REVIEWER_INVALID");
  if (!Array.isArray(gold.artifacts) || gold.artifacts.length === 0 || !Array.isArray(gold.scenarios) || gold.scenarios.length === 0) fail("GOLD_SCHEMA_INVALID");

  const artifacts = new Map();
  for (const artifact of gold.artifacts) {
    if (!isRecord(artifact) || !hasOnlyKeys(artifact, new Set(["artifact_id", "document_id", "path", "sha256", "input_hash"]))
      || !nonEmpty(artifact.artifact_id) || !nonEmpty(artifact.document_id) || !nonEmpty(artifact.path)
      || !SHA256.test(artifact.sha256 ?? "") || !SHA256.test(artifact.input_hash ?? "") || artifacts.has(artifact.artifact_id)) fail("GOLD_ARTIFACT_INVALID");
    artifacts.set(artifact.artifact_id, artifact);
  }

  const scenarioIds = new Set();
  for (const scenario of gold.scenarios) {
    if (!isRecord(scenario) || !hasOnlyKeys(scenario, new Set(["scenario_id", "source_artifact_id", "document_type", "llm_assisted_required", "fields", "expected_row_ids"]))
      || !nonEmpty(scenario.scenario_id) || scenarioIds.has(scenario.scenario_id)
      || !artifacts.has(scenario.source_artifact_id) || !KNOWN_DOCUMENT_TYPES.has(scenario.document_type)
      || scenario.llm_assisted_required !== true || !Array.isArray(scenario.fields) || !Array.isArray(scenario.expected_row_ids)) fail("GOLD_SCENARIO_INVALID");
    scenarioIds.add(scenario.scenario_id);
    const artifact = artifacts.get(scenario.source_artifact_id);
    const fieldKeys = new Set();
    for (const field of scenario.fields) {
      const provenanceKeys = new Set(["document_id", "source_part_id", "source_ref", "page_no", "sheet_name", "cell_address", "table_id", "row_id", "column_index", "source_text"]);
      if (!isRecord(field) || !hasOnlyKeys(field, new Set(["field_key", "critical", "expected_value", "expected_raw_value", "source_path", "expected_provenance"]))
        || !nonEmpty(field.field_key) || fieldKeys.has(field.field_key) || typeof field.critical !== "boolean"
        || !Object.hasOwn(field, "expected_value") || !nonEmpty(field.expected_raw_value) || !nonEmpty(field.source_path)
        || !isRecord(field.expected_provenance) || !hasOnlyKeys(field.expected_provenance, provenanceKeys) || field.expected_provenance.document_id !== artifact.document_id
        || typeof field.expected_provenance.source_text !== "string"
        || !field.expected_provenance.source_text.includes(field.expected_raw_value)) fail("GOLD_FIELD_INVALID");
      const locator = field.expected_provenance.source_ref ?? field.expected_provenance.source_part_id;
      if (!nonEmpty(locator) || locator !== field.source_path) fail("GOLD_SOURCE_PATH_INVALID");
      fieldKeys.add(field.field_key);
    }
    if (scenario.expected_row_ids.some((id) => !nonEmpty(id)) || new Set(scenario.expected_row_ids).size !== scenario.expected_row_ids.length) fail("GOLD_ROWS_INVALID");
  }
  return { artifacts, scenarioIds };
}

export async function verifySourceArtifacts(gold, projectRoot) {
  const validated = validateGold(gold);
  const parsedByArtifact = new Map();
  for (const artifact of validated.artifacts.values()) {
    let bytes;
    try {
      bytes = await readFile(safeResolve(projectRoot, artifact.path));
    } catch {
      fail("SOURCE_ARTIFACT_MISSING");
    }
    if (sha256(bytes) !== artifact.sha256) fail("SOURCE_ARTIFACT_HASH_MISMATCH");
    let parsed;
    try {
      parsed = JSON.parse(bytes.toString("utf8"));
    } catch {
      fail("SOURCE_ARTIFACT_INVALID_JSON");
    }
    if (!isRecord(parsed) || parsed.document_id !== artifact.document_id || sha256(JSON.stringify(parsed)) !== artifact.input_hash) fail("SOURCE_ARTIFACT_INPUT_HASH_MISMATCH");
    parsedByArtifact.set(artifact.artifact_id, parsed);
  }
  for (const scenario of gold.scenarios) {
    const artifact = validated.artifacts.get(scenario.source_artifact_id);
    const source = parsedByArtifact.get(artifact.artifact_id);
    for (const field of scenario.fields) {
      const node = resolveSourcePath(source, field.source_path);
      const sourceStrings = stringValues(node);
      if (!sourceStrings.includes(field.expected_provenance.source_text) || !field.expected_provenance.source_text.includes(field.expected_raw_value)) fail("GOLD_SOURCE_VALUE_MISMATCH");
    }
  }
  return parsedByArtifact;
}

export function validateRunManifest(manifest, gold) {
  const { scenarioIds } = validateGold(gold);
  if (!isRecord(manifest) || manifest.schema_version !== "mvp-extraction-run-manifest-v1" || !Array.isArray(manifest.runs) || manifest.runs.length === 0) fail("RUN_MANIFEST_INVALID");
  const runIds = new Set();
  return manifest.runs.map((run) => {
    if (!isRecord(run) || !nonEmpty(run.run_id) || runIds.has(run.run_id) || !Array.isArray(run.scenarios)) fail("RUN_MANIFEST_INVALID");
    runIds.add(run.run_id);
    const entries = new Map();
    for (const entry of run.scenarios) {
      if (!isRecord(entry) || !scenarioIds.has(entry.scenario_id) || entries.has(entry.scenario_id)) fail("RUN_MANIFEST_SCENARIO_INVALID");
      if (entry.status === "completed") {
        if (!nonEmpty(entry.path) || !SHA256.test(entry.sha256 ?? "")) fail("RUN_MANIFEST_PREDICTION_INVALID");
      } else if (entry.status === "failed") {
        if (!/^[A-Z][A-Z0-9_]{1,63}$/.test(entry.error_code ?? "")) fail("RUN_MANIFEST_FAILURE_INVALID");
      } else fail("RUN_MANIFEST_STATUS_INVALID");
      entries.set(entry.scenario_id, entry);
    }
    for (const scenarioId of scenarioIds) {
      if (!entries.has(scenarioId)) entries.set(scenarioId, { scenario_id: scenarioId, status: "failed", error_code: "PREDICTION_MISSING" });
    }
    return { run_id: run.run_id, scenarios: entries };
  });
}

function predictionPayload(value) {
  if (!isRecord(value)) return null;
  if (isRecord(value.extraction)) return value.extraction;
  return value;
}

function validatePrediction(value, scenario, artifact) {
  const result = predictionPayload(value);
  if (!isRecord(result)) return { failure_code: "PREDICTION_INVALID" };
  if (result.document_id !== artifact.document_id) return { failure_code: "PREDICTION_DOCUMENT_ID_MISMATCH" };
  if (result.input_hash !== artifact.input_hash) return { failure_code: "PREDICTION_INPUT_HASH_MISMATCH" };
  if (result.document_type !== scenario.document_type) return { failure_code: "PREDICTION_DOCUMENT_TYPE_MISMATCH" };
  let validated;
  try {
    validated = validateExtraction(result.document_type, result);
  } catch {
    return { failure_code: "PREDICTION_SCHEMA_INVALID" };
  }
  const llm = validated.extraction_engine?.llm;
  if (validated.mode === "rules_only" || !llm?.called || !llm?.response_validated) return { failure_code: "LLM_REQUIRED_NOT_SATISFIED" };
  return { result: validated, llm_assisted: true };
}

function outputRows(result, documentType) {
  if (documentType === "addendum") return Array.isArray(result.changes) ? result.changes : [];
  if (documentType === "contract") return Array.isArray(result.payment_schedule) ? result.payment_schedule : [];
  return Array.isArray(result.line_items) ? result.line_items : [];
}

function scoreScenario(scenario, artifact, prediction) {
  const expectedFields = scenario.fields;
  const expectedCritical = expectedFields.filter((field) => field.critical).length;
  const expectedNoncritical = expectedFields.length - expectedCritical;
  const expectedRows = scenario.expected_row_ids.length;
  const failed = prediction?.status === "failed" ? prediction.error_code : null;
  const validated = failed ? null : validatePrediction(prediction?.value, scenario, artifact);
  const failureCode = failed ?? validated?.failure_code ?? null;
  const result = failureCode ? null : validated.result;

  const expectedByKey = new Map(expectedFields.map((field) => [field.field_key, field]));
  const accepted = [];
  const fieldOutput = result?.fields ?? {};
  for (const [fieldKey, field] of Object.entries(fieldOutput)) {
    if (field?.status === "extracted") accepted.push({ fieldKey, field });
  }

  let fieldTp = 0;
  let criticalTp = 0;
  let noncriticalTp = 0;
  const acceptedCorrectKeys = new Set();
  for (const expected of expectedFields) {
    const actual = fieldOutput[expected.field_key];
    const provenance = actual?.provenance;
    const locator = provenance?.source_ref ?? provenance?.source_part_id;
    const correct = actual?.status === "extracted"
      && isDeepStrictEqual(actual.value, expected.expected_value)
      && actual.source_value === expected.expected_raw_value
      && locator === expected.source_path
      && checkProvenanceSubset(provenance, expected.expected_provenance);
    if (correct) {
      fieldTp++;
      acceptedCorrectKeys.add(expected.field_key);
      if (expected.critical) criticalTp++;
      else noncriticalTp++;
    }
  }

  const expectedRowSet = new Set(scenario.expected_row_ids);
  const actualRows = result ? outputRows(result, scenario.document_type) : [];
  const rowSeen = new Set();
  let rowTp = 0;
  for (const row of actualRows) {
    if (expectedRowSet.has(row?.row_id) && !rowSeen.has(row.row_id)) {
      rowTp++;
      rowSeen.add(row.row_id);
    }
  }

  const fieldCounts = countsFor(expectedFields.length, accepted.length, fieldTp);
  const criticalCounts = recallCounts(expectedCritical, criticalTp);
  const noncriticalCounts = recallCounts(expectedNoncritical, noncriticalTp);
  const rowCounts = countsFor(expectedRows, actualRows.length, rowTp);
  const exactAcceptedCount = accepted.filter(({ fieldKey }) => acceptedCorrectKeys.has(fieldKey)).length;
  const exactAcceptedRate = ratio(exactAcceptedCount, accepted.length);

  return {
    scenario_id: scenario.scenario_id,
    document_id: artifact.document_id,
    status: failureCode ? "failed" : "scored",
    failure_code: failureCode,
    llm_assisted: !failureCode,
    fields: fieldCounts,
    critical_fields: criticalCounts,
    noncritical_fields: noncriticalCounts,
    accepted_value_source_correctness: { correct: exactAcceptedCount, accepted: accepted.length, rate: exactAcceptedRate },
    rows: rowCounts,
  };
}

function addCounts(target, source, keys) {
  for (const key of keys) target[key] += source[key];
}

function aggregateCounts(scenarios, property, keys) {
  const counts = Object.fromEntries(keys.map((key) => [key, 0]));
  for (const scenario of scenarios) addCounts(counts, scenario[property], keys);
  return counts;
}

export function scoreRun({ gold, run, artifacts, predictions }) {
  const scenarioScores = gold.scenarios.map((scenario) => {
    const artifact = artifacts.get(scenario.source_artifact_id);
    return scoreScenario(scenario, artifact, predictions.get(scenario.scenario_id));
  });
  const fieldTotals = aggregateCounts(scenarioScores, "fields", ["tp", "fp", "fn", "expected", "predicted"]);
  const criticalTotals = aggregateCounts(scenarioScores, "critical_fields", ["tp", "fn", "expected"]);
  const noncriticalTotals = aggregateCounts(scenarioScores, "noncritical_fields", ["tp", "fn", "expected"]);
  const rowTotals = aggregateCounts(scenarioScores, "rows", ["tp", "fp", "fn", "expected", "predicted"]);
  const acceptedValueSource = scenarioScores.reduce((total, score) => ({
    correct: total.correct + score.accepted_value_source_correctness.correct,
    accepted: total.accepted + score.accepted_value_source_correctness.accepted,
  }), { correct: 0, accepted: 0 });
  const metrics = {
    fields: { ...fieldTotals, precision: ratio(fieldTotals.tp, fieldTotals.predicted), recall: ratio(fieldTotals.tp, fieldTotals.expected) },
    critical_fields: { ...criticalTotals, recall: ratio(criticalTotals.tp, criticalTotals.expected) },
    noncritical_fields: { ...noncriticalTotals, recall: ratio(noncriticalTotals.tp, noncriticalTotals.expected) },
    accepted_value_source_correctness: { ...acceptedValueSource, rate: ratio(acceptedValueSource.correct, acceptedValueSource.accepted) },
    rows: { ...rowTotals, precision: ratio(rowTotals.tp, rowTotals.predicted), recall: ratio(rowTotals.tp, rowTotals.expected) },
  };
  const gates = {
    llm_required: scenarioScores.every((score) => score.llm_assisted) ? "pass" : "fail",
    critical_field_recall: thresholdGate(metrics.critical_fields.recall, MVP_EXTRACTION_THRESHOLDS.critical_field_recall),
    noncritical_field_recall: thresholdGate(metrics.noncritical_fields.recall, MVP_EXTRACTION_THRESHOLDS.noncritical_field_recall),
    accepted_value_source_correctness: thresholdGate(metrics.accepted_value_source_correctness.rate, MVP_EXTRACTION_THRESHOLDS.accepted_value_source_correctness),
    row_recall: thresholdGate(metrics.rows.recall, MVP_EXTRACTION_THRESHOLDS.row_recall),
  };
  const gateStates = Object.values(gates);
  const status = gateStates.includes("fail") ? "fail" : gateStates.includes("not_applicable") ? "incomplete" : "pass";
  return {
    run_id: run.run_id,
    status,
    scenario_count: scenarioScores.length,
    failed_scenario_count: scenarioScores.filter((score) => score.status === "failed").length,
    metrics,
    gates,
    scenarios: scenarioScores,
  };
}

export function aggregate(runReports) {
  if (!Array.isArray(runReports) || runReports.length === 0) fail("RUN_REPORTS_REQUIRED");
  const ordered = [...runReports].sort((left, right) => {
    const statusRank = { fail: 0, incomplete: 1, pass: 2 };
    if (statusRank[left.status] !== statusRank[right.status]) return statusRank[left.status] - statusRank[right.status];
    const a = left.metrics.critical_fields.recall ?? -1;
    const b = right.metrics.critical_fields.recall ?? -1;
    if (a !== b) return a - b;
    const c = left.metrics.noncritical_fields.recall ?? -1;
    const d = right.metrics.noncritical_fields.recall ?? -1;
    if (c !== d) return c - d;
    return (left.metrics.rows.recall ?? -1) - (right.metrics.rows.recall ?? -1);
  });
  const passedRepeats = runReports.filter((report) => report.status === "pass").length;
  return {
    repeat_count: runReports.length,
    passed_repeat_count: passedRepeats,
    status: passedRepeats === runReports.length ? "pass" : "fail",
    worst_repeat_id: ordered[0].run_id,
    runs: runReports,
  };
}

export async function loadPredictionEntry(entry, manifestRoot) {
  if (entry.status === "failed") return { status: "failed", error_code: entry.error_code };
  let bytes;
  try {
    bytes = await readFile(safeResolve(manifestRoot, entry.path));
  } catch {
    return { status: "failed", error_code: "PREDICTION_FILE_MISSING" };
  }
  if (sha256(bytes) !== entry.sha256) return { status: "failed", error_code: "PREDICTION_FILE_HASH_MISMATCH" };
  try {
    return { status: "ready", value: JSON.parse(bytes.toString("utf8")), prediction_sha256: entry.sha256 };
  } catch {
    return { status: "failed", error_code: "PREDICTION_INVALID_JSON" };
  }
}

export function artifactMapFromGold(gold) {
  return validateGold(gold).artifacts;
}
