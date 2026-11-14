<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { api } from "./api";
import VerificationPanel from "./components/VerificationPanel.vue";
import WorkflowDashboard from "./components/WorkflowDashboard.vue";
import AppIcon from "./components/AppIcon.vue";
import DocumentsList from "./components/DocumentsList.vue";
import DocumentMarkdown from "./components/DocumentMarkdown.vue";
import { documentStatusLabel } from "./documentStatus";
import BrandLogo from "./components/BrandLogo.vue";
import VerificationScopePicker from "./components/VerificationScopePicker.vue";
import DataClassificationPicker from "./components/DataClassificationPicker.vue";
import EvidencePanel from "./components/EvidencePanel.vue";
import type { DocumentResult, EvidenceSide, LinkEvidence, StageName, TraceDocument, TraceProject, TraceLink, VerificationScope } from "./types";

const projects = ref<TraceProject[]>([]);
const activeProject = ref<TraceProject | null>(null);
const activeTab = ref<"overview" | "documents" | "links" | "verification">("overview");
watch(activeTab, tab => {
  if (activeProject.value) history.replaceState(null, "", `?project=${encodeURIComponent(activeProject.value.id)}&tab=${tab}`);
});
const selectedDocument = ref<TraceDocument | null>(null);
const selectedEvidence = ref<LinkEvidence | { source: EvidenceSide; target?: EvidenceSide } | null>(null);
const documentResult = ref<DocumentResult | null>(null);
const documentLoading = ref(false);
const documentError = ref("");
const documentViewerTab = ref<'markdown' | 'data'>('markdown');
const resultSheet = ref<HTMLElement | null>(null);
let documentRequest = 0;
async function loadDocumentResult(projectId: string, documentId: string) {
  const request = ++documentRequest;
  documentLoading.value = true; documentError.value = "";
  try {
    const result = await api.result(projectId, documentId);
    if (request === documentRequest && activeProject.value?.id === projectId && selectedDocument.value?.id === documentId) documentResult.value = result;
  } catch (error) {
    if (request === documentRequest && activeProject.value?.id === projectId && selectedDocument.value?.id === documentId) documentError.value = error instanceof Error ? error.message : "Не удалось открыть документ. Повторите попытку.";
  } finally { if (request === documentRequest) documentLoading.value = false; }
}
const createOpen = ref(false);
const createName = ref("");
const createError = ref("");
const nameInput = ref<HTMLInputElement | null>(null);
const profileOpen = ref(false);
const userName = ref(localStorage.getItem("trace-profile-name") || "Артём");
watch(userName, value => {
  localStorage.setItem("trace-profile-name", value.trim());
  const userId = localStorage.getItem("trace-user-id");
  if (userId) localStorage.setItem(`trace-profile-name:${userId}`, value.trim());
});
async function signOut() {
  try {
    const response = await fetch("/api/auth/logout", { method: "POST" });
    if (!response.ok) throw new Error("Не удалось выйти. Попробуйте ещё раз.");
    localStorage.removeItem("trace-user-id");
    localStorage.removeItem("trace-profile-name");
    location.assign("/logIn");
  } catch (error) { errorText.value = error instanceof Error ? error.message : "Не удалось выйти"; }
}
let returnFocus: HTMLElement | null = null;
function goHome() {
  activeProject.value = null; selectedDocument.value = null; selectedEvidence.value = null; documentResult.value = null;
  kfzFiles.value = []; primaryFiles.value = []; clearNotices();
  history.replaceState(null, "", location.pathname);
}
function closeCreate() { if (!busy.value) createOpen.value = false; }
function modalKeys(event: KeyboardEvent) {
  if (event.key === "Escape") closeCreate();
  if (event.key !== "Tab") return;
  const nodes = Array.from((event.currentTarget as HTMLElement).querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select, summary')).filter(el => el.getClientRects().length);
  const first = nodes[0], last = nodes[nodes.length - 1];
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
}
watch(createOpen, async open => {
  if (open) { returnFocus = document.activeElement as HTMLElement; createError.value = ""; await nextTick(); nameInput.value?.focus(); }
  else returnFocus?.focus();
});
const createClassification = ref<TraceProject["data_classification"]>("confidential");
const allowExternal = ref(true);
const createScope = ref<VerificationScope>({});

const kfzFiles = ref<File[]>([]);
const primaryFiles = ref<File[]>([]);
const busy = ref(false);
const busyLabel = ref("");
const errorText = ref("");
const successText = ref("");
const projectsLoading = ref(true);
const settingsOpen = ref(false);
const settingsClass = ref<TraceProject["data_classification"]>("confidential");
const settingsConsent = ref(false);
const settingsScope = ref<VerificationScope>({});

function openSettings() { if (!activeProject.value) return; settingsClass.value = activeProject.value.data_classification === "confidential" ? "confidential" : "public"; settingsConsent.value = true; settingsScope.value = { ...activeProject.value.verification_scope }; settingsOpen.value = true; }
async function saveSettings() {
  if (!activeProject.value) return;
  clearNotices(); busy.value = true;
  try { activeProject.value = await api.updateSettings(activeProject.value.id, { data_classification: settingsClass.value, allow_external_llm: settingsConsent.value, verification_scope: settingsScope.value }); settingsOpen.value = false; selectedDocument.value = null; documentResult.value = null; selectedEvidence.value = null; successText.value = "Настройки сохранены. Запустите проверку заново, чтобы применить выбранную модель."; }
  catch (error) { errorText.value = error instanceof Error ? error.message : "Не удалось сохранить настройки"; }
  finally { busy.value = false; }
}
function friendlyError(error?: { code?: string; message?: string } | null) { return error?.code === "EXTERNAL_LLM_CONSENT_REQUIRED" ? "Для поиска связей нужна внешняя модель. Откройте настройки, выберите вариант данных и сохраните его, чтобы разрешить обработку через сторонний API." : error?.message || ""; }

let pollTimer: number | undefined;

const activeIsRunning = computed(() => Boolean(activeProject.value && (activeProject.value.status === "running" || Object.values(activeProject.value.stages).some((stage) => ["queued", "running"].includes(stage.status)))));
const pendingReview = computed(() => activeProject.value?.linking_result?.links.filter((link) => link.status !== "rejected" && link.verification_status === "not_reviewed").length ?? 0);
const linkCount = computed(() => activeProject.value?.linking_result?.links.length ?? 0);
const canProcess = computed(() => Boolean(activeProject.value?.documents.some((doc) => doc.role === "kfz") && activeProject.value?.documents.some((doc) => doc.role === "primary")));

function clearNotices() { errorText.value = ""; successText.value = ""; }
function formatDate(value: string) { try { return new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)); } catch { return value; } }
function statusLabel(value: string) { return ({ draft: "Черновик", running: "Обрабатывается", completed: "Обработан", partial: "Есть ошибки", failed: "Ошибка" } as Record<string, string>)[value] || value; }
function docTypeLabel(value?: string | null) { return ({ kfz_report: "Отчёт КФЗ", contract: "Договор", act: "Акт", invoice: "Счёт", addendum: "Доп. соглашение", registry: "Реестр", unknown: "Тип не определён" } as Record<string, string>)[value || ""] || "Ожидает разбора"; }
function stageTitle(stage: StageName) { return ({ parser: "Распознавание", extraction: "Извлечение данных", linking: "Поиск пар", reconciliation: "Расчёт", verification: "Сверка" })[stage]; }
function stageStatusLabel(value?: string) { return ({ queued: "В очереди", running: "В работе", completed: "Готово", failed: "Ошибка", blocked: "Нужно разрешение", pending: "Ожидает" } as Record<string, string>)[value || ""] || value || "Ожидает"; }
function shortId(value: string) { return value.slice(0, 8).toUpperCase(); }
function fileKind(name: string) { return name.split(".").pop()?.toUpperCase() || "FILE"; }
async function setFiles(event: Event, target: "kfz" | "primary") {
  const input = event.target as HTMLInputElement;
  const files = Array.from(input.files || []);
  if (!files.length || busy.value || activeIsRunning.value) return;
  if (target === "kfz") kfzFiles.value = files.slice(0, 1); else primaryFiles.value = files;
  await uploadRole(target);
  input.value = "";
}

async function refreshProjects(keepSelection = true) {
  try {
    const response = await api.listProjects(); projects.value = response.projects;
    const target = keepSelection ? activeProject.value?.id : null;
    if (target && response.projects.some((project) => project.id === target)) await refreshActive(target);

  } catch (error) { errorText.value = error instanceof Error ? error.message : "Не удалось загрузить проекты"; }
}
async function refreshActive(id: string) {
  try { const project = await api.getProject(id); if (activeProject.value?.id === id) { activeProject.value = project; const updated = project.documents.find(d => d.id === selectedDocument.value?.id); if (updated) { const changed = updated.extraction_id !== selectedDocument.value?.extraction_id || updated.has_parser_result !== selectedDocument.value?.has_parser_result; selectedDocument.value = updated; if (changed) { if (updated.has_parser_result) await loadDocumentResult(id, updated.id); else { ++documentRequest; documentResult.value = null; documentLoading.value = false; documentError.value = ""; } } } } }
  catch (error) { errorText.value = error instanceof Error ? error.message : "Не удалось загрузить комплект"; }
}
async function selectProject(project: TraceProject) { clearNotices(); activeProject.value = project; selectedDocument.value = null; documentResult.value = null; selectedEvidence.value = null; activeTab.value = "overview"; kfzFiles.value = []; primaryFiles.value = []; history.replaceState(null, "", `?project=${encodeURIComponent(project.id)}`); await refreshActive(project.id); }
async function createProject() {
  if (busy.value) return;
  clearNotices(); createError.value = "";
  if (!createName.value.trim()) { createError.value = "Укажите название проекта"; nameInput.value?.focus(); return; }
  busy.value = true; busyLabel.value = "Создаём комплект…";
  try {
    const project = await api.createProject({ name: createName.value.trim(), data_classification: createClassification.value, allow_external_llm: allowExternal.value, verification_scope: createScope.value });
    activeProject.value = project; activeTab.value = "overview"; selectedDocument.value = null; selectedEvidence.value = null; documentResult.value = null; history.replaceState(null, "", `?project=${encodeURIComponent(project.id)}`); projects.value = [project, ...projects.value]; createOpen.value = false; createName.value = ""; kfzFiles.value = []; primaryFiles.value = [];
    successText.value = "Проект создан. Добавьте отчёт и документы для сравнения — подскажем каждый шаг.";
  } catch (error) { createError.value = error instanceof Error ? error.message : "Не удалось создать проект"; }
  finally { busy.value = false; busyLabel.value = ""; }
}
async function uploadRole(role: "kfz" | "primary") {
  if (!activeProject.value || busy.value || activeIsRunning.value) return;
  const files = role === "kfz" ? kfzFiles.value : primaryFiles.value;
  if (!files.length) { errorText.value = role === "kfz" ? "Выбрать отчёт КФЗ" : "Выбрать договоры, акты или счета"; return; }
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
  clearNotices(); busy.value = true; busyLabel.value = `Повторяем этап «${stageTitle(stage)}»…`;
  try { await api.retry(activeProject.value.id, stage); await refreshActive(activeProject.value.id); successText.value = `Этап «${stageTitle(stage)}» запущен повторно. Предыдущие успешные результаты сохранены.`; }
  catch (error) { errorText.value = error instanceof Error ? error.message : "Не удалось повторить этап"; }
  finally { busy.value = false; busyLabel.value = ""; }
}
async function openDocument(doc: TraceDocument) {
  ++documentRequest;
  selectedDocument.value = doc; activeTab.value = "documents"; selectedEvidence.value = null; documentResult.value = null;
  documentViewerTab.value = 'markdown'; documentError.value = ""; documentLoading.value = false;
  const projectId = activeProject.value?.id;
  if (projectId && doc.has_parser_result) void loadDocumentResult(projectId, doc.id);
  await nextTick();
  if (selectedDocument.value?.id === doc.id) resultSheet.value?.scrollIntoView({ block: 'start' });
}
function selectField(field: any, path: string, doc: TraceDocument) {
  const extracted = field?.extracted ?? field;
  const provenance = extracted?.provenance;
  if (!provenance || !activeProject.value) return;
  const normalizedValue = extracted.value == null ? "" : typeof extracted.value === "string" ? extracted.value : JSON.stringify(extracted.value);
  selectedEvidence.value = { source: { document_id: provenance.document_id || doc.document_id, path, raw_value: extracted.source_value, normalized_value: normalizedValue, provenance } };
}
function evidenceClick(evidence: LinkEvidence) { selectedEvidence.value = evidence; }
async function decide(link: TraceLink, status: "confirmed" | "rejected") {
  if (!activeProject.value) return;
  clearNotices(); busy.value = true; busyLabel.value = status === "confirmed" ? "Подтверждаем связь…" : "Отклоняем связь…";
  try { const result = await api.decide(activeProject.value.id, link.link_id, status); activeProject.value.linking_result = result.linking_result; await refreshActive(activeProject.value.id); successText.value = status === "confirmed" ? "Связь подтверждена и сохранена." : "Связь отклонена и сохранена."; }
  catch (error) { errorText.value = error instanceof Error ? error.message : "Решение не сохранено"; }
  finally { busy.value = false; busyLabel.value = ""; }
}
function primitiveFields(extraction: Record<string, any>) { return Object.entries(extraction.fields || {}).filter(([, value]) => value && typeof value === "object"); }
function parserParts(result: DocumentResult | null) { return (result?.parser_result?.visual_layout?.parts || result?.parser_result?.parts || []).slice(0, 32); }
function fieldValue(value: any) { return value?.value == null ? "—" : typeof value.value === "string" ? value.value : JSON.stringify(value.value); }
function bboxHint(side?: EvidenceSide) { const p = side?.provenance; if (!p) return ""; if (p.sheet_name || p.cell_address) return `${p.sheet_name || "Лист"}${p.cell_address ? `!${p.cell_address}` : ""}`; if (p.page_no) return `стр. ${p.page_no}`; return "Фрагмент"; }
function isReviewable(link: TraceLink) { return link.status !== "rejected" && link.verification_status === "not_reviewed"; }
function linkStatus(link: TraceLink) { return link.verification_status === "human_confirmed" ? "Подтверждена" : link.verification_status === "human_rejected" ? "Отклонена" : link.status === "review" ? "На проверке" : link.status === "proposed" ? "Предложена" : link.status; }
function classificationLabel(value: string) { return ({ confidential: "Конфиденциальные", synthetic: "Неконфиденциальные", public: "Неконфиденциальные", anonymized: "Неконфиденциальные" } as Record<string, string>)[value] || value; }

onMounted(async () => {
  await refreshProjects(false); projectsLoading.value = false;
  const requestedTab = new URLSearchParams(window.location.search).get("tab");
  const requestedProject = new URLSearchParams(window.location.search).get("project");
  if (requestedProject && projects.value.some((project) => project.id === requestedProject)) {
    const requested = projects.value.find(p => p.id === requestedProject);
    if (requested) await selectProject(requested);
    if (["verification", "documents", "links"].includes(requestedTab || "")) activeTab.value = requestedTab as "verification" | "documents" | "links";
  }
  pollTimer = window.setInterval(async () => {
    if (activeProject.value && activeIsRunning.value) { await refreshActive(activeProject.value.id); await refreshProjects(false); }
  }, 2500);
});
onUnmounted(() => { if (pollTimer) window.clearInterval(pollTimer); });
</script>

<template>
  <div class="app-shell" :class="{ 'home-shell': !activeProject, 'report-shell': activeProject && activeTab === 'verification' }">
    <a class="skip-link" href="#main-content">Перейти к содержимому</a>
    <aside v-if="activeProject" class="sidebar" :inert="createOpen">
      <a class="brand" href="/" aria-label="Phystech Trace — главная"><BrandLogo /></a>
      <button class="back-projects" @click="goHome"><AppIcon name="back" />Все проекты</button>
      <div class="sidebar-project-name">{{ activeProject.name }}</div>
      <nav aria-label="Разделы проекта" class="project-navigation">
        <button v-for="tab in ([{ id: 'overview', title: 'По шагам', icon: 'grid' }, { id: 'documents', title: 'Документы', icon: 'file' }, { id: 'links', title: 'Пары документов', icon: 'link' }, { id: 'verification', title: 'Результаты сверки', icon: 'result' }] as const)" :key="tab.id" class="nav-item" :class="{ active: activeTab === tab.id }" :aria-current="activeTab === tab.id ? 'page' : undefined" @click="activeTab = tab.id"><AppIcon :name="tab.icon" /><span>{{ tab.title }}</span><span v-if="tab.id === 'documents'" class="nav-count">{{ activeProject.documents.length }}</span><span v-if="tab.id === 'links' && pendingReview" class="nav-count">{{ pendingReview }}</span></button>
      </nav>
      <div class="sidebar-bottom"><div class="sidebar-tip"><AppIcon name="file" /><b>Всё в одном проекте</b><p>Документы, связи и результаты сохраняются автоматически.</p></div><button class="profile-button" @click="profileOpen = !profileOpen" :aria-expanded="profileOpen"><span class="avatar">{{ userName.slice(0, 1) || 'Я' }}</span><span>{{ userName || 'Мой профиль' }}<small>Личный кабинет</small></span></button></div>
    </aside>

    <main id="main-content" class="main-area" :inert="createOpen">
      <header class="topbar"><a v-if="!activeProject" class="home-brand" href="/" aria-label="Phystech Trace — главная"><BrandLogo /></a><div v-else class="breadcrumbs"><button @click="goHome">Мои проекты</button><i>/</i><b>{{ activeProject.name }}</b></div><button class="profile-button top-profile" @click="profileOpen = !profileOpen" :aria-expanded="profileOpen" aria-label="Настроить имя профиля"><span class="avatar">{{ userName.slice(0, 1) || 'Я' }}</span></button></header>
      <div v-if="profileOpen" class="profile-editor"><label class="form-label">Ваше имя<input v-model="userName" maxlength="60" @keydown.enter="profileOpen = false" /></label><button class="button button-outline" @click="profileOpen = false">Готово</button><button class="button button-outline" @click="signOut">Выйти</button></div>

      <div v-if="errorText" class="notice notice-error" role="alert"><span>!</span><div>{{ errorText }}</div><button @click="errorText = ''" aria-label="Закрыть">×</button></div>
      <div v-if="successText" class="notice notice-success" role="status"><span>✓</span><div>{{ successText }}</div><button @click="successText = ''" aria-label="Закрыть">×</button></div>

      <section v-if="!activeProject" class="projects-home">
        <h1>Здравствуйте{{ userName.trim() ? `, ${userName.trim()}` : '' }}<span>.</span></h1>
        <div class="home-section-title"><h2>Мои проекты</h2><span>{{ projects.length }}</span></div>
        <div v-if="projectsLoading" class="projects-loading" role="status">Загружаем ваши проекты…</div>
        <div v-else class="project-grid">
          <button class="project-tile create-project-tile" @click="createOpen = true"><div class="project-cover create-cover"><span class="create-plus"><AppIcon name="plus" /></span></div><div class="project-tile-caption"><b>Новый проект</b><small>Начать проверку документов</small></div></button>
          <button v-for="(project, index) in projects" :key="project.id" class="project-tile" @click="selectProject(project)"><div class="project-cover" :class="`cover-tone-${index % 3}`"><div class="cover-document"><AppIcon name="file" /><i></i><i></i><i></i></div><span class="cover-number">{{ String(index + 1).padStart(2, '0') }}</span><span class="cover-status" :class="project.status">{{ statusLabel(project.status) }}</span></div><div class="project-tile-caption"><b>{{ project.name }}</b><small>{{ formatDate(project.updated_at) }}</small></div></button>
        </div>
      </section>

      <section v-else class="project-view">
        <div class="project-heading"><div><div class="eyebrow">КОМПЛЕКТ · {{ shortId(activeProject.id) }} <span class="heading-dot">•</span> {{ classificationLabel(activeProject.data_classification) }}</div><h1>{{ activeProject.name }}</h1><div class="project-meta"><span>Создан {{ formatDate(activeProject.created_at) }}</span><i>·</i><span>{{ activeProject.documents.length }} {{ activeProject.documents.length === 1 ? "документ" : "документов" }}</span><span class="overall-status" :class="activeProject.status"><i></i>{{ statusLabel(activeProject.status) }}</span><span>Модель: {{ activeProject.data_classification === "confidential" ? "Gemma 26B · локально" : "DeepSeek V4.1 Flash · сторонний API" }}</span><button class="text-button" :disabled="busy || activeIsRunning" @click="openSettings">Настройки данных</button></div></div><div v-if="activeTab === 'documents'" class="heading-actions"><button v-if="activeProject.status === 'draft' || activeProject.status === 'partial'" class="button button-dark" :disabled="busy || !canProcess" @click="startProcess">{{ activeProject.status === 'partial' ? 'Продолжить проверку' : 'Проверить документы' }} <span>↗</span></button><span v-else-if="activeIsRunning" class="running-caption"><i class="spinner"></i>Обработка комплекта</span></div></div>

        <WorkflowDashboard v-if="activeTab === 'overview'" :project="activeProject" :busy="busy" @settings="openSettings" @navigate="activeTab = $event" @process="startProcess" @retry="retryStage" />

        <div v-else-if="activeTab === 'documents'" class="documents-layout" :class="{ 'documents-without-evidence': !selectedEvidence }"><div class="documents-main"><details class="documents-upload" :open="!canProcess"><summary>Добавить документы<span>Отчёт КФЗ, договоры, акты и счета</span></summary><section class="upload-panel"><div class="section-heading"><div><span class="eyebrow">ШАГ 1 ИЗ 4 · ДОКУМЕНТЫ</span><h2>Какие документы проверяем?</h2><p>Выберите отчёт, затем договоры, акты или счета. Файлы загрузятся сразу после выбора.</p></div><span class="upload-lock">ДО 25 МБ НА ФАЙЛ</span></div>
              <div class="upload-columns"><div class="upload-card"><div class="upload-card-head"><span class="file-icon kfz">K</span><div><b>Отчёт КФЗ</b><small>Отчёт, данные которого нужно проверить</small></div><span class="required-tag">ОБЯЗАТЕЛЬНО</span></div><label class="dropzone"><input type="file" :disabled="busy || activeIsRunning" accept=".pdf,.xlsx,.xls,.csv,.docx,.png,.jpg,.jpeg,.webp,.txt" @change="setFiles($event, 'kfz')" /><span class="drop-icon">↑</span><b>Выбрать отчёт КФЗ</b><small>PDF, XLSX, DOCX или изображение · до 25 МБ</small></label><div v-if="kfzFiles.length" class="selected-files"><span>{{ kfzFiles[0].name }}</span><button aria-label="Убрать выбранный отчёт" :disabled="busy" @click="kfzFiles = []">×</button></div><div v-if="!kfzFiles.length" class="upload-doc-list"><div v-for="doc in activeProject.documents.filter((item) => item.role === 'kfz')" :key="doc.id" class="existing-file"><span class="file-type">{{ fileKind(doc.file_name) }}</span><span>{{ doc.file_name }}</span><i class="done-mark">✓</i></div></div><button v-if="kfzFiles.length" class="button button-outline upload-submit" :disabled="busy" @click="uploadRole('kfz')">Загрузить КФЗ <span>↑</span></button></div>
                <div class="upload-card"><div class="upload-card-head"><span class="file-icon primary">P</span><div><b>Документы для сравнения</b><small>Договоры, акты, счета, реестры</small></div><span class="optional-tag">{{ activeProject.documents.filter((item) => item.role === 'primary').length }} ФАЙЛОВ</span></div><label class="dropzone"><input type="file" multiple :disabled="busy || activeIsRunning" accept=".pdf,.xlsx,.xls,.csv,.docx,.png,.jpg,.jpeg,.webp,.txt" @change="setFiles($event, 'primary')" /><span class="drop-icon">↑</span><b>Выбрать договоры, акты или счета</b><small>Можно загрузить несколько файлов · до 25 МБ каждый</small></label><div v-if="primaryFiles.length" class="selected-files"><span>{{ primaryFiles.length }} файлов · {{ primaryFiles.map((file) => file.name).join(', ') }}</span><button aria-label="Убрать выбранные документы" :disabled="busy" @click="primaryFiles = []">×</button></div><div v-if="!primaryFiles.length" class="upload-doc-list">{{ activeProject.documents.filter((item) => item.role === 'primary').length ? 'Первичные документы уже загружены.' : 'Файлы появятся здесь после загрузки.' }}</div><button v-if="primaryFiles.length" class="button button-outline upload-submit" :disabled="busy" @click="uploadRole('primary')">Загрузить {{ primaryFiles.length }} {{ primaryFiles.length === 1 ? 'файл' : 'файла' }} <span>↑</span></button></div></div>
              <div class="upload-footer"><span><i></i> {{ activeIsRunning ? 'Проверка идёт. Можно следить за ней в разделе «По шагам».' : canProcess ? 'Всё готово. Теперь можно запустить проверку.' : !activeProject.documents.some(d => d.role === 'kfz') ? 'Сначала выберите отчёт КФЗ в поле слева.' : 'Отчёт загружен. Добавьте хотя бы один документ для сравнения.' }}</span><button v-if="canProcess" class="text-button" :disabled="busy || activeIsRunning" @click="startProcess">Проверить документы <b>→</b></button></div>
            </section></details><div class="section-heading"><div><span class="eyebrow">ЗАГРУЖЕННЫЕ ФАЙЛЫ</span><h2>Результаты по документам</h2><p>Состояние каждого файла обновляется автоматически. Нажмите на документ, чтобы открыть его распознанную Markdown-версию.</p></div></div><div v-if="!activeProject.documents.length" class="empty-state"><span>▤</span><b>Пока нет документов</b><p>Загрузите отчёт КФЗ и первичные файлы с помощью полей выше.</p></div><DocumentsList v-else :documents="activeProject.documents" :selected-id="selectedDocument?.id" :extraction-stage="activeProject.stages.extraction" @open="openDocument" />
            <div v-if="selectedDocument" ref="resultSheet" class="result-sheet document-viewer"><div class="result-sheet-head"><div><span class="eyebrow">{{ selectedDocument.role === 'kfz' ? 'ОТЧЁТ КФЗ' : 'ПЕРВИЧНЫЙ ДОКУМЕНТ' }} · {{ fileKind(selectedDocument.file_name) }}</span><h3>{{ selectedDocument.file_name }}</h3></div><a :href="`/api/projects/${activeProject.id}/sources/${selectedDocument.document_id}`" target="_blank" rel="noreferrer" class="button button-outline">Открыть файл ↗</a></div><p class="document-viewer-status">{{ documentStatusLabel(selectedDocument, activeProject.stages.extraction) }}</p><div class="document-viewer-tabs" role="group" aria-label="Содержимое документа"><button :aria-pressed="documentViewerTab === 'markdown'" @click="documentViewerTab = 'markdown'">Распознанный документ · MD</button><button :aria-pressed="documentViewerTab === 'data'" @click="documentViewerTab = 'data'">Найденные данные</button></div><div v-if="documentLoading" class="empty-state compact-empty" role="status"><span class="spinner dark-spinner"></span><b>Открываем распознанный документ…</b></div><div v-else-if="documentError" class="notice notice-error" role="alert"><div>{{ documentError }}</div><button class="button button-outline" @click="loadDocumentResult(activeProject.id, selectedDocument.id)">Попробовать снова</button></div><DocumentMarkdown v-else-if="documentViewerTab === 'markdown' && documentResult?.parser_result" :key="selectedDocument.id" :parser="documentResult.parser_result" :file-name="selectedDocument.file_name" /><div v-else-if="documentResult?.extraction" class="extraction-result"><div class="extraction-summary"><span class="classification-pill">{{ docTypeLabel(documentResult.extraction.document_type) }}</span><span>Схема {{ documentResult.extraction.schema_version }}</span><span>{{ documentResult.extraction.extraction_engine?.parser_adapter }}</span><span class="review-count">{{ documentResult.extraction.review_required?.length || 0 }} требуют проверки</span></div><div v-if="primitiveFields(documentResult.extraction).length" class="field-grid"><button v-for="[key, value] in primitiveFields(documentResult.extraction)" :key="key" class="field-card" :class="`field-${(value as any).status}`" @click="selectField(value, `fields.${key}`, selectedDocument!)"><span>{{ (value as any).label || key.replaceAll('_', ' ') }}</span><b>{{ fieldValue(value) }}</b><small>{{ bboxHint({ document_id: selectedDocument!.document_id, provenance: (value as any).provenance }) || 'Источник не определён' }}</small></button></div><div v-for="table in documentResult.extraction.tables || []" :key="table.id" class="extraction-table-wrap"><div class="table-caption"><b>{{ table.title || table.role || 'Таблица' }}</b><span>{{ table.rows?.length || 0 }} строк</span></div><table class="data-table"><thead><tr><th>Строка</th><th>Показатель</th><th>Значение</th><th>Источник</th></tr></thead><tbody><template v-for="row in table.rows || []" :key="row.row_id"><tr v-for="field in ['identifier','description','unit','quantity','actual_quantity','amount']" :key="`${row.row_id}-${field}`" v-show="(row as any)[field]?.value != null"><td>{{ row.row_id }}</td><td>{{ field }}</td><td>{{ fieldValue((row as any)[field]) }}</td><td><button class="locator-button" @click="selectField((row as any)[field], `tables.${table.id}.rows.${row.row_id}.${field}`, selectedDocument!)">{{ bboxHint({ document_id: selectedDocument!.document_id, provenance: (row as any)[field]?.provenance }) || 'Открыть источник ↗' }}</button></td></tr></template></tbody></table></div><details class="parser-parts"><summary>Результат распознавания · {{ documentResult.parser_result?.parts?.length || 0 }} элементов</summary><div v-for="(part, index) in parserParts(documentResult)" :key="index" class="parser-part"><span>{{ part.kind }}</span><b>{{ part.text || part.value || part.display_value || part.caption || 'Структурный фрагмент' }}</b><small>{{ part.page_no ? `стр. ${part.page_no}` : part.sheet_name ? `${part.sheet_name}!${part.coordinate || part.address || ''}` : '' }}</small></div><p v-if="(documentResult.parser_result?.parts?.length || 0) > 32" class="muted">Показаны первые 32 фрагмента; полный JSON сохранён в Parser.</p></details><details class="parser-parts"><summary>Полные извлечённые данные</summary><pre class="result-json">{{ JSON.stringify(documentResult.extraction, null, 2) }}</pre></details></div><div v-else class="empty-state compact-empty"><b>{{ selectedDocument.parser_error ? 'Не удалось распознать файл' : documentViewerTab === 'data' && selectedDocument.has_parser_result ? 'Данные ещё не извлечены' : 'Распознанный текст ещё не готов' }}</b><p>{{ selectedDocument.parser_error ? 'Обработка остановилась на распознавании. Откройте оригинал или повторите этап.' : selectedDocument.extraction_error ? 'Текст уже распознан, но извлечение данных завершилось ошибкой. Markdown доступен на соседней вкладке.' : activeIsRunning ? 'Документ обрабатывается. Результат появится здесь автоматически — обновлять страницу не нужно.' : 'Запустите проверку документов. После распознавания здесь появится Markdown-версия.' }}</p><button v-if="!activeIsRunning && !busy && (selectedDocument.parser_error || selectedDocument.extraction_error)" class="button button-outline" @click="retryStage(selectedDocument.parser_error ? 'parser' : 'extraction')">Повторить {{ selectedDocument.parser_error ? 'распознавание' : 'извлечение данных' }}</button><button v-else-if="!activeIsRunning && !selectedDocument.has_parser_result && canProcess" class="button button-dark" :disabled="busy" @click="startProcess">Проверить документы</button></div><details v-if="selectedDocument.parser_error || selectedDocument.extraction_error" class="document-error-details"><summary>Подробности ошибки</summary><pre>{{ selectedDocument.parser_error?.message || selectedDocument.extraction_error?.message }}</pre></details></div>
          </div><aside v-if="selectedEvidence" class="documents-aside"><EvidencePanel v-if="activeProject" :project-id="activeProject.id" :evidence="selectedEvidence" /><div class="aside-card source-legend"><span class="eyebrow">PROVENANCE</span><h3>Откуда взялось значение</h3><p><b>PDF</b> · номер страницы, bbox и система координат.</p><p><b>XLSX</b> · имя листа и точный адрес ячейки.</p><p><b>DOCX</b> · исходный элемент и текст подтверждения.</p></div></aside></div>

        <VerificationPanel v-else-if="activeTab === 'verification'" :project="activeProject" :busy="busy" @retry="retryStage" @decision="activeProject.report_decision = $event" />
        <div v-else class="links-layout"><div class="links-main"><div class="section-heading"><div><span class="eyebrow">ШАГ 3 ИЗ 4 · ВАШЕ РЕШЕНИЕ</span><h2>Какие документы относятся друг к другу? <span v-if="linkCount" class="heading-count">{{ linkCount }}</span></h2><p>Программа нашла возможные пары документов. Откройте подтверждающие фрагменты и сравните данные. Подтвердите пару, если документы относятся друг к другу, или отклоните, если нет.</p></div></div><div v-if="!activeProject.linking_result" class="empty-state linking-empty"><span>↗</span><b>Связи ещё не готовы</b><p>{{ friendlyError(activeProject.stages.linking?.error) || (activeProject.stages.linking?.status === 'running' ? 'Программа ищет пары документов. Дождитесь завершения — страница обновится автоматически.' : 'Откройте раздел «По шагам» — там показано, что нужно сделать дальше.') }}</p><button v-if="activeProject.stages.linking?.error?.code === 'EXTERNAL_LLM_CONSENT_REQUIRED'" class="button button-outline" @click="openSettings">Открыть настройки</button><button v-else-if="['failed','blocked'].includes(activeProject.stages.linking?.status)" class="button button-outline" @click="retryStage('linking')">Повторить поиск пар <span>↻</span></button></div><div v-else><div v-if="!pendingReview" class="next-action"><div><b>Все предложения просмотрены</b><p>Теперь посмотрите совпадения и расхождения в результатах сверки.</p></div><button class="button button-dark" @click="activeTab = 'verification'">Посмотреть результаты <AppIcon name="arrow" /></button></div><div v-if="pendingReview" class="review-banner"><span>!</span><div><b>{{ pendingReview }} {{ pendingReview === 1 ? 'связь ожидает' : 'связи ожидают' }} решения</b><small>Нажмите «Посмотреть фрагменты» под предложением, сравните документы и выберите решение.</small></div></div><div v-if="!activeProject.linking_result.links.length" class="empty-state compact-empty"><span>⌁</span><b>Связи не найдены</b><p>{{ activeProject.linking_result.analysis_summary || 'Для этого комплекта нет подтверждённых связей.' }}</p></div><article v-for="link in activeProject.linking_result.links" :key="link.link_id" class="link-card" :class="{ 'link-awaiting': isReviewable(link) }"><div class="link-card-top"><span class="link-kind"><i>⌁</i>{{ link.relationship_type.replaceAll('_', ' ') }}</span><span class="link-state" :class="link.status">{{ linkStatus(link) }}</span></div><div class="link-chain"><div class="link-endpoint"><small>ИСТОЧНИК</small><b>{{ activeProject.documents.find((doc) => doc.document_id === link.source_document_id)?.file_name || shortId(link.source_document_id) }}</b><span v-if="link.source_row_id">Строка {{ link.source_row_id }}</span></div><div class="chain-arrow">⟶<small>{{ Math.round(link.confidence * 100) }}%</small></div><div class="link-endpoint"><small>ЦЕЛЕВОЙ ДОКУМЕНТ</small><b>{{ activeProject.documents.find((doc) => doc.document_id === link.target_document_id)?.file_name || shortId(link.target_document_id) }}</b><span v-if="link.target_row_id">Строка {{ link.target_row_id }}</span></div></div><p class="link-explanation">{{ link.explanation }}</p><div v-if="link.conflicts?.length" class="link-conflicts">Возможные расхождения: {{ link.conflicts.join(' · ') }}</div><div class="link-evidence-list"><button v-for="(evidence, index) in link.evidence" :key="index" class="evidence-chip" @click="evidenceClick(evidence)"><span>Посмотреть фрагменты · {{ index + 1 }}</span><b>{{ evidence.signal }}</b><small>{{ bboxHint(evidence.source) }} ↔ {{ bboxHint(evidence.target) }}</small><i>↗</i></button></div><div v-if="isReviewable(link)" class="link-actions"><span>ЭТИ ДОКУМЕНТЫ ОТНОСЯТСЯ ДРУГ К ДРУГУ?</span><div><button class="button button-reject" :disabled="busy" @click="decide(link, 'rejected')">Нет, отклонить</button><button class="button button-confirm" :disabled="busy" @click="decide(link, 'confirmed')">Да, подтвердить <b>✓</b></button></div></div><div v-else-if="link.verification_status !== 'not_reviewed'" class="decision-saved">Решение сохранено · {{ link.verification_status === 'human_confirmed' ? 'подтверждено специалистом' : 'отклонено специалистом' }}</div></article><div v-if="activeProject.linking_result.warnings?.length" class="warning-list"><b>Замечания к найденным парам</b><p v-for="warning in activeProject.linking_result.warnings" :key="warning">{{ warning }}</p></div><div v-if="activeProject.linking_result.unlinked_documents?.length" class="unlinked-list"><b>Без найденной связи · {{ activeProject.linking_result.unlinked_documents.length }}</b><p v-for="item in activeProject.linking_result.unlinked_documents" :key="item.document_id">{{ activeProject.documents.find((doc) => doc.document_id === item.document_id)?.file_name || shortId(item.document_id) }} · {{ item.reason }}</p></div></div></div><aside class="links-aside"><EvidencePanel v-if="activeProject" :project-id="activeProject.id" :evidence="selectedEvidence" /><div class="aside-card link-summary"><span class="eyebrow">НАЙДЕННЫЕ ПАРЫ</span><div class="summary-number">{{ linkCount.toString().padStart(2, '0') }}<small>связей</small></div><p>{{ activeProject.linking_result?.analysis_summary || 'Предложения появятся после автоматической проверки документов.' }}</p><div class="summary-divider"></div><div class="summary-row"><span>На проверке</span><b>{{ pendingReview }}</b></div><div class="summary-row"><span>Не связано</span><b>{{ activeProject.linking_result?.unlinked_documents?.length || 0 }}</b></div><small v-if="activeProject.linking_result?.linking_run_id" class="run-id">{{ activeProject.linking_result.linking_run_id }}</small></div></aside></div>
      </section>
    </main>

    <div v-if="settingsOpen && activeProject" class="modal-backdrop" @click.self="settingsOpen = false" @keydown.esc="settingsOpen = false"><section class="create-modal project-setup-modal" role="dialog" aria-modal="true" aria-labelledby="settings-title"><div class="modal-head"><h2 id="settings-title">Настройки обработки</h2><button class="icon-button close-button" aria-label="Закрыть" @click="settingsOpen = false">×</button></div><DataClassificationPicker v-model="settingsClass" v-model:consent="settingsConsent" :disabled="busy || activeIsRunning" /><VerificationScopePicker v-model="settingsScope" :disabled="busy || activeIsRunning" /><div class="modal-actions"><button class="button button-quiet" @click="settingsOpen = false">Отмена</button><button class="button button-dark" :disabled="busy || activeIsRunning" @click="saveSettings">Сохранить</button></div></section></div>
    <div v-if="busy" class="busy-strip"><span class="spinner"></span>{{ busyLabel }}</div>
    <div v-if="createOpen" class="modal-backdrop" @click.self="closeCreate" @keydown="modalKeys"><section class="create-modal project-setup-modal" role="dialog" aria-modal="true" aria-labelledby="create-title"><div class="modal-head"><div><span class="eyebrow">НОВЫЙ ПРОЕКТ</span><h2 id="create-title">Создать проект</h2></div><button class="icon-button close-button" @click="closeCreate" aria-label="Закрыть">×</button></div><label class="form-label">Название проекта<input ref="nameInput" v-model="createName" :aria-invalid="!!createError" :aria-describedby="createError ? 'create-error' : undefined" maxlength="200" placeholder="Например, КФЗ · I квартал 2026" @keydown.enter="createProject" /></label><p v-if="createError" id="create-error" class="create-error" role="alert">{{ createError }}</p><DataClassificationPicker v-model="createClassification" v-model:consent="allowExternal" :disabled="busy" /><VerificationScopePicker v-model="createScope" :disabled="busy" /><div class="modal-actions"><button class="button button-quiet" @click="closeCreate">Отмена</button><button class="button button-dark" :disabled="busy" @click="createProject">Создать проект <span>↗</span></button></div></section></div>
  </div>
</template>
