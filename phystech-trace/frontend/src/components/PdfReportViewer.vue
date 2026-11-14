<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
const props = defineProps<{ projectId: string; open: boolean }>();
const emit = defineEmits<{ close: [] }>();
const panel = ref<HTMLElement | null>(null), closeButton = ref<HTMLButtonElement | null>(null);
const loading = ref(false), error = ref(''), blobUrl = ref('');
const url = computed(() => `/api/projects/${encodeURIComponent(props.projectId)}/report.pdf`);
let controller: AbortController | null = null, returnFocus: HTMLElement | null = null, previousOverflow = '';
function cleanup() { controller?.abort(); if (blobUrl.value) URL.revokeObjectURL(blobUrl.value); blobUrl.value = ''; }
watch(() => props.open, async open => {
  cleanup(); error.value = '';
  if (!open) { document.body.style.overflow = previousOverflow; returnFocus?.focus(); return; }
  returnFocus = document.activeElement as HTMLElement; previousOverflow = document.body.style.overflow; document.body.style.overflow = 'hidden';
  await nextTick(); closeButton.value?.focus(); loading.value = true;
  const request = new AbortController(); controller = request;
  try {
    const result = await fetch(url.value, { signal: request.signal, cache: 'no-store' });
    if (!result.ok) throw new Error('Не удалось сформировать заключение. Повторите попытку.');
    const blob = await result.blob();
    if (!request.signal.aborted) blobUrl.value = URL.createObjectURL(blob);
  } catch (e) { if (!request.signal.aborted) error.value = e instanceof Error ? e.message : 'Не удалось открыть PDF.'; }
  finally { if (!request.signal.aborted) loading.value = false; }
});
function keys(event: KeyboardEvent) {
  if (event.key === 'Escape') { event.preventDefault(); emit('close'); }
  if (event.key !== 'Tab' || !panel.value) return;
  const items = [...panel.value.querySelectorAll<HTMLElement>('button,a[href],iframe')];
  if (event.shiftKey && document.activeElement === items[0]) { event.preventDefault(); items.at(-1)?.focus(); }
  else if (!event.shiftKey && document.activeElement === items.at(-1)) { event.preventDefault(); items[0]?.focus(); }
}
onBeforeUnmount(() => { cleanup(); if (props.open) { document.body.style.overflow = previousOverflow; returnFocus?.focus(); } });
</script>
<template>
  <Teleport to="body"><div v-if="open" class="pdf-overlay" @click.self="emit('close')" @keydown="keys"><section ref="panel" role="dialog" aria-modal="true" aria-labelledby="pdf-title" class="pdf-dialog">
    <header><div><span>Готовый документ · PDF</span><h2 id="pdf-title">Заключение о проверке</h2></div><div class="pdf-actions"><a :href="blobUrl || url" download="verification-conclusion.pdf" class="pdf-download">Скачать PDF ↓</a><button ref="closeButton" aria-label="Закрыть заключение" @click="emit('close')">×</button></div></header>
    <p class="pdf-caption">Итоги сверки, подтверждающие документы и ваше решение. Ссылки в PDF открывают оригиналы документов.</p>
    <p v-if="loading" class="pdf-message" role="status">Формируем заключение…</p><p v-else-if="error" class="pdf-message" role="alert">{{ error }}</p><iframe v-else-if="blobUrl" :src="blobUrl + '#view=FitH&toolbar=1'" title="Заключение о проверке в PDF" class="pdf-preview"></iframe>
  </section></div></Teleport>
</template>
<style scoped>
.pdf-overlay{position:fixed;inset:0;z-index:125;background:#182c226b;backdrop-filter:blur(3px);padding:25px;display:grid;place-items:center}.pdf-dialog{width:min(1180px,100%);height:calc(100dvh - 50px);background:#f4f6f0;border:1px solid #dce4d7;border-radius:14px;overflow:hidden;display:flex;flex-direction:column;box-shadow:0 20px 90px #132b292b}.pdf-dialog header{padding:18px 25px;background:#fff;display:flex;justify-content:space-between;align-items:center;gap:20px;border-bottom:1px solid #e1e7dc}.pdf-dialog header span{font-size:11px;color:#6a7c6a}.pdf-dialog h2{font-size:21px;margin:4px 0;color:#284531}.pdf-actions{display:flex;align-items:center;gap:18px}.pdf-download{font-size:13px;background:#2e6142;color:white;border-radius:8px;padding:11px 16px;text-decoration:none;font-weight:600;white-space:nowrap}.pdf-actions button{background:#fff;border:1px solid #dce4d5;border-radius:8px;width:40px;height:40px;font-size:26px;cursor:pointer;color:#36583b}.pdf-caption{font-size:12px;color:#63775e;margin:12px 25px;line-height:1.6}.pdf-preview{border:0;flex:1;min-height:0;width:100%;background:#525659}.pdf-message{padding:30px;font-size:14px;color:#49613f}.pdf-dialog a:focus-visible,.pdf-dialog button:focus-visible{outline:3px solid #7faa6c;outline-offset:3px}@media(max-width:620px){.pdf-overlay{padding:0}.pdf-dialog{height:100dvh;border-radius:0;border:0}.pdf-dialog header{padding:16px;gap:10px}.pdf-dialog h2{font-size:16px}.pdf-actions{gap:8px}.pdf-download{font-size:11px;padding:10px}.pdf-caption{margin:10px 16px;font-size:11px}}
</style>
