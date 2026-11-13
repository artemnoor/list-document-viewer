<script setup lang="ts">
import { computed } from "vue";
import type { EvidenceSide, LinkEvidence, Provenance } from "../types";

const props = defineProps<{ projectId: string; evidence?: LinkEvidence | { source: EvidenceSide; target?: EvidenceSide } | null }>();
const sides = computed(() => props.evidence ? [props.evidence.source, ...(props.evidence.target ? [props.evidence.target] : [])] : []);
function sourcePath(side: EvidenceSide) { return `/api/projects/${encodeURIComponent(props.projectId)}/sources/${encodeURIComponent(side.document_id)}`; }
function pagePath(side: EvidenceSide, p: Provenance) { return `${sourcePath(side)}/pages/${Math.max(1, Number(p.page_no) || 1)}`; }
function box(p: Provenance) {
  const b = p.bbox, size = p.page_size;
  if (!b || !size?.width || !size.height) return null;
  const bottomLeft = (b.coord_origin ?? p.coordinate_origin ?? "").toUpperCase().includes("BOTTOM");
  const top = bottomLeft ? size.height - b.b : b.t;
  const height = Math.max(0, b.b - b.t);
  return { left: `${(b.l / size.width) * 100}%`, top: `${(top / size.height) * 100}%`, width: `${((b.r - b.l) / size.width) * 100}%`, height: `${(height / size.height) * 100}%` };
}
function pretty(value: unknown) { if (value == null) return "—"; return typeof value === "string" ? value : JSON.stringify(value); }
</script>

<template>
  <section class="evidence-panel">
    <div class="evidence-panel-head"><div><span class="eyebrow">ПЕРВОИСТОЧНИК</span><h3>{{ evidence ? 'Подтверждающий фрагмент' : 'Выберите значение или связь' }}</h3></div><span class="source-mark">↗</span></div>
    <div v-if="!evidence" class="evidence-empty"><div class="empty-glyph">⌕</div><p>Нажмите на поле или связь, чтобы открыть исходный документ и его координаты.</p></div>
    <div v-else class="evidence-sides">
      <article v-for="(side, index) in sides" :key="`${side.document_id}-${index}`" class="evidence-side">
        <div class="evidence-side-title"><span>{{ side.provenance?.page_no ? `PDF · страница ${side.provenance.page_no}` : side.provenance?.cell_address ? 'Ячейка XLSX' : 'Фрагмент документа' }}</span><a :href="sourcePath(side)" target="_blank" rel="noreferrer">Открыть файл ↗</a></div>
        <div v-if="side.provenance?.page_no" class="page-preview">
          <img :src="pagePath(side, side.provenance)" :alt="`Страница ${side.provenance.page_no}`" loading="lazy" />
          <div v-if="box(side.provenance)" class="bbox-highlight" :style="box(side.provenance) || undefined"></div>
        </div>
        <a v-else-if="/\.(png|jpe?g|webp|gif|bmp)$/i.test(side.provenance?.source_ref || '')" class="image-source" :href="sourcePath(side)" target="_blank" rel="noreferrer"><img :src="sourcePath(side)" alt="Исходное изображение" /></a>
        <div class="source-locator">
          <div v-if="side.provenance?.sheet_name || side.provenance?.cell_address" class="locator-chip">{{ side.provenance?.sheet_name || 'Лист' }}<b v-if="side.provenance?.cell_address">!{{ side.provenance.cell_address }}</b></div>
          <div v-if="side.path" class="locator-path">{{ side.path }}</div>
          <blockquote>{{ side.provenance?.source_text || pretty(side.raw_value) || 'Исходный текст не сохранён' }}</blockquote>
          <div class="locator-values"><span>В источнике <strong>{{ pretty(side.raw_value) }}</strong></span><span>Нормализовано <strong>{{ pretty(side.normalized_value) }}</strong></span></div>
          <div v-if="side.provenance?.source_ref || side.provenance?.source_part_id || side.provenance?.row_id" class="locator-id">{{ [side.provenance?.source_part_id, side.provenance?.row_id, side.provenance?.source_ref].filter(Boolean).join(' · ') }}</div>
        </div>
      </article>
    </div>
  </section>
</template>
