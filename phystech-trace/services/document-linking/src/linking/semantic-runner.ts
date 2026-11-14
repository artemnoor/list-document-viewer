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

export function assertExactPairDecisions(decisions: unknown, expectedPairIds: string[]) {
  const expected = new Set(expectedPairIds);
  if (expected.size !== expectedPairIds.length) throw fail("План подробной проверки содержит повторяющийся pair_id.");
  if (!Array.isArray(decisions) || decisions.length !== expected.size) throw fail("Ответ подробной проверки не содержит ровно одно решение на каждый ожидаемый pair_id.");
  const seen = new Set<string>();
  for (const decision of decisions) {
    if (!decision || typeof decision.pair_id !== "string" || !expected.has(decision.pair_id)) throw fail("Ответ подробной проверки содержит посторонний pair_id.");
    if (seen.has(decision.pair_id)) throw fail("Ответ подробной проверки содержит повторяющийся pair_id.");
    if (!["no_relation", "insufficient_evidence", "supported"].includes(decision.state)) throw fail("Ответ подробной проверки содержит некорректное состояние pair_id.");
    seen.add(decision.pair_id);
  }
  if (seen.size !== expected.size) throw fail("Ответ подробной проверки пропустил ожидаемый pair_id.");
  return decisions as Array<{ pair_id: string; state: "no_relation" | "insufficient_evidence" | "supported"; reason?: string }>;
}

export function hasCompleteNoRelationAudit(expectedPairIds: string[], decisions: unknown) {
  try { return assertExactPairDecisions(decisions, expectedPairIds).every(decision => decision.state === "no_relation"); }
  catch { return false; }
}

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
    const requestTokens = estimateTokens(prompt + context);
    if (requestTokens > limit) throw fail(`Семантическая задача ${task.task_id} превышает Q1-контекст (${requestTokens}/${limit}); данные не обрезаны.`, 413);
    if (task.response) return true;
    if (task.attempts >= 3) {
      for (const failure of [...(task.failures ?? [])].reverse()) {
        if (failure.response === undefined) continue;
        try {
          check(failure.response);
          task.response = failure.response;
          updateCoverage(); await hooks.checkpoint();
          return true;
        } catch { /* Revalidate saved raw responses with the current strict validator. */ }
      }
    }
    let correction = task.failures?.at(-1)?.message ?? "";
    while (task.attempts < 3) {
      if (hooks.exhausted()) return false;
      const requestContext = correction ? `${context}\n\nValidation correction: the previous response failed local structural/provenance validation (${correction}). Return a complete corrected response for this exact task. Keep every required source item; use only IDs present in the supplied context. Do not add explanations outside JSON.` : context;
      if (estimateTokens(prompt + requestContext) > limit) throw fail("Семантическая задача с коррекцией превышает Q1-контекст; исходные данные не обрезаны.", 413);
      task.attempts++; await hooks.checkpoint();
      let received: unknown;
      try {
        const response = await hooks.request(requestContext, prompt, 4000, `semantic.${task.task_id}:attempt:${task.attempts}`);
        received = response.value;
        if (response.finishReason === "length") throw fail("Ограниченный ответ модели обрезан.");
        check(received);
        task.response = received; updateCoverage(); await hooks.checkpoint(); return true;
      } catch (error: any) {
        task.failures.push({ message: String(error.message), ...(received !== undefined ? { response: received } : {}) }); await hooks.checkpoint();
        if (error.status !== 502 || task.attempts >= 3) throw error;
        // Only trusted validator messages are included; model output is never reflected into a retry prompt.
        correction = String(error.message).slice(0, 240);
      }
    }
    throw fail(`Исчерпаны попытки задачи ${task.task_id}.`);
  };
  const validateFragment = (fragment: any, expectedId: string, allowedIds: Set<string>) => {
    const source = fragmentMap.get(fragment?.fragment_id);
    if (!source || fragment.fragment_id !== expectedId || !allowedIds.has(fragment.fragment_id) || typeof fragment.summary !== "string" || !fragment.summary.trim() || fragment.summary.length > 800 || !Array.isArray(fragment.anchors) || fragment.anchors.length > 24 || !Array.isArray(fragment.open_questions) || fragment.open_questions.length > 6) throw fail("Некорректная семантическая навигация исходного фрагмента.");
    for (const anchor of fragment.anchors) if (!source.reference_ids.includes(anchor?.reference_id) || typeof anchor.meaning !== "string" || anchor.meaning.length > 160) throw fail("Навигация ссылается на несуществующий исходный факт.");
    if (fragment.open_questions.some((question: unknown) => typeof question !== "string" || question.length > 160)) throw fail("Слишком большой вопрос навигации.");
  };
  const recoverMissingFragments = async (batch: typeof plan.discovery_batches[number], task: BoundedTaskCheckpoint) => {
    const recovered = new Map<string, any>();
    for (const failure of task.failures ?? []) {
      const fragments = (failure.response as any)?.fragments;
      if (!Array.isArray(fragments)) continue;
      for (const fragment of fragments) {
        try { validateFragment(fragment, fragment?.fragment_id, new Set(batch.fragment_ids)); recovered.set(fragment.fragment_id, fragment); }
        catch { /* Partial model output is retained only when it passes the same provenance checks. */ }
      }
    }
    for (const fragmentId of batch.fragment_ids) {
      if (recovered.has(fragmentId)) continue;
      if (hooks.exhausted()) return false;
      const source = fragmentMap.get(fragmentId)!;
      if (estimateTokens(DISCOVERY_PROMPT + source.context) > limit) throw fail("Исходный фрагмент превышает Q1-контекст; данные не обрезаны.", 413);
      const response = await hooks.request(source.context, DISCOVERY_PROMPT, 4000, `semantic.${task.task_id}:recover:${fragmentId}`);
      if (response.finishReason === "length" || !Array.isArray((response.value as any)?.fragments) || (response.value as any).fragments.length !== 1) throw fail("Повторное чтение отдельного исходного фрагмента вернуло неполный ответ.");
      const fragment = (response.value as any).fragments[0];
      validateFragment(fragment, fragmentId, new Set([fragmentId]));
      recovered.set(fragmentId, fragment);
      await hooks.checkpoint();
    }
    task.response = { fragments: batch.fragment_ids.map(id => recovered.get(id)) };
    updateCoverage(); await hooks.checkpoint();
    return true;
  };
  progress.phase = "reading_documents"; updateCoverage(); await hooks.checkpoint();
  const minimum = state.discovery.filter(task => !task.response).length + (state.routing ? state.routing.filter(task => !task.response).length : pairs.length ? 1 : 0);
  if (progress.calls + minimum > hooks.maxCalls) throw fail(`Недостаточный бюджет семантического чтения: минимум ${minimum} новых вызовов; осталось ${hooks.maxCalls - progress.calls}.`, 413);
  for (let index = 0; index < plan.discovery_batches.length; index++) {
    const batch = plan.discovery_batches[index], saved = state.discovery[index];
    let okay: boolean;
    try { okay = await requestTask(saved, batch.context, DISCOVERY_PROMPT, value => {
      if (!Array.isArray(value?.fragments) || value.fragments.length !== batch.fragment_ids.length) throw fail("Потерян результат исходного фрагмента.");
      const returned = new Set<string>();
      for (const fragment of value.fragments) {
        if (returned.has(fragment?.fragment_id)) throw fail("Некорректная семантическая навигация исходного фрагмента.");
        validateFragment(fragment, fragment?.fragment_id, new Set(batch.fragment_ids));
        returned.add(fragment.fragment_id);
      }
    }); } catch (error: any) {
      const exhaustedAfterIncompleteBatch = saved.attempts >= 3 && saved.failures?.some(failure => failure.message === "Потерян результат исходного фрагмента.");
      if (error.message !== "Потерян результат исходного фрагмента." && !exhaustedAfterIncompleteBatch) throw error;
      okay = await recoverMissingFragments(batch, saved);
      if (!okay) return partial();
    }
    if (!okay) return partial();
  }
  const navigation = state.discovery.flatMap(task => task.response.fragments);
  const routeContext = (items: Pair[]) => JSON.stringify({ stage: "route", document_pairs: items, fragment_manifest: plan.fragments.map(fragment => ({ fragment_id: fragment.fragment_id, document_id: fragment.document_id, rows: fragment.rows })), navigation: navigation.filter(fragment => items.some(pair => pair.document_ids.includes(fragmentMap.get(fragment.fragment_id)!.document_id))) });
  if (!state.routing) {
    const groups: Pair[][] = []; let current: Pair[] = [];
    for (const pair of pairs) {
      if (current.length && (current.length >= 12 || estimateTokens(ROUTING_PROMPT + routeContext([...current, pair])) > limit)) { groups.push(current); current = []; }
      current.push(pair);
      if (estimateTokens(ROUTING_PROMPT + routeContext(current)) > limit) throw fail("Навигация пары превышает Q1; данные не обработаны.", 413);
    }
    if (current.length) groups.push(current);
    state.routing = groups.map((items, index) => taskState(`route:${index}`, items.map(pair => pair.pair_id)));
    updateCoverage(); await hooks.checkpoint();
  } else if (state.routing.some(task => {
    const taskPairs = pairs.filter(pair => task.fragment_keys.includes(pair.pair_id));
    return taskPairs.length > 12 || estimateTokens(ROUTING_PROMPT + routeContext(taskPairs)) > limit;
  })) {
    // Migrate older input-token-only route batches: they could require the model to emit
    // over a hundred decisions in one 4k-token response. Keep any complete saved decisions,
    // preserve failed responses for audit, and resume with bounded output batches.
    const prior = state.routing;
    const savedDecisions = new Map(prior.flatMap(task => task.response?.decisions ?? []).map((decision: Decision) => [decision.pair_id, decision]));
    const failures = prior.flatMap(task => task.failures ?? []);
    const groups: Pair[][] = []; let current: Pair[] = [];
    for (const pair of pairs) {
      if (current.length && (current.length >= 12 || estimateTokens(ROUTING_PROMPT + routeContext([...current, pair])) > limit)) { groups.push(current); current = []; }
      current.push(pair);
      if (estimateTokens(ROUTING_PROMPT + routeContext(current)) > limit) throw fail("Навигация пары превышает Q1; данные не обработаны.", 413);
    }
    if (current.length) groups.push(current);
    state.routing = groups.map((items, index) => {
      const task = taskState(`route:${index}`, items.map(pair => pair.pair_id));
      const decisions = items.map(pair => savedDecisions.get(pair.pair_id));
      if (decisions.every(Boolean)) task.response = { decisions };
      if (index === 0) task.failures = failures;
      return task;
    });
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
          const invalidReferences = !Array.isArray(decision.reference_ids) || decision.reference_ids.some((id: string) => !canonicalIds.has(id) || !pair.document_ids.includes(refs.get(id)!.document_id));
          if (invalidReferences) {
            if (decision.state === "candidate") {
              const citedFragments = decision.fragment_ids.map((id: string) => fragmentMap.get(id)!).filter((fragment: SemanticFragment) => pair.document_ids.includes(fragment.document_id));
              const originalReferences = [...new Set<string>(citedFragments.flatMap((fragment: SemanticFragment) => navigation.find(item => item.fragment_id === fragment.fragment_id)?.anchors.filter((anchor: any) => fragment.reference_ids.includes(anchor.reference_id)).slice(0, 1).map((anchor: any) => anchor.reference_id) ?? []))];
              const coversBothDocuments = pair.document_ids.every(documentId => originalReferences.some(id => refs.get(id)?.document_id === documentId));
              if (coversBothDocuments) {
                decision.reference_ids = originalReferences;
                decision.reason += " Routing reference IDs were invalid; exact source references from the cited original fragments are sent for independent verification.";
              } else {
                decision.state = "insufficient_context";
                delete decision.reference_ids;
                decision.reason += " Invalid reference IDs prevented candidate verification.";
              }
            } else {
              // Invalid citations can never support a negative claim.
              decision.state = "insufficient_context";
              delete decision.reference_ids;
              decision.reason += " Invalid reference IDs prevent a reliable relationship decision.";
            }
          }
          if (decision.reference_ids !== undefined && decision.reference_ids.some((id: string) => !canonicalIds.has(id) || !pair.document_ids.includes(refs.get(id)!.document_id))) throw fail("Кандидат ссылается на несуществующее evidence.");
          if (["candidate", "no_relation"].includes(decision.state) && pair.document_ids.some(id => !decision.reference_ids.some((referenceId: string) => refs.get(referenceId)!.document_id === id))) throw fail("Решению о паре не хватает исходного факта с одной из сторон; отсутствие связи нельзя вывести из сводки.");
          if (decision.state === "no_relation") {
            const pairFragments = plan.fragments.filter(fragment => pair.document_ids.includes(fragment.document_id));
            if (pairFragments.some(fragment => !decision.fragment_ids.includes(fragment.fragment_id) || !decision.reference_ids.some((id: string) => fragment.reference_ids.includes(id)))) throw fail("Предварительный no_relation не покрывает исходными anchor все фрагменты обоих документов; отсутствие связи нельзя объявить по краткой сводке.");
          }
        } else if (["candidate", "no_relation"].includes(decision.state)) {
          if (decision.state === "candidate") {
            const citedFragments = decision.fragment_ids.map((id: string) => fragmentMap.get(id)!).filter((fragment: SemanticFragment) => pair.document_ids.includes(fragment.document_id));
            const originalReferences = [...new Set<string>(citedFragments.flatMap((fragment: SemanticFragment) => navigation.find(item => item.fragment_id === fragment.fragment_id)?.anchors.filter((anchor: any) => fragment.reference_ids.includes(anchor.reference_id)).slice(0, 1).map((anchor: any) => anchor.reference_id) ?? []))];
            if (pair.document_ids.every(documentId => originalReferences.some(id => refs.get(id)?.document_id === documentId))) {
              decision.reference_ids = originalReferences;
              decision.reason += " Routing omitted reference IDs; exact source references from the cited original fragments are sent for independent verification.";
            } else {
              decision.state = "insufficient_context";
              decision.reason += " Missing reference IDs prevented candidate verification.";
            }
          } else {
            // A negative without valid citations is never promoted to a no-link finding.
            decision.state = "insufficient_context";
            decision.reason += " Missing reference IDs prevent a reliable relationship decision.";
          }
        }
        if (decision.row_ids !== undefined && (!Array.isArray(decision.row_ids) || decision.row_ids.some((rowId: string) => !plan.source_coverage.row_ids.includes(`${pair.document_ids.find(id => registry.some(ref => ref.document_id === id && ref.row_id === rowId)) ?? ""}:${rowId}`)))) throw fail("Кандидат ссылается на несуществующую строку.");
        seen.add(pair.pair_id);
      }
    });
    if (!okay) return partial();
  }
  state.decisions ??= state.routing.flatMap(task => task.response.decisions);
  // Narrow citations recovered from invalid routing IDs to the model's already-validated
  // navigation anchors. The source facts remain exact; this keeps verification bounded.
  for (const decision of state.decisions) {
    if (decision.state !== "candidate" || !/Routing (?:reference IDs were invalid|omitted reference IDs)/.test(decision.reason)) continue;
    const fragments = decision.fragment_ids.map(id => fragmentMap.get(id)).filter((fragment): fragment is SemanticFragment => fragment !== undefined && decision.document_ids.includes(fragment.document_id));
    const references = [...new Set<string>(fragments.flatMap(fragment => navigation.find(item => item.fragment_id === fragment.fragment_id)?.anchors.filter((anchor: any) => fragment.reference_ids.includes(anchor.reference_id)).slice(0, 1).map((anchor: any) => anchor.reference_id) ?? []))];
    if (decision.document_ids.every(documentId => references.some(id => refs.get(id)?.document_id === documentId))) decision.reference_ids = references;
  }
  const proof = (id: string) => {
    const ref = refs.get(id)!, sourceText = ref.provenance?.source_text;
    return { reference_id: id, document_id: ref.document_id, path: ref.json_path, raw_value: ref.raw_value, ...(ref.row_id ? { row_id: ref.row_id } : {}), ...(typeof sourceText === "string" && sourceText.length <= 500 ? { source_text: sourceText } : {}), source_available: ref.provenance?.source_available ?? false, ...(typeof sourceText === "string" && sourceText.length > 500 ? { source_text_deferred: true, source_text_length: sourceText.length } : {}) };
  };
  const requestedSourceReferences = (request: any, fragment: SemanticFragment) => {
    const paths = Array.isArray(request.paths) ? request.paths.filter((path: unknown): path is string => typeof path === "string") : [];
    const namedIds = [...new Set<string>((String(request.reason ?? "").match(/\br[a-z0-9]+\b/gi) ?? []).filter(id => {
      const reference = refs.get(id);
      if (!reference || reference.document_id !== request.document_id) return false;
      return !paths.length || paths.some((requestedPath: string) => reference.json_path === requestedPath || reference.json_path.startsWith(`${requestedPath}.`) || reference.json_path.startsWith(`${requestedPath}[`));
    }))];
    if (namedIds.length) return namedIds;
    const pathMatches = paths.length ? fragment.reference_ids.filter(id => {
      const path = refs.get(id)?.json_path;
      return path && paths.some((requestedPath: string) => path === requestedPath || path.startsWith(`${requestedPath}.`) || path.startsWith(`${requestedPath}[`));
    }) : [];
    if (pathMatches.length) return pathMatches.slice(0, 16);
    const identifying = /(date|period|organization|entity|company|contract|customer|supplier|employer|employee|party|name|number|inn|tax|address|payroll|statement|период|дата|организац|компани|договор|заказчик|поставщик|работодатель|сотрудник|наименован|номер|инн|ведомость)/i;
    const relevant = fragment.reference_ids.filter(id => identifying.test(refs.get(id)?.json_path ?? "")).slice(0, 16);
    return relevant.length ? relevant : fragment.reference_ids.slice(0, 16);
  };
  if (state.verification && state.verification_inputs) {
    let migrated = false;
    state.verification_inputs.forEach((items, index) => {
      if (state.verification![index]?.result) return;
      for (const item of items) {
        const decision = state.decisions!.find(candidate => candidate.pair_id === (item.document_pair_id ?? item.pair_id));
        if (!decision || decision.state !== "candidate" || !/Routing (?:reference IDs were invalid|omitted reference IDs)/.test(decision.reason)) continue;
        const fragments = decision.fragment_ids.map(id => fragmentMap.get(id)).filter((fragment): fragment is SemanticFragment => fragment !== undefined && decision.document_ids.includes(fragment.document_id));
        const references = [...new Set<string>(fragments.flatMap(fragment => navigation.find(nav => nav.fragment_id === fragment.fragment_id)?.anchors.filter((anchor: any) => fragment.reference_ids.includes(anchor.reference_id)).slice(0, 1).map((anchor: any) => anchor.reference_id) ?? []))];
        if (!decision.document_ids.every(documentId => references.some(id => refs.get(id)?.document_id === documentId))) continue;
        item.reference_ids = references;
        item.original_references = references.map(proof);
        migrated = true;
      }
    });
    if (migrated) await hooks.checkpoint();
  }
  const verifyPrompt = `${hooks.systemPrompt}\nVerify semantic candidates from their ORIGINAL references. Earlier navigation is not proof. A routing no_relation is a hypothesis, never a final result: independently search the supplied original facts for contrary support and return links if found. If supplied facts are insufficient, say insufficient_evidence; reaffirm no_relation only after checking the supplied originals. Read actual meaning, ambiguity, repeated amounts, multiple agreements and every supplied row. All reference_id resolve to original exact values and provenance; only listed IDs may be cited. Do not invent paths or coordinates. Return the usual links/unlinked_document_ids/context_requests/analysis_summary JSON plus pair_decisions:[{pair_id,state:"no_relation"|"insufficient_evidence"|"supported",reason}]. An empty link list does not mean no relation; explicitly distinguish inadequate proof. Additional original fragments may be requested by document_id and chunk_index from the manifest.`;
  const verificationContext = (items: any[]) => JSON.stringify({ stage: "verify", source_manifest: plan.fragments.map(fragment => ({ document_id: fragment.document_id, chunk_index: fragment.chunk_index })), candidates: items.map(item => item.original_facts ? ({ pair_id: item.pair_id, document_pair_id: item.document_pair_id, routing_state: item.routing_state, document_ids: item.document_ids, reason: item.reason, original_facts: item.original_facts }) : item) });
  if (!state.verification) {
    const jobs: any[] = [];
    for (const decision of state.decisions.filter(item => item.state !== "insufficient_context")) {
      if (decision.state === "no_relation") {
        // A short navigation summary cannot establish absence. Recheck model-selected exact anchors
        // from every source fragment, plus every original fact in their rows. If this cannot fit Q1,
        // fail explicitly with the route checkpoint intact; never turn an unaudited negative into no_link_found.
        const sourceFragments = plan.fragments.filter(fragment => decision.document_ids.includes(fragment.document_id));
        const makeAudit = (fragments: SemanticFragment[], auditId: string) => {
          const fragmentIds = new Set(fragments.map(fragment => fragment.fragment_id));
          const referenceIds = new Set((decision.reference_ids ?? []).filter(id => referenceFragments.get(id)?.some(fragment => fragmentIds.has(fragment.fragment_id))));
          const rowKeys = new Set([...referenceIds].flatMap(id => { const ref = refs.get(id)!; return ref.row_id ? [`${ref.document_id}:${ref.row_id}`] : []; }));
          for (const id of canonicalIds) { const ref = refs.get(id)!; if (ref.row_id && rowKeys.has(`${ref.document_id}:${ref.row_id}`)) referenceIds.add(id); }
          const originalFacts = fragments.map(fragment => ({ fragment_id: fragment.fragment_id, document_id: fragment.document_id, facts: fragment.facts.filter(fact => referenceIds.has(fact[0]) || (fact[3] && rowKeys.has(`${fragment.document_id}:${fact[3]}`))) })).filter(fragment => fragment.facts.length);
          const auditedIds = new Set(originalFacts.flatMap(fragment => fragment.facts.map(fact => fact[0])));
          const finalReferenceIds = [...referenceIds].filter(id => auditedIds.has(id));
          return { pair_id: auditId, document_pair_id: decision.pair_id, routing_state: decision.state, document_ids: decision.document_ids, reason: decision.reason, original_facts: originalFacts, reference_ids: finalReferenceIds };
        };
        const audit = makeAudit(sourceFragments, decision.pair_id);
        if (estimateTokens(verifyPrompt + verificationContext([audit])) <= limit) jobs.push(audit);
        else {
          const [leftId, rightId] = decision.document_ids;
          const left = sourceFragments.filter(fragment => fragment.document_id === leftId), right = sourceFragments.filter(fragment => fragment.document_id === rightId);
          for (const leftFragment of left) for (const rightFragment of right) {
            const bounded = makeAudit([leftFragment, rightFragment], `${decision.pair_id}@${leftFragment.chunk_index}:${rightFragment.chunk_index}`);
            if (estimateTokens(verifyPrompt + verificationContext([bounded])) > limit) throw fail(`Отрицательное решение ${decision.pair_id} не проверяется по оригинальным фрагментам ${leftFragment.chunk_index}/${rightFragment.chunk_index} в Q1; связь не объявлена отсутствующей. Routing checkpoint сохранён.`, 413);
            jobs.push(bounded);
          }
        }
        continue;
      }
      const selected = new Set<string>(decision.reference_ids ?? []);
      if (!selected.size) for (const id of decision.fragment_ids.length ? decision.fragment_ids : plan.fragments.filter(fragment => decision.document_ids.includes(fragment.document_id)).map(fragment => fragment.fragment_id)) for (const ref of fragmentMap.get(id)!.reference_ids) selected.add(ref);
      const citedOnly = new Set(selected);
      const rowKeys = new Set([...selected].flatMap(id => { const ref = refs.get(id)!; return ref.row_id ? [`${ref.document_id}:${ref.row_id}`] : []; }));
      for (const row of decision.row_ids ?? []) for (const doc of decision.document_ids) rowKeys.add(`${doc}:${row}`);
      // Expand actual selected rows structurally, not by coincident amounts/numbers.
      for (const id of canonicalIds) { const ref = refs.get(id)!; if (ref.row_id && rowKeys.has(`${ref.document_id}:${ref.row_id}`)) selected.add(id); }
      const makeCandidate = () => ({ pair_id: decision.pair_id, document_pair_id: decision.pair_id, routing_state: decision.state, document_ids: decision.document_ids, reason: decision.reason, hypotheses: decision.hypotheses ?? [], original_references: [...selected].map(proof), reference_ids: [...selected] });
      let candidate = makeCandidate();
      if (estimateTokens(verifyPrompt + verificationContext([candidate])) > limit) {
        // Keep the exact references selected by routing when whole-row expansion would exceed Q1.
        selected.clear(); citedOnly.forEach(id => selected.add(id));
        candidate = makeCandidate();
      }
      if (estimateTokens(verifyPrompt + verificationContext([candidate])) > limit) throw fail(`Точный контекст кандидата ${decision.pair_id} не помещается в Q1; требуется более точная навигация, источники не обрезаны.`, 413);
      jobs.push(candidate);
    }
    const plannedAuditIds = jobs.map(item => item.pair_id);
    if (new Set(plannedAuditIds).size !== plannedAuditIds.length) throw fail("План подробной проверки содержит повторяющийся pair_id.");
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
  if (state.verification && state.verification_inputs) {
    const pinnedInputs: any[][] = [], pinnedTasks: BoundedTaskCheckpoint[] = [], pending: any[] = [];
    state.verification.forEach((task, index) => {
      if (task.result || task.response || task.followup || task.attempts > 0 || task.failures.length) {
        pinnedTasks.push(task); pinnedInputs.push(state.verification_inputs![index]);
      } else pending.push(...state.verification_inputs![index]);
    });
    if (pending.length > 1) {
      const groups: any[][] = []; let current: any[] = [];
      for (const candidate of pending) {
        if (current.length && (current.length >= 8 || estimateTokens(verifyPrompt + verificationContext([...current, candidate])) > limit)) { groups.push(current); current = []; }
        current.push(candidate);
        if (estimateTokens(verifyPrompt + verificationContext(current)) > limit) throw fail(`Точный контекст кандидата ${candidate.pair_id} не помещается в Q1 после безопасной навигации.`, 413);
      }
      if (current.length) groups.push(current);
      state.verification_inputs = [...pinnedInputs, ...groups];
      state.verification = [...pinnedTasks, ...groups.map((items, index) => taskState(`verify:compact:${index}`, items.map(item => item.pair_id)))];
      updateCoverage(); await hooks.checkpoint();
    }
  }
  for (let index = 0; index < state.verification.length; index++) {
    const saved = state.verification[index];
    if (saved.result) continue;
    const candidates = state.verification_inputs![index];
    let context = verificationContext(candidates);
    const expectedPairIds = candidates.map((candidate: any) => candidate.pair_id);
    if (new Set(expectedPairIds).size !== expectedPairIds.length) throw fail("План подробной проверки содержит повторяющийся pair_id.");
    const normalizePairStates = (value: any) => {
      if (!Array.isArray(value?.pair_decisions)) return;
      for (const decision of value.pair_decisions) if (!["no_relation", "insufficient_evidence", "supported"].includes(decision?.state)) {
        decision.state = "insufficient_evidence";
        decision.reason = `${String(decision.reason ?? "")} Unsupported pair state was held as insufficient_evidence.`;
      }
    };
    const checkPairDecisions = (value: any) => {
      if (!Array.isArray(value?.context_requests) || value.context_requests.length === 0) {
        normalizePairStates(value);
        assertExactPairDecisions(value?.pair_decisions, expectedPairIds);
      }
    };
    const okay = await requestTask(saved, context, verifyPrompt, value => {
      if (!Array.isArray(value?.links) || !Array.isArray(value?.unlinked_document_ids) || !Array.isArray(value?.context_requests)) throw fail("Невалидный контракт подробной проверки кандидатов.");
      checkPairDecisions(value);
    });
    if (!okay) return partial();
    if (saved.response.context_requests.length) {
      // An incomplete first answer is allowed to request more originals; its final follow-up
      // must still account for exactly the verification jobs in this task.
    } else assertExactPairDecisions(saved.response.pair_decisions, expectedPairIds);
    let originalRefs = candidates.flatMap((candidate: any) => candidate.original_references ?? candidate.reference_ids.map((id: string) => proof(id)));
    if (saved.response.context_requests.length) {
      if (hooks.exhausted()) return partial();
      const expanded = new Set(originalRefs.map((ref: any) => ref.reference_id));
      for (const request of saved.response.context_requests) {
        const fragment = plan.fragments.find(fragment => fragment.document_id === request.document_id && fragment.chunk_index === request.chunk_index);
        if (!fragment) throw fail("Запрошен несуществующий оригинальный фрагмент.");
        requestedSourceReferences(request, fragment).forEach(id => expanded.add(id));
      }
      if (expanded.size === originalRefs.length) {
        // The model requested only references already supplied. Keep its explicit
        // insufficient_evidence decisions and close the unfulfillable request safely.
        saved.response.context_requests = [];
        saved.response.analysis_summary = `${String(saved.response.analysis_summary ?? "")} Requested source references were already present; unresolved pairs remain insufficient_evidence.`;
        await hooks.checkpoint();
      } else {
        const expandedRefs = [...expanded].map(id => proof(String(id)));
        const followupCandidates = candidates.map((candidate: any) => ({ pair_id: candidate.pair_id, document_pair_id: candidate.document_pair_id, routing_state: candidate.routing_state, document_ids: candidate.document_ids, reason: candidate.reason, hypotheses: candidate.hypotheses, reference_ids: candidate.reference_ids }));
        context = JSON.stringify({ stage: "verify", candidates: followupCandidates, requested_original_references: expandedRefs });
        const followup = saved.followup ??= taskState(`${saved.task_id}:source`, []);
        let expandedOkay: boolean;
        try {
          expandedOkay = await requestTask(followup, context, verifyPrompt, value => {
            if (!Array.isArray(value?.links) || !Array.isArray(value?.unlinked_document_ids) || !Array.isArray(value?.context_requests) || value.context_requests.length) throw fail("Дополнительная проверка оригиналов не завершена.");
            normalizePairStates(value);
            assertExactPairDecisions(value.pair_decisions, expectedPairIds);
          });
        } catch (error) {
          const last = followup.failures?.at(-1)?.response as any;
          if (followup.attempts < 3 || !last || !Array.isArray(last.links) || last.links.length || !Array.isArray(last.context_requests) || !last.context_requests.length) throw error;
          normalizePairStates(last);
          const decisions = assertExactPairDecisions(last.pair_decisions, expectedPairIds);
          if (decisions.some(decision => decision.state !== "insufficient_evidence")) throw error;
          followup.response = { ...last, context_requests: [], analysis_summary: `${String(last.analysis_summary ?? "")} Further source requests were not resolved; pair outcomes remain insufficient_evidence.` };
          await hooks.checkpoint();
          expandedOkay = true;
        }
        if (!expandedOkay) return partial();
        assertExactPairDecisions(followup.response.pair_decisions, expectedPairIds);
        originalRefs = expandedRefs;
      }
    }
    if (saved.followup?.response) {
      const expanded = new Set(originalRefs.map((ref: any) => ref.reference_id));
      for (const request of saved.response.context_requests) {
        const fragment = plan.fragments.find(fragment => fragment.document_id === request.document_id && fragment.chunk_index === request.chunk_index)!;
        requestedSourceReferences(request, fragment).forEach(id => expanded.add(id));
      }
      originalRefs = [...expanded].map(id => proof(String(id)));
      const followupCandidates = candidates.map((candidate: any) => ({ pair_id: candidate.pair_id, document_pair_id: candidate.document_pair_id, routing_state: candidate.routing_state, document_ids: candidate.document_ids, reason: candidate.reason, hypotheses: candidate.hypotheses, reference_ids: candidate.reference_ids }));
      context = JSON.stringify({ stage: "verify", candidates: followupCandidates, requested_original_references: originalRefs });
      assertExactPairDecisions(saved.followup.response.pair_decisions, expectedPairIds);
    }
    const validated = await hooks.validate(saved.followup?.response ?? saved.response, context, new Set(originalRefs.map((ref: any) => ref.reference_id)), saved);
    if (!validated.complete) return partial();
    saved.result = { links: validated.links, diagnostics: validated.invalidRelationshipDiagnostics, summary: validated.analysisSummary };
    updateCoverage(); await hooks.checkpoint();
  }
  const links = mergeTaskLinks(state.verification.flatMap(task => task.result!.links));
  const diagnostics = state.verification.flatMap(task => task.result!.diagnostics);
  const pairOutcomes = state.decisions.map(decision => {
    if (decision.state === "insufficient_context") return { ...decision, outcome: "insufficient_evidence" };
    const audits = state.verification_inputs!.flat().filter((item: any) => (item.document_pair_id ?? item.pair_id) === decision.pair_id);
    const auditIds = audits.map((item: any) => item.pair_id);
    const auditAnswers = state.verification!.flatMap((task, index) => {
      const expected = state.verification_inputs![index].map((item: any) => item.pair_id);
      return assertExactPairDecisions((task.followup?.response ?? task.response)?.pair_decisions, expected);
    }).filter((item: any) => auditIds.includes(item.pair_id));
    const supported = links.some(link => link.status !== "rejected" && decision.document_ids.includes(link.source_document_id) && decision.document_ids.includes(link.target_document_id));
    const noRelationVerified = audits.length > 0 && new Set(auditIds).size === auditIds.length && hasCompleteNoRelationAudit(auditIds, auditAnswers);
    return { ...decision, outcome: supported ? "linked" : noRelationVerified && !diagnostics.some(item => decision.document_ids.includes(item.source_document_id!) && decision.document_ids.includes(item.target_document_id!) && !["corrected", "withdrawn"].includes(item.resolution ?? "")) ? "no_link_found" : "insufficient_evidence" };
  });
  const unlinked = documents.filter(doc => { const outcomes = pairOutcomes.filter(pair => pair.document_ids.includes(doc.document_id)); return outcomes.length > 0 && outcomes.every(pair => pair.outcome === "no_link_found"); }).map(doc => doc.document_id);
  updateCoverage();
  const result = hooks.result("complete");
  return { ...result, complete: true, links, invalidRelationshipDiagnostics: diagnostics, unlinkedDocumentIds: unlinked,
    analysisCoverage: { documents: documents.map(doc => ({ document_id: doc.document_id, state: links.some(link => link.status !== "rejected" && [link.source_document_id, link.target_document_id].includes(doc.document_id)) ? "linked" : unlinked.includes(doc.document_id) ? "no_link_found" : "insufficient_evidence" })), total_tasks: allTasks().length, completed_tasks: allTasks().length, total_references: registry.length, processed_references: progress.coverage!.reference_ids.length, semantic: { model_read_references: plan.source_coverage.meaningful_references, metadata_references: plan.source_coverage.metadata_references, source_rows: plan.source_coverage.row_ids, pair_decisions: pairOutcomes.map(pair => ({ pair_id: pair.pair_id, document_ids: pair.document_ids, state: pair.outcome, reason: pair.reason })) } },
    analysisSummary: `Semantic staged analysis: ${plan.fragments.length} source fragments, ${pairs.length} document pairs, ${state.decisions.filter(pair => pair.state !== "no_relation").length} candidate pairs; all original business facts/rows read. Metadata audited separately. Candidate recall requires independent gold.`,
  };
}
