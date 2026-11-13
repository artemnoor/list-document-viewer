import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { analyzeDocumentSet, GEMMA_MODEL } from "../src/linking/llm-matcher";
import { planSemanticLinking } from "../src/linking/semantic-plan";
import { estimateRequestInputTokens } from "../scripts/quality-live-budget";

const documents = readdirSync("fixtures/upstream-structured-extraction-1.2.0").filter(name => name.endsWith(".json")).map(name => JSON.parse(readFileSync(`fixtures/upstream-structured-extraction-1.2.0/${name}`, "utf8"))).filter(doc => doc.document_type !== "addendum");
const systemPrompt = readFileSync("prompts/document-linking-system.md", "utf8");
const reply = (value: unknown) => new Response(JSON.stringify({ model: GEMMA_MODEL, choices: [{ message: { content: JSON.stringify(value) }, finish_reason: "stop" }], usage: { prompt_tokens: 100, completion_tokens: 20 } }));

test("full five-document fixture leaves room for Extraction within Q1 without skipping semantic sources", async (t) => {
  const original = globalThis.fetch;
  let calls = 0;
  let maxSerializedTokens = 0;
  let maxSerializedStage = "";
  globalThis.fetch = async (_url, init) => {
    calls++;
    const body = JSON.parse(String(init?.body));
    assert.ok(Math.ceil((body.messages[0].content.length + body.messages[1].content.length) / 2) <= 16000);
    const serializedTokens = estimateRequestInputTokens(body);
    if (serializedTokens > maxSerializedTokens) { maxSerializedTokens = serializedTokens; maxSerializedStage = JSON.parse(body.messages[1].content.slice(body.messages[1].content.indexOf("{"))).stage; }
    assert.ok(body.max_tokens <= 4000);
    const user = body.messages[1].content;
    const context = JSON.parse(user.slice(user.indexOf("{")));
    if (context.stage === "discover") return reply({ fragments: context.fragments.map((fragment: any) => ({ fragment_id: fragment.fragment_id, summary: "Financial facts, original rows and possible documentary relations", anchors: fragment.facts.slice(0, 2).map((fact: any) => ({ reference_id: fact[0], meaning: "Source fact for detailed comparison" })), open_questions: [] })) });
    if (context.stage === "route") return reply({ decisions: context.document_pairs.map((pair: any) => ({ ...pair, state: "candidate", reference_ids: pair.document_ids.map((docId: string) => context.navigation.find((fragment: any) => context.fragment_manifest.find((f: any) => f.fragment_id === fragment.fragment_id)?.document_id === docId)?.anchors?.[0]?.reference_id).filter(Boolean), reason: "Needs original factual verification", fragment_ids: context.fragment_manifest.filter((fragment: any) => pair.document_ids.includes(fragment.document_id)).map((fragment: any) => fragment.fragment_id) })) });
    return reply({ links: [], unlinked_document_ids: [], context_requests: [], pair_decisions: context.candidates.map((candidate: any) => ({ pair_id: candidate.pair_id, state: "insufficient_evidence", reason: "Offline structural verification does not make semantic negative claims" })), analysis_summary: "Offline structural verification; no semantic gold claim" });
  };
  try {
    const result = await analyzeDocumentSet(documents, { apiKey: "offline-only", timeoutMs: 1000, maxCalls: 28, maxInputTokens: 16000, systemPrompt });
    assert.equal(result.complete, true);
    assert.ok(calls <= 28);
    assert.ok(maxSerializedTokens <= 16000, `serialized request exceeded Q1: ${maxSerializedTokens} in ${maxSerializedStage}`);
    assert.equal(result.analysisCoverage?.documents.length, 5);
    assert.equal(result.analysisCoverage?.processed_references, result.analysisCoverage?.total_references);
    t.diagnostic(JSON.stringify({ kind: "q1_offline_transport", linking_calls: calls, extraction_reserved_calls: 12, q1_total: calls + 12, total_q1_budget: 40, max_estimated_input_tokens: maxSerializedTokens, max_input_stage: maxSerializedStage, processed_references: result.analysisCoverage?.processed_references, total_references: result.analysisCoverage?.total_references, model_read_references: result.analysisCoverage?.semantic?.model_read_references, metadata_audited_separately: result.analysisCoverage?.semantic?.metadata_references, source_rows: result.analysisCoverage?.semantic?.source_rows.length, document_pairs: result.analysisCoverage?.semantic?.pair_decisions.length, pair_outcomes: [...new Set(result.analysisCoverage?.semantic?.pair_decisions.map((pair: any) => pair.state))] }));
  } finally { globalThis.fetch = original; }
});

test("Parser source_text is included as navigation context and remains distinct from citeable value", () => {
  const document = structuredClone(documents[0]);
  const field = Object.values(document.fields).find((value: any) => value && typeof value === "object" && value.provenance && "value" in value) as any;
  assert.ok(field);
  const original = field.provenance.source_text;
  field.provenance.source_text = "Заголовок таблицы: смысл поля и контекст исходной строки";
  const plan = planSemanticLinking([document], { maxInputTokens: 16000, systemPrompt });
  const facts = plan.discovery_batches.flatMap(batch => JSON.parse(batch.context).fragments.flatMap((fragment: any) => fragment.facts));
  const context = facts.find((fact: any) => fact[4]?.kind === "source_text");
  assert.ok(context);
  assert.equal(context[2], field.provenance.source_text);
  assert.equal(context[3], facts.find((fact: any) => fact[0] === context[0])?.[3]);
  assert.notEqual(context[2], field.value);
  field.provenance.source_text = original;
});

test("full-five no_relation decisions are audited against anchors from every source fragment within Q1", async (t) => {
  const original = globalThis.fetch; let calls = 0, maxEstimated = 0, verified = new Set<string>();
  globalThis.fetch = async (_url, init) => {
    calls++;
    const body = JSON.parse(String(init?.body)); maxEstimated = Math.max(maxEstimated, estimateRequestInputTokens(body));
    const user = body.messages[1].content, context = JSON.parse(user.slice(user.indexOf("{")));
    if (context.stage === "discover") return reply({ fragments: context.fragments.map((fragment: any) => ({ fragment_id: fragment.fragment_id, summary: "Every fragment has been read", anchors: fragment.facts.slice(0, 24).map((fact: any) => ({ reference_id: fact[0], meaning: "Original fact retained for candidate or negative audit" })), open_questions: [] })) });
    if (context.stage === "route") return reply({ decisions: context.document_pairs.map((pair: any) => ({ ...pair, state: "no_relation", reason: "Tentative negative; original anchors from all fragments require review", reference_ids: [...new Set(context.navigation.filter((nav: any) => pair.document_ids.includes(context.fragment_manifest.find((item: any) => item.fragment_id === nav.fragment_id)?.document_id)).flatMap((nav: any) => nav.anchors.map((anchor: any) => anchor.reference_id)))], fragment_ids: context.fragment_manifest.filter((fragment: any) => pair.document_ids.includes(fragment.document_id)).map((fragment: any) => fragment.fragment_id) })) });
    const pairDecisions = context.candidates.map((candidate: any) => { verified.add(candidate.document_pair_id ?? candidate.pair_id); assert.ok(candidate.original_facts.every((fragment: any) => fragment.facts.length > 0)); return { pair_id: candidate.pair_id, state: "no_relation", reason: "All supplied original anchors and selected rows checked" }; });
    return reply({ links: [], unlinked_document_ids: [], context_requests: [], pair_decisions: pairDecisions, analysis_summary: "Offline audit plumbing only; not a semantic no-link claim" });
  };
  try {
    const result = await analyzeDocumentSet(documents, { apiKey: "offline-only", timeoutMs: 1000, maxCalls: 28, maxInputTokens: 16000, systemPrompt });
    assert.equal(result.complete, true);
    assert.equal(verified.size, 10);
    assert.ok(result.analysisCoverage?.semantic?.pair_decisions.every((pair: any) => pair.state === "no_link_found"));
    assert.equal(result.analysisCoverage?.processed_references, result.analysisCoverage?.total_references);
    assert.ok(calls + 12 <= 40, `Linking=${calls}, Extraction reserve=12, Q1=${calls + 12}/40`);
    assert.ok(maxEstimated <= 16000);
    t.diagnostic(JSON.stringify({ kind: "full_five_all_negative_anchor_audit_mock_not_semantic_quality", linking_calls: calls, extraction_reserved_calls: 12, total_q1_calls: calls + 12, q1_limit: 40, max_estimated_input_tokens: maxEstimated, verified_negative_pairs: verified.size, references_processed: result.analysisCoverage?.processed_references, references_total: result.analysisCoverage?.total_references, outcome: "all mock replies no_relation after original-anchor verification" }));
  } finally { globalThis.fetch = original; }
});
