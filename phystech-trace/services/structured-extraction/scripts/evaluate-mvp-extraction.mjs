#!/usr/bin/env node
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import {
  aggregate,
  artifactMapFromGold,
  loadPredictionEntry,
  scoreRun,
  validateRunManifest,
  verifySourceArtifacts,
} from "../lib/evaluation/mvp-quality.mjs";

const levels = { debug: 10, info: 20, warn: 30, error: 40 };
const configuredLevel = (process.env.LOG_LEVEL ?? "info").toLowerCase();
const logLevel = Object.hasOwn(levels, configuredLevel) ? configuredLevel : "info";

function log(level, event, fields = {}) {
  if (levels[level] < levels[logLevel]) return;
  process.stderr.write(`${JSON.stringify({ timestamp: new Date().toISOString(), level, event, ...fields })}\n`);
}

function cliError(code) {
  const error = new Error(code);
  error.code = code;
  return error;
}

function parseArgs(args) {
  const options = {};
  for (let index = 0; index < args.length; index++) {
    const flag = args[index];
    if (flag === "--help" || flag === "-h") return { help: true };
    if (!["--gold", "--predictions", "--out"].includes(flag)) throw cliError("UNKNOWN_ARGUMENT");
    const value = args[index + 1];
    if (!value || value.startsWith("--")) throw cliError("ARGUMENT_VALUE_REQUIRED");
    options[flag.slice(2)] = value;
    index++;
  }
  if (!options.gold || !options.predictions || !options.out) throw cliError("REQUIRED_ARGUMENTS_MISSING");
  return options;
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

async function readJson(path, failureCode) {
  let bytes;
  try {
    bytes = await readFile(path);
  } catch {
    throw cliError(failureCode);
  }
  try {
    return { value: JSON.parse(bytes.toString("utf8")), bytes };
  } catch {
    throw cliError(`${failureCode}_INVALID_JSON`);
  }
}

export async function runEvaluation(options, projectRoot = process.cwd()) {
  const goldPath = resolve(projectRoot, options.gold);
  const predictionManifestPath = resolve(projectRoot, options.predictions);
  const [{ value: gold, bytes: goldBytes }, { value: manifest }] = await Promise.all([
    readJson(goldPath, "GOLD_FILE"),
    readJson(predictionManifestPath, "RUN_MANIFEST_FILE"),
  ]);
  const artifacts = artifactMapFromGold(gold);
  await verifySourceArtifacts(gold, projectRoot);
  const runs = validateRunManifest(manifest, gold);
  log("info", "mvp_extraction_evaluation_started", { scenario_count: gold.scenarios.length, repeat_count: runs.length, artifact_count: artifacts.size });

  const reports = [];
  for (const run of runs) {
    const predictions = new Map();
    for (const [scenarioId, entry] of run.scenarios) {
      predictions.set(scenarioId, await loadPredictionEntry(entry, dirname(predictionManifestPath)));
    }
    const runReport = scoreRun({ gold, run, artifacts, predictions });
    for (const scenario of runReport.scenarios) {
      if (scenario.status === "failed") log("warn", "mvp_extraction_scenario_failed", { run_id: run.run_id, scenario_id: scenario.scenario_id, code: scenario.failure_code });
    }
    reports.push(runReport);
  }
  const results = aggregate(reports);
  const output = {
    schema_version: "mvp-extraction-report-v1",
    created_at: new Date().toISOString(),
    gold_sha256: sha256(goldBytes),
    gold_review_mode: gold.review_mode,
    source_artifact_count: artifacts.size,
    scenario_count: gold.scenarios.length,
    ...results,
  };
  const outputPath = resolve(projectRoot, options.out);
  await mkdir(dirname(outputPath), { recursive: true });
  await writeFile(outputPath, `${JSON.stringify(output, null, 2)}\n`, { encoding: "utf8", mode: 0o600 });
  log(results.status === "pass" ? "info" : "warn", "mvp_extraction_evaluation_completed", {
    status: results.status,
    passed_repeat_count: results.passed_repeat_count,
    repeat_count: results.repeat_count,
    report: options.out,
  });
  return { output, outputPath };
}

const help = `Usage: node scripts/evaluate-mvp-extraction.mjs --gold <gold.json> --predictions <run-manifest.json> --out <report.json>

The gold file pins parser artifact byte hashes and runtime input hashes. The run manifest has this shape:
{
  "schema_version": "mvp-extraction-run-manifest-v1",
  "runs": [{
    "run_id": "repeat-1",
    "scenarios": [
      { "scenario_id": "case-1", "status": "completed", "path": "predictions/case-1.json", "sha256": "<file sha256>" },
      { "scenario_id": "case-2", "status": "failed", "error_code": "PROVIDER_FAILED" }
    ]
  }]
}
Prediction paths are relative to the run manifest. Missing scenarios and failed model calls remain failed in every denominator. LOG_LEVEL supports debug, info, warn, and error.`;

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try {
    const options = parseArgs(process.argv.slice(2));
    if (options.help) process.stdout.write(`${help}\n`);
    else {
      const { output } = await runEvaluation(options);
      if (output.status !== "pass") process.exitCode = 1;
    }
  } catch (error) {
    const code = typeof error?.code === "string" ? error.code : "EVALUATION_FAILED";
    log("error", "mvp_extraction_evaluation_failed", { code });
    process.exitCode = 2;
  }
}
