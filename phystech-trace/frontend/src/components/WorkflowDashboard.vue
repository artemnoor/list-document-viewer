<script setup lang="ts">
import { computed } from 'vue';
import type { TraceProject, StageName } from '../types';
import AppIcon from './AppIcon.vue';
import StageCards from './StageCards.vue';
import { money, reportRows } from '../reportView';
const props = defineProps<{ project: TraceProject; busy: boolean }>();
const emit = defineEmits<{ navigate: [tab: 'documents' | 'links' | 'verification']; process: []; retry: [stage: StageName]; settings: [] }>();
const ready = computed(() => ['kfz', 'primary'].every(role => props.project.documents.some(d => d.role === role)));
const running = computed(() => props.project.status === 'running' || Object.values(props.project.stages).some(s => ['running', 'queued'].includes(s.status)));
const failed = computed(() => (['parser', 'extraction', 'linking', 'reconciliation', 'verification'] as StageName[]).find(s => ['failed', 'blocked'].includes(props.project.stages[s]?.status)));
const consentBlocked = computed(() => props.project.stages.linking?.error?.code === 'EXTERNAL_LLM_CONSENT_REQUIRED');
const parsed = computed(() => props.project.documents.filter(d => d.has_parser_result).length);
const extracted = computed(() => props.project.documents.filter(d => d.extraction_id).length);
const liveStages = [ { id: 'parser', title: 'Распознавание документов' }, { id: 'extraction', title: 'Извлечение данных' }, { id: 'linking', title: 'Поиск связей с ИИ' }, { id: 'reconciliation', title: 'Расчёт' }, { id: 'verification', title: 'Сверка' } ] as const;
const statusText: Record<string,string> = { pending:'Ожидает', queued:'В очереди', running:'В работе', completed:'Готово', failed:'Ошибка', blocked:'Остановлено', skipped:'Пропущено' };
function friendlyError(error?: { code?:string; message?:string } | null) { return error?.code === 'EXTERNAL_LLM_CONSENT_REQUIRED' ? 'Для поиска связей нужна внешняя модель. Откройте настройки, выберите вариант данных и сохраните его, чтобы разрешить обработку через сторонний API.' : error?.message || 'Обработка остановлена. Повторите этап.'; }
const analyzed = computed(() => props.project.stages.linking?.status === 'completed');
const pending = computed(() => props.project.linking_result?.links.filter(l => l.status !== 'rejected' && l.verification_status === 'not_reviewed').length ?? 0);
const finished = computed(() => props.project.stages.verification?.status === 'completed' && !!(props.project.financial_audit || props.project.verification_result));
const reviewSummary = computed(() => {
  const rows = reportRows(props.project), total = rows.find(r => r.isTotal);
  const mismatches = rows.filter(r => r.status === 'mismatch' && !r.isTotal);
  const missing = rows.filter(r => ['insufficient_data', 'needs_review', 'manual_review'].includes(r.status));
  return { hasProblems: !!mismatches.length || total?.status === 'mismatch', text: total?.status === 'mismatch' ? `Разница в общем итоге — ${money(Math.abs(Number(total.difference)))}. Откройте отчёт, чтобы увидеть причину и документы.` : missing.length ? `Неподтверждённых показателей: ${missing.length}. Посмотрите, каких данных не хватает.` : 'Проверенные показатели совпадают с первичными документами.' };
});
const current = computed(() => !ready.value ? 0 : failed.value || !analyzed.value ? 1 : pending.value ? 2 : 3);
const nextHint = computed(() => !ready.value
  ? !props.project.documents.some(d => d.role === 'kfz') ? 'Сначала добавьте отчёт КФЗ — документ, данные которого нужно проверить.' : 'Теперь добавьте договоры, акты или счета, с которыми нужно сравнить отчёт.'
  : failed.value ? friendlyError(props.project.stages[failed.value]?.error)
  : running.value ? 'Сейчас программа читает и сравнивает документы. Ничего нажимать не нужно — ход работы обновится сам.'
  : !analyzed.value ? 'Документы на месте. Запустите проверку одной кнопкой — все этапы выполнятся автоматически.'
  : pending.value ? 'Программа предложила, какие документы относятся друг к другу. Посмотрите фрагменты и проверьте эти предложения.'
  : finished.value ? 'Можно посмотреть, какие данные совпали и где есть расхождения.' : 'Предложения проверены. Откройте результаты, чтобы увидеть состояние сверки.');
const steps = computed(() => [
  { title: 'Добавьте документы', hint: 'Нужны отчёт КФЗ и хотя бы один документ для сравнения: договор, акт, счёт или реестр.', icon: 'file', done: ready.value, action: 'Добавить документы' },
  { title: 'Запустите проверку', hint: failed.value ? friendlyError(props.project.stages[failed.value]?.error) : running.value ? 'Документы обрабатываются. Прогресс обновляется автоматически.' : 'Распознаем содержимое, извлечём данные и найдём связи между документами.', icon: 'link', done: analyzed.value, action: consentBlocked.value ? 'Открыть настройки' : failed.value ? 'Повторить этап' : 'Проверить документы' },
  { title: 'Проверьте найденные пары', hint: pending.value ? `Предложений для проверки: ${pending.value}. Посмотрите фрагменты: если документы относятся друг к другу, подтвердите пару. Если нет — отклоните.` : analyzed.value ? 'Предложений, ожидающих вашего решения, нет. Можно посмотреть результаты.' : 'Программа предложит пары документов. Вы сможете посмотреть, почему они связаны, и принять решение.', icon: 'check', done: analyzed.value && !pending.value, action: 'Проверить предложения' },
  { title: 'Посмотрите результаты', hint: finished.value ? 'Сверка готова. Посмотрите показатели, расхождения и их источники.' : 'Здесь будут совпадения, расхождения и фрагменты документов, на которых основан результат.', icon: 'result', done: finished.value, action: finished.value ? 'Открыть результаты' : 'Открыть сверку' },
]);
const completed = computed(() => steps.value.filter(s => s.done).length);
function act(index: number) {
  if (index === 0) emit('navigate', 'documents');
  else if (index === 1) { if (consentBlocked.value) emit('settings'); else if (failed.value) emit('retry', failed.value); else emit('process'); }
  else emit('navigate', index === 2 ? 'links' : 'verification');
}
</script>
<template>
  <div class="workflow-dashboard">
    <div class="dashboard-intro"><div><span class="eyebrow">ОТ ДОКУМЕНТОВ К РЕЗУЛЬТАТУ</span><h2>{{ completed === 4 ? 'Проверка завершена' : 'Проверим документы по шагам' }}</h2><p>{{ completed === 4 ? 'Все этапы пройдены. Результаты и исходные документы сохранены в проекте.' : ready ? 'Файлы загружены. Следующее действие — в подсказке ниже.' : 'Начните с загрузки файлов — дальше мы подскажем, что делать.' }}</p></div><div class="progress-circle" :style="{ '--progress': `${completed * 25}%` }"><span>{{ completed }}<small>из 4</small></span></div></div>
    <section class="next-action" aria-label="Что делать дальше"><div><b>{{ running ? 'Проверка идёт' : completed === 4 ? 'Всё готово' : 'Что делать сейчас' }}</b><p>{{ nextHint }}</p></div><button v-if="!running" class="button button-dark" :disabled="busy" @click="act(completed === 4 ? 3 : current)">{{ completed === 4 ? 'Посмотреть результаты' : steps[current].action }}<AppIcon name="arrow" /></button></section>
    <details v-if="project.documents.length" class="live-progress"><summary>Как проходит автоматическая проверка</summary><div class="live-heading"><div><h3>Ход обработки</h3><p>Распознано {{ parsed }} из {{ project.documents.length }} · извлечены данные из {{ extracted }} из {{ project.documents.length }}</p></div><button class="button button-outline" @click="emit('navigate', 'documents')">Посмотреть документы</button></div><div class="live-stage-list"><div v-for="item in liveStages" :key="item.id" class="live-stage"><div><b>{{ item.title }}</b><span>{{ statusText[project.stages[item.id]?.status] || 'Ожидает' }}<template v-if="project.stages[item.id]?.total"> · {{ project.stages[item.id].completed }} из {{ project.stages[item.id].total }}<template v-if="item.id === 'parser' || item.id === 'extraction'"> · осталось {{ Math.max(0, project.stages[item.id].total - project.stages[item.id].completed) }}</template></template></span><span v-if="project.stages[item.id]?.status === 'running' && project.stages[item.id]?.current_file" class="current-file">{{ project.stages[item.id].current_file }}</span></div><progress v-if="project.stages[item.id]?.total" :value="project.stages[item.id].completed" :max="project.stages[item.id].total" :aria-label="item.title" /></div></div><p class="ai-state"><b>ИИ: </b>{{ project.stages.linking?.status === 'completed' ? 'поиск связей завершён' : project.stages.linking?.status === 'running' ? 'идёт поиск связей внешней моделью' : project.allow_external_llm ? 'разрешён для выбранной модели' : 'внешняя модель не разрешена' }}. <button class="text-button" @click="emit('settings')">Настройки обработки</button></p></details>
    <ol class="workflow-steps"><li v-for="(step, index) in steps" :key="step.title" :class="{ 'step-current': index === current && !step.done, 'step-done': step.done }"><div class="step-icon"><AppIcon :name="step.done ? 'check' : step.icon" /></div><div class="step-copy"><small>ШАГ 0{{ index + 1 }}</small><h3>{{ step.title }}</h3><p>{{ step.hint }}</p></div><span v-if="step.done" class="step-complete"><AppIcon name="check" /> Выполнено</span><button v-else-if="index === current" class="button button-dark" :disabled="busy || (index === 1 && running)" @click="act(index)">{{ index === 1 && running ? 'Идёт обработка…' : step.action }}<AppIcon v-if="!running || index !== 1" name="arrow" /></button><span v-else class="step-wait">{{ index === 3 && running ? 'Идёт сверка' : 'Следующий шаг' }}</span></li></ol>
    <div v-if="failed && current !== 1" class="notice notice-error" role="alert"><div>{{ friendlyError(project.stages[failed]?.error) }}</div><button :disabled="busy || running" @click="consentBlocked ? emit('settings') : emit('retry', failed)">{{ consentBlocked ? 'Открыть настройки' : 'Повторить этап ↻' }}</button></div>
    <div v-if="finished" class="results-ready" :class="{ 'results-have-problems': reviewSummary.hasProblems }"><div><b>{{ reviewSummary.hasProblems ? 'В отчёте найдены расхождения' : 'Результаты сверки готовы' }}</b><p>{{ reviewSummary.text }}</p><p v-if="project.report_decision && !project.report_decision.outdated"><strong>{{ project.report_decision.status === 'accepted' ? 'Ваше решение: отчёт принят' : 'Ваше решение: отчёт отклонён' }}</strong></p></div><button class="button button-dark" @click="emit('navigate', 'verification')">Посмотреть отчёт<AppIcon name="arrow" /></button></div>
    <div class="dashboard-foot"><span>{{ project.documents.length }} документов в проекте</span><button class="text-button" @click="emit('navigate', 'documents')">Открыть документы <AppIcon name="arrow" /></button></div>
    <details class="processing-details"><summary>Технические подробности</summary><StageCards :stages="project.stages" :on-retry="(stage) => emit('retry', stage)" /></details>
  </div>
</template>
