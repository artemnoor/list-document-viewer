import { test } from "node:test";
import assert from "node:assert/strict";
import { runLinkingStrategy } from "../src/linking/strategy-experiments";
import { GEMMA_MODEL } from "../src/linking/llm-matcher";
import { buildEvidenceRegistry } from "../src/linking/evidence-registry";

function docs(): any[] {
  return ["doc-a", "doc-b"].map((document_id, index) => ({
    extraction_id: `ex-${index}`, document_id, document_type: "future-type", version: 1, schema_version: "1.2.0",
    source: { value: `source-${index}`, provenance: { document_id, source_available: true, source_text: `source-${index}` } },
  }));
}
const base = (documents: any[]) => ({ apiKey: "test-only", timeoutMs: 1000, maxInputTokens: 100_000, systemPrompt: "test system prompt", documents });
function fetchJson(handler: (request: any, index: number) => unknown) {
  const original = globalThis.fetch; let count = 0; const requests: any[] = [];
  globalThis.fetch = async (_input, init) => { const request = JSON.parse(String(init?.body)); requests.push(request); return new Response(JSON.stringify({ model: GEMMA_MODEL, choices: [{ message: { content: JSON.stringify(handler(request, count++)) } }], usage: { prompt_tokens: 30, completion_tokens: 20 }, cost: 0.001 }), { status: 200 }); };
  return { restore: () => { globalThis.fetch = original; }, get count() { return count; }, requests };
}
const candidate = (source_document_id: string, target_document_id: string, relationship_type = "explains") => ({ relationship_type, source_document_id, target_document_id, explanation: "shared transaction context", confidence: 0.7, status: "proposed", conflicts: [], alternatives: [] });

test("strategy A delegates to the existing matcher and records its raw responses", async () => {
  const input = docs(), mock = fetchJson(() => ({ links: [], unlinked_document_ids: input.map(document => document.document_id), analysis_summary: "Reviewed the full set.", context_requests: [] }));
  try {
    const result = await runLinkingStrategy("A", input, { ...base(input), maxCalls: 8 });
    assert.equal(result.baseline?.complete, true); assert.equal(result.calls.length, 1); assert.equal(result.calls[0].label, "baseline.relationship-analysis");
    assert.equal((result.calls[0].raw_response as any).analysis_summary, "Reviewed the full set."); assert.equal(result.unlinked_document_ids.length, 2);
  } finally { mock.restore(); }
});

test("strategy B discovers first, selects exact references in a second pass, and retains unproven candidates", async () => {
  const input = docs(), refs = buildEvidenceRegistry(input), src = refs.find(ref => ref.document_id === "doc-a" && ref.json_path === "source.value")!, target = refs.find(ref => ref.document_id === "doc-b" && ref.json_path === "source.value")!;
  const mock = fetchJson((request, index) => index === 0
    ? { candidates: [candidate("doc-a", "doc-b"), candidate("doc-x", "doc-b", "uncited")], unlinked_document_ids: [], analysis_summary: "Candidates" }
    : { evidence: [{ candidate_index: 0, evidence: [{ source_reference_id: src.reference_id, target_reference_id: target.reference_id, signal: "context", explanation: "evidence" }] }], unresolved: [{ candidate_index: 1, reason: "not enough" }] });
  try {
    const result = await runLinkingStrategy("B", input, base(input));
    assert.equal(mock.count, 2); assert.equal(result.candidates.length, 2); assert.equal(result.links.length, 1);
    assert.equal(result.links[0].evidence[0].source.path, src.json_path); assert.equal(result.links[0].evidence[0].target.path, target.json_path);
    assert.equal(result.diagnostics.length, 1); assert.match(result.diagnostics[0].reason, /invalid|reference/);
  } finally { mock.restore(); }
});

test("strategy B keeps malformed status and row-id proposals visible as review candidates", async () => {
  const input = docs(), refs = buildEvidenceRegistry(input), src = refs.find(ref => ref.document_id === "doc-a" && ref.json_path === "source.value")!, target = refs.find(ref => ref.document_id === "doc-b" && ref.json_path === "source.value")!;
  const malformed = { ...candidate("doc-a", "doc-b"), status: "unverified", source_row_id: "source.value" };
  const mock = fetchJson((_request, index) => index === 0
    ? { candidates: [malformed], unlinked_document_ids: [], analysis_summary: "Candidate retained" }
    : { evidence: [{ candidate_index: 0, evidence: [{ source_reference_id: src.reference_id, target_reference_id: target.reference_id, signal: "context", explanation: "exact source elements" }] }] });
  try {
    const result = await runLinkingStrategy("B", input, base(input));
    assert.equal(result.candidates.length, 1); assert.equal(result.links.length, 1);
    assert.equal(result.links[0].status, "review"); assert.equal(result.links[0].source_row_id, undefined);
    assert.match(result.diagnostics[0].reason, /invalid_status|row_id/);
    assert.equal((result.candidates[0] as any).model_status, "unverified");
  } finally { mock.restore(); }
});

test("LLM evidence pass, not a synonym dictionary, chooses semantic duplicate candidates", async () => {
  const input = docs(), refs = buildEvidenceRegistry(input), src = refs.find(ref => ref.document_id === "doc-a" && ref.json_path === "source.value")!, target = refs.find(ref => ref.document_id === "doc-b" && ref.json_path === "source.value")!;
  const proposals = [candidate("doc-a", "doc-b", "amends"), candidate("doc-a", "doc-b", "amendment_of")];
  const mock = fetchJson((_request, index) => index === 0
    ? { candidates: proposals, unlinked_document_ids: [], analysis_summary: "Two phrasings" }
    : { semantic_duplicate_groups: [{ candidate_indices: [0, 1], canonical_candidate_index: 0, canonical_relationship_type: "amends" }], evidence: [{ candidate_index: 0, evidence: [{ source_reference_id: src.reference_id, target_reference_id: target.reference_id, signal: "context", explanation: "same relation" }] }] });
  try {
    const result = await runLinkingStrategy("B", input, base(input));
    assert.equal(result.candidates.length, 2); assert.equal(result.links.length, 1);
    assert.equal(result.links[0].relationship_type, "amends");
    assert.deepEqual(result.semantic_deduplication?.collapsed_candidate_indices, [1]);
    assert.equal(mock.requests[1].messages[0].content.includes("не используй словарь типов связей"), true);
  } finally { mock.restore(); }
});

test("strategy C unions independent candidates, lets critic add a candidate, debates only on model request, then validates evidence", async () => {
  const input = docs(), refs = buildEvidenceRegistry(input), src = refs.find(ref => ref.document_id === "doc-a" && ref.json_path === "source.value")!, target = refs.find(ref => ref.document_id === "doc-b" && ref.json_path === "source.value")!;
  const allCandidates = [candidate("doc-a", "doc-b"), candidate("doc-b", "doc-a", "reverse-context")];
  const mock = fetchJson((request, index) => {
    if (index < 2) return { candidates: index === 0 ? [allCandidates[0]] : [allCandidates[1]], unlinked_document_ids: [], analysis_summary: "independent" };
    if (index === 2) return { candidates: [], debate_requested: true, disagreements: [{ candidate_index: 0, issue: "direction" }], unlinked_document_ids: [], analysis_summary: "critic" };
    if (index === 3) return { candidates: allCandidates, unlinked_document_ids: [], analysis_summary: "debated" };
    return { evidence: allCandidates.map((candidate, candidate_index) => ({ candidate_index, evidence: [{ source_reference_id: candidate.source_document_id === "doc-a" ? src.reference_id : target.reference_id, target_reference_id: candidate.target_document_id === "doc-a" ? src.reference_id : target.reference_id, signal: "test", explanation: "exact source refs" }] })) };
  });
  try {
    const result = await runLinkingStrategy("C", input, base(input));
    assert.equal(mock.count, 5); assert.equal(result.candidates.length, 2); assert.equal(result.links.length, 2);
    assert.equal(result.calls[0].label, "C.independent-agent-1"); assert.equal(result.calls[1].label, "C.independent-agent-2");
    assert.deepEqual(mock.requests[0].messages[1], mock.requests[1].messages[1]);
  } finally { mock.restore(); }
});
