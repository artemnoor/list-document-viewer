import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { aggregate, loadPredictionEntry, scoreRun, verifySourceArtifacts } from "../lib/evaluation/mvp-quality.mjs";

const hash = (value) => createHash("sha256").update(value).digest("hex");

function makeFixture() {
  const source = {
    document_id: "extract-case-1",
    parts: [{ text: "Номер: Д-2026/01" }, { text: "Дата: 30.04.2026" }],
  };
  const sourceBytes = Buffer.from(JSON.stringify(source));
  const artifact = {
    artifact_id: "artifact-1",
    document_id: source.document_id,
    path: "source.json",
    sha256: hash(sourceBytes),
    input_hash: hash(JSON.stringify(source)),
  };
  const field = (fieldKey, critical, expectedValue, raw, sourceRef, sourceText) => ({
    field_key: fieldKey,
    critical,
    expected_value: expectedValue,
    expected_raw_value: raw,
    source_path: sourceRef,
    expected_provenance: { document_id: source.document_id, source_ref: sourceRef, source_text: sourceText },
  });
  const gold = {
    schema_version: "mvp-extraction-gold-v1",
    review_mode: "single_reviewer",
    reviewer_id: "human-reviewer-1",
    artifacts: [artifact],
    scenarios: [{
      scenario_id: "case-1",
      source_artifact_id: artifact.artifact_id,
      document_type: "contract",
      llm_assisted_required: true,
      fields: [
        field("contract_number", true, "Д-2026/01", "Д-2026/01", "#/parts/0", "Номер: Д-2026/01"),
        field("contract_date", false, "2026-04-30", "30.04.2026", "#/parts/1", "Дата: 30.04.2026"),
      ],
      expected_row_ids: ["row-a", "row-b"],
    }],
  };
  const extractionValue = (value, sourceValue, sourceRef, sourceText, status = "extracted") => ({
    value,
    source_value: sourceValue,
    status,
    confidence: 1,
    provenance: sourceRef ? { document_id: source.document_id, source_ref: sourceRef, source_text: sourceText } : null,
  });
  const makeRow = (rowId) => ({
    row_id: rowId,
    line_number: extractionValue(null, null, null, "", "missing"),
    identifier: extractionValue(null, null, null, "", "missing"),
    description: extractionValue(null, null, null, "", "missing"),
    unit: extractionValue(null, null, null, "", "missing"),
    quantity: extractionValue(null, null, null, "", "missing"),
    plan_quantity: extractionValue(null, null, null, "", "missing"),
    actual_quantity: extractionValue(null, null, null, "", "missing"),
    unit_price: extractionValue(null, null, null, "", "missing"),
    amount: extractionValue(null, null, null, "", "missing"),
    source_cells: [],
    row_status: "missing",
  });
  const makePrediction = () => ({
    extraction_id: "prediction-1",
    document_id: source.document_id,
    version: 1,
    schema_version: "1.2.0",
    extracted_at: "2026-11-13T00:00:00.000Z",
    document_type: "contract",
    input_hash: artifact.input_hash,
    mode: "llm_assisted",
    classification: { type: "contract", label: "Договор", confidence: 1, status: "classified" },
    extraction_engine: {
      rules_executed: true,
      llm: { provider: "synthetic", model: "fixture", called: true, response_validated: true },
      parser_adapter: "fixture",
    },
    fields: {
      contract_number: extractionValue("Д-2026/01", "Д-2026/01", "#/parts/0", "Номер: Д-2026/01"),
      contract_date: extractionValue("2026-04-30", "30.04.2026", "#/parts/1", "Дата: 30.04.2026"),
    },
    tables: [],
    indicators: [],
    missing_fields: [],
    review_required: [],
    payment_schedule: [makeRow("row-a"), makeRow("row-b")],
  });
  const run = { run_id: "repeat-1" };
  const artifacts = new Map([[artifact.artifact_id, artifact]]);
  const predictions = new Map([["case-1", { status: "ready", value: makePrediction() }]]);
  return { source, sourceBytes, artifact, gold, run, artifacts, predictions, makePrediction };
}

test("missing critical field is an FN and fails critical recall", () => {
  const fixture = makeFixture();
  const prediction = fixture.makePrediction();
  delete prediction.fields.contract_number;
  fixture.predictions.set("case-1", { status: "ready", value: prediction });
  const report = scoreRun(fixture);
  assert.equal(report.metrics.critical_fields.expected, 1);
  assert.equal(report.metrics.critical_fields.fn, 1);
  assert.equal(report.metrics.critical_fields.recall, 0);
  assert.equal(report.gates.critical_field_recall, "fail");
});

test("matching normalized value with wrong raw value or source is not accepted as correct", () => {
  const fixture = makeFixture();
  const prediction = fixture.makePrediction();
  prediction.fields.contract_number.source_value = "Д-2026/02";
  prediction.fields.contract_number.provenance.source_ref = "#/parts/99";
  fixture.predictions.set("case-1", { status: "ready", value: prediction });
  const report = scoreRun(fixture);
  assert.equal(report.metrics.critical_fields.tp, 0);
  assert.equal(report.metrics.critical_fields.fn, 1);
  assert.equal(report.metrics.accepted_value_source_correctness.rate, 0.5);
});

test("duplicate and omitted row IDs remain separate FP and FN counts", () => {
  const fixture = makeFixture();
  const prediction = fixture.makePrediction();
  prediction.payment_schedule = [prediction.payment_schedule[0], structuredClone(prediction.payment_schedule[0]), {
    ...prediction.payment_schedule[0], row_id: "unexpected-row",
  }];
  fixture.predictions.set("case-1", { status: "ready", value: prediction });
  const report = scoreRun(fixture);
  assert.deepEqual({ tp: report.metrics.rows.tp, fp: report.metrics.rows.fp, fn: report.metrics.rows.fn }, { tp: 1, fp: 2, fn: 1 });
});

test("unexpected accepted fields are false positives while noncritical recall keeps its denominator", () => {
  const fixture = makeFixture();
  const prediction = fixture.makePrediction();
  prediction.fields.contract_date.status = "missing";
  prediction.fields.unreviewed_extra = {
    value: "unexpected", source_value: "unexpected", status: "extracted", confidence: 1, provenance: null,
  };
  fixture.predictions.set("case-1", { status: "ready", value: prediction });
  const report = scoreRun(fixture);
  assert.equal(report.metrics.noncritical_fields.expected, 1);
  assert.equal(report.metrics.noncritical_fields.fn, 1);
  assert.equal(report.metrics.fields.fp, 1);
  assert.equal(report.metrics.fields.fn, 1);
});

test("forged provenance fails accepted source correctness even when typed and raw values match", () => {
  const fixture = makeFixture();
  const prediction = fixture.makePrediction();
  prediction.fields.contract_date.provenance.document_id = "other-document";
  fixture.predictions.set("case-1", { status: "ready", value: prediction });
  const report = scoreRun(fixture);
  assert.equal(report.metrics.noncritical_fields.tp, 0);
  assert.equal(report.metrics.accepted_value_source_correctness.rate, 0.5);
});

test("source artifact byte hash tampering is rejected", async () => {
  const fixture = makeFixture();
  const directory = await mkdtemp(join(tmpdir(), "mvp-extraction-gold-"));
  try {
    await writeFile(join(directory, fixture.artifact.path), fixture.sourceBytes);
    assert.equal((await verifySourceArtifacts(fixture.gold, directory)).size, 1);
    await writeFile(join(directory, fixture.artifact.path), `${fixture.sourceBytes.toString("utf8")} `);
    await assert.rejects(() => verifySourceArtifacts(fixture.gold, directory), { code: "SOURCE_ARTIFACT_HASH_MISMATCH" });
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test("prediction file hash tampering is represented as a failed result", async () => {
  const directory = await mkdtemp(join(tmpdir(), "mvp-extraction-prediction-"));
  try {
    const path = join(directory, "prediction.json");
    await writeFile(path, JSON.stringify({ extraction: { synthetic: true } }));
    const entry = { status: "completed", path: "prediction.json", sha256: "0".repeat(64) };
    assert.deepEqual(await loadPredictionEntry(entry, directory), { status: "failed", error_code: "PREDICTION_FILE_HASH_MISMATCH" });
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test("invalid output schema is failed and cannot be counted as an empty successful extraction", () => {
  const fixture = makeFixture();
  // Pass identity gates so this fixture reaches the output-schema check.
  fixture.predictions.set("case-1", { status: "ready", value: {
    document_id: fixture.artifact.document_id,
    input_hash: fixture.artifact.input_hash,
    document_type: "contract",
  } });
  const report = scoreRun(fixture);
  assert.equal(report.scenarios[0].failure_code, "PREDICTION_SCHEMA_INVALID");
  assert.equal(report.metrics.critical_fields.recall, 0);
  assert.equal(report.metrics.rows.recall, 0);
});

test("failed model result and rules-only fallback fail LLM-required while preserving misses", () => {
  const fixture = makeFixture();
  fixture.predictions.set("case-1", { status: "failed", error_code: "PROVIDER_FAILED" });
  const failed = scoreRun(fixture);
  assert.equal(failed.failed_scenario_count, 1);
  assert.equal(failed.metrics.critical_fields.fn, 1);
  assert.equal(failed.metrics.rows.fn, 2);
  assert.equal(failed.gates.llm_required, "fail");

  const fallback = fixture.makePrediction();
  fallback.mode = "rules_only";
  fallback.extraction_engine.llm.called = false;
  fallback.extraction_engine.llm.response_validated = false;
  fixture.predictions.set("case-1", { status: "ready", value: fallback });
  const fallbackReport = scoreRun(fixture);
  assert.equal(fallbackReport.scenarios[0].failure_code, "LLM_REQUIRED_NOT_SATISFIED");
  assert.equal(fallbackReport.metrics.critical_fields.fn, 1);
  assert.equal(aggregate([failed, fallbackReport]).passed_repeat_count, 0);
});

test("missing prediction remains a failed scenario instead of an empty successful graph", () => {
  const fixture = makeFixture();
  fixture.predictions.set("case-1", { status: "failed", error_code: "PREDICTION_MISSING" });
  const report = scoreRun(fixture);
  assert.equal(report.scenarios[0].failure_code, "PREDICTION_MISSING");
  assert.equal(report.metrics.fields.recall, 0);
});
