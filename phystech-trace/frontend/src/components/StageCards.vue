<script setup lang="ts">
import type { StageName, StageState } from "../types";

defineProps<{ stages: Record<StageName, StageState>; onRetry: (stage: StageName) => void }>();
const stageInfo: { id: StageName; title: string; hint: string; icon: string }[] = [
  { id: "parser", title: "Parser", hint: "Распознавание и структура", icon: "01" },
  { id: "extraction", title: "Extraction", hint: "Реквизиты и строки", icon: "02" },
  { id: "linking", title: "Linking", hint: "Связи и evidence", icon: "03" },
];
const labels: Record<string, string> = { pending: "Ожидает", queued: "В очереди", running: "В работе", completed: "Готово", failed: "Ошибка", blocked: "Заблокировано", skipped: "Пропущено" };
</script>

<template>
  <div class="stage-grid" aria-label="Этапы обработки">
    <article v-for="(item, index) in stageInfo" :key="item.id" class="stage-card" :class="`stage-${stages[item.id]?.status || 'pending'}`">
      <div class="stage-top"><span class="stage-index">{{ item.icon }}</span><span class="stage-status"><i></i>{{ labels[stages[item.id]?.status] || stages[item.id]?.status }}</span></div>
      <div class="stage-title-row"><h3>{{ item.title }}</h3><span v-if="index < stageInfo.length - 1" class="stage-connector">→</span></div>
      <p>{{ item.hint }}</p>
      <div v-if="stages[item.id]?.status === 'running'" class="stage-progress"><span :style="{ width: `${stages[item.id]?.total ? Math.max(8, (stages[item.id]?.completed / stages[item.id]?.total) * 100) : 8}%` }"></span></div>
      <div v-if="stages[item.id]?.total" class="stage-count">{{ stages[item.id]?.completed }} / {{ stages[item.id]?.total }} документов</div>
      <div v-if="stages[item.id]?.error?.message" class="stage-error">{{ stages[item.id]?.error?.message }}</div>
      <div v-if="stages[item.id]?.warning" class="stage-warning">{{ stages[item.id]?.warning }}</div>
      <button v-if="['failed','blocked'].includes(stages[item.id]?.status)" class="text-button stage-retry" @click="onRetry(item.id)">Повторить этап <span>↻</span></button>
    </article>
  </div>
</template>
