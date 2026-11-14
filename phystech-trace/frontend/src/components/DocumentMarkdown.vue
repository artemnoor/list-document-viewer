<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue';
const props = defineProps<{ parser: Record<string, any>; fileName: string }>();
const view = ref<'preview' | 'source'>('preview');
const markdown = computed(() => [props.parser.export_markdown, props.parser.markdown].find(value => typeof value === 'string' && value.trim()) || '');
const downloadUrl = ref('');
watch(markdown, text => {
  if (downloadUrl.value) URL.revokeObjectURL(downloadUrl.value);
  downloadUrl.value = text ? URL.createObjectURL(new Blob([text], { type: 'text/markdown;charset=utf-8' })) : '';
}, { immediate: true });
onUnmounted(() => { if (downloadUrl.value) URL.revokeObjectURL(downloadUrl.value); });
// Parser produces sanitized HTML. The isolated preview additionally disallows scripts,
// remote resources and access to the application, including for older saved results.
const preview = computed(() => typeof props.parser.markdown_preview === 'string' ? props.parser.markdown_preview : '');
const previewDocument = computed(() => `<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{font:16px/1.7 system-ui,sans-serif;color:#24242c;margin:0;padding:24px;overflow-wrap:anywhere}h1,h2,h3{line-height:1.3}h1{font-size:26px}h2{font-size:22px}table{border-collapse:collapse;display:block;max-width:100%;overflow:auto;font-size:14px}td,th{border:1px solid #ddd;padding:8px 12px;text-align:left}pre{overflow:auto;padding:16px;background:#f6f6fa}code{font-family:monospace}blockquote{border-left:3px solid #ccc;margin-left:0;padding-left:16px}a{color:#4934f3}@media(max-width:500px){body{padding:16px;font-size:15px}}</style></head><body>${preview.value}</body></html>`);
</script>

<template>
  <section class="document-markdown" aria-label="Распознанная Markdown-версия">
    <div class="markdown-toolbar"><div class="markdown-view-switch" role="group" aria-label="Вид Markdown"><button :aria-pressed="view === 'preview'" @click="view = 'preview'">Читать документ</button><button :aria-pressed="view === 'source'" @click="view = 'source'">Исходный Markdown</button></div><a v-if="downloadUrl" :href="downloadUrl" :download="fileName.replace(/\.[^.]+$/, '') + '.md'" class="button button-outline">Скачать .md</a></div>
    <p class="markdown-caption">Распознанная версия исходного файла. Она доступна, даже если извлечение данных ещё не завершилось.</p>
    <iframe v-if="view === 'preview' && preview.trim()" class="markdown-preview" :srcdoc="previewDocument" sandbox="" title="Распознанный документ в Markdown" referrerpolicy="no-referrer"></iframe>
    <template v-else-if="markdown"><p v-if="view === 'preview'" class="markdown-caption">Для этого сохранённого результата доступен исходный Markdown.</p><pre class="markdown-source" tabindex="0">{{ markdown }}</pre></template>
    <div v-else class="empty-state compact-empty"><b>В этом результате нет Markdown-текста</b><p>Откройте оригинал или посмотрите найденные данные на соседней вкладке.</p></div>
  </section>
</template>
