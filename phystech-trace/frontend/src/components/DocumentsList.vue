<script setup lang="ts">
import { computed, ref } from 'vue';
import { documentStatus, documentStatusLabel, type DocumentStatus } from '../documentStatus';
import type { StageState, TraceDocument } from '../types';

const props = defineProps<{ documents: TraceDocument[]; selectedId?: string; extractionStage?: StageState }>();
const emit = defineEmits<{ open: [document: TraceDocument] }>();
const filter = ref<'all' | DocumentStatus>('all');
const filters = [
  { id: 'all', title: 'Все файлы' }, { id: 'done', title: 'Обработаны' },
  { id: 'processing', title: 'В обработке' }, { id: 'waiting', title: 'Ожидают' }, { id: 'error', title: 'С ошибками' },
] as const;
const counts = computed(() => {
  const result = { all: props.documents.length, done: 0, processing: 0, waiting: 0, error: 0 };
  for (const doc of props.documents) result[documentStatus(doc, props.extractionStage)]++;
  return result;
});
const visible = computed(() => props.documents.filter(doc => filter.value === 'all' || documentStatus(doc, props.extractionStage) === filter.value));
</script>

<template>
  <section class="documents-status-list" aria-label="Состояние документов">
    <p class="documents-totals" role="status">Обработано {{ counts.done }} из {{ counts.all }} · в обработке {{ counts.processing }} · ожидают {{ counts.waiting }} · с ошибками {{ counts.error }}</p>
    <p class="documents-status-help">«Обработан» означает: текст распознан и данные извлечены. Поиск пар и сверка всего проекта выполняются отдельно.</p>
    <div class="document-filters" role="group" aria-label="Показать документы по состоянию">
      <button v-for="item in filters" :key="item.id" :aria-pressed="filter === item.id" @click="filter = item.id">{{ item.title }} <span>{{ counts[item.id] }}</span></button>
    </div>
    <div v-if="!visible.length" class="empty-state compact-empty"><b>В этой группе пока нет файлов</b><button class="text-button" @click="filter = 'all'">Показать все документы</button></div>
    <div v-else class="document-list">
      <button v-for="doc in visible" :key="doc.id" class="document-row document-status-row" :class="{ chosen: selectedId === doc.id }" :aria-pressed="selectedId === doc.id" @click="emit('open', doc)">
        <span class="file-type">{{ doc.file_name.split('.').pop()?.toUpperCase() }}</span>
        <span class="document-name"><b>{{ doc.file_name }}</b><small>{{ doc.role === 'kfz' ? 'Отчёт КФЗ' : 'Документ для сравнения' }} · {{ doc.has_parser_result ? 'Открыть распознанный Markdown' : 'Посмотреть состояние' }}</small></span>
        <span class="document-state"><span class="document-status-badge" :class="`status-${documentStatus(doc, extractionStage)}`">{{ documentStatusLabel(doc, extractionStage) }}</span><small>Текст: {{ doc.has_parser_result ? 'готов' : doc.parser_state === 'running' ? 'распознаётся' : doc.parser_state === 'error' ? 'ошибка' : 'не готов' }} · данные: {{ doc.extraction_id ? 'готовы' : documentStatus(doc, extractionStage) === 'processing' && doc.has_parser_result ? 'извлекаются' : doc.extraction_error ? 'ошибка' : 'ожидают' }}</small></span>
        <span class="row-arrow" aria-hidden="true">→</span>
      </button>
    </div>
  </section>
</template>
