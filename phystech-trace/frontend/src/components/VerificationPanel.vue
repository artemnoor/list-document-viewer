<script setup lang="ts">
import type { TraceProject, StageName } from "../types";
defineProps<{ project: TraceProject; busy: boolean }>();
defineEmits<{ retry: [stage: StageName] }>();
const labels: Record<string, string> = { matched: "Совпадает", mismatch: "Расхождение", needs_review: "Требуется проверка", insufficient_data: "Недостаточно данных", manual_review: "Требуется проверка", calculated: "Рассчитано", not_applicable: "Не применимо" };
function value(item: any) {
  const v = item?.normalized_value ?? item?.source_value;
  if (v == null) return "—";
  if (typeof v === "object" && v.amount != null) return String(v.amount);
  if (typeof v === "object" && v.start && v.end) return `${v.start} — ${v.end}`;
  return typeof v === "object" ? JSON.stringify(v) : String(v);
}
</script>
<template>
  <section class="result-sheet verification-panel">
    <div class="section-heading"><div><span class="eyebrow">RECONCILIATION → VERIFICATION</span><h2>Сверка показателей</h2><p>Ожидаемое значение рассчитывается по источникам и независимо проверяется.</p></div>
      <button class="button button-outline" :disabled="busy || !project.linking_result" @click="$emit('retry', 'reconciliation')">Пересчитать и проверить</button>
    </div>
    <div v-if="project.verification_result" class="extraction-summary"><b>{{ labels[project.verification_result.overall_status] || project.verification_result.overall_status }}</b><span>Проверено: {{ project.verification_result.completeness.verified_indicators }} / {{ project.verification_result.completeness.total_indicators }}</span><span>Доказанных расхождений: {{ project.verification_result.conclusion.mismatch_count }}</span></div>
    <p v-else class="muted">{{ project.stages.verification?.error?.message || project.stages.reconciliation?.error?.message || 'Сверка появится после обработки комплекта.' }}</p>
    <div v-if="project.verification_result" class="extraction-table-wrap"><table class="data-table"><thead><tr><th>Показатель</th><th>В КФЗ</th><th>Ожидается</th><th>Разница</th><th>Заключение</th></tr></thead><tbody><tr v-for="item in project.verification_result.indicators" :key="item.target_id"><td>{{ item.label || item.semantic_key || item.target_id }}</td><td>{{ value(item.actual) }} {{ item.actual?.currency || '' }}</td><td>{{ value(item.expected) }} {{ item.expected?.currency || '' }}</td><td>{{ item.difference?.absolute ?? '—' }}</td><td><b>{{ labels[item.status] || item.status }}</b><p>{{ item.uncertainty?.status_reason }}</p><details><summary>Доказательства и причины</summary><p v-for="reason in item.uncertainty?.reasons || []" :key="reason">{{ reason }}</p><pre>{{ JSON.stringify({ diagnostics: item.diagnostics, trust: item.trust, evidence: item.evidence }, null, 2) }}</pre></details></td></tr></tbody></table></div>
    <div class="link-actions"><a v-if="project.reconciliation_result" :href="`/api/projects/${project.id}/reconciliation`" target="_blank">Расчёт и исходные доказательства ↗</a><a v-if="project.verification_result" :href="`/api/projects/${project.id}/verification`" target="_blank">Полный результат проверки ↗</a><button v-if="project.reconciliation_result && project.stages.verification?.status === 'failed'" class="button button-outline" :disabled="busy" @click="$emit('retry','verification')">Повторить проверку</button></div>
    <details v-if="project.reconciliation_result"><summary>Планы расчёта и исключённые источники</summary><pre>{{ JSON.stringify(project.reconciliation_result, null, 2) }}</pre></details>
  </section>
</template>
<style scoped>
.verification-panel { min-width: 0; } pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 420px; overflow: auto; font-size: 11px; } details { margin-top: 12px; } summary { cursor: pointer; } .link-actions { flex-wrap: wrap; gap: 16px; } .data-table td { vertical-align: top; } .data-table td p { max-width: 440px; white-space: normal; }
</style>
