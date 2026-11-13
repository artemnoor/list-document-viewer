import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const tsxCli = resolve("node_modules/tsx/dist/cli.mjs");
const prepareScript = resolve("scripts/prepare-annotation-packets.ts");
const compileScript = resolve("scripts/compile-expert-annotations.ts");
const reviewSourceFixtures = [
  "fixtures/demo-structured-extraction/contract-ambiguous-a.json",
  "fixtures/demo-structured-extraction/contract-ambiguous-b.json",
];

function runScript(script: string, args: string[], cwd: string) {
  return spawnSync(process.execPath, [tsxCli, script, ...args], {
    cwd,
    encoding: "utf8",
    timeout: 30000,
    maxBuffer: 1024 * 1024,
  });
}

function createReviewRoot() {
  // These temporary fixture edits are for compiler mechanics only; they are never benchmark gold.
  const root = mkdtempSync(join(tmpdir(), "phystech-trace-annotation-test-"));
  const sourcePaths = reviewSourceFixtures.map((fixture, index) => {
    const document = JSON.parse(readFileSync(resolve(fixture), "utf8"));
    document.document_id = `test-document-${index + 1}`;
    document.extraction_id = `test-extraction-${index + 1}`;
    const path = `evaluation/sources/document-${index + 1}.json`;
    mkdirSync(resolve(root, "evaluation/sources"), { recursive: true });
    writeFileSync(resolve(root, path), `${JSON.stringify(document, null, 2)}\n`);
    return path;
  });
  writeFileSync(resolve(root, "evaluation/scenarios.json"), `${JSON.stringify({
    scenarios: [{ id: "synthetic-compiler-check", documents: sourcePaths, focus: "Synthetic test mechanics only; not benchmark gold." }],
  }, null, 2)}\n`);
  return root;
}

function createPreparedRoot(mode: "single" | "expert") {
  const root = createReviewRoot();
  const outputDirectory = mode === "single" ? "evaluation/mvp-v1/packets" : "evaluation/annotation-packets";
  const prepared = runScript(prepareScript, ["--mode", mode, "--out", outputDirectory], root);
  assert.equal(prepared.status, 0, `${prepared.stderr}\n${prepared.stdout}`);
  return { root, outputDirectory };
}

function readJson(path: string) {
  return JSON.parse(readFileSync(path, "utf8"));
}

function completeAsSingleReviewer(packet: any, reviewerId = "human-reviewer-test-01") {
  packet.reviewer_id = reviewerId;
  packet.review_status = "complete";
  for (const pair of packet.document_pair_decisions) {
    pair.decision = "not_supported";
    pair.relationship_instances = [];
    pair.contradicting_evidence = [];
    pair.ambiguity_notes = "";
  }
  return packet;
}

function writePacket(root: string, directory: string, filename: string, packet: unknown) {
  writeFileSync(resolve(root, directory, filename), `${JSON.stringify(packet, null, 2)}\n`);
}

function compileSingle(root: string, extraArgs: string[] = []) {
  return runScript(compileScript, [
    "--mode", "single",
    "--packets", "evaluation/mvp-v1/packets",
    "--out", "evaluation/mvp-v1/gold.json",
    ...extraArgs,
  ], root);
}

test("annotation release contains ten unlabeled, hash-pinned expert packets", () => {
  const root = resolve("evaluation/annotation-packets"), manifest = JSON.parse(readFileSync(resolve(root, "manifest.json"), "utf8"));
  assert.equal(manifest.scenarios.length, 10);
  for (const item of manifest.scenarios) {
    const [reviewer1, reviewer2] = item.reviewer_packets.map((file: string) => JSON.parse(readFileSync(resolve(root, file), "utf8")));
    const adjudication = JSON.parse(readFileSync(resolve(root, item.adjudication_packet), "utf8"));
    for (const packet of [reviewer1, reviewer2, adjudication]) {
      assert.equal(packet.scenario_id, item.scenario_id);
      assert.equal(packet.source_bundle_sha256, item.source_bundle_sha256);
      assert.equal(packet.review_status, "pending");
      assert.ok(packet.document_pair_decisions.length > 0);
      assert.ok(packet.document_pair_decisions.every((pair: any) => pair.decision === "pending"));
      for (const source of packet.source_documents) {
        const bytes = readFileSync(resolve(source.path));
        assert.equal(createHash("sha256").update(bytes).digest("hex"), source.sha256);
      }
    }
    assert.equal("predictions" in reviewer1, false);
    assert.equal("gold_links" in reviewer1, false);
  }
});

test("single-reviewer mode compiles one completed human packet without claiming adjudication", (t) => {
  const { root, outputDirectory } = createPreparedRoot("single");
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const manifest = readJson(resolve(root, outputDirectory, "manifest.json"));
  assert.equal(manifest.review_mode, "single_reviewer");
  assert.equal(manifest.scenarios[0].reviewer_packets.length, 1);
  assert.equal("adjudication_packet" in manifest.scenarios[0], false);

  const filename = manifest.scenarios[0].reviewer_packets[0];
  const packet = completeAsSingleReviewer(readJson(resolve(root, outputDirectory, filename)));
  writePacket(root, outputDirectory, filename, packet);
  const compiled = compileSingle(root);
  assert.equal(compiled.status, 0, `${compiled.stderr}\n${compiled.stdout}`);

  const gold = readJson(resolve(root, "evaluation/mvp-v1/gold.json"));
  assert.equal(gold.review_mode, "single_reviewer");
  assert.deepEqual(gold.reviewer_ids, ["human-reviewer-test-01"]);
  assert.equal(gold.scenarios[0].reviewed_document_pairs.length, 1);
  assert.equal("adjudicated_document_pairs" in gold.scenarios[0], false);
  assert.deepEqual(gold.scenarios[0].gold_links, []);
});

test("single-reviewer mode rejects pending packets and missing pair decisions", (t) => {
  const pending = createPreparedRoot("single");
  t.after(() => rmSync(pending.root, { recursive: true, force: true }));
  const pendingRun = compileSingle(pending.root);
  assert.notEqual(pendingRun.status, 0);
  assert.match(pendingRun.stderr, /pending or mismatched packets/);

  const missing = createPreparedRoot("single");
  t.after(() => rmSync(missing.root, { recursive: true, force: true }));
  const missingManifest = readJson(resolve(missing.root, missing.outputDirectory, "manifest.json"));
  const missingFile = missingManifest.scenarios[0].reviewer_packets[0];
  const missingPacket = completeAsSingleReviewer(readJson(resolve(missing.root, missing.outputDirectory, missingFile)));
  missingPacket.document_pair_decisions = [];
  writePacket(missing.root, missing.outputDirectory, missingFile, missingPacket);
  const missingRun = compileSingle(missing.root);
  assert.notEqual(missingRun.status, 0);
  assert.match(missingRun.stderr, /undecided document pairs/);
});

test("single-reviewer mode rejects changed source hashes and unsafe evidence paths or values", (t) => {
  const changedSource = createPreparedRoot("single");
  t.after(() => rmSync(changedSource.root, { recursive: true, force: true }));
  const sourcePath = resolve(changedSource.root, "evaluation/sources/document-1.json");
  writeFileSync(sourcePath, `${readFileSync(sourcePath, "utf8")}\n`);
  const changedHashRun = compileSingle(changedSource.root);
  assert.notEqual(changedHashRun.status, 0);
  assert.match(changedHashRun.stderr, /Source file hash changed/);

  for (const variant of ["path", "value"] as const) {
    const review = createPreparedRoot("single");
    t.after(() => rmSync(review.root, { recursive: true, force: true }));
    const manifest = readJson(resolve(review.root, review.outputDirectory, "manifest.json"));
    const filename = manifest.scenarios[0].reviewer_packets[0];
    const packet = completeAsSingleReviewer(readJson(resolve(review.root, review.outputDirectory, filename)));
    const pair = packet.document_pair_decisions[0];
    const docs = packet.source_documents;
    const source = readJson(resolve(review.root, docs[0].path));
    const target = readJson(resolve(review.root, docs[1].path));
    const path = variant === "path" ? "fields.contract_number.not_present" : "fields.contract_number.value";
    pair.contradicting_evidence = [{
      source: { document_id: docs[0].document_id, path, raw_value: "mechanics-only" },
      target: { document_id: docs[1].document_id, path: "fields.contract_number.value", raw_value: target.fields.contract_number.value },
      explanation: "Synthetic compiler validation; not a benchmark label.",
    }];
    if (variant === "value") pair.contradicting_evidence[0].source.raw_value = "wrong raw value";
    else pair.contradicting_evidence[0].source.raw_value = source.fields.contract_number.value;
    writePacket(review.root, review.outputDirectory, filename, packet);
    const result = compileSingle(review.root);
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /path\/raw_value mismatch/);
  }
});

test("single-reviewer mode rejects placeholder identities", (t) => {
  const review = createPreparedRoot("single");
  t.after(() => rmSync(review.root, { recursive: true, force: true }));
  const manifest = readJson(resolve(review.root, review.outputDirectory, "manifest.json"));
  const filename = manifest.scenarios[0].reviewer_packets[0];
  const packet = completeAsSingleReviewer(readJson(resolve(review.root, review.outputDirectory, filename)), "pending");
  writePacket(review.root, review.outputDirectory, filename, packet);
  const result = compileSingle(review.root);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /invalid reviewer identity/);
});

test("expert mode still requires two reviewers and a separate adjudicator", (t) => {
  const { root, outputDirectory } = createPreparedRoot("expert");
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const manifest = readJson(resolve(root, outputDirectory, "manifest.json"));
  const files = [...manifest.scenarios[0].reviewer_packets, manifest.scenarios[0].adjudication_packet];
  for (const [index, filename] of files.entries()) {
    const packet = readJson(resolve(root, outputDirectory, filename));
    packet.reviewer_id = `human-expert-test-${index + 1}`;
    packet.review_status = "complete";
    for (const pair of packet.document_pair_decisions) {
      pair.decision = "not_supported";
      pair.relationship_instances = [];
      pair.contradicting_evidence = [];
      pair.ambiguity_notes = "";
    }
    writePacket(root, outputDirectory, filename, packet);
  }
  const compiled = runScript(compileScript, [
    "--mode", "expert",
    "--packets", outputDirectory,
    "--out", "evaluation/expert-gold.json",
  ], root);
  assert.equal(compiled.status, 0, `${compiled.stderr}\n${compiled.stdout}`);
  const gold = readJson(resolve(root, "evaluation/expert-gold.json"));
  assert.equal(gold.review_mode, "independent_adjudication");
  assert.equal(gold.reviewer_ids.length, 3);
  assert.equal(gold.scenarios[0].adjudicated_document_pairs.length, 1);
  assert.equal("reviewed_document_pairs" in gold.scenarios[0], false);
});
