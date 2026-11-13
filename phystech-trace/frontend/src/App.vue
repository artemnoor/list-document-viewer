<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { api, services } from "./api";
import StageCards from "./components/StageCards.vue";
import EvidencePanel from "./components/EvidencePanel.vue";
import type { DocumentResult, EvidenceSide, LinkEvidence, StageName, TraceDocument, TraceProject, TraceLink } from "./types";

const projects = ref<TraceProject[]>([]);
const activeProject = ref<TraceProject | null>(null);
const activeTab = ref<"overview" | "documents" | "links">("overview");
const selectedDocument = ref<TraceDocument | null>(null);
const selectedEvidence = ref<LinkEvidence | { source: EvidenceSide; target?: EvidenceSide } | null>(null);
const documentResult = ref<DocumentResult | null>(null);
const createOpen = ref(false);
const createName = ref("");
const createClassification = ref<TraceProject["data_classification"]>("confidential");
const allowExternal = ref(false);
const kfzFiles = ref<File[]>([]);
const primaryFiles = ref<File[]>([]);
const busy = ref(false);
const busyLabel = ref("");
const errorText = ref("");
const successText = ref("");
const loadingProject = ref(false);
let pollTimer: number | undefined;

const activeIsRunning = computed(() => Boolean(activeProject.value && Object.values(activeProject.value.stages).some((stage) => ["queued", "running"].includes(stage.status))));
const pendingReview = computed(() => activeProject.value?.linking_result?.links.filter((link) => ["proposed", "review"].includes(link.status) && link.verification_status === "not_reviewed").length ?? 0);
const linkCount = computed(() => activeProject.value?.linking_result?.links.length ?? 0);
const canProcess = computed(() => Boolean(activeProject.value?.documents.some((doc) => doc.role === "kfz") && activeProject.value?.documents.some((doc) => doc.role === "primary")));
const stageOrder: StageName[] = ["parser", "extraction", "linking"];

function clearNotices() { errorText.value = ""; successText.value = ""; }
function formatDate(value: string) { try { return new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)); } catch { return value; } }
function statusLabel(value: string) { return ({ draft: "Черновик", running: "Обрабатывается", completed: "Готов", partial: "Есть ошибки", failed: "Ошибка" } as Record<string, string>)[value] || value; }
function docTypeLabel(value?: string | null) { return ({ kfz_report: "Отчёт КФЗ", contract: "Договор", act: "Акт", invoice: "Счёт", addendum: "Доп. соглашение", registry: "Реестр", unknown: "Тип не определён" } as Record<string, string>)[value || ""] || "Ожидает разбора"; }
function stageStatusLabel(value?: string) { return ({ queued: "В очереди", running: "В работе", completed: "Готово", failed: "Ошибка", blocked: "Нужно разрешение", pending: "Ожидает" } as Record<string, string>)[value || ""] || value || "Ожидает"; }
function shortId(value: string) { return value.slice(0, 8).toUpperCase(); }
function fileKind(name: string) { return name.split(".").pop()?.toUpperCase() || "FILE"; }
function setFiles(event: Event, target: "kfz" | "primary") { const files = Array.from((event.target as HTMLInputElement).files || []); if (target === "kfz") kfzFiles.value = files.slice(0, 1); else primaryFiles.value = files; }

async function refreshProjects(keepSelection = true) {
  try {
    const response = await api.listProjects(); projects.value = response.projects;
    const target = keepSelection ? activeProject.value?.id : null;
    if (target && response.projects.some((project) => project.id === target)) await refreshActive(target);
    else if (!activeProject.value && response.projects.length) await refreshActive(response.projects[0].id);
  } catch (error) { errorText.value = error instanceof Error ? error.message : "Не удалось загрузить проекты"; }
}
async function refreshActive(id: string) {
  loadingProject.value = true;
  try { activeProject.value = await api.getProject(id); }
  catch (error) { errorText.value = error instanceof Error ? error.message : "Не удалось загрузить комплект"; }
  finally { loadingProject.value = false; }
}
async function selectProject(project: TraceProject) { clearNotices(); activeProject.value = project; selectedDocument.value = null; documentResult.value = null; selectedEvidence.value = null; activeTab.value = "overview"; await refreshActive(project.id); }
async function createProject() {
  clearNotices();
  if (!createName.value.trim()) { errorText.value = "Укажите название комплекта"; return; }
  busy.value = true; busyLabel.value = "Создаём комплект…";
  try {
    const project = await api.createProject({ name: createName.value.trim(), data_classification: createClassification.value, allow_external_llm: allowExternal.value });
    activeProject.value = project; projects.value = [project, ...projects.value]; createOpen.value = false; createName.value = ""; kfzFiles.value = []; primaryFiles.value = [];
    successText.value = "Комплект создан. Загрузите КФЗ и первичные документы.";
  } catch (error) { errorText.value = error instanceof Error ? error.message : "Не удалось создать комплект"; }
  finally { busy.value = false; busyLabel.value = ""; }
}
async function uploadRole(role: "kfz" | "primary") {
  if (!activeProject.value) return;
  const files = role === "kfz" ? kfzFiles.value : primaryFiles.value;
  if (!files.length) { errorText.value = role === "kfz" ? "Выберите файл КФЗ" : "Выберите первичные документы"; return; }
  clearNotices(); busy.value = true; busyLabel.value = role === "kfz" ? "Загружаем отчёт КФЗ…" : "Загружаем первичные документы…";
  try {
    const result = await api.upload(activeProject.value.id, role, files) as { documents: { duplicate: boolean }[] };
    const duplicates = result.documents.filter((item) => item.duplicate).length;
    if (role === "kfz") kfzFiles.value = []; else primaryFiles.value = [];
    await refreshProjects(); successText.value = duplicates ? `Загрузка завершена. Повторных файлов: ${duplicates}.` : `Загружено файлов: ${result.documents.length}.`;
  } catch (error) { errorText.value = error instanceof Error ? error.message : "Загрузка не удалась"; }
  finally { busy.value = false; busyLabel.value = ""; }
}
async function startProcess() {
  if (!activeProject.value) return;
  clearNotices(); busy.value = true; busyLabel.value = "Запускаем этапы…";
  try { await api.process(activeProject.value.id); await refreshActive(activeProject.value.id); activeTab.value = "overview"; successText.value = "Обработка запущена. Статусы обновляются автоматически."; }
  catch (error) { errorText.value = error instanceof Error ? error.message : "Не удалось запустить обработку"; }
  finally { busy.value = false; busyLabel.value = ""; }
}
async function retryStage(stage: StageName) {
  if (!activeProject.value) return;
  clearNotices(); busy.value = true; busyLabel.value = `Повторяем ${stage}…`;
  try { await api.retry(activeProject.value.id, stage); await refreshActive(activeProject.value.id); successText.value = `Этап ${stage} поставлен в очередь. Успешные предыдущие результаты сохранены.`; }
  catch (error) { errorText.value = error instanceof Error ? error.message : "Не удалось повторить этап"; }
  finally { busy.value = false; busyLabel.value = ""; }
}
async function openDocument(doc: TraceDocument) {
  selectedDocument.value = doc; activeTab.value = "documents"; selectedEvidence.value = null; documentResult.value = null;
  if (!activeProject.value || !doc.has_parser_result) return;
  try { documentResult.value = await api.result(activeProject.value.id, doc.id); }
  catch (error) { errorText.value = error instanceof Error ? error.message : "Не удалось загрузить результаты документа"; }
}
function selectField(field: any, path: string, doc: TraceDocument) {
  const extracted = field?.extracted ?? field;
  const provenance = extracted?.provenance;
  if (!provenance || !activeProject.value) return;
  const normalizedValue = extracted.value == null ? "" : typeof extracted.value === "string" ? extracted.value : JSON.stringify(extracted.value);
  selectedEvidence.value = { source: { document_id: provenance.document_id || doc.document_id, path, raw_value: extracted.source_value, normalized_value: normalizedValue, provenance } };
}
function selectLink(link: TraceLink) { activeTab.value = "links"; selectedEvidence.value = link.evidence[0] || null; }
function evidenceClick(evidence: LinkEvidence) { selectedEvidence.value = evidence; }
async function decide(link: TraceLink, status: "confirmed" | "rejected") {
  if (!activeProject.value) return;
  clearNotices(); busy.value = true; busyLabel.value = status === "confirmed" ? "Подтверждаем связь…" : "Отклоняем связь…";
  try { const result = await api.decide(activeProject.value.id, link.link_id, status); activeProject.value.linking_result = result.linking_result; successText.value = status === "confirmed" ? "Связь подтверждена и сохранена." : "Связь отклонена и сохранена."; }
  catch (error) { errorText.value = error instanceof Error ? error.message : "Решение не сохранено"; }
  finally { busy.value = false; busyLabel.value = ""; }
}
function rowsFor(extraction: Record<string, any>) { return extraction.line_items || extraction.payment_schedule || extraction.changes || []; }
function primitiveFields(extraction: Record<string, any>) { return Object.entries(extraction.fields || {}).filter(([, value]) => value && typeof value === "object"); }
function parserParts(result: DocumentResult | null) { return (result?.parser_result?.visual_layout?.parts || result?.parser_result?.parts || []).slice(0, 32); }
function fieldValue(value: any) { return value?.value == null ? "—" : typeof value.value === "string" ? value.value : JSON.stringify(value.value); }
function bboxHint(side?: EvidenceSide) { const p = side?.provenance; if (!p) return ""; if (p.sheet_name || p.cell_address) return `${p.sheet_name || "Лист"}${p.cell_address ? `!${p.cell_address}` : ""}`; if (p.page_no) return `стр. ${p.page_no}`; return "Фрагмент"; }
function isReviewable(link: TraceLink) { return ["proposed", "review"].includes(link.status) && link.verification_status === "not_reviewed"; }
function linkStatus(link: TraceLink) { return link.verification_status === "human_confirmed" ? "Подтверждена" : link.verification_status === "human_rejected" ? "Отклонена" : link.status === "review" ? "На проверке" : link.status === "proposed" ? "Предложена" : link.status; }
function classificationLabel(value: string) { return ({ confidential: "Конфиденциальные", synthetic: "Синтетические", public: "Открытые", anonymized: "Обезличенные" } as Record<string, string>)[value] || value; }

onMounted(async () => {
  await refreshProjects(false);
  pollTimer = window.setInterval(async () => {
    if (activeProject.value && activeIsRunning.value) { await refreshActive(activeProject.value.id); await refreshProjects(false); }
  }, 2500);
});
onUnmounted(() => { if (pollTimer) window.clearInterval(pollTimer); });
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand"><div class="brand-glyph"><span></span><span></span><span></span><span></span></div><div><strong>phystech<span> trace</span></strong><small>DOCUMENT INTELLIGENCE</small></div></div>
      <div class="sidebar-section"><span class="sidebar-label">РАБОЧЕЕ ПРОСТРАНСТВО</span><button class="nav-item active"><span class="nav-icon">▦</span>Комплекты документов<span class="nav-count">{{ projects.length }}</span></button></div>
      <div class="sidebar-section project-nav"><div class="sidebar-row"><span class="sidebar-label">ПОСЛЕДНИЕ КОМПЛЕКТЫ</span><button class="icon-button" title="Создать комплект" @click="createOpen = true">＋</button></div>
        <button v-for="project in projects.slice(0, 7)" :key="project.id" class="project-nav-item" :class="{ selected: activeProject?.id === project.id }" @click="selectProject(project)"><i :class="`project-dot ${project.status}`"></i><span><b>{{ project.name }}</b><small>{{ formatDate(project.updated_at) }}</small></span><span v-if="project.status === 'partial'" class="mini-alert">!</span></button>
        <div v-if="!projects.length" class="sidebar-empty">Здесь появятся ваши комплекты.</div>
      </div>
      <div class="sidebar-bottom"><div class="privacy-note"><span class="privacy-icon">◈</span><div><b>Данные остаются под контролем</b><p>Внешняя модель запускается только по явному разрешению для открытых, синтетических или обезличенных файлов.</p></div></div><div class="sidebar-footer">PHYSTECH TRACE · 1.0</div></div>
    </aside>

    <main class="main-area">
      <header class="topbar"><div class="breadcrumbs"><span>Пространство</span><i>/</i><b>{{ activeProject?.name || "Обзор" }}</b></div><div class="topbar-actions"><span class="system-pill"><i></i>Сервисы {{ activeProject ? "доступны" : "готовы" }}</span><div class="avatar">PT</div></div></header>

      <div v-if="errorText" class="notice notice-error" role="alert"><span>!</span><div>{{ errorText }}</div><button @click="errorText = ''" aria-label="Закрыть">×</button></div>
      <div v-if="successText" class="notice notice-success" role="status"><span>✓</span><div>{{ successText }}</div><button @click="successText = ''" aria-label="Закрыть">×</button></div>

      <section v-if="!activeProject" class="welcome-view">
        <div class="welcome-copy"><span class="eyebrow">СКВОЗНАЯ ПРОВЕРКА ДОКУМЕНТОВ</span><h1>Следите за каждым<br /><em>источником данных.</em></h1><p>Загрузите комплект документов КФЗ. Phystech Trace покажет путь от распознавания файла до каждой найденной связи и подтверждающего фрагмента.</p><button class="button button-dark" @click="createOpen = true">Создать комплект <span>↗</span></button></div>
        <div class="flow-illustration"><div class="flow-lines"><span></span><span></span><span></span></div><div class="flow-node node-parser"><small>01 · PARSER</small><b>Распознавание</b><i>PDF · XLSX · DOCX</i></div><div class="flow-node node-extract"><small>02 · EXTRACTION</small><b>Структурированные данные</b><i>значение + provenance</i></div><div class="flow-node node-link"><small>03 · LINKING</small><b>Связи с доказательствами</b><i>документ ↔ строка</i></div><div class="flow-stamp">TRACE<br />TO SOURCE</div></div>
        <div class="welcome-services"><span>API ДОКУМЕНТАЦИЯ</span><a v-for="service in services" :key="service.name" :href="service.url" target="_blank" rel="noreferrer">{{ service.name }} <b>↗</b></a></div>
      </section>

      <section v-else class="project-view">
        <div class="project-heading"><div><div class="eyebrow">КОМПЛЕКТ · {{ shortId(activeProject.id) }} <span class="heading-dot">•</span> {{ classificationLabel(activeProject.data_classification) }}</div><h1>{{ activeProject.name }}</h1><div class="project-meta"><span>Создан {{ formatDate(activeProject.created_at) }}</span><i>·</i><span>{{ activeProject.documents.length }} {{ activeProject.documents.length === 1 ? "документ" : "документов" }}</span><span class="overall-status" :class="activeProject.status"><i></i>{{ statusLabel(activeProject.status) }}</span></div></div><div class="heading-actions"><button v-if="activeProject.status === 'draft' || activeProject.status === 'partial'" class="button button-dark" :disabled="busy || !canProcess" @click="startProcess">{{ activeProject.status === 'partial' ? 'Продолжить обработку' : 'Запустить обработку' }} <span>↗</span></button><span v-else-if="activeIsRunning" class="running-caption"><i class="spinner"></i>Обработка комплекта</span></div></div>

        <div class="tabbar" role="tablist"><button :class="{ current: activeTab === 'overview' }" @click="activeTab = 'overview'">Обзор <span class="tab-index">01</span></button><button :class="{ current: activeTab === 'documents' }" @click="activeTab = 'documents'">Документы <span class="tab-badge">{{ activeProject.documents.length }}</span></button><button :class="{ current: activeTab === 'links' }" @click="activeTab = 'links'">Связи <span v-if="linkCount" class="tab-badge">{{ linkCount }}</span><span v-if="pendingReview" class="tab-review">{{ pendingReview }} на проверке</span></button><div class="tab-spacer"></div><a v-for="service in services" :key="service.name" class="swagger-shortcut" :href="service.url" target="_blank" rel="noreferrer" :title="service.name">API <b>↗</b></a></div>

        <div v-if="activeTab === 'overview'" class="overview-layout">
          <div class="overview-main"><StageCards :stages="activeProject.stages" :on-retry="retryStage" />
            <section class="upload-panel"><div class="section-heading"><div><span class="eyebrow">ШАГ 01 · ВХОДНЫЕ ДАННЫЕ</span><h2>Состав комплекта</h2><p>Добавьте один отчёт КФЗ и первичные документы для проверки.</p></div><span class="upload-lock">ЛОКАЛЬНАЯ ЗАГРУЗКА</span></div>
              <div class="upload-columns"><div class="upload-card"><div class="upload-card-head"><span class="file-icon kfz">K</span><div><b>Отчёт КФЗ</b><small>Один файл · основной документ</small></div><span class="required-tag">ОБЯЗАТЕЛЬНО</span></div><label class="dropzone"><input type="file" accept=".pdf,.xlsx,.xls,.csv,.docx,.png,.jpg,.jpeg,.webp,.txt" @change="setFiles($event, 'kfz')" /><span class="drop-icon">↑</span><b>Выберите файл КФЗ</b><small>PDF, XLSX, DOCX или изображение · до 25 МБ</small></label><div v-if="kfzFiles.length" class="selected-files"><span>{{ kfzFiles[0].name }}</span><button @click="kfzFiles = []">×</button></div><div v-if="!kfzFiles.length" class="upload-doc-list"><div v-for="doc in activeProject.documents.filter((item) => item.role === 'kfz')" :key="doc.id" class="existing-file"><span class="file-type">{{ fileKind(doc.file_name) }}</span><span>{{ doc.file_name }}</span><i class="done-mark">✓</i></div></div><button v-if="kfzFiles.length" class="button button-outline upload-submit" :disabled="busy" @click="uploadRole('kfz')">Загрузить КФЗ <span>↑</span></button></div>
                <div class="upload-card"><div class="upload-card-head"><span class="file-icon primary">P</span><div><b>Первичные документы</b><small>Договоры, акты, счета, реестры</small></div><span class="optional-tag">{{ activeProject.documents.filter((item) => item.role === 'primary').length }} ФАЙЛОВ</span></div><label class="dropzone"><input type="file" multiple accept=".pdf,.xlsx,.xls,.csv,.docx,.png,.jpg,.jpeg,.webp,.txt" @change="setFiles($event, 'primary')" /><span class="drop-icon">↑</span><b>Выберите первичные документы</b><small>Можно загрузить несколько файлов · до 25 МБ каждый</small></label><div v-if="primaryFiles.length" class="selected-files"><span>{{ primaryFiles.length }} файлов · {{ primaryFiles.map((file) => file.name).join(', ') }}</span><button @click="primaryFiles = []">×</button></div><div v-if="!primaryFiles.length" class="upload-doc-list">{{ activeProject.documents.filter((item) => item.role === 'primary').length ? 'Первичные документы уже загружены.' : 'Файлы появятся здесь после загрузки.' }}</div><button v-if="primaryFiles.length" class="button button-outline upload-submit" :disabled="busy" @click="uploadRole('primary')">Загрузить {{ primaryFiles.length }} {{ primaryFiles.length === 1 ? 'файл' : 'файла' }} <span>↑</span></button></div></div>
              <div class="upload-footer"><span><i></i> Файл сохраняется в хранилище Parser и доступен для просмотра по исходному ID.</span><button v-if="canProcess" class="text-button" :disabled="busy || activeIsRunning" @click="startProcess">Запустить комплект <b>→</b></button></div>
            </section>
            <section v-if="activeProject.documents.length" class="compact-docs"><div class="section-heading small-heading"><div><span class="eyebrow">ЗАГРУЖЕННЫЕ ФАЙЛЫ</span><h2>Документы комплекта</h2></div><button class="text-button" @click="activeTab = 'documents'">Открыть все <b>→</b></button></div><button v-for="doc in activeProject.documents.slice(0, 5)" :key="doc.id" class="document-row" @click="openDocument(doc)"><span class="file-type">{{ fileKind(doc.file_name) }}</span><span class="document-name"><b>{{ doc.file_name }}</b><small>{{ doc.role === 'kfz' ? 'Отчёт КФЗ' : docTypeLabel(doc.document_type) }}</small></span><span class="row-stage">{{ stageStatusLabel(doc.extraction_id ? 'completed' : doc.parser_state) }}</span><span class="row-arrow">↗</span></button></section>
          </div>
          <aside class="overview-aside"><div class="aside-card"><span class="eyebrow">СВОДКА</span><div class="summary-number">{{ activeProject.documents.length.toString().padStart(2, '0') }}<small>документов</small></div><div class="summary-divider"></div><div class="summary-row"><span>КФЗ</span><b>{{ activeProject.documents.filter((doc) => doc.role === 'kfz').length }} / 1</b></div><div class="summary-row"><span>Первичные</span><b>{{ activeProject.documents.filter((doc) => doc.role === 'primary').length }}</b></div><div class="summary-row"><span>Обнаружено связей</span><b>{{ linkCount }}</b></div><div class="summary-row"><span>Требуют решения</span><b :class="{ 'review-number': pendingReview }">{{ pendingReview }}</b></div><a class="aside-cta" href="http://localhost:8084/docs" target="_blank" rel="noreferrer">Документация Gateway <span>↗</span></a></div>
            <div class="aside-card privacy-card"><span class="privacy-icon">◈</span><b>Политика обработки</b><p>Класс данных: <strong>{{ classificationLabel(activeProject.data_classification) }}</strong>. Внешний LLM: <strong>{{ activeProject.allow_external_llm ? 'разрешён' : 'запрещён' }}</strong>.</p><span v-if="activeProject.allow_external_llm" class="policy-enabled"><i></i>Явное разрешение сохранено</span><span v-else class="policy-disabled">Результат остаётся внутри сервисов</span></div>
          </aside>
        </div>

        <div v-else-if="activeTab === 'documents'" class="documents-layout"><div class="documents-main"><div class="section-heading"><div><span class="eyebrow">ПАРСЕР → EXTRACTION</span><h2>Результаты по документам</h2><p>Оригинальный файл, распознавание и структурированные значения с координатами источника.</p></div></div><div v-if="!activeProject.documents.length" class="empty-state"><span>▤</span><b>Пока нет документов</b><p>Добавьте КФЗ и первичные файлы на вкладке «Обзор».</p></div><div v-else class="document-list"><button v-for="doc in activeProject.documents" :key="doc.id" class="document-row detailed" :class="{ chosen: selectedDocument?.id === doc.id }" @click="openDocument(doc)"><span class="file-type">{{ fileKind(doc.file_name) }}</span><span class="document-name"><b>{{ doc.file_name }}</b><small>{{ doc.role === 'kfz' ? 'Отчёт КФЗ' : docTypeLabel(doc.document_type) }} · {{ shortId(doc.document_id) }}</small></span><span class="row-stage">{{ stageStatusLabel(doc.extraction_id ? 'completed' : doc.parser_state) }}</span><span class="row-arrow">→</span></button></div>
            <div v-if="selectedDocument" class="result-sheet"><div class="result-sheet-head"><div><span class="eyebrow">{{ selectedDocument.role === 'kfz' ? 'ОТЧЁТ КФЗ' : 'ПЕРВИЧНЫЙ ДОКУМЕНТ' }} · {{ fileKind(selectedDocument.file_name) }}</span><h3>{{ selectedDocument.file_name }}</h3></div><a :href="`/api/projects/${activeProject.id}/sources/${selectedDocument.document_id}`" target="_blank" rel="noreferrer" class="button button-outline">Открыть файл ↗</a></div><div class="result-tabs"><span>Document Parser</span><i>→</i><span>Structured Extraction</span></div><div v-if="documentResult?.extraction" class="extraction-result"><div class="extraction-summary"><span class="classification-pill">{{ docTypeLabel(documentResult.extraction.document_type) }}</span><span>Схема {{ documentResult.extraction.schema_version }}</span><span>{{ documentResult.extraction.extraction_engine?.parser_adapter }}</span><span class="review-count">{{ documentResult.extraction.review_required?.length || 0 }} требуют проверки</span></div><div v-if="primitiveFields(documentResult.extraction).length" class="field-grid"><button v-for="[key, value] in primitiveFields(documentResult.extraction)" :key="key" class="field-card" :class="`field-${(value as any).status}`" @click="selectField(value, `fields.${key}`, selectedDocument!)"><span>{{ (value as any).label || key.replaceAll('_', ' ') }}</span><b>{{ fieldValue(value) }}</b><small>{{ bboxHint({ document_id: selectedDocument!.document_id, provenance: (value as any).provenance }) || 'Источник не определён' }}</small></button></div><div v-for="table in documentResult.extraction.tables || []" :key="table.id" class="extraction-table-wrap"><div class="table-caption"><b>{{ table.title || table.role || 'Таблица' }}</b><span>{{ table.rows?.length || 0 }} строк</span></div><table class="data-table"><thead><tr><th>Строка</th><th>Показатель</th><th>Значение</th><th>Источник</th></tr></thead><tbody><template v-for="row in table.rows || []" :key="row.row_id"><tr v-for="field in ['identifier','description','unit','quantity','actual_quantity','amount']" :key="`${row.row_id}-${field}`" v-show="(row as any)[field]?.value != null"><td>{{ row.row_id }}</td><td>{{ field }}</td><td>{{ fieldValue((row as any)[field]) }}</td><td><button class="locator-button" @click="selectField((row as any)[field], `tables.${table.id}.rows.${row.row_id}.${field}`, selectedDocument!)">{{ bboxHint({ document_id: selectedDocument!.document_id, provenance: (row as any)[field]?.provenance }) || 'Открыть источник ↗' }}</button></td></tr></template></tbody></table></div><details class="parser-parts"><summary>Результат распознавания · {{ documentResult.parser_result?.parts?.length || 0 }} элементов</summary><div v-for="(part, index) in parserParts(documentResult)" :key="index" class="parser-part"><span>{{ part.kind }}</span><b>{{ part.text || part.value || part.display_value || part.caption || 'Структурный фрагмент' }}</b><small>{{ part.page_no ? `стр. ${part.page_no}` : part.sheet_name ? `${part.sheet_name}!${part.coordinate || part.address || ''}` : '' }}</small></div><p v-if="(documentResult.parser_result?.parts?.length || 0) > 32" class="muted">Показаны первые 32 фрагмента; полный JSON сохранён в Parser.</p></details></div><div v-else-if="documentResult?.parser_result" class="partial-result"><span class="spinner dark-spinner"></span><div><b>{{ stageStatusLabel(selectedDocument.parser_state) }}</b><p>{{ selectedDocument.parser_error?.message || selectedDocument.extraction_error?.message || 'Parser JSON уже сохранён. Extraction появится после завершения предыдущего этапа.' }}</p></div></div><div v-else class="partial-result"><span class="spinner dark-spinner"></span><div><b>Результаты пока недоступны</b><p>{{ selectedDocument.parser_error?.message || 'Дождитесь завершения этапа Parser.' }}</p></div></div></div>
          </div><aside class="documents-aside"><EvidencePanel v-if="activeProject" :project-id="activeProject.id" :evidence="selectedEvidence" /><div class="aside-card source-legend"><span class="eyebrow">PROVENANCE</span><h3>Откуда взялось значение</h3><p><b>PDF</b> · номер страницы, bbox и система координат.</p><p><b>XLSX</b> · имя листа и точный адрес ячейки.</p><p><b>DOCX</b> · исходный элемент и текст подтверждения.</p></div></aside></div>

        <div v-else class="links-layout"><div class="links-main"><div class="section-heading"><div><span class="eyebrow">STRUCTURED EXTRACTION → DOCUMENT LINKING</span><h2>Связи комплекта <span v-if="linkCount" class="heading-count">{{ linkCount }}</span></h2><p>Связи предложены Linking, прошли техническую проверку evidence и ждут решения эксперта.</p></div></div><div v-if="!activeProject.linking_result" class="empty-state linking-empty"><span>↗</span><b>Связи ещё не готовы</b><p>{{ activeProject.stages.linking?.error?.message || (activeProject.stages.linking?.status === 'running' ? 'Linking обрабатывает весь комплект документов.' : 'Загрузите документы и запустите этапы обработки.') }}</p><button v-if="['failed','blocked'].includes(activeProject.stages.linking?.status)" class="button button-outline" @click="retryStage('linking')">Повторить Linking <span>↻</span></button></div><div v-else><div v-if="pendingReview" class="review-banner"><span>!</span><div><b>{{ pendingReview }} {{ pendingReview === 1 ? 'связь ожидает' : 'связи ожидают' }} решения</b><small>Откройте evidence, затем подтвердите или отклоните предложение.</small></div></div><div v-if="!activeProject.linking_result.links.length" class="empty-state compact-empty"><span>⌁</span><b>Связи не найдены</b><p>{{ activeProject.linking_result.analysis_summary || 'Для этого комплекта нет подтверждённых связей.' }}</p></div><article v-for="link in activeProject.linking_result.links" :key="link.link_id" class="link-card" :class="{ 'link-awaiting': isReviewable(link) }"><div class="link-card-top"><span class="link-kind"><i>⌁</i>{{ link.relationship_type.replaceAll('_', ' ') }}</span><span class="link-state" :class="link.status">{{ linkStatus(link) }}</span></div><div class="link-chain"><div class="link-endpoint"><small>ИСТОЧНИК</small><b>{{ activeProject.documents.find((doc) => doc.document_id === link.source_document_id)?.file_name || shortId(link.source_document_id) }}</b><span v-if="link.source_row_id">Строка {{ link.source_row_id }}</span></div><div class="chain-arrow">⟶<small>{{ Math.round(link.confidence * 100) }}%</small></div><div class="link-endpoint"><small>ЦЕЛЕВОЙ ДОКУМЕНТ</small><b>{{ activeProject.documents.find((doc) => doc.document_id === link.target_document_id)?.file_name || shortId(link.target_document_id) }}</b><span v-if="link.target_row_id">Строка {{ link.target_row_id }}</span></div></div><p class="link-explanation">{{ link.explanation }}</p><div v-if="link.conflicts?.length" class="link-conflicts">Возможные расхождения: {{ link.conflicts.join(' · ') }}</div><div class="link-evidence-list"><button v-for="(evidence, index) in link.evidence" :key="index" class="evidence-chip" @click="evidenceClick(evidence)"><span>ПОДТВЕРЖДЕНИЕ {{ index + 1 }}</span><b>{{ evidence.signal }}</b><small>{{ bboxHint(evidence.source) }} ↔ {{ bboxHint(evidence.target) }}</small><i>↗</i></button></div><div v-if="isReviewable(link)" class="link-actions"><span>РЕШЕНИЕ ЭКСПЕРТА</span><div><button class="button button-reject" :disabled="busy" @click="decide(link, 'rejected')">Отклонить</button><button class="button button-confirm" :disabled="busy" @click="decide(link, 'confirmed')">Подтвердить <b>✓</b></button></div></div><div v-else-if="link.verification_status !== 'not_reviewed'" class="decision-saved">Решение сохранено · {{ link.verification_status === 'human_confirmed' ? 'подтверждено специалистом' : 'отклонено специалистом' }}</div></article><div v-if="activeProject.linking_result.warnings?.length" class="warning-list"><b>Предупреждения Linking</b><p v-for="warning in activeProject.linking_result.warnings" :key="warning">{{ warning }}</p></div><div v-if="activeProject.linking_result.unlinked_documents?.length" class="unlinked-list"><b>Без найденной связи · {{ activeProject.linking_result.unlinked_documents.length }}</b><p v-for="item in activeProject.linking_result.unlinked_documents" :key="item.document_id">{{ activeProject.documents.find((doc) => doc.document_id === item.document_id)?.file_name || shortId(item.document_id) }} · {{ item.reason }}</p></div></div></div><aside class="links-aside"><EvidencePanel v-if="activeProject" :project-id="activeProject.id" :evidence="selectedEvidence" /><div class="aside-card link-summary"><span class="eyebrow">LINKING RUN</span><div class="summary-number">{{ linkCount.toString().padStart(2, '0') }}<small>связей</small></div><p>{{ activeProject.linking_result?.analysis_summary || 'Результат анализа появится после завершения Linking.' }}</p><div class="summary-divider"></div><div class="summary-row"><span>На проверке</span><b>{{ pendingReview }}</b></div><div class="summary-row"><span>Не связано</span><b>{{ activeProject.linking_result?.unlinked_documents?.length || 0 }}</b></div><small v-if="activeProject.linking_result?.linking_run_id" class="run-id">{{ activeProject.linking_result.linking_run_id }}</small></div></aside></div>
      </section>
    </main>

    <div v-if="busy" class="busy-strip"><span class="spinner"></span>{{ busyLabel }}</div>
    <div v-if="createOpen" class="modal-backdrop" @click.self="createOpen = false"><section class="create-modal" role="dialog" aria-modal="true" aria-labelledby="create-title"><div class="modal-head"><div><span class="eyebrow">НОВАЯ ПРОВЕРКА</span><h2 id="create-title">Создать комплект</h2></div><button class="icon-button close-button" @click="createOpen = false" aria-label="Закрыть">×</button></div><label class="form-label">Название комплекта<input v-model="createName" autofocus maxlength="200" placeholder="Например, КФЗ · I квартал 2026" @keydown.enter="createProject" /></label><label class="form-label">Класс данных<select v-model="createClassification"><option value="confidential">Конфиденциальные</option><option value="synthetic">Синтетические</option><option value="public">Открытые</option><option value="anonymized">Обезличенные</option></select></label><label class="consent-card" :class="{ disabled: createClassification === 'confidential' }"><input v-model="allowExternal" type="checkbox" :disabled="createClassification === 'confidential'" /><span><b>Разрешить внешнюю модель для этого комплекта</b><small>Для Linking и выбранного режима Extraction данные отправятся в Polza AI. Можно включить только для открытых, синтетических или обезличенных документов.</small></span></label><p v-if="createClassification === 'confidential'" class="privacy-hint">Для конфиденциальных документов вызовы внешней модели заблокированы. Parser и rules Extraction работают локально.</p><div class="modal-actions"><button class="button button-quiet" @click="createOpen = false">Отмена</button><button class="button button-dark" :disabled="busy" @click="createProject">Создать комплект <span>↗</span></button></div></section></div>
  </div>
</template>
