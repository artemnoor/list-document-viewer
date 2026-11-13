import { test } from "node:test";
import assert from "node:assert/strict";
import { assertExactPairDecisions, hasCompleteNoRelationAudit } from "../src/linking/semantic-runner";

test("verification decisions must uniquely and exactly cover the expected audit IDs", () => {
  assert.deepEqual(assertExactPairDecisions([
    { pair_id: "pair-A", state: "no_relation" },
    { pair_id: "pair-B@0:1", state: "insufficient_evidence" },
  ], ["pair-A", "pair-B@0:1"]).map(item => item.pair_id), ["pair-A", "pair-B@0:1"]);
  assert.throws(() => assertExactPairDecisions([
    { pair_id: "pair-A", state: "no_relation" },
    { pair_id: "pair-A", state: "no_relation" },
  ], ["pair-A", "pair-B"]), /ровно одно решение|повторяющийся pair_id/);
  assert.throws(() => assertExactPairDecisions([{ pair_id: "pair-A", state: "no_relation" }], ["pair-A", "pair-B"]), /ровно одно решение|пропустил ожидаемый/);
  assert.throws(() => assertExactPairDecisions([
    { pair_id: "pair-A", state: "no_relation" },
    { pair_id: "pair-B", state: "no_relation" },
    { pair_id: "unrequested", state: "no_relation" },
  ], ["pair-A", "pair-B"]), /ровно одно решение|посторонний pair_id/);
  assert.throws(() => assertExactPairDecisions([], ["pair-A", "pair-A"]), /повторяющийся pair_id/);
});

test("no_link_found requires one explicit no_relation per unique expected audit", () => {
  const expected = ["pair:0:1@0:0", "pair:0:1@0:1"];
  assert.equal(hasCompleteNoRelationAudit(expected, [
    { pair_id: expected[0], state: "no_relation" },
    { pair_id: expected[1], state: "no_relation" },
  ]), true);
  assert.equal(hasCompleteNoRelationAudit(expected, [{ pair_id: expected[0], state: "no_relation" }]), false);
  assert.equal(hasCompleteNoRelationAudit(expected, [
    { pair_id: expected[0], state: "no_relation" },
    { pair_id: expected[0], state: "no_relation" },
  ]), false);
  assert.equal(hasCompleteNoRelationAudit(expected, [
    { pair_id: expected[0], state: "no_relation" },
    { pair_id: expected[1], state: "insufficient_evidence" },
  ]), false);
});
