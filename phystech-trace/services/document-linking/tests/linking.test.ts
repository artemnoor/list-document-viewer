import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { linkDocuments } from "../src/linking/link-resolver";
import { analyzeDocumentSet, GEMMA_MODEL } from "../src/linking/llm-matcher";
import { validateInput } from "../src/contracts/input";
import { linkingOutputSchema } from "../src/contracts/output";
import { buildEvidenceRegistry } from "../src/linking/evidence-registry";
import { resolveJsonPath } from "../src/linking/evidence-validation";

const systemPrompt = readFileSync("public/prompts/document-linking-system.md", "utf8");
const fixtureDocs = readdirSync("fixtures/upstream-structured-extraction-1.2.0").filter(name => name.endsWith(".json")).map(name => JSON.parse(readFileSync(`fixtures/upstream-structured-extraction-1.2.0/${name}`, "utf8")));
test("evidence registry indexes arbitrary nested values and inherits row/provenance context", () => {
  const document: any = { document_id: "registry-doc", document_type: "future-kind", fields: { arbitrary: { value: "  A  B  ", provenance: { document_id: "registry-doc", source_available: true, source_text: "A B" }, future_metadata: { code: 17 } } }, tables: [{ rows: [{ row_id: "row-x", cells: [{ value: 9 }] }] }] };
  const refs = buildEvidenceRegistry([document]);
  assert.equal(new Set(refs.map(ref => ref.reference_id)).size, refs.length);
  const value = refs.find(ref => ref.json_path === "fields.arbitrary.value")!;
  assert.equal(value.raw_value, "  A  B  "); assert.equal(value.normalized_value, "A B"); assert.deepEqual(value.provenance, document.fields.arbitrary.provenance);
  const rowCell = refs.find(ref => ref.json_path === "tables[0].rows[0].cells[0].value")!;
  assert.equal(rowCell.row_id, "row-x"); assert.equal(resolveJsonPath(document, rowCell.json_path), rowCell.raw_value);
  assert.equal(refs.find(ref => ref.json_path === "fields.arbitrary.future_metadata.code")?.raw_value, 17);
});
test("complete upstream set is sent as one unfiltered Gemma context", async () => {
  const checked = validateInput(fixtureDocs); assert.equal(checked.success, true);
  const docs = checked.success ? checked.documents : [];
  const originalFetch = globalThis.fetch; let calls = 0; let sent: any;
  globalThis.fetch = async (_input, init) => { calls++; sent = JSON.parse(String(init?.body)); return new Response(JSON.stringify({ model: GEMMA_MODEL, choices: [{ message: { content: JSON.stringify({ links: [], unlinked_document_ids: docs.map(d => d.document_id), analysis_summary: "Reviewed all documents.", context_requests: [] }) } }], usage: { prompt_tokens: 1234, completion_tokens: 18 }, cost: 0.001 }), { status: 200 }); };
  try {
    const result = await analyzeDocumentSet(docs, { apiKey: "test-only", timeoutMs: 1000, maxCalls: 52, maxInputTokens: 4_000_000, systemPrompt });
    assert.equal(calls, 1); assert.equal(sent.model, GEMMA_MODEL); assert.equal(sent.messages[1].content.includes('"source_cells"'), true);
    const context = JSON.parse(sent.messages[1].content.slice(sent.messages[1].content.indexOf("\n") + 1));
    assert.deepEqual(context.documents, docs); assert.ok(context.evidence_registry.length > 0); assert.ok(context.evidence_registry.every((entry: any) => entry.document_id && Array.isArray(entry.references) && entry.references.every((ref: any[]) => typeof ref[0] === "string" && typeof ref[1] === "string")));
    assert.equal(result.inputTokens, 1234); assert.equal(result.costAmount, 0.001); assert.deepEqual(result.unlinkedDocumentIds, docs.map(d => d.document_id));
  } finally { globalThis.fetch = originalFetch; }
});

test("large complete sets use Gemma document passes before whole-set relationship analysis", async () => {
  const docs = fixtureDocs, originalFetch = globalThis.fetch; let calls = 0, finalContext: any;
  globalThis.fetch = async (_input, init) => {
    calls++; const body: any = JSON.parse(String(init?.body)); const userText = body.messages[1].content;
    if (userText.startsWith("{")) { const fragment = JSON.parse(userText).document; return new Response(JSON.stringify({ model: GEMMA_MODEL, choices: [{ message: { content: JSON.stringify({ fragments: [{ document_id: fragment.document_id, chunk_index: fragment.chunk_index, facts: [], summary: "studied" }] }) } }], usage: { prompt_tokens: 100, completion_tokens: 20 } }), { status: 200 }); }
    finalContext = JSON.parse(userText.slice(userText.indexOf("\n") + 1));
    return new Response(JSON.stringify({ model: GEMMA_MODEL, choices: [{ message: { content: JSON.stringify({ links: [], unlinked_document_ids: docs.map(d => d.document_id), analysis_summary: "All reviewed.", context_requests: [] }) } }], usage: { prompt_tokens: 100, completion_tokens: 10 } }), { status: 200 });
  };
  try {
    const result = await analyzeDocumentSet(docs as any, { apiKey: "test-only", timeoutMs: 1000, maxCalls: 52, maxInputTokens: 180000, systemPrompt });
    assert.ok(calls > 1); assert.equal(result.calls, calls); assert.equal(finalContext.documents.length, docs.length); assert.equal(result.unlinkedDocumentIds.length, docs.length);
  } finally { globalThis.fetch = originalFetch; }
});

test("completed Gemma document fragments persist and resume after an interrupted run", async () => {
  const docs = ["contract-ambiguous-a.json", "contract-ambiguous-b.json", "act-ambiguous-1.json", "receipt-unknown-1.json"].map(name => JSON.parse(readFileSync(`fixtures/demo-structured-extraction/${name}`, "utf8"))) as any[];
  const originalFetch = globalThis.fetch; let saved: any, firstCalls = 0;
  globalThis.fetch = async (_input, init) => {
    firstCalls++; const request: any = JSON.parse(String(init?.body)), user = request.messages[1].content;
    if (user.startsWith("{")) { const fragment = JSON.parse(user).document; return new Response(JSON.stringify({ model: GEMMA_MODEL, choices: [{ message: { content: JSON.stringify({ fragments: [{ document_id: fragment.document_id, chunk_index: fragment.chunk_index, summary: "checkpoint", facts: [] }] }) } }], usage: { prompt_tokens: 11, completion_tokens: 4 } }), { status: 200 }); }
    return new Response(JSON.stringify({ model: GEMMA_MODEL, choices: [{ message: { content: JSON.stringify({ links: [], unlinked_document_ids: docs.map(d => d.document_id), analysis_summary: "done", context_requests: [] }) } }], usage: { prompt_tokens: 5, completion_tokens: 2 } }), { status: 200 });
  };
  try {
    const options = { apiKey: "test-only", timeoutMs: 1000, maxCalls: 52, maxInputTokens: 1800, systemPrompt: "short" };
    await analyzeDocumentSet(docs, { ...options, onProgress: async state => { saved = state; } });
    assert.ok(saved.completed_fragments.length >= docs.length); assert.equal(saved.calls, firstCalls);
    const callsBeforeResume = firstCalls; let resumed: any;
    const result = await analyzeDocumentSet(docs, { ...options, resumeProgress: saved, onProgress: async state => { resumed = state; } });
    assert.equal(firstCalls - callsBeforeResume, 1); assert.equal(result.calls, saved.calls + 1); assert.equal(result.strategy, "document_fragments_then_full_set");
  } finally { globalThis.fetch = originalFetch; }
});

test("staged Gemma can request an exact original fragment and reconsider the whole set", async () => {
  const docs = [{ document_id: "long-doc", document_type: "contract", long_text: "x".repeat(12_000) }], originalFetch = globalThis.fetch; let requestedContext: any, finalPasses = 0;
  globalThis.fetch = async (_input, init) => {
    const request: any = JSON.parse(String(init?.body)), user = request.messages[1].content;
    if (user.startsWith("{")) { const fragment = JSON.parse(user).document; return new Response(JSON.stringify({ model: GEMMA_MODEL, choices: [{ message: { content: JSON.stringify({ fragments: [{ document_id: fragment.document_id, chunk_index: fragment.chunk_index, summary: "navigation only", facts: [] }] }) } }], usage: { prompt_tokens: 10, completion_tokens: 2 } }), { status: 200 }); }
    finalPasses++;
    const context = JSON.parse(user.slice(user.indexOf("\n") + 1));
    if (finalPasses === 1) return new Response(JSON.stringify({ model: GEMMA_MODEL, choices: [{ message: { content: JSON.stringify({ links: [], unlinked_document_ids: [docs[0].document_id], analysis_summary: "Need original source", context_requests: [{ document_id: docs[0].document_id, chunk_index: 0, reason: "Inspect source details", paths: [] }] }) } }], usage: { prompt_tokens: 10, completion_tokens: 2 } }), { status: 200 });
    requestedContext = context.requested_source_fragments;
    return new Response(JSON.stringify({ model: GEMMA_MODEL, choices: [{ message: { content: JSON.stringify({ links: [], unlinked_document_ids: [docs[0].document_id], analysis_summary: "Reconsidered using the original fragment", context_requests: [] }) } }], usage: { prompt_tokens: 10, completion_tokens: 2 } }), { status: 200 });
  };
  try {
    const result = await analyzeDocumentSet(docs as any, { apiKey: "test-only", timeoutMs: 1000, maxCalls: 300, maxInputTokens: 1800, systemPrompt: "short" });
    assert.equal(result.complete, true); assert.equal(finalPasses, 2); assert.equal(result.analysisSummary, "Reconsidered using the original fragment");
    assert.equal(requestedContext.length, 1); assert.equal(requestedContext[0].document_id, docs[0].document_id); assert.ok(requestedContext[0].fragment.path_values.length > 0);
  } finally { globalThis.fetch = originalFetch; }
});

test("full-set Gemma can request an original fragment and resume from its checkpoint", async () => {
  const docs = fixtureDocs.filter(doc => ["contract-2026-0315", "addendum-2026-04"].includes(doc.document_id));
  const requestedId = "contract-2026-0315", requestedPath = "fields.contract_number.value", originalFetch = globalThis.fetch;
  let modelCalls = 0, saved: any, resumedContext: any;
  globalThis.fetch = async (_input, init) => {
    modelCalls++;
    const body: any = JSON.parse(String(init?.body)), user = body.messages[1].content;
    if (modelCalls === 1) return new Response(JSON.stringify({ model: GEMMA_MODEL, choices: [{ message: { content: JSON.stringify({ links: [], unlinked_document_ids: docs.map(doc => doc.document_id), analysis_summary: "Checking the source field.", context_requests: [{ document_id: requestedId, chunk_index: 0, reason: "Re-read the original contract number", paths: [requestedPath] }] }) } }] }), { status: 200 });
    resumedContext = JSON.parse(user.slice(user.indexOf("\n") + 1));
    return new Response(JSON.stringify({ model: GEMMA_MODEL, choices: [{ message: { content: JSON.stringify({ links: [], unlinked_document_ids: docs.map(doc => doc.document_id), analysis_summary: "Full source rechecked.", context_requests: [] }) } }] }), { status: 200 });
  };
  try {
    const options = { apiKey: "test-only", timeoutMs: 1000, maxCalls: 4, maxInputTokens: 999999, systemPrompt, maxModelCallsPerInvocation: 1 };
    const partial = await analyzeDocumentSet(docs, { ...options, onProgress: async state => { saved = state; } });
    assert.equal(partial.complete, false); assert.equal(saved.calls, 1); assert.equal(saved.requested_source_fragments.length, 1);
    const result = await analyzeDocumentSet(docs, { ...options, resumeProgress: saved });
    assert.equal(result.complete, true); assert.equal(result.calls, 2); assert.equal(modelCalls, 2);
    assert.equal(resumedContext.documents.length, docs.length);
    assert.ok(resumedContext.requested_source_fragments[0].fragment.path_values.some((item: any) => item.path === requestedPath));
  } finally { globalThis.fetch = originalFetch; }
});

test("model choice is pinned and missing credentials fail without fallback", async () => {
  await assert.rejects(() => analyzeDocumentSet([], { apiKey: "test-only", timeoutMs: 10, maxCalls: 1, model: "other/model" }), /Разрешена только модель/);
  await assert.rejects(() => linkDocuments(fixtureDocs), /POLZA_API_KEY/);
});

test("unknown evidence references are diagnosed, then Gemma can repair its own proposal", async () => {
  const docs = fixtureDocs.slice(0, 2), originalFetch = globalThis.fetch;
  const registry = buildEvidenceRegistry(docs), hasExactSource = (ref: any) => ref.provenance?.source_available === true && typeof ref.raw_value === "string" && typeof ref.provenance.source_text === "string" && ref.provenance.source_text.normalize("NFKC").toLowerCase().includes(ref.raw_value.normalize("NFKC").toLowerCase()), sourceRef = registry.find(ref => ref.document_id === docs[0].document_id && hasExactSource(ref))?.reference_id, targetRef = registry.find(ref => ref.document_id === docs[1].document_id && hasExactSource(ref))?.reference_id;
  assert.ok(sourceRef && targetRef); let calls = 0;
  const proposal = { relationship_type: "new_open_relationship", source_document_id: docs[0].document_id, target_document_id: docs[1].document_id, evidence: [{ source_reference_id: "invented-source", target_reference_id: "invented-target", signal: "context", explanation: "initial model proposal" }], confidence: 0.7, status: "proposed" };
  globalThis.fetch = async (_input, init) => {
    calls++; const body: any = JSON.parse(String(init?.body));
    const value = calls === 1 ? { links: [proposal], unlinked_document_ids: [], analysis_summary: "", context_requests: [] } : { corrections: [{ proposal_index: 0, action: "replace", link: { ...proposal, evidence: [{ source_reference_id: sourceRef, target_reference_id: targetRef, signal: "context", explanation: "corrected IDs" }] } }] };
    return new Response(JSON.stringify({ model: GEMMA_MODEL, choices: [{ message: { content: JSON.stringify(value) } }] }), { status: 200 });
  };
  try {
    const result = await analyzeDocumentSet(docs as any, { apiKey: "test-only", timeoutMs: 1000, maxCalls: 52, maxInputTokens: 999999, systemPrompt });
    assert.equal(result.links.length, 1); assert.equal(result.calls, 2); assert.equal(result.invalidRelationshipDiagnostics.length, 1); assert.equal(result.invalidRelationshipDiagnostics[0].resolution, "corrected", JSON.stringify(result.invalidRelationshipDiagnostics[0]));
    assert.deepEqual(result.invalidRelationshipDiagnostics[0].proposal, proposal); assert.ok((result.links[0].evidence[0].source.path));
    calls = 0;
    const linked = await linkDocuments(docs, { llm: { enabled: true, apiKey: "test-only", maxCalls: 52, maxInputTokens: 999999, systemPrompt } }); assert.equal(linked.links.length, 1); assert.equal(linked.link_validation_diagnostics.length, 1); assert.equal(linked.link_validation_diagnostics[0].resolution, "corrected"); assert.ok(linked.link_validation_diagnostics[0].proposal);
  }
  finally { globalThis.fetch = originalFetch; }
});

test("source text OCR uncertainty keeps the Gemma link for review with a diagnostic", async () => {
  const docs = structuredClone(fixtureDocs.filter(doc => ["contract-2026-0315", "addendum-2026-04"].includes(doc.document_id))) as any[];
  const source = docs.find(doc => doc.document_id === "contract-2026-0315");
  const target = docs.find(doc => doc.document_id === "addendum-2026-04");
  source.fields.contract_number.provenance.source_text = "КД-24/03-1S";
  const registry = buildEvidenceRegistry(docs), sourceRef = registry.find(ref => ref.document_id === source.document_id && ref.json_path === "fields.contract_number.value")!, targetRef = registry.find(ref => ref.document_id === target.document_id && ref.json_path === "fields.base_contract.value")!;
  const relationship = { relationship_type: "amends", source_document_id: source.document_id, target_document_id: target.document_id, evidence: [{ source_reference_id: sourceRef.reference_id, target_reference_id: targetRef.reference_id, signal: "reference", explanation: "The addendum names the base agreement." }], confidence: 0.9, status: "confirmed" };
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ model: GEMMA_MODEL, choices: [{ message: { content: JSON.stringify({ links: [relationship], unlinked_document_ids: [], analysis_summary: "One OCR fragment needs review.", context_requests: [] }) } }] }), { status: 200 });
  try {
    const result = await linkDocuments(docs, { llm: { enabled: true, apiKey: "test-only", maxCalls: 52, maxInputTokens: 999999, systemPrompt } });
    assert.equal(result.links.length, 1);
    assert.equal(result.links[0].status, "review");
    assert.equal(result.review_required[0].link_id, result.links[0].link_id);
    assert.equal(result.link_validation_diagnostics.length, 1);
    assert.ok(result.link_validation_diagnostics[0].reason_codes.includes("source_text_value_mismatch"));
    assert.equal(linkingOutputSchema.safeParse(result).success, true);
  } finally { globalThis.fetch = originalFetch; }
});

test("malformed status and path-shaped row_id retain the model relation as review", async () => {
  const docs = fixtureDocs.filter(doc => ["contract-2026-0315", "addendum-2026-04"].includes(doc.document_id));
  const registry = buildEvidenceRegistry(docs), sourceRef = registry.find(ref => ref.document_id === docs[0].document_id && ref.provenance?.source_available === true)!, targetRef = registry.find(ref => ref.document_id === docs[1].document_id && ref.provenance?.source_available === true)!;
  const proposal = { relationship_type: "amends", source_document_id: docs[0].document_id, target_document_id: docs[1].document_id, source_row_id: sourceRef.json_path, evidence: [{ source_reference_id: sourceRef.reference_id, target_reference_id: targetRef.reference_id, signal: "context", explanation: "The addendum changes terms." }], confidence: 0.8, status: "unverified" };
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ model: GEMMA_MODEL, choices: [{ message: { content: JSON.stringify({ links: [proposal], unlinked_document_ids: [], analysis_summary: "Keep the uncertain proposal visible.", context_requests: [] }) } }] }), { status: 200 });
  try {
    const result = await linkDocuments(docs, { llm: { enabled: true, apiKey: "test-only", maxCalls: 52, maxInputTokens: 999999, systemPrompt } });
    assert.equal(result.links.length, 1); assert.equal(result.links[0].status, "review");
    assert.equal(result.links[0].source_row_id, undefined);
    assert.equal(result.link_validation_diagnostics.length, 1);
    assert.ok(result.link_validation_diagnostics[0].reason_codes.includes("invalid_link_metadata"));
    assert.ok(result.link_validation_diagnostics[0].reason_codes.includes("row_id_not_found"));
    assert.equal(result.link_validation_diagnostics[0].candidate_status, "review");
    assert.deepEqual(result.link_validation_diagnostics[0].proposal, proposal);
    assert.equal(linkingOutputSchema.safeParse(result).success, true);
  } finally { globalThis.fetch = originalFetch; }
});

test("a bad evidence citation does not discard another technically valid citation", async () => {
  const docs = fixtureDocs.filter(doc => ["contract-2026-0315", "addendum-2026-04"].includes(doc.document_id));
  const registry = buildEvidenceRegistry(docs), sourceRef = registry.find(ref => ref.document_id === docs[0].document_id && ref.provenance?.source_available === true)!, targetRef = registry.find(ref => ref.document_id === docs[1].document_id && ref.provenance?.source_available === true)!;
  const proposal = { relationship_type: "amends", source_document_id: docs[0].document_id, target_document_id: docs[1].document_id, evidence: [{ source_reference_id: "invented", target_reference_id: "invented", signal: "bad", explanation: "unresolvable" }, { source_reference_id: sourceRef.reference_id, target_reference_id: targetRef.reference_id, signal: "valid", explanation: "exact source values" }], confidence: 0.8, status: "confirmed" };
  const originalFetch = globalThis.fetch; let calls = 0;
  globalThis.fetch = async () => {
    calls++;
    const content = calls === 1 ? { links: [proposal], unlinked_document_ids: [], analysis_summary: "One citation is valid.", context_requests: [] } : { corrections: [] };
    return new Response(JSON.stringify({ model: GEMMA_MODEL, choices: [{ message: { content: JSON.stringify(content) } }] }), { status: 200 });
  };
  try {
    const result = await analyzeDocumentSet(docs, { apiKey: "test-only", timeoutMs: 1000, maxCalls: 52, maxInputTokens: 999999, systemPrompt });
    assert.equal(result.links.length, 1); assert.equal(result.links[0].status, "review");
    assert.equal(result.links[0].evidence.length, 1); assert.equal(result.invalidRelationshipDiagnostics.length, 1);
    assert.equal(result.invalidRelationshipDiagnostics[0].resolution, "review_required");
    assert.deepEqual(result.invalidRelationshipDiagnostics[0].proposal, proposal);
  } finally { globalThis.fetch = originalFetch; }
});

test("LLM-only output satisfies the versioned stage 4 contract", async () => {
  const docs = fixtureDocs, originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ model: GEMMA_MODEL, choices: [{ message: { content: JSON.stringify({ links: [], unlinked_document_ids: docs.map(d => d.document_id), analysis_summary: "Complete set reviewed.", context_requests: [] }) } }], usage: { prompt_tokens: 100, completion_tokens: 10 } }), { status: 200 });
  try { const result = await linkDocuments(docs, { llm: { enabled: true, apiKey: "test-only", maxCalls: 52, maxInputTokens: 4_000_000, systemPrompt } }); assert.equal(linkingOutputSchema.safeParse(result).success, true); assert.equal(result.contract_version, "1.2.0"); assert.equal(result.processing_metadata.llm.model, GEMMA_MODEL); }
  finally { globalThis.fetch = originalFetch; }
});
