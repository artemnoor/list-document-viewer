import { test } from "node:test";
import assert from "node:assert/strict";
import { analyzeDocumentSet, GEMMA_MODEL } from "../src/linking/llm-matcher";
import { buildEvidenceRegistry } from "../src/linking/evidence-registry";
import { resolveJsonPath } from "../src/linking/evidence-validation";
import { planSemanticLinking } from "../src/linking/semantic-plan";
import { documents as docs, gold, systemPrompt } from "../evaluation/synthetic-routing-fixture";
const response = (payload: unknown) => new Response(JSON.stringify({ model: GEMMA_MODEL, choices: [{ message: { content: JSON.stringify(payload) }, finish_reason: "stop" }], usage: { prompt_tokens: 300, completion_tokens: 100 } }));
const edgeKey = (edge: any) => JSON.stringify([edge.source_document_id, edge.target_document_id, edge.relationship_type, edge.source_row_id ?? null, edge.target_row_id ?? null]);

test("negative routing is provisional: original-anchor verification recovers repeated-amount and row links", async (t) => {
  const originalFetch = globalThis.fetch;
  const registry = buildEvidenceRegistry(docs), byPath = new Map(registry.map(ref => [`${ref.document_id}\0${ref.json_path}`, ref]));
  const plan = planSemanticLinking(docs, { maxInputTokens: 8000, systemPrompt });
  const canonicalId = (id: string) => Object.entries(plan.alias_map).find(([canonical, aliases]) => canonical === id || aliases.includes(id))?.[0] ?? id;
  const goldEdges = gold.positive_relations.map((edge: any) => {
    const source = byPath.get(`${edge.source_document_id}\0${edge.source_path}`), target = byPath.get(`${edge.target_document_id}\0${edge.target_path}`);
    return { ...edge, source_ref: source && { ...source, reference_id: canonicalId(source.reference_id) }, target_ref: target && { ...target, reference_id: canonicalId(target.reference_id) } };
  });
  assert.ok(goldEdges.every((edge: any) => edge.source_ref && edge.target_ref), "independent gold must cite existing fixture paths");
  let calls = 0, routingPairs: any[] = [], auditedPairs = new Set<string>(), mockFailure = "", injectedDiscoveryFailure = false;
  globalThis.fetch = async (_input, init) => {
    try {
    calls++;
    const body = JSON.parse(String(init?.body)), user = body.messages[1].content, jsonContext = user.slice(user.indexOf("{")).split("\n\nValidation correction:")[0], context = JSON.parse(jsonContext);
    if (context.stage === "discover") {
      if (!injectedDiscoveryFailure) {
        injectedDiscoveryFailure = true;
        return response({ fragments: context.fragments.map(() => ({ fragment_id: "unknown-fragment", summary: "invalid first response", anchors: [], open_questions: [] })) });
      }
      if (user.includes("Validation correction:")) mockFailure = "invalid discovery response was retried with bounded validator feedback";
      return response({ fragments: context.fragments.map((fragment: any) => ({ fragment_id: fragment.fragment_id, summary: fragment.facts.map((fact: any) => fact[2]).filter((raw: any) => typeof raw === "string").join(" | ").slice(0, 800) || "Source rows", anchors: fragment.facts.slice(0, 24).map((fact: any) => ({ reference_id: fact[0], meaning: String(fact[1].join("; ")).slice(0, 160) })), open_questions: [] })) });
    }
    if (context.stage === "route") {
      routingPairs = context.document_pairs.map((pair: any) => ({ ...pair, state: "no_relation" }));
      // Adversarial mock route: it marks every pair negative, including gold positives.
      // This models a false negative from condensed navigation; independent labels stay in the gold file.
      return response({ decisions: context.document_pairs.map((pair: any) => ({ ...pair, state: "no_relation", reason: "Only a compact summary was considered; verify original anchors", reference_ids: [...new Set(context.navigation.filter((nav: any) => pair.document_ids.includes(context.fragment_manifest.find((item: any) => item.fragment_id === nav.fragment_id)?.document_id)).flatMap((nav: any) => nav.anchors.map((anchor: any) => anchor.reference_id)))], fragment_ids: context.fragment_manifest.filter((fragment: any) => pair.document_ids.includes(fragment.document_id)).map((fragment: any) => fragment.fragment_id) })) });
    }
    const links: any[] = [], pairDecisions: any[] = [];
    for (const candidate of context.candidates) {
      auditedPairs.add(candidate.pair_id);
      const expectedFragments = plan.fragments.filter(fragment => candidate.document_ids.includes(fragment.document_id)).map(fragment => fragment.fragment_id).sort();
      assert.deepEqual(candidate.original_facts.map((fragment: any) => fragment.fragment_id).sort(), expectedFragments, "negative verification must receive anchors from every source fragment");
      const allFactIds = new Set(candidate.original_facts.flatMap((fragment: any) => fragment.facts.map((fact: any) => fact[0])));
      const expected = goldEdges.filter((edge: any) => candidate.document_ids.includes(edge.source_document_id) && candidate.document_ids.includes(edge.target_document_id));
      if (!expected.length) { pairDecisions.push({ pair_id: candidate.pair_id, state: "no_relation", reason: "Original semantic facts and rows checked" }); continue; }
      for (const edge of expected) {
        assert.ok(allFactIds.has(edge.source_ref.reference_id), `gold source alias is not model-visible: ${edge.source_document_id}:${edge.source_path}:${edge.source_ref.reference_id}`); assert.ok(allFactIds.has(edge.target_ref.reference_id), `gold target alias is not model-visible: ${edge.target_document_id}:${edge.target_path}:${edge.target_ref.reference_id}`);
        links.push({ relationship_type: edge.relationship_type, source_document_id: edge.source_document_id, target_document_id: edge.target_document_id, ...(edge.source_row_id ? { source_row_id: edge.source_row_id } : {}), ...(edge.target_row_id ? { target_row_id: edge.target_row_id } : {}), evidence: [{ source_reference_id: edge.source_ref.reference_id, target_reference_id: edge.target_ref.reference_id, signal: "semantic_and_row_context", explanation: "Mock verifier reads the exact fixture evidence IDs and independent synthetic scenario." }], explanation: "Synthetic scenario relation", confidence: 0.95, status: "confirmed" });
      }
      pairDecisions.push({ pair_id: candidate.pair_id, state: "supported", reason: "Original facts support one or more relations" });
    }
    return response({ links, unlinked_document_ids: [], context_requests: [], pair_decisions: pairDecisions, analysis_summary: "Synthetic mock only; no real-model claim" });
    } catch (error: any) {
      mockFailure = String(error?.stack ?? error);
      return response({ links: [], unlinked_document_ids: [], context_requests: [], pair_decisions: [], analysis_summary: "Mock assertion failure captured for test diagnosis" });
    }
  };
  try {
    const result = await analyzeDocumentSet(docs, { apiKey: "offline-only", timeoutMs: 1000, maxCalls: 28, maxInputTokens: 8000, systemPrompt });
    assert.match(mockFailure, /retried with bounded validator feedback/);
    const goldKeys = new Set<string>(goldEdges.map(edgeKey)), predictionKeys = new Set<string>(result.links.map(edgeKey));
    const truePositive = [...predictionKeys].filter(key => goldKeys.has(key)).length, falsePositive = [...predictionKeys].filter(key => !goldKeys.has(key)).length, falseNegative = [...goldKeys].filter(key => !predictionKeys.has(key)).length;
    const precision = truePositive / Math.max(1, truePositive + falsePositive), recall = truePositive / Math.max(1, truePositive + falseNegative), f1 = 2 * precision * recall / Math.max(1e-9, precision + recall);
    const goldPairs = new Set(gold.positive_relations.map((edge: any) => JSON.stringify([edge.source_document_id, edge.target_document_id])));
    const routedPositivePairs = new Set(routingPairs.filter(pair => pair.state === "candidate" && goldPairs.has(JSON.stringify(pair.document_ids))).map(pair => JSON.stringify(pair.document_ids)));
    const routingRecall = routedPositivePairs.size / goldPairs.size;
    assert.equal(routingRecall, 0, "adversarial route is expected to miss all synthetic positives");
    assert.equal(recall, 1, "verification must recover positives from full originals after false-negative routing");
    assert.equal(precision, 1); assert.equal(f1, 1);
    assert.equal(result.invalidRelationshipDiagnostics.length, 0);
    assert.equal(result.links.length, goldEdges.length);
    assert.ok(gold.explicit_negative_pairs.every((pair: string[]) => !result.links.some((link: any) => pair.includes(link.source_document_id) && pair.includes(link.target_document_id))));
    for (const edge of goldEdges.filter((item: any) => item.source_row_id || item.target_row_id)) {
      const actual = result.links.find((link: any) => edgeKey(link) === edgeKey(edge));
      assert.ok(actual);
      assert.equal(actual.status, "confirmed");
      assert.ok(actual.evidence.some((item: any) => resolveJsonPath(docs.find(doc => doc.document_id === edge.source_document_id), item.source.path) === item.source.raw_value));
      assert.ok(actual.evidence.some((item: any) => resolveJsonPath(docs.find(doc => doc.document_id === edge.target_document_id), item.target.path) === item.target.raw_value));
    }
    assert.deepEqual([...auditedPairs].sort(), routingPairs.map(pair => pair.pair_id).sort(), "every routed-negative pair must receive original-fact verification");
    assert.ok(calls <= 28);
    t.diagnostic(JSON.stringify({ kind: "synthetic_scripted_mock_not_model_quality", routing_recall: routingRecall, post_verification_recall: recall, precision, f1, direction_and_rows_exact: true, evidence_diagnostics: result.invalidRelationshipDiagnostics.length, routing_false_negatives_recovered: goldEdges.length, calls, extraction_reserved_calls: 12, total_q1_calls: calls + 12, total_references: result.analysisCoverage?.total_references, processed_references: result.analysisCoverage?.processed_references, duration_ms: result.durationMs }));
  } finally { globalThis.fetch = originalFetch; }
});

test("an oversized negative audit stays unprocessed in the routing checkpoint", async () => {
  const oversized = structuredClone(docs);
  const context = oversized[0].fields.context_note;
  const raw = "Длинный исходный текст со значимыми условиями в удалённых частях. ".repeat(850);
  context.value = raw; context.source_value = raw; context.provenance.source_text = raw;
  const originalFetch = globalThis.fetch; let calls = 0, saved: any;
  globalThis.fetch = async (_input, init) => {
    calls++;
    const user = JSON.parse(String(init?.body)).messages[1].content, request = JSON.parse(user.slice(user.indexOf("{")));
    if (request.stage === "discover") return response({ fragments: request.fragments.map((fragment: any) => ({ fragment_id: fragment.fragment_id, summary: "All supplied source slices were read", anchors: fragment.facts.slice(0, 24).map((fact: any) => ({ reference_id: fact[0], meaning: "Original source slice" })), open_questions: [] })) });
    if (request.stage === "route") return response({ decisions: request.document_pairs.map((pair: any) => ({ ...pair, state: "no_relation", reason: "Tentative negative; original audit required", reference_ids: [...new Set(request.navigation.filter((nav: any) => pair.document_ids.includes(request.fragment_manifest.find((item: any) => item.fragment_id === nav.fragment_id)?.document_id)).flatMap((nav: any) => nav.anchors.map((anchor: any) => anchor.reference_id)))], fragment_ids: request.fragment_manifest.filter((fragment: any) => pair.document_ids.includes(fragment.document_id)).map((fragment: any) => fragment.fragment_id) })) });
    throw new Error("Oversized no_relation audit must fail before a provider request");
  };
  try {
    await assert.rejects(() => analyzeDocumentSet(oversized, { apiKey: "offline-only", timeoutMs: 1000, maxCalls: 28, maxInputTokens: 16000, systemPrompt, onProgress: async state => { saved = state; } }), (error: any) => error.status === 413 && /не проверяется по оригинальным фрагментам/.test(error.message));
    assert.ok(calls > 1 && calls < 28);
    assert.ok(saved.semantic.routing.every((task: any) => task.response), "routing decisions must survive the failed audit");
    assert.equal(saved.semantic.verification, undefined, "no negative audit is marked complete when it did not fit");
    assert.equal(saved.coverage.completed_tasks, saved.semantic.discovery.filter((task: any) => task.response).length + saved.semantic.routing.length);
  } finally { globalThis.fetch = originalFetch; }
});
