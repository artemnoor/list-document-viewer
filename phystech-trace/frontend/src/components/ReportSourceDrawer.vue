<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import type { TraceProject } from '../types';
import type { ReportSource } from '../reportView';
import { money } from '../reportView';
import { api } from '../api';
import DocumentMarkdown from './DocumentMarkdown.vue';
import AppIcon from './AppIcon.vue';
const props = defineProps<{ source: ReportSource | null; project: TraceProject }>();
const emit = defineEmits<{ close: [] }>();
const closeButton = ref<HTMLButtonElement | null>(null);
const panel = ref<HTMLElement | null>(null);
const parser = ref<Record<string, any> | null>(null);
const loading = ref(false), error = ref(''), imageFailed = ref(false);
let generation = 0, returnFocus: HTMLElement | null = null, oldOverflow = '';
const doc = computed(() => props.project.documents.find(d => d.document_id === props.source?.document_id));
const filename = computed(() => doc.value?.file_name || props.source?.file_name || 'Документ');
const original = computed(() => `/api/projects/${encodeURIComponent(props.project.id)}/sources/${encodeURIComponent(props.source?.document_id || '')}`);
const page = computed(() => Math.max(1, props.source?.provenance?.page_no || 1));
const isPDF = computed(() => /\.pdf$/i.test(filename.value));
const isImage = computed(() => /\.(png|jpe?g|webp|gif)$/i.test(filename.value));
const pageImage = computed(() => isPDF.value ? `${original.value}/pages/${page.value}` : original.value);
const amountText = computed(() => {
  const v = props.source?.value;
  return v && typeof v === 'object' && 'amount' in v ? money(v, v.currency) : typeof v === 'string' || typeof v === 'number' ? String(v) : '';
});
const excerpt = computed(() => {
  const text = props.source?.provenance?.source_text || props.source?.source_value;
  if (typeof text === 'string' || typeof text === 'number') return String(text);
  return amountText.value || 'Откройте документ, чтобы прочитать исходный фрагмент.';
});
const highlight = computed(() => {
  const p = props.source?.provenance, b = p?.bbox, size = p?.page_size;
  if (!b || !size?.width || !size.height) return null;
  const lower = (b.coord_origin || p?.coordinate_origin || '').toUpperCase().includes('BOTTOM');
  const top = lower ? size.height - Math.max(b.t, b.b) : Math.min(b.t, b.b);
  return { left: `${Math.max(0, b.l / size.width * 100)}%`, top: `${Math.max(0, top / size.height * 100)}%`, width: `${Math.abs(b.r - b.l) / size.width * 100}%`, height: `${Math.abs(b.b - b.t) / size.height * 100}%` };
});
function restore() { document.body.style.overflow = oldOverflow; returnFocus?.focus(); }
watch(() => props.source, async (source, before) => {
  const request = ++generation;
  parser.value = null; error.value = ''; imageFailed.value = false; loading.value = false;
  if (!source) { if (before) restore(); return; }
  if (!before) { returnFocus = document.activeElement as HTMLElement; oldOverflow = document.body.style.overflow; document.body.style.overflow = 'hidden'; }
  await nextTick(); closeButton.value?.focus();
  if (isPDF.value || isImage.value) return;
  if (!doc.value) { error.value = 'Этот документ недоступен в комплекте.'; return; }
  loading.value = true;
  try { const result = await api.result(props.project.id, doc.value.id); if (request === generation) parser.value = result.parser_result || null; }
  catch { if (request === generation) error.value = 'Не удалось открыть просмотр документа. Попробуйте ещё раз или скачайте оригинал.'; }
  finally { if (request === generation) loading.value = false; }
}, { immediate: true });
function keys(event: KeyboardEvent) {
  if (event.key === 'Escape') { event.preventDefault(); emit('close'); }
  if (event.key !== 'Tab' || !panel.value) return;
  const elements = Array.from(panel.value.querySelectorAll<HTMLElement>('button:not([disabled]),a[href],input,textarea,iframe,[tabindex="0"]'));
  const first = elements[0], last = elements.at(-1);
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
}
onBeforeUnmount(() => { generation++; if (props.source) restore(); });
</script>
<template>
  <Teleport to="body">
    <div v-if="source" class="report-source-overlay" @click.self="emit('close')" @keydown="keys">
      <section ref="panel" class="report-source-panel" role="dialog" aria-modal="true" aria-labelledby="report-source-title">
        <header class="source-header"><div><span class="source-eyebrow">Подтверждение из документа</span><h2 id="report-source-title">{{ filename }}</h2></div><button ref="closeButton" class="source-close" aria-label="Закрыть документ" @click="emit('close')">×</button></header>
        <div class="source-excerpt"><div class="source-location"><AppIcon name="file" /><b>{{ source.provenance?.sheet_name ? source.provenance.sheet_name + (source.provenance.cell_address ? ' · ячейка ' + source.provenance.cell_address : '') : isPDF ? 'Страница ' + page : 'Исходный фрагмент' }}</b></div><blockquote>{{ excerpt }}</blockquote><div v-if="amountText" class="source-value"><span>Значение в источнике</span><strong>{{ amountText }}</strong></div></div>
        <div class="source-reading"><div class="source-reading-head"><h3>{{ isPDF || isImage ? 'Оригинал документа' : 'Документ целиком' }}</h3><a :href="original + (isPDF ? '#page=' + page : '')" target="_blank" rel="noreferrer">Открыть оригинал ↗</a></div>
          <div v-if="(isPDF || isImage) && !imageFailed" class="source-paper"><img :src="pageImage" :alt="isPDF ? 'Страница ' + page + ' документа ' + filename : filename" @error="imageFailed = true" /><span v-if="highlight && isPDF" class="source-highlight" :style="highlight"></span></div>
          <p v-else-if="imageFailed" class="source-message">Предпросмотр недоступен. Откройте оригинал по ссылке выше.</p>
          <p v-else-if="loading" class="source-message" role="status">Открываем документ…</p>
          <p v-else-if="error" class="source-message" role="alert">{{ error }}</p>
          <DocumentMarkdown v-else-if="parser" :parser="parser" :file-name="filename" />
          <p v-else class="source-message">Распознанная версия недоступна. Откройте оригинал документа.</p>
        </div>
      </section>
    </div>
  </Teleport>
</template>
<style scoped>
.report-source-overlay{position:fixed;inset:0;z-index:120;background:rgba(21,33,29,.38);backdrop-filter:blur(3px);display:flex;justify-content:flex-end}.report-source-panel{width:min(820px,94vw);height:100dvh;background:#f7f8f5;overflow:auto;box-shadow:-16px 0 80px #15291b24;color:#21362e}.source-header{position:sticky;top:0;z-index:2;background:#fff;padding:25px 30px;display:flex;justify-content:space-between;gap:24px;border-bottom:1px solid #e0e5df}.source-header h2{font-size:19px;line-height:1.4;margin:7px 0 0;overflow-wrap:anywhere}.source-eyebrow{font-size:12px;color:#60746b}.source-close{border:1px solid #dce4de;width:40px;height:40px;flex-shrink:0;border-radius:10px;background:#fff;font-size:25px;cursor:pointer;color:#294637}.source-excerpt{margin:24px 28px;padding:22px;background:#fff;border:1px solid #dae3db;border-left:3px solid #337757;border-radius:10px}.source-location{display:flex;align-items:center;gap:9px;font-size:13px}.source-excerpt blockquote{margin:15px 0;line-height:1.7;overflow-wrap:anywhere;font-size:15px;color:#53665d}.source-value{display:flex;align-items:center;justify-content:space-between;gap:15px;border-top:1px solid #edf0eb;padding-top:14px;font-size:12px;color:#63756b}.source-value strong{font-size:20px;color:#254d38;font-variant-numeric:tabular-nums}.source-reading{padding:0 28px 36px}.source-reading-head{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:16px}.source-reading-head h3{font-size:15px}.source-reading-head a{font-size:13px;color:#2b6549;text-underline-offset:4px}.source-paper{position:relative;background:#fff;line-height:0;border:1px solid #dde4dd;border-radius:6px;overflow:hidden}.source-paper img{width:100%;height:auto;display:block}.source-highlight{position:absolute;border:2px solid #bb652c;background:#f7d18242;box-shadow:0 0 0 4px #ffdc8238;pointer-events:none;min-height:8px}.source-message{padding:30px;background:#fff;border-radius:10px;line-height:1.6}.source-reading :deep(.markdown-preview){min-height:65dvh}.source-reading :deep(.markdown-toolbar){flex-wrap:wrap}.source-reading :deep(.markdown-source){white-space:pre-wrap;overflow-wrap:anywhere}.source-close:focus-visible{outline:3px solid #459765;outline-offset:3px}@media(max-width:600px){.report-source-panel{width:100%}.source-header{padding:20px}.source-excerpt{margin:18px 16px;padding:17px}.source-reading{padding:0 16px 24px}.source-header h2{font-size:16px}.source-value{align-items:flex-start;flex-direction:column}.source-reading-head{align-items:flex-start}.source-reading-head a{max-width:120px}}
</style>
