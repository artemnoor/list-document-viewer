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
const offlineSemanticReply = (context: any) => {
  if (context.stage === "discover") return { fragments: context.fragments.map((fragment: any) => ({ fragment_id: fragment.fragment_id, summary: "Offline structural coverage only", anchors: fragment.facts.slice(0, 2).map((fact: any) => ({ reference_id: fact[0], meaning: "Offline source anchor" })), open_questions: [] })) };
  if (context.stage === "route") return { decisions: context.document_pairs.map((pair: any) => ({ ...pair, state: "candidate", reason: "Offline structural fixture checks the candidate verifier path only", reference_ids: pair.document_ids.map((documentId: string) => context.navigation.find((fragment: any) => context.fragment_manifest.find((item: any) => item.fragment_id === fragment.fragment_id)?.document_id === documentId)?.anchors?.[0]?.reference_id).filter(Boolean), fragment_ids: context.fragment_manifest.filter((fragment: any) => pair.document_ids.includes(fragment.document_id)).map((fragment: any) => fragment.fragment_id) })) };
  return { links: [], unlinked_document_ids: [], context_requests: [], pair_decisions: context.candidates.map((candidate: any) => ({ pair_id: candidate.pair_id, state: "no_relation", reason: "Offline verifier inspected supplied originals; semantic gold not measured" })), analysis_summary: "Offline structural coverage only" };
};
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

test("large upstream sets compare bounded originals with complete document coverage", async (t) => {
  const originalFetch = globalThis.fetch; const seen = new Set<string>(); let calls=0, saved:any;
  globalThis.fetch = async (_input, init) => {
    calls++; const body = JSON.parse(String(init?.body)), user=body.messages[1].content;
    const context=JSON.parse(user.slice(user.indexOf("{") ));
    assert.ok(Math.ceil((body.messages[0].content.length+user.length)/2)<=180000);
    if (context.stage === "discover") for(const fragment of context.fragments) {seen.add(fragment.document_id);assert.ok(fragment.facts.length || fragment.rows.length === 0);}
    return new Response(JSON.stringify({model:GEMMA_MODEL,choices:[{message:{content:JSON.stringify(offlineSemanticReply(context))}}]}),{status:200});
  };
  try {
    const result=await analyzeDocumentSet(fixtureDocs,{apiKey:"test-only",timeoutMs:1000,maxCalls:10000,maxInputTokens:180000,systemPrompt,onProgress:async s=>{saved=s;}});
    assert.equal(result.complete,true); assert.ok(calls>1);assert.equal(result.calls,calls);
    assert.deepEqual([...seen].sort(),fixtureDocs.map(d=>d.document_id).sort());
    assert.equal(saved.coverage.completed_tasks,saved.coverage.total_tasks);
    assert.equal(saved.coverage.reference_ids.length,buildEvidenceRegistry(fixtureDocs).length);
    t.diagnostic(JSON.stringify({kind:"offline_transport_coverage",documents:fixtureDocs.length,calls,fragments:saved.total_fragments,tasks:saved.coverage.total_tasks,references:saved.coverage.reference_ids.length}));
  } finally {globalThis.fetch=originalFetch;}
});

for (const count of [3, 5]) test(`native fixture subset of ${count} documents retains complete source coverage`, async (t) => {
  const selected = fixtureDocs.filter(doc => doc.document_type !== "addendum").slice(0, count);
  assert.equal(selected.length, count);
  const original = globalThis.fetch;
  globalThis.fetch = async (_input, init) => {
    const user = JSON.parse(String(init?.body)).messages[1].content;
    const context = JSON.parse(user.slice(user.indexOf("{")));
    return new Response(JSON.stringify({ model: GEMMA_MODEL, choices: [{ message: { content: JSON.stringify(offlineSemanticReply(context)) } }] }), { status: 200 });
  };
  try {
    const result = await analyzeDocumentSet(selected, { apiKey: "offline-only", timeoutMs: 1000, maxCalls: 10000, maxInputTokens: 180000, systemPrompt });
    assert.equal(result.complete, true);
    assert.equal(result.analysisCoverage?.processed_references, buildEvidenceRegistry(selected).length);
    assert.equal(result.analysisCoverage?.completed_tasks, result.analysisCoverage?.total_tasks);
    t.diagnostic(JSON.stringify({ kind: "offline_transport_coverage", documents: count, calls: result.calls, coverage: result.analysisCoverage }));
  } finally { globalThis.fetch = original; }
});

test("completed bounded source tasks persist and resume with no repeated requests", async () => {
  const docs=[{document_id:"single",document_type:"contract",text:"x".repeat(5000)}] as any[];
  const originalFetch=globalThis.fetch;let saved:any,calls=0;const users=new Set<string>();
  globalThis.fetch=async(_input,init)=>{
    const user=JSON.parse(String(init?.body)).messages[1].content;
    assert.equal(users.has(user),false);users.add(user);calls++;
    return new Response(JSON.stringify({model:GEMMA_MODEL,choices:[{message:{content:JSON.stringify({links:[],unlinked_document_ids:[],context_requests:[],analysis_summary:"Read source"})}}]}),{status:200});
  };
  try{
    const opts={apiKey:"test-only",timeoutMs:1000,maxCalls:300,maxInputTokens:2400,systemPrompt:"short",maxModelCallsPerInvocation:1,onProgress:async(s:any)=>{saved=s;}};
    let result=await analyzeDocumentSet(docs,opts);assert.equal(result.complete,false);assert.deepEqual(result.unlinkedDocumentIds,[]);
    for(let i=0;!result.complete&&i<300;i++)result=await analyzeDocumentSet(docs,{...opts,resumeProgress:saved});
    assert.equal(result.complete,true);assert.equal(result.calls,calls);
    const before=calls;await analyzeDocumentSet(docs,{...opts,resumeProgress:saved});assert.equal(calls,before);
  }finally{globalThis.fetch=originalFetch;}
});

test("bounded Gemma can request another original fragment and preserve it across resume",async()=>{
  const docs=[{document_id:"long-doc",document_type:"contract",text:"x".repeat(5000)}] as any[];
  const originalFetch=globalThis.fetch;let calls=0,saved:any,expanded=false;
  globalThis.fetch=async(_input,init)=>{
    calls++;const user=JSON.parse(String(init?.body)).messages[1].content,context=JSON.parse(user.slice(user.indexOf("\n")+1));
    if(calls===2) {assert.equal(context.documents.length,2);assert.ok(context.documents.some((f:any)=>f.chunk_index===1));expanded=true;}
    return new Response(JSON.stringify({model:GEMMA_MODEL,choices:[{message:{content:JSON.stringify({links:[],unlinked_document_ids:[],context_requests:calls===1?[{document_id:"long-doc",chunk_index:1,paths:[],reason:"Read neighboring source"}]:[],analysis_summary:"Read originals"})}}]}),{status:200});
  };
  try{
    const opts={apiKey:"test-only",timeoutMs:1000,maxCalls:300,maxInputTokens:2400,systemPrompt:"short",maxModelCallsPerInvocation:1,onProgress:async(s:any)=>{saved=s;}};
    let result=await analyzeDocumentSet(docs,opts);assert.equal(result.complete,false);
    for(let i=0;!result.complete&&i<300;i++)result=await analyzeDocumentSet(docs,{...opts,resumeProgress:saved});
    assert.equal(result.complete,true);assert.equal(expanded,true);
    assert.ok(saved.bounded_tasks[0].response._expanded_fragment_keys.length===2);
  }finally{globalThis.fetch=originalFetch;}
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
