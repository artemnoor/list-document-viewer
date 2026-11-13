import { test } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

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
