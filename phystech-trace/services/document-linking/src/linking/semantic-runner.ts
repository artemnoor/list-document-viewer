import type { Extraction } from "../contracts/input";
import type { ModelRun } from "./llm-matcher";
import type { AnalysisProgressState, BoundedTaskCheckpoint, Link } from "./types";
import { buildEvidenceRegistry } from "./evidence-registry";
import { mergeTaskLinks } from "./bounded-merge";
import { DISCOVERY_PROMPT, ROUTING_PROMPT, estimateTokens, planSemanticLinking, type SemanticFragment } from "./semantic-plan";

type Hooks = {
  systemPrompt: string; maxInputTokens: number; maxCalls: number;
  progress: AnalysisProgressState;
  checkpoint: () => Promise<void>; exhausted: () => boolean;
  request: (context: string, prompt: string, maxOutput: number, label: string) => Promise<{ value: unknown; finishReason?: string }>;
  validate: (value: any, context: string, visible: Set<string>, owner: BoundedTaskCheckpoint) => Promise<ModelRun>;
  result: (phase: ModelRun["phase"]) => ModelRun;
};
type Pair = { pair_id: string; document_ids: string[] };
type Decision = Pair & { state: "candidate" | "no_relation" | "insufficient_context"; reason: string; fragment_ids: string[]; reference_ids?: string[]; row_ids?: string[]; hypotheses?: string[] };
export type SemanticProgress = { plan_hash: string; discovery: BoundedTaskCheckpoint[]; routing?: BoundedTaskCheckpoint[]; verification?: BoundedTaskCheckpoint[]; decisions?: Decision[]; verification_inputs?: any[] };
const taskState = (id: string, keys: string[]): BoundedTaskCheckpoint => ({ task_id: id, fragment_keys: keys, attempts: 0, failures: [] });
const fail = (message: string, status = 502) => Object.assign(new Error(message), { status, retryable: false });

export async function runSemanticAnalysis(documents: Extraction[], hooks: Hooks): Promise<ModelRun> {
  // Reserve room for the JSON request envelope and provider schema included by the shared Q1 ledger.
  const limit = Math.min(15400, hooks.maxInputTokens);
  const plan = planSemanticLinking(documents, { systemPrompt: hooks.systemPrompt, maxInputTokens: limit });
  const progress = hooks.progress;
  if (progress.bounded_plan_hash && !progress.semantic) throw fail("Checkpoint старого полного перебора сохранён; для новой стратегии требуется отдельный запуск.", 409);
  if (progress.semantic && progress.semantic.plan_hash !== plan.plan_hash) throw fail("Checkpoint относится к другому семантическому плану.", 409);
  const state = progress.semantic ??= { plan_hash: plan.plan_hash, discovery: plan.discovery_batches.map(batch => taskState(batch.batch_id, batch.fragment_ids)) };
  const registry = buildEvidenceRegistry(documents);
  const refs = new Map(registry.map(reference => [reference.reference_id, reference]));
  const fragmentMap = new Map(plan.fragments.map(fragment => [fragment.fragment_id, fragment]));
  const canonicalIds = new Set(plan.fragments.flatMap(fragment => fragment.reference_ids));
  const referenceFragments = new Map<string, SemanticFragment[]>();
  for (const fragment of plan.fragments) for (const id of fragment.reference_ids) referenceFragments.set(id, [...referenceFragments.get(id) ?? [], fragment]);
  const pairs: Pair[] = [];
  for (let i = 0; i < documents.length; i++) for (let j = i + 1; j < documents.length; j++) pairs.push({ pair_id: `pair:${i}:${j}`, document_ids: [documents[i].document_id, documents[j].document_id] });
  const allTasks = () => [...state.discovery, ...state.routing ?? [], ...state.verification ?? []];
  const updateCoverage = () => {
    const readKeys = new Set(state.discovery.filter(task => task.response).flatMap(task => task.fragment_keys));
    const readFragments = plan.fragments.filter(fragment => readKeys.has(fragment.fragment_id));
    const readAliases = new Set(readFragments.flatMap(fragment => fragment.alias_reference_ids));
    progress.coverage = { document_ids: [...new Set(readFragments.map(fragment => fragment.document_id))], fragment_keys: [...readKeys], reference_ids: [...new Set([...plan.metadata_reference_ids, ...readAliases])], total_tasks: allTasks().length, completed_tasks: state.discovery.filter(task => task.response).length + (state.routing ?? []).filter(task => task.response).length + (state.verification ?? []).filter(task => task.result).length };
    progress.total_fragments = plan.fragments.length;
  };
  const partial = () => { updateCoverage(); return hooks.result(progress.phase ?? "reading_documents"); };
  const requestTask = async (task: BoundedTaskCheckpoint, context: string, prompt: string, check: (value: any) => void) => {
    if (estimateTokens(prompt + context) > limit) throw fail("Семантическая задача превышает Q1-контекст; данные не обрезаны.", 413);
    if (task.response) return true;
    while (task.attempts < 3) {
      if (hooks.exhausted()) return false;
      task.attempts++; await hooks.checkpoint();
      let received: unknown;
      try {
        const response = await hooks.request(context, prompt, 4000, `semantic.${task.task_id}:attempt:${task.attempts}`);
        received = response.value;
        if (response.finishReason === "length") throw fail("Ограниченный ответ модели обрезан.");
        check(received);
        task.response = received; updateCoverage(); await hooks.checkpoint(); return true;
      } catch (error: any) {
        task.failures.push({ message: String(error.message), ...(received !== undefined ? { response: received } : {}) }); await hooks.checkpoint();
        if (error.status !== 502 || task.attempts >= 3) throw error;
      }
    }
    throw fail(`Исчерпаны попытки задачи ${task.task_id}.`);
  };
  progress.phase = "reading_documents"; updateCoverage(); await hooks.checkpoint();
  const minimum = state.discovery.filter(task => !task.response).length + (state.routing ? state.routing.filter(task => !task.response).length : pairs.length ? 1 : 0);
  if (progress.calls + minimum > hooks.maxCalls) throw fail(`Недостаточный бюджет семантического чтения: минимум ${minimum} новых вызовов; осталось ${hooks.maxCalls - progress.calls}.`, 413);
  for (let index = 0; index < plan.discovery_batches.length; index++) {
    const batch = plan.discovery_batches[index], saved = state.discovery[index];
    const okay = await requestTask(saved, batch.context, DISCOVERY_PROMPT, value => {
      if (!Array.isArray(value?.fragments) || value.fragments.length !== batch.fragment_ids.length) throw fail("Потерян результат исходного фрагмента.");
      const returned = new Set<string>();
      for (const fragment of value.fragments) {
        const source = fragmentMap.get(fragment?.fragment_id);
        if (!source || !batch.fragment_ids.includes(fragment.fragment_id) || returned.has(fragment.fragment_id) || typeof fragment.summary !== "string" || !fragment.summary.trim() || fragment.summary.length > 600 || !Array.isArray(fragment.anchors) || fragment.anchors.length > 6 || !Array.isArray(fragment.open_questions) || fragment.open_questions.length > 4) throw fail("Некорректная семантическая навигация исходного фрагмента.");
        for (const anchor of fragment.anchors) if (!source.reference_ids.includes(anchor?.reference_id) || typeof anchor.meaning !== "string" || anchor.meaning.length > 100) throw fail("Навигация ссылается на несуществующий исходный факт.");
        if (fragment.open_questions.some((question: unknown) => typeof question !== "string" || question.length > 120)) throw fail("Слишком большой вопрос навигации.");
        returned.add(fragment.fragment_id);
      }
    });
    if (!okay) return partial();
  }
  const navigation = state.discovery.flatMap(task => task.response.fragments);
  const routeContext = (items: Pair[]) => JSON.stringify({ stage: "route", document_pairs: items, fragment_manifest: plan.fragments.map(fragment => ({ fragment_id: fragment.fragment_id, document_id: fragment.document_id, rows: fragment.rows })), navigation: navigation.filter(fragment => items.some(pair => pair.document_ids.includes(fragmentMap.get(fragment.fragment_id)!.document_id))) });
  if (!state.routing) {
    const groups: Pair[][] = []; let current: Pair[] = [];
    for (const pair of pairs) {
      if (current.length && estimateTokens(ROUTING_PROMPT + routeContext([...current, pair])) > limit) { groups.push(current); current = []; }
      current.push(pair);
      if (estimateTokens(ROUTING_PROMPT + routeContext(current)) > limit) throw fail("Навигация пары превышает Q1; данные не обработаны.", 413);
    }
    if (current.length) groups.push(current);
    state.routing = groups.map((items, index) => taskState(`route:${index}`, items.map(pair => pair.pair_id)));
    updateCoverage(); await hooks.checkpoint();
  }
  progress.phase = "resolving_relationships";
  for (const saved of state.routing) {
    const taskPairs = pairs.filter(pair => saved.fragment_keys.includes(pair.pair_id));
    const okay = await requestTask(saved, routeContext(taskPairs), ROUTING_PROMPT, value => {
      if (!Array.isArray(value?.decisions) || value.decisions.length !== taskPairs.length) throw fail("Не все пары документов получили решение о кандидатах.");
      const seen = new Set<string>();
      for (const decision of value.decisions) {
        const pair = taskPairs.find(item => item.pair_id === decision?.pair_id);
        if (!pair || seen.has(pair.pair_id) || !Array.isArray(decision.document_ids) || JSON.stringify([...decision.document_ids].sort()) !== JSON.stringify([...pair.document_ids].sort()) || !["candidate", "no_relation", "insufficient_context"].includes(decision.state) || typeof decision.reason !== "string" || !decision.reason.trim() || !Array.isArray(decision.fragment_ids)) throw fail("Некорректное либо пропущенное решение о паре документов.");
        if (decision.fragment_ids.some((id: string) => !fragmentMap.has(id) || !pair.document_ids.includes(fragmentMap.get(id)!.document_id))) throw fail("Кандидат ссылается на чужой или несуществующий фрагмент.");
        if (decision.reference_ids !== undefined) {
          if (!Array.isArray(decision.reference_ids) || decision.reference_ids.some((id: string) => !canonicalIds.has(id) || !pair.document_ids.includes(refs.get(id)!.document_id))) throw fail("Кандидат ссылается на несуществующее evidence.");
          if (decision.state === "candidate" && pair.document_ids.some(id => !decision.reference_ids.some((referenceId: string) => refs.get(referenceId)!.document_id === id))) throw fail("Кандидату не хватает исходного факта с одной из сторон связи.");
        }
        if (decision.row_ids !== undefined && (!Array.isArray(decision.row_ids) || decision.row_ids.some((rowId: string) => !plan.source_coverage.row_ids.includes(`${pair.document_ids.find(id => registry.some(ref => ref.document_id === id && ref.row_id === rowId)) ?? ""}:${rowId}`)))) throw fail("Кандидат ссылается на несуществующую строку.");
        seen.add(pair.pair_id);
      }
    });
    if (!okay) return partial();
  }
  state.decisions ??= state.routing.flatMap(task => task.response.decisions);
  const proof = (id: string) => { const ref = refs.get(id)!; return { reference_id: id, document_id: ref.document_id, path: ref.json_path, raw_value: ref.raw_value, ...(ref.row_id ? { row_id: ref.row_id } : {}), source_text: ref.provenance?.source_text ?? null, source_available: ref.provenance?.source_available ?? false }; };
  const verifyPrompt = `${hooks.systemPrompt}\nVerify these semantic candidates from their ORIGINAL references. Earlier navigation is not proof. Read actual meaning, ambiguity, repeated amounts, multiple agreements and every supplied row. All reference_id resolve to original exact values and provenance; only listed IDs may be cited. Do not invent paths or coordinates. Return the usual links/unlinked_document_ids/context_requests/analysis_summary JSON plus pair_decisions:[{pair_id,state:"no_relation"|"insufficient_evidence"|"supported",reason}]. An empty link list does not mean no relation; explicitly distinguish inadequate proof. Additional original fragments may be requested by document_id and chunk_index from the manifest.`;
  const verificationContext = (items: any[]) => JSON.stringify({ stage: "verify", source_manifest: plan.fragments.map(fragment => ({ document_id: fragment.document_id, chunk_index: fragment.chunk_index })), candidates: items });
  if (!state.verification) {
    const jobs: any[] = [];
    for (const decision of state.decisions.filter(item => item.state !== "no_relation")) {
      const selected = new Set<string>(decision.reference_ids ?? []);
      if (!selected.size) for (const id of decision.fragment_ids.length ? decision.fragment_ids : plan.fragments.filter(fragment => decision.document_ids.includes(fragment.document_id)).map(fragment => fragment.fragment_id)) for (const ref of fragmentMap.get(id)!.reference_ids) selected.add(ref);
      const rowKeys = new Set([...selected].flatMap(id => { const ref = refs.get(id)!; return ref.row_id ? [`${ref.document_id}:${ref.row_id}`] : []; }));
      for (const row of decision.row_ids ?? []) for (const doc of decision.document_ids) rowKeys.add(`${doc}:${row}`);
      // Expand actual selected rows structurally, not by coincident amounts/numbers.
      for (const id of canonicalIds) { const ref = refs.get(id)!; if (ref.row_id && rowKeys.has(`${ref.document_id}:${ref.row_id}`)) selected.add(id); }
      const candidate = { pair_id: decision.pair_id, document_ids: decision.document_ids, reason: decision.reason, hypotheses: decision.hypotheses ?? [], original_references: [...selected].map(proof) };
      if (estimateTokens(verifyPrompt + verificationContext([candidate])) > limit) throw fail(`Точный контекст кандидата ${decision.pair_id} не помещается в Q1; требуется более точная навигация, источники не обрезаны.`, 413);
      jobs.push(candidate);
    }
    const inputs: any[][] = []; let current: any[] = [];
    for (const candidate of jobs) {
      if (current.length && estimateTokens(verifyPrompt + verificationContext([...current, candidate])) > limit) { inputs.push(current); current = []; }
      current.push(candidate);
    }
    if (current.length) inputs.push(current);
    state.verification_inputs = inputs;
    state.verification = inputs.map((items, index) => taskState(`verify:${index}`, items.map(item => item.pair_id)));
    updateCoverage(); await hooks.checkpoint();
  }
  for (let index = 0; index < state.verification.length; index++) {
    const saved = state.verification[index];
    if (saved.result) continue;
    const candidates = state.verification_inputs![index];
    let context = verificationContext(candidates);
    const okay = await requestTask(saved, context, verifyPrompt, value => {
      if (!Array.isArray(value?.links) || !Array.isArray(value?.unlinked_document_ids) || !Array.isArray(value?.context_requests)) throw fail("Невалидный контракт подробной проверки кандидатов.");
    });
    if (!okay) return partial();
    let originalRefs = candidates.flatMap((candidate: any) => candidate.original_references);
    if (saved.response.context_requests.length) {
      if (hooks.exhausted()) return partial();
      const expanded = new Set(originalRefs.map((ref: any) => ref.reference_id));
      for (const request of saved.response.context_requests) {
        const fragment = plan.fragments.find(fragment => fragment.document_id === request.document_id && fragment.chunk_index === request.chunk_index);
        if (!fragment) throw fail("Запрошен несуществующий оригинальный фрагмент.");
        fragment.reference_ids.forEach(id => expanded.add(id));
      }
      if (expanded.size === originalRefs.length) throw fail("Модель повторно запросила только уже переданные оригиналы.");
      const expandedRefs = [...expanded].map(id => proof(String(id)));
      context = JSON.stringify({ stage: "verify", candidates, requested_original_references: expandedRefs });
      const followup = saved.followup ??= taskState(`${saved.task_id}:source`, []);
      const expandedOkay = await requestTask(followup, context, verifyPrompt, value => {
        if (!Array.isArray(value?.links) || !Array.isArray(value?.unlinked_document_ids) || !Array.isArray(value?.context_requests) || value.context_requests.length) throw fail("Дополнительная проверка оригиналов не завершена.");
      });
      if (!expandedOkay) return partial();
      originalRefs = expandedRefs;
    }
    if (saved.followup?.response) {
      const expanded = new Set(originalRefs.map((ref: any) => ref.reference_id));
      for (const request of saved.response.context_requests) plan.fragments.find(fragment => fragment.document_id === request.document_id && fragment.chunk_index === request.chunk_index)!.reference_ids.forEach(id => expanded.add(id));
      originalRefs = [...expanded].map(id => proof(String(id)));
      context = JSON.stringify({ stage: "verify", candidates, requested_original_references: originalRefs });
    }
    const validated = await hooks.validate(saved.followup?.response ?? saved.response, context, new Set(originalRefs.map((ref: any) => ref.reference_id)), saved);
    if (!validated.complete) return partial();
    saved.result = { links: validated.links, diagnostics: validated.invalidRelationshipDiagnostics, summary: validated.analysisSummary };
    updateCoverage(); await hooks.checkpoint();
  }
  const links = mergeTaskLinks(state.verification.flatMap(task => task.result!.links));
  const diagnostics = state.verification.flatMap(task => task.result!.diagnostics);
  const pairOutcomes = state.decisions.map(decision => {
    if (decision.state === "no_relation") return { ...decision, outcome: "no_link_found" };
    const task = state.verification!.find(task => task.fragment_keys.includes(decision.pair_id));
    const answer = (task?.followup?.response ?? task?.response)?.pair_decisions?.find((item: any) => item.pair_id === decision.pair_id);
    const supported = links.some(link => link.status !== "rejected" && decision.document_ids.includes(link.source_document_id) && decision.document_ids.includes(link.target_document_id));
    return { ...decision, outcome: supported ? "linked" : answer?.state === "no_relation" && !diagnostics.some(item => decision.document_ids.includes(item.source_document_id!) && decision.document_ids.includes(item.target_document_id!) && !["corrected", "withdrawn"].includes(item.resolution ?? "")) ? "no_link_found" : "insufficient_evidence" };
  });
  const unlinked = documents.filter(doc => { const outcomes = pairOutcomes.filter(pair => pair.document_ids.includes(doc.document_id)); return outcomes.length > 0 && outcomes.every(pair => pair.outcome === "no_link_found"); }).map(doc => doc.document_id);
  updateCoverage();
  const result = hooks.result("complete");
  return { ...result, complete: true, links, invalidRelationshipDiagnostics: diagnostics, unlinkedDocumentIds: unlinked,
    analysisCoverage: { documents: documents.map(doc => ({ document_id: doc.document_id, state: links.some(link => link.status !== "rejected" && [link.source_document_id, link.target_document_id].includes(doc.document_id)) ? "linked" : unlinked.includes(doc.document_id) ? "no_link_found" : "insufficient_evidence" })), total_tasks: allTasks().length, completed_tasks: allTasks().length, total_references: registry.length, processed_references: progress.coverage!.reference_ids.length, semantic: { model_read_references: plan.source_coverage.meaningful_references, metadata_references: plan.source_coverage.metadata_references, source_rows: plan.source_coverage.row_ids, pair_decisions: pairOutcomes.map(pair => ({ pair_id: pair.pair_id, document_ids: pair.document_ids, state: pair.outcome, reason: pair.reason })) } },
    analysisSummary: `Semantic staged analysis: ${plan.fragments.length} source fragments, ${pairs.length} document pairs, ${state.decisions.filter(pair => pair.state !== "no_relation").length} candidate pairs; all original business facts/rows read. Metadata audited separately. Candidate recall requires independent gold.`,
  };
}
