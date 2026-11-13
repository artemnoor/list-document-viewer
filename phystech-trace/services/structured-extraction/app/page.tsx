"use client";

import {
  AlertCircle, AlertTriangle, ArrowDownToLine, ArrowLeftRight, Check, CheckCircle2, ChevronDown, ChevronRight,
  CircleHelp, Clipboard, Clock3, Code2, Database, Download, FileJson2, FileSpreadsheet, FileText,
  FolderOpen, Hash, Menu, PanelRightOpen, RefreshCw, Search, ShieldCheck, Table2, Upload, X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

type DocumentSummary = {
  id: string; title: string; file_name: string; format: string; is_demo: boolean;
  page_count: number | null; is_synthetic?: boolean; input_version?: number; latest_run_status?: string | null; latest_extraction: { id: string; version: number; document_type: string; created_at: string; mode?: string } | null;
};
type Provenance = {
  document_id: string; source_part_id?: string; source_ref?: string; page_no?: number | null;
  sheet_name?: string | null; cell_address?: string | null; bbox?: { l: number; t: number; r: number; b: number; coord_origin?: string } | null;
  coordinate_origin?: string | null; page_size?: { width: number; height: number; unit: string } | null;
  table_id?: string; row_id?: string; column_index?: number; source_text: string; confidence?: number | null;
};
type ExtractedValue = { label?: string; value: any; source_value: string | null; status: "extracted" | "review" | "missing"; confidence: number | null; provenance: Provenance | null; normalization_note?: string | null; source_method?: string; conflict?: any };
type ParserTable = { id: string; caption: string; role: string; headers: string[]; page_no?: number | null; rows: Array<{ row_id: string; page_no?: number | null; sheet_name?: string | null; cells: Array<{ id?: string; column: number; text: string; address?: string; bbox?: Provenance["bbox"]; provenance?: Provenance | null }> }> };
type DocumentData = { id: string; title: string; file_name: string; format: string; is_demo: boolean; is_synthetic?: boolean; input_version: number; parser_json: any; parser_view?: any; latest_extraction: any; extraction_version: number; latest_run_status?: string | null; latest_run_error?: any };

const typeLabels: Record<string, string> = { kfz_report: "Отчёт КФЗ", contract: "Договор", act: "Акт", invoice: "Счёт", addendum: "Доп. соглашение", registry: "Реестр" };
const demoTypes: Record<string, string> = { "kfz-2026-q1": "kfz_report", "contract-2026-0315": "contract", "act-2026-0424": "act", "invoice-2026-0408": "invoice", "addendum-2026-04": "addendum", "registry-2026-04": "registry" };
const demoOrder = ["kfz-2026-q1", "contract-2026-0315", "act-2026-0424", "invoice-2026-0408", "addendum-2026-04", "registry-2026-04"];
const unitLabels: Record<string, string> = { piece: "шт.", set: "компл.", person_hour: "чел.-ч", cubic_meter: "м³", meter: "м", kilogram: "кг", tonne: "т", object: "объект", point: "точка", shift: "смена", trip: "рейс", line: "линия" };

function dateDisplay(value: string) {
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  return match ? `${match[3]}.${match[2]}.${match[1]}` : value;
}

function decimalDisplay(value: string) {
  const negative = value.startsWith("-");
  const [whole = "0", fraction] = value.replace(/^-/, "").split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  return `${negative ? "−" : ""}${grouped}${fraction ? `,${fraction}` : ""}`;
}

function formatValue(value: any) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string") {
    if (/^20\d{2}-\d{2}-\d{2}$/.test(value)) return dateDisplay(value);
    return unitLabels[value] ?? value;
  }
  if (typeof value === "number") return new Intl.NumberFormat("ru-RU").format(value);
  if (typeof value === "object" && "amount" in value) {
    const currencySymbols: Record<string, string> = { RUB: "₽", EUR: "€", USD: "$", CNY: "CNY" };
    return `${decimalDisplay(String(value.amount))}${value.currency ? ` ${currencySymbols[value.currency] ?? value.currency}` : ""}`;
  }
  if (typeof value === "object" && "start" in value && "end" in value) return `${dateDisplay(value.start)} — ${dateDisplay(value.end)}`;
  return JSON.stringify(value);
}

function StatusBadge({ status }: { status: string }) {
  if (status === "review") return <span className="status-badge status-review"><AlertTriangle size={12} /> Проверить</span>;
  if (status === "missing") return <span className="status-badge status-missing"><CircleHelp size={12} /> Нет значения</span>;
  return <span className="status-badge status-good"><CheckCircle2 size={12} /> Извлечено</span>;
}

function LocationText({ provenance }: { provenance: Provenance | null }) {
  if (!provenance) return <span className="source-location">Источник не найден</span>;
  if (provenance.cell_address) return <span className="source-location">{provenance.sheet_name} · {provenance.cell_address}</span>;
  if (provenance.page_no) return <span className="source-location">Стр. {provenance.page_no}{provenance.bbox ? ` · ${Math.round(provenance.bbox.l)}, ${Math.round(provenance.bbox.t)}` : ""}</span>;
  return <span className="source-location">Источник · {provenance.source_part_id ?? provenance.source_ref ?? "—"}</span>;
}

function DocumentGlyph({ format }: { format: string }) {
  const Icon = format === "XLSX" ? FileSpreadsheet : FileText;
  return <span className={`document-glyph ${format === "XLSX" ? "glyph-sheet" : ""}`}><Icon size={17} strokeWidth={1.8} /></span>;
}

export default function Home() {
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [activeDocument, setActiveDocument] = useState<DocumentData | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [activeTab, setActiveTab] = useState<"result" | "parser" | "json">("result");
  const [parserSection, setParserSection] = useState("logical_tables");
  const [filter, setFilter] = useState("Все");
  const [search, setSearch] = useState("");
  const [showMobileDocuments, setShowMobileDocuments] = useState(true);
  const [loading, setLoading] = useState(true);
  const [extracting, setExtracting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [citation, setCitation] = useState<Provenance | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [currentSheet, setCurrentSheet] = useState("Реестр");
  const [sourceTab, setSourceTab] = useState<"view" | "json">("view");
  const [extractionMode, setExtractionMode] = useState<"rules_only" | "llm_assisted" | "compare">("llm_assisted");
  const [llmReadiness, setLlmReadiness] = useState<any>(null);
  const [userAuthenticated, setUserAuthenticated] = useState<boolean | null>(null);
  const [history, setHistory] = useState<any[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const uploadRef = useRef<HTMLInputElement>(null);

  const loadDocuments = useCallback(async (selectId?: string) => {
    setLoading(true);
    setError("");
    try {
      const response = await fetch("/api/documents", { cache: "no-store" });
      const data: any = await response.json();
      if (!response.ok) throw new Error(data.error ?? "Не удалось загрузить документы");
      setUserAuthenticated(Boolean(data.user_authenticated));
      const list = [...(data.documents ?? [])].sort((a: DocumentSummary, b: DocumentSummary) => {
        const ai = demoOrder.indexOf(a.id); const bi = demoOrder.indexOf(b.id);
        if (ai >= 0 || bi >= 0) return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi);
        return a.title.localeCompare(b.title, "ru");
      });
      setDocuments(list);
      const nextId = selectId || selectedId || list.find((item: DocumentSummary) => item.id === "kfz-2026-q1")?.id || list[0]?.id;
      if (nextId) await loadDocument(nextId);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Ошибка загрузки данных");
    } finally {
      setLoading(false);
    }
  }, [selectedId]);

  const loadDocument = useCallback(async (id: string) => {
    setSelectedId(id);
    setError("");
    try {
      const response = await fetch(`/api/documents/${encodeURIComponent(id)}`, { cache: "no-store" });
      const data: any = await response.json();
      if (!response.ok) throw new Error(data.error ?? "Не удалось открыть документ");
      setActiveDocument(data.document);
      setCitation(null);
      setCurrentPage(1);
      setCurrentSheet(data.document.parser_json?.workbook?.active_sheet ?? data.document.parser_view?.sheet_names?.[0] ?? "Реестр");
      setActiveTab("result");
      const historyResponse = await fetch(`/api/documents/${encodeURIComponent(id)}/extractions`, { cache: "no-store" });
      const historyData: any = await historyResponse.json();
      setHistory(historyResponse.ok ? historyData.history ?? [] : []);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Ошибка открытия документа");
    }
  }, []);

  useEffect(() => { void loadDocuments(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    void fetch("/api/health", { cache: "no-store" }).then((response) => response.json()).then((data: any) => setLlmReadiness(data.llm ?? null)).catch(() => setLlmReadiness({ configured: false }));
  }, []);

  const filteredDocuments = useMemo(() => {
    const q = search.trim().toLocaleLowerCase("ru-RU");
    return documents.filter((document) => {
      const type = document.latest_extraction?.document_type ?? demoTypes[document.id];
      const matchesFilter = filter === "Все" || (filter === "КФЗ" && type === "kfz_report") || (filter === "Договоры" && ["contract", "addendum"].includes(type ?? "")) || (filter === "Первичка" && ["act", "invoice", "registry"].includes(type ?? ""));
      return matchesFilter && (!q || `${document.title} ${document.file_name} ${typeLabels[type ?? ""] ?? ""}`.toLocaleLowerCase("ru-RU").includes(q));
    });
  }, [documents, filter, search]);

  const parserJson = activeDocument?.parser_json;
  const rawParserJson = parserJson?.analysis_json ?? parserJson?.analysis ?? parserJson;
  const parserView = activeDocument?.parser_view;
  const extraction = activeDocument?.latest_extraction;
  const resultRows = extraction?.line_items ?? extraction?.payment_schedule ?? extraction?.changes ?? [];
  const sourceTables: ParserTable[] = parserView?.tables ?? rawParserJson?.logical_tables ?? [];
  const pageCount = Number(parserView?.page_count ?? rawParserJson?.page_count ?? 1);
  const sheetNames: string[] = parserView?.sheet_names ?? rawParserJson?.workbook?.sheet_names ?? Object.keys(rawParserJson?.visual_layout?.sheets ?? {});
  const sourceElements: any[] = parserView?.elements ?? [];
  const sourceIsWorkbook = activeDocument?.format === "XLSX";
  const sourceHasPageNavigation = !sourceIsWorkbook && (activeDocument?.format === "PDF" || activeDocument?.format === "PPTX" || sourceElements.some((element) => Number.isFinite(element.provenance?.page_no)) || sourceTables.some((table) => Number.isFinite(table.page_no)));
  const sourceRowsForTable = (table: ParserTable) => table.rows.filter((row) => sourceIsWorkbook ? row.sheet_name === currentSheet : sourceHasPageNavigation ? row.page_no === currentPage || row.page_no == null && table.page_no === currentPage : true);
  const sourceTableIsVisible = (table: ParserTable) => sourceRowsForTable(table).length > 0;
  const sourcePage = parserView?.page_sizes?.[String(currentPage)] ?? parserView?.page_sizes?.[currentPage] ?? {};
  const sourcePageSize = sourcePage.size ?? sourcePage.unrotated_size ?? sourcePage;
  const sourcePageSizeLabel = sourcePageSize.width && sourcePageSize.height ? `${Math.round(sourcePageSize.width)} × ${Math.round(sourcePageSize.height)} pt` : "Размер не указан";
  const llmAllowed = Boolean(activeDocument?.is_demo || activeDocument?.is_synthetic);
  const modeLabels: Record<string, string> = { rules_only: "Rules Only", llm_assisted: "LLM Assisted", compare: "Compare" };

  const runExtraction = async () => {
    if (!selectedId) return;
    setExtracting(true);
    setError("");
    try {
      const response = await fetch(`/api/documents/${encodeURIComponent(selectedId)}/extract`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ mode: extractionMode }) });
      const data: any = await response.json();
      if (!response.ok) throw new Error([data.error, data.code].filter(Boolean).join(" · ") || "Не удалось запустить извлечение");
      setActiveDocument((current) => current ? { ...current, latest_extraction: data.extraction, extraction_version: data.extraction.version } : current);
      setDocuments((items) => items.map((item) => item.id === selectedId ? { ...item, latest_extraction: { id: data.extraction.extraction_id, version: data.extraction.version, document_type: data.extraction.document_type, created_at: data.extraction.extracted_at } } : item));
      const historyResponse = await fetch(`/api/documents/${encodeURIComponent(selectedId)}/extractions`, { cache: "no-store" });
      const historyData: any = await historyResponse.json();
      setHistory(historyResponse.ok ? historyData.history ?? [] : []);
      setActiveTab("result");
      setNotice(`${extractionMode === "compare" ? "Сравнение" : extractionMode === "rules_only" ? "Rules Only" : "LLM Assisted"} v${data.extraction.version} сохранено в D1`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Ошибка извлечения");
    } finally {
      setExtracting(false);
      window.setTimeout(() => setNotice(""), 3600);
    }
  };

  const uploadParserJson = async (files?: FileList | File[]) => {
    const selectedFiles = files ? Array.from(files) : [];
    if (!selectedFiles.length) return;
    setBusy(true);
    setError("");
    try {
      const syntheticAcknowledged = window.confirm("Разрешить Polza AI обрабатывать импортированный JSON? Подтвердите только для синтетических или обезличенных данных. Если отказаться, документ будет доступен только в режиме Rules Only.");
      const parsedFiles = await Promise.all(selectedFiles.map(async (file) => ({ file, json: JSON.parse(await file.text()) })));
      const layoutItem = parsedFiles.find(({ json }) => json && typeof json === "object" && !json.document && !json.model_parts && json.pages && json.source && Array.isArray(json.parts));
      const parserItem = parsedFiles.find((item) => item !== layoutItem) ?? parsedFiles[0];
      const response = await fetch("/api/parser-json", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ parser_json: parserItem.json, ...(layoutItem ? { layout_json: layoutItem.json } : {}), file_name: parserItem.file.name, synthetic_acknowledged: syntheticAcknowledged }) });
      const data: any = await response.json();
      if (!response.ok) throw new Error((data.details ?? [data.error]).filter(Boolean).join(" · "));
      await loadDocuments(data.document.id);
      setNotice(layoutItem ? "Результаты analysis.json и layout.json сохранены. OCR не запускался." : "JSON результата парсера сохранён. OCR и распознавание не запускались.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Файл не удалось прочитать как JSON");
    } finally {
      setBusy(false);
      if (uploadRef.current) uploadRef.current.value = "";
      window.setTimeout(() => setNotice(""), 4200);
    }
  };

  const focusSource = (provenance: Provenance | null) => {
    if (!provenance) return;
    setCitation(provenance);
    setSourceTab("view");
    if (provenance.page_no) setCurrentPage(provenance.page_no);
    if (provenance.sheet_name) setCurrentSheet(provenance.sheet_name);
    window.setTimeout(() => document.getElementById("source-panel")?.scrollIntoView({ behavior: "smooth", block: "nearest" }), 40);
  };

  const comparisonProvenance = (item: any) => item.llm?.provenance ?? item.rules?.provenance ?? item.llm?.identifier?.provenance ?? item.rules?.identifier?.provenance ?? null;
  const comparisonValue = (item: any, method: "rules" | "llm") => {
    const value = item[method];
    if (!value) return "—";
    if (value.source_value !== undefined) return value.source_value ?? (value.value == null ? "—" : formatValue(value.value));
    return [value.identifier?.source_value, value.description?.source_value, value.amount?.source_value].filter(Boolean).join(" · ") || "Строка найдена";
  };

  const exportJson = async () => {
    if (!extraction) return;
    const content = JSON.stringify(extraction, null, 2);
    const blob = new Blob([content], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${activeDocument?.id ?? "extraction"}-extraction-v${extraction.version}.json`;
    link.click();
    URL.revokeObjectURL(url);
    try { await navigator.clipboard.writeText(content); setNotice("JSON скачан и скопирован в буфер обмена"); }
    catch { setNotice("JSON скачан"); }
    window.setTimeout(() => setNotice(""), 3600);
  };

  const copyParserJson = async () => {
    if (!parserJson) return;
    try { await navigator.clipboard.writeText(JSON.stringify(parserJson, null, 2)); setNotice("Структура парсера скопирована"); }
    catch { setNotice("Буфер обмена недоступен"); }
    window.setTimeout(() => setNotice(""), 3600);
  };

  const openExtractionVersion = async (id: string) => {
    try {
      const response = await fetch(`/api/extractions/${encodeURIComponent(id)}`, { cache: "no-store" });
      const data: any = await response.json();
      if (!response.ok) throw new Error(data.error ?? "Не удалось открыть версию");
      setActiveDocument((current) => current ? { ...current, latest_extraction: data.extraction } : current);
      setActiveTab("result");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Не удалось открыть версию извлечения"); }
  };

  const schemaSections = ["parts", "model_parts", "visual_layout", "logical_tables", "provenance", "document"];

  return (
    <div className="app-shell">
      <aside className="document-sidebar">
        <div className="brand-lockup">
          <div className="brand-mark">К</div>
          <div><strong>КФЗ</strong><span>EXTRACTION DESK</span></div>
          <button className="icon-button mobile-menu" aria-label={showMobileDocuments ? "Свернуть список документов" : "Открыть список документов"} aria-expanded={showMobileDocuments} aria-controls="document-picker" onClick={() => setShowMobileDocuments((open) => !open)}><Menu size={18} /></button>
        </div>
        <div className="workspace-caption"><span className="live-dot" /> ДЕМОНСТРАЦИОННЫЙ КОНТУР</div>
        <div id="document-picker" className={`mobile-document-picker ${showMobileDocuments ? "" : "collapsed"}`}>
          <div className="side-label-row"><span>ДОКУМЕНТЫ</span><span className="count-pill">{documents.length}</span></div>
          <label className="search-box"><Search size={15} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Найти документ" /></label>
          <div className="filter-row">
            {["Все", "КФЗ", "Договоры", "Первичка"].map((item) => <button key={item} className={`filter-chip ${filter === item ? "selected" : ""}`} onClick={() => setFilter(item)}>{item}</button>)}
          </div>
          <div className="document-list" aria-label="Подготовленные документы">
            {loading && <div className="list-placeholder"><span className="spinner" /> Загружаю документы…</div>}
            {!loading && filteredDocuments.map((document) => {
              return <button key={document.id} className={`document-row ${selectedId === document.id ? "active" : ""}`} onClick={() => void loadDocument(document.id)}>
                <DocumentGlyph format={document.format} />
                <span className="document-row-copy"><strong>{document.title}</strong><span>{document.file_name}</span><em>{document.format}{document.page_count ? ` · ${document.format === "XLSX" ? `${document.page_count} листа` : `${document.page_count} стр.`}` : ""}</em></span>
                <span className={`document-state ${document.latest_extraction ? "state-ready" : ""}`} title={document.latest_extraction ? `Версия ${document.latest_extraction.version}` : "Ожидает извлечения"}>{document.latest_extraction ? <Check size={12} /> : <span />}</span>
              </button>;
            })}
            {!loading && !filteredDocuments.length && <div className="empty-documents">Документы не найдены</div>}
          </div>
        </div>
        <div className="sidebar-bottom">
          <button className="import-button" onClick={() => uploadRef.current?.click()} disabled={busy}><Upload size={16} /> {busy ? "Импортирую…" : "Импорт JSON парсера"}</button>
          <input ref={uploadRef} type="file" accept="application/json,.json" multiple hidden onChange={(event) => void uploadParserJson(event.target.files ?? undefined)} />
          <div className="storage-note"><Database size={14} /><span><strong>Постоянное хранилище</strong><small>Cloudflare D1 · межустройственная синхронизация</small></span><CheckCircle2 size={14} className="storage-check" /></div>
        </div>
      </aside>

      <main className="workspace-main">
        <header className="topbar">
          <div className="breadcrumb"><span>Рабочее пространство</span><ChevronRight size={14} /><strong>Structured Extraction</strong></div>
          <div className="topbar-right"><span className="stage-pill"><span>ЭТАП 01</span> Извлечение</span>{userAuthenticated ? <span className="user-dot" title="Вход подтверждён">А</span> : <a className="signin-link" href="/signin-with-chatgpt?return_to=%2F">Войти для сохранения</a>}</div>
        </header>
        <div className="main-scroll">
          <section className="page-heading">
            <div className="heading-copy"><div className="eyebrow"><span className="eyebrow-dot" /> КОНТРОЛЬ ДАННЫХ · ПИЛОТ</div><h1>Извлечение данных</h1><p>Преобразуйте результаты парсера в проверяемые поля с точной ссылкой на источник.</p></div>
            <div className="pipeline-card"><span className="pipeline-step done"><Check size={12} /> Parser JSON</span><span className="pipeline-line" /><span className="pipeline-step current"><span className="pulse-dot" /> Structured Extraction</span><span className="pipeline-line muted" /><span className="pipeline-step future">Linking <small>позже</small></span></div>
          </section>

          {error && <div className="alert error-alert"><AlertCircle size={17} /><span>{error}</span><button onClick={() => setError("")} aria-label="Скрыть ошибку"><X size={15} /></button></div>}
          {notice && <div className="toast-notice"><CheckCircle2 size={16} /> {notice}</div>}
          {activeDocument?.latest_run_status === "failed" && !error && <div className="alert error-alert"><AlertCircle size={17} /><span>Последний запуск завершился ошибкой: {activeDocument.latest_run_error?.message ?? activeDocument.latest_run_error?.technical?.reason ?? "подробности доступны в истории"}</span></div>}

          {activeDocument && <section className="mode-selector panel-card" aria-label="Режим извлечения">
            <div className="mode-selector-heading"><div><span className="eyebrow">ОБРАБОТКА</span><h3>Режим извлечения</h3></div><span className={`llm-state ${llmReadiness?.configured ? "llm-state-ready" : "llm-state-off"}`}><span />Polza AI {llmReadiness?.configured ? "доступна по конфигурации" : "не настроена"}</span></div>
            <div className="mode-options" role="radiogroup" aria-label="Режим Structured Extraction">
              {(["rules_only", "llm_assisted", "compare"] as const).map((value) => <button key={value} role="radio" aria-checked={extractionMode === value} className={extractionMode === value ? "selected" : ""} onClick={() => setExtractionMode(value)}><strong>{modeLabels[value]}</strong><small>{value === "rules_only" ? "Только детерминированные правила" : value === "llm_assisted" ? "Правила + подтверждённые ответы LLM" : "Одинаковый JSON в обоих режимах"}</small></button>)}
            </div>
            <div className="mode-footnote"><span>Модель: {llmReadiness?.model ?? "deepseek/deepseek-v4-flash"}</span><span>{extractionMode !== "rules_only" && !llmAllowed ? "Для импортированного документа LLM отключена: требуется отметить данные синтетическими/обезличенными при импорте." : llmReadiness?.configured ? `Провайдер: ${llmReadiness.provider}` : "Rules Only работает без LLM. Для LLM нужен серверный секрет POLZA_API_KEY."}</span></div>
            {!userAuthenticated && <div className="auth-note">Запуск и сохранение результата требуют входа через ChatGPT. <a href="/signin-with-chatgpt?return_to=%2F">Войти</a></div>}
          </section>}

          {activeDocument ? <>
            <section className="selected-document-card">
              <div className="selected-file-icon"><DocumentGlyph format={activeDocument.format} /></div>
              <div className="selected-file-info"><div className="selected-file-name"><h2>{activeDocument.title}</h2><span className={`demo-tag ${activeDocument.is_demo ? "" : "import-tag"}`}>{activeDocument.is_demo ? "ДЕМО-ДАННЫЕ" : "ИМПОРТ JSON"}</span></div><p><span>{activeDocument.file_name}</span><i />{activeDocument.format}{pageCount ? ` · ${activeDocument.format === "XLSX" ? `${sheetNames.length || pageCount} листа` : `${pageCount} страницы`}` : ""}<i /><span className="parser-version">{parserJson?.parser_output_version ?? parserJson?.analysis_version ?? "Parser JSON"}</span></p></div>
              <div className="selected-file-actions"><span className={`classification-pill ${extraction ? "classified" : "waiting"}`}><span className="status-dot" />{extraction ? typeLabels[extraction.document_type] ?? extraction.document_type : "Тип ещё не определён"}</span><button className="primary-button" onClick={() => void runExtraction()} disabled={extracting || !userAuthenticated || (extractionMode !== "rules_only" && !llmAllowed)}><RefreshCw className={extracting ? "spin" : ""} size={15} />{extracting ? "Извлекаю…" : `Запустить ${modeLabels[extractionMode]}`}</button></div>
            </section>

            <div className="content-tabs-row">
              <div className="content-tabs" role="tablist" aria-label="Представление данных">
                <button className={activeTab === "result" ? "active" : ""} onClick={() => setActiveTab("result")}><ShieldCheck size={15} /> Результат{extraction ? <span className="tab-count">v{extraction.version}</span> : null}</button>
                <button className={activeTab === "parser" ? "active" : ""} onClick={() => setActiveTab("parser")}><Code2 size={15} /> Структура парсинга</button>
                <button className={activeTab === "json" ? "active" : ""} onClick={() => setActiveTab("json")}><FileJson2 size={15} /> JSON</button>
              </div>
              <div className="extraction-meta-actions">{extraction && <div className="extraction-meta"><Clock3 size={13} /> v{extraction.version} · {modeLabels[extraction.mode] ?? extraction.mode ?? "извлечение"}{extraction.input_version !== activeDocument.input_version ? " · устаревшая версия входа" : ""}</div>}<button className="history-toggle" onClick={() => setHistoryOpen((open) => !open)}><Clock3 size={13} /> История {history.length ? `(${history.length})` : ""}</button></div>
            </div>

            {extraction && <div className="execution-status"><span className={extraction.extraction_engine?.llm?.called ? "execution-live" : "execution-rules"}><span />{extraction.extraction_engine?.llm?.called ? `LLM вызвана · ${extraction.extraction_engine.llm.provider}` : "LLM не вызывалась · Rules"}</span><span>Проверка ответа: {extraction.extraction_engine?.llm?.validation_status ?? "не запускалась"}</span>{extraction.extraction_engine?.llm?.duration_ms != null && <span>{extraction.extraction_engine.llm.duration_ms} мс</span>}</div>}

            {historyOpen && <section className="history-panel panel-card"><div className="panel-heading"><div><span className="eyebrow">ВЕРСИИ D1</span><h3>История извлечений</h3></div><span className="panel-caption">результат связан с версией входного JSON</span></div>{history.length ? <div className="history-list">{history.map((item) => <button key={item.id} className={`history-row ${item.status === "completed" ? "" : "history-failed"}`} onClick={() => item.status === "completed" && void openExtractionVersion(item.id)} disabled={item.status !== "completed"}><span><strong>v{item.version} · {modeLabels[item.mode] ?? item.mode}</strong><small>Вход v{item.input_version} · {new Date(item.created_at).toLocaleString("ru-RU", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}{item.error?.message ? ` · ${item.error.message}` : ""}</small></span><span className={`history-status ${item.status}`}>{item.status === "completed" ? "готово" : item.status === "running" ? "выполняется" : item.status === "stale" ? "устарело" : "ошибка"}</span></button>)}</div> : <div className="history-empty">История появится после первого запуска.</div>}</section>}

            {activeTab === "result" && !extraction && <section className="empty-result panel-card">
              <div className="empty-icon"><ArrowLeftRight size={23} /></div><div><span className="eyebrow">ГОТОВЫЙ РЕЗУЛЬТАТ ПАРСЕРА</span><h3>Входные данные уже распознаны</h3><p>Этот шаг классифицирует документ, нормализует поля и сохраняет каждую ссылку на страницу или ячейку. OCR и разбор исходного файла не выполняются.</p><button className="primary-button" onClick={() => void runExtraction()} disabled={extracting || !userAuthenticated || (extractionMode !== "rules_only" && !llmAllowed)}><RefreshCw className={extracting ? "spin" : ""} size={15} />{extracting ? "Извлекаю…" : `Запустить ${modeLabels[extractionMode]}`}</button></div>
            </section>}

            {activeTab === "result" && extraction && <>
              <section className="summary-strip">
                <div className="summary-card main-summary"><span className="summary-label">ТИП ДОКУМЕНТА</span><div className="summary-type"><div className="summary-type-icon"><FileText size={17} /></div><strong>{typeLabels[extraction.document_type] ?? extraction.document_type}</strong><span className="confidence-tag">{Math.round((extraction.classification?.confidence ?? 0) * 100)}% совпадение</span></div><small>Определено по содержимому Parser JSON</small></div>
                <div className="summary-card"><span className="summary-label">СТРОКИ ТАБЛИЦ</span><strong className="summary-number">{resultRows.length}</strong><small>{extraction.document_type === "kfz_report" ? "все строки КФЗ включены" : "извлечено из таблиц"}</small></div>
                <div className="summary-card"><span className="summary-label">ТРЕБУЮТ ПРОВЕРКИ</span><strong className={`summary-number ${extraction.review_required?.length ? "warn-number" : ""}`}>{extraction.review_required?.length ?? 0}</strong><small>{extraction.missing_fields?.length ?? 0} пустых реквизитов</small></div>
              </section>

              <section className="panel-card fields-panel">
                <div className="panel-heading"><div><span className="eyebrow">РЕКВИЗИТЫ</span><h3>Извлечённые поля</h3></div><span className="panel-caption">исходное значение + нормализованное</span></div>
                <div className="field-grid">
                  {Object.entries(extraction.fields ?? {}).map(([key, value]: [string, any]) => <button key={key} className={`field-card ${value.status === "review" ? "field-needs-review" : ""} ${value.status === "missing" ? "field-empty" : ""}`} onClick={() => focusSource(value.provenance)}>
                    <span className="field-top"><span>{value.label ?? key.replace(/_/g, " ")}</span><span className={`field-status-dot ${value.status}`} /></span>
                    <strong>{formatValue(value.value)}</strong>
                    <span className="field-source"><span>{value.source_value ? `В исходнике: ${value.source_value}` : "Значение отсутствует"}</span><LocationText provenance={value.provenance} /></span>
                    {value.status === "review" && <span className="field-note"><AlertTriangle size={12} /> {value.normalization_note ?? "Требует проверки"}</span>}
                    {value.conflict && <span className="field-conflict"><span>Rules: {value.conflict.rules?.source_value ?? "—"}</span><span>LLM: {value.conflict.llm?.source_value ?? "—"}</span></span>}
                  </button>)}
                </div>
              </section>

              {resultRows.length > 0 && <section className="panel-card line-items-panel">
                <div className="panel-heading"><div><span className="eyebrow">ДЕТАЛИЗАЦИЯ</span><h3>{extraction.document_type === "kfz_report" ? "Все проверяемые строки КФЗ" : extraction.document_type === "contract" ? "Этапы и платежи" : extraction.document_type === "addendum" ? "Изменяемые условия" : "Строки документа"}</h3></div><span className="row-count"><Table2 size={14} /> {resultRows.length} строк</span></div>
                <div className="data-table-wrap"><table className="data-table"><thead><tr><th>№</th><th>Идентификатор</th><th>Наименование</th><th>Ед.</th>{extraction.document_type === "kfz_report" ? <><th>План</th><th>Факт</th></> : <th>Кол-во</th>}<th>Цена за ед.</th><th>Сумма</th></tr></thead><tbody>
                  {resultRows.map((row: any, index: number) => <tr key={row.row_id} className={row.row_status === "review" ? "row-review" : ""}>
                    <td><ValueLink value={row.line_number} onClick={focusSource} fallback={String(index + 1).padStart(2, "0")} /></td>
                    <td><ValueLink value={row.identifier} onClick={focusSource} /></td>
                    <td className="description-cell"><ValueLink value={row.description} onClick={focusSource} /></td>
                    <td><ValueLink value={row.unit} onClick={focusSource} /></td>
                    {extraction.document_type === "kfz_report" ? <><td><ValueLink value={row.plan_quantity} onClick={focusSource} /></td><td><ValueLink value={row.actual_quantity} onClick={focusSource} /></td></> : <td><ValueLink value={row.quantity} onClick={focusSource} /></td>}
                    <td><ValueLink value={row.unit_price} onClick={focusSource} /></td><td className="amount-cell"><ValueLink value={row.amount} onClick={focusSource} /></td>
                  </tr>)}
                </tbody></table></div>
                <div className="table-footnote"><span><span className="legend-dot normal" /> Извлечено</span><span><span className="legend-dot review" /> Нужна проверка</span><span>Нажмите на значение, чтобы перейти к источнику</span></div>
                {extraction.tables?.filter((table: any) => table.role !== "line_items" && table.role !== "metadata").map((table: any) => <details className="source-table-details" key={table.id}><summary>{table.title}<ChevronDown size={14} /></summary><div className="raw-table-scroll"><table className="data-table compact-table"><thead><tr>{table.headers.map((header: string, i: number) => <th key={i}>{header}</th>)}</tr></thead><tbody>{table.rows.map((row: any) => <tr key={row.row_id}>{row.source_cells.map((cell: any, i: number) => <td key={i}><ValueLink value={cell.extracted} onClick={focusSource} /></td>)}</tr>)}</tbody></table></div></details>)}
              </section>}

              {extraction.comparison && <section className="comparison-panel panel-card"><div className="panel-heading"><div><span className="eyebrow">RULES VS LLM ASSISTED</span><h3>Сравнение методов</h3></div></div><div className="comparison-counts"><span>Совпало <strong>{extraction.comparison.counts.matches}</strong></span><span>Расхождений <strong>{extraction.comparison.counts.discrepancies}</strong></span><span>Только Rules <strong>{extraction.comparison.counts.rules_only}</strong></span><span>Только LLM <strong>{extraction.comparison.counts.llm_only}</strong></span></div>
                {extraction.comparison.discrepancies.slice(0, 8).map((item: any, index: number) => <button key={`diff-${item.path}-${index}`} className="comparison-row" onClick={() => focusSource(comparisonProvenance(item))}><strong>Расхождение · {item.path}</strong><span>Rules: {comparisonValue(item, "rules")}</span><span>LLM: {comparisonValue(item, "llm")}</span></button>)}
                {extraction.comparison.rules_only.slice(0, 5).map((item: any, index: number) => <button key={`rules-${item.path}-${index}`} className="comparison-row comparison-only" onClick={() => focusSource(comparisonProvenance(item))}><strong>Только Rules · {item.path}</strong><span>{comparisonValue(item, "rules")}</span></button>)}
                {extraction.comparison.llm_only.slice(0, 5).map((item: any, index: number) => <button key={`llm-${item.path}-${index}`} className="comparison-row comparison-only" onClick={() => focusSource(comparisonProvenance(item))}><strong>Только LLM · {item.path}</strong><span>{comparisonValue(item, "llm")}</span></button>)}
                {extraction.comparison.matches.slice(0, 5).map((item: any, index: number) => <button key={`match-${item.path}-${index}`} className="comparison-row comparison-match" onClick={() => focusSource(comparisonProvenance(item))}><strong>Совпадение · {item.path}</strong><span>Rules: {comparisonValue(item, "rules")}</span><span>LLM: {comparisonValue(item, "llm")}</span></button>)}</section>}
              {extraction.review_required?.length > 0 && <section className="review-panel panel-card"><div className="panel-heading"><div><span className="eyebrow">КОНТРОЛЬ КАЧЕСТВА</span><h3>Значения для ручной проверки</h3></div><span className="review-count"><AlertTriangle size={13} /> {extraction.review_required.length}</span></div><div className="review-list">{extraction.review_required.slice(0, 8).map((item: any, i: number) => <button key={`${item.path}-${i}`} className="review-row" onClick={() => focusSource(item.provenance)}><span className="review-triangle"><AlertTriangle size={14} /></span><span><strong>{item.source_value ?? "Значение не распознано"}</strong><small>{item.path.replace(/^fields\./, "").replaceAll("_", " ")} · {item.reason}</small></span><LocationText provenance={item.provenance} /><ChevronRight size={14} /></button>)}{extraction.review_required.length > 8 && <div className="more-reviews">И ещё {extraction.review_required.length - 8} значений отмечены для проверки.</div>}</div></section>}
              {extraction.missing_fields?.length > 0 && <section className="missing-note"><CircleHelp size={15} /><span><strong>Пустые реквизиты не дополнены:</strong> {extraction.missing_fields.map((key: string) => extraction.fields?.[key]?.label ?? key).join(", ")}</span></section>}
            </>}

            {activeTab === "parser" && <section className="parser-explorer panel-card"><div className="panel-heading"><div><span className="eyebrow">ВХОДНОЙ СЛОЙ</span><h3>Структура Document Parser</h3></div><button className="text-action" onClick={() => void copyParserJson()}><Clipboard size={14} /> Копировать JSON</button></div><p className="parser-note">Входной JSON хранится отдельно от результата. Для native JSON без logical_tables здесь показаны таблицы, собранные адаптером из ячеек и фрагментов.</p><div className="schema-tabs">{schemaSections.map((section) => <button key={section} className={parserSection === section ? "active" : ""} onClick={() => setParserSection(section)}>{section}</button>)}</div><div className="json-panel parser-json"><pre>{JSON.stringify(parserSection === "visual_layout" ? rawParserJson?.visual_layout ?? parserJson?.layout_json ?? null : parserSection === "logical_tables" ? rawParserJson?.logical_tables ?? parserView?.tables ?? null : parserSection === "provenance" ? sourceElements.map((element) => ({ id: element.id, provenance: element.provenance })) : rawParserJson?.[parserSection] ?? null, null, 2)}</pre></div><div className="parser-foot"><span><Hash size={13} /> {parserSection === "logical_tables" && !rawParserJson?.logical_tables ? `${parserView?.tables?.length ?? 0} адаптированных таблиц` : Array.isArray(rawParserJson?.[parserSection]) ? `${rawParserJson[parserSection].length} элементов` : `${Object.keys(rawParserJson?.[parserSection] ?? {}).length} свойств`}</span><span>parser_output_version: {rawParserJson?.parser_output_version ?? rawParserJson?.analysis_version ?? "Document Parser"}</span></div></section>}

            {activeTab === "json" && <section className="export-panel panel-card"><div className="panel-heading"><div><span className="eyebrow">НОРМАЛИЗОВАННЫЙ РЕЗУЛЬТАТ</span><h3>JSON Structured Extraction</h3></div><div className="export-actions"><button className="secondary-button" onClick={() => void navigator.clipboard.writeText(JSON.stringify(extraction, null, 2)).then(() => setNotice("Результат скопирован"))} disabled={!extraction}><Clipboard size={14} /> Копировать</button><button className="primary-button compact" onClick={() => void exportJson()} disabled={!extraction}><Download size={14} /> Скачать JSON</button></div></div>{extraction ? <div className="json-panel"><pre>{JSON.stringify(extraction, null, 2)}</pre></div> : <div className="no-json"><FileJson2 size={25} /><strong>Сначала запустите извлечение</strong><span>Здесь появится нормализованный JSON с версиями, полями, таблицами и provenance.</span></div>}</section>}
          </> : <section className="loading-screen panel-card"><span className="spinner" /> {loading ? "Открываю документы…" : "Выберите документ слева"}</section>}

          <footer className="workspace-footer"><span>Structured Extraction · v1.0</span><span><Database size={13} /> D1 включена</span><span>Демо-набор · 6 документов</span></footer>
        </div>
      </main>

      <aside className="source-panel" id="source-panel">
        <div className="source-panel-header"><div className="source-title"><span className="eyebrow">ПЕРВОИСТОЧНИК</span><strong>{citation?.cell_address ? citation.sheet_name : citation?.page_no ? `Страница ${citation.page_no}` : "Документ"}</strong></div><button className="icon-button" onClick={() => setCitation(null)} aria-label="Сбросить выделение"><PanelRightOpen size={17} /></button></div>
        <div className="source-toggle"><button className={sourceTab === "view" ? "active" : ""} onClick={() => setSourceTab("view")}><FolderOpen size={14} /> Представление</button><button className={sourceTab === "json" ? "active" : ""} onClick={() => setSourceTab("json")}><Code2 size={14} /> Parser JSON</button></div>
        {sourceTab === "view" ? <>
          <div className="source-demo-banner"><span className="demo-star">✳</span><span><strong>{activeDocument?.is_demo ? "Демонстрационное представление" : "Представление по результату парсера"}</strong><small>{activeDocument?.is_demo ? "Не исходный PDF/XLSX. Геометрия и ячейки согласованы с provenance." : "Исходный файл не загружен. Показаны распознанные фрагменты и таблицы с адресами источника."}</small></span></div>
          {activeDocument?.format === "XLSX" && <div className="sheet-tabs">{sheetNames.map((sheet) => <button key={sheet} onClick={() => setCurrentSheet(sheet)} className={currentSheet === sheet ? "active" : ""}>{sheet}</button>)}</div>}
          {sourceHasPageNavigation && <div className="page-controls"><button onClick={() => setCurrentPage((value) => Math.max(1, value - 1))} disabled={currentPage <= 1}>‹</button><span>Страница <strong>{currentPage}</strong> из {pageCount}</span><button onClick={() => setCurrentPage((value) => Math.min(pageCount, value + 1))} disabled={currentPage >= pageCount}>›</button><span className="page-size">{sourcePageSizeLabel}</span></div>}
          <div className={`source-sheet ${activeDocument?.format === "XLSX" ? "source-workbook" : ""}`}>
            {activeDocument?.format === "XLSX" && <div className="sheet-column-head">{sheetNames.join(" · ")}</div>}
            <div className="source-page-head"><span className="source-org">{activeDocument?.title ?? "Документ"}</span><span>{activeDocument?.file_name}</span></div>
            {sourceTables.filter(sourceTableIsVisible).map((table) => {
              const rows = sourceRowsForTable(table);
              return <div className="source-table-block" key={table.id}><div className="source-table-caption">{table.caption}</div><table className="source-document-table"><thead><tr>{table.headers.map((header, i) => <th key={i}>{header}</th>)}</tr></thead><tbody>{rows.map((row) => <tr key={row.row_id}>{row.cells.map((cell, i) => {
                const sourceId = cell.id ?? cell.provenance?.source_part_id;
                const selected = Boolean(citation && ((citation.source_part_id && sourceId === citation.source_part_id) || (citation.cell_address && cell.address === citation.cell_address)));
                return <td key={sourceId ?? i} className={selected ? "source-highlight" : ""} data-cell-id={sourceId}><button onClick={() => cell.provenance && setCitation(cell.provenance)} disabled={!cell.provenance} title={cell.provenance ? "Перейти к источнику" : "В результате парсера нет ссылки на эту ячейку"}>{cell.text || <span className="empty-cell">—</span>}</button></td>;
              })}</tr>)}</tbody></table></div>;
            })}
            {sourceElements.filter((element) => element.kind !== "cell" && (!sourceHasPageNavigation || element.provenance?.page_no === currentPage || element.provenance?.page_no == null) && element.text?.trim()).filter((element, index, all) => all.findIndex((candidate) => candidate.text === element.text && candidate.provenance?.page_no === element.provenance?.page_no) === index).map((element) => {
              const selected = Boolean(citation && citation.source_part_id === element.id);
              return <button key={element.id} className={`source-text-fragment ${selected ? "source-highlight" : ""}`} onClick={() => setCitation(element.provenance)} data-source-element-id={element.id}>
                <span>{element.text}</span><small>Parser fragment · {element.provenance?.source_ref ?? element.id}</small>
              </button>;
            })}
            {!sourceTables.some(sourceTableIsVisible) && !sourceElements.some((element) => element.kind !== "cell" && (!sourceHasPageNavigation || element.provenance?.page_no === currentPage || element.provenance?.page_no == null) && element.text?.trim()) && <div className="source-empty-page"><FileText size={25} /><strong>{sourceHasPageNavigation ? `Страница ${currentPage}` : activeDocument?.format === "XLSX" ? currentSheet : "Исходные фрагменты"}</strong><span>В подготовленном результате парсера нет структурированных таблиц или текста для этого представления.</span></div>}
            <div className="source-signatures"><span>Подготовленная копия</span><span>Без юридической силы</span></div>
          </div>
          {citation && <div className="citation-card"><div className="citation-heading"><span className="citation-pin" /><strong>Источник значения</strong></div><p>«{citation.source_text || "Пустая ячейка"}»</p><div className="citation-meta"><LocationText provenance={citation} /><span>{citation.confidence == null ? "Уверенность не оценивалась" : `Уверенность ${Math.round(citation.confidence * 100)}%`}</span></div>{citation.bbox && <small className="bbox-detail">PDF bbox: [{citation.bbox.l.toFixed(1)}, {citation.bbox.t.toFixed(1)}, {citation.bbox.r.toFixed(1)}, {citation.bbox.b.toFixed(1)}] {citation.page_size?.unit ?? "координат"} · {citation.coordinate_origin ?? citation.bbox.coord_origin}</small>}</div>}
        </> : <div className="source-json-view"><pre>{JSON.stringify(parserJson, null, 2)}</pre></div>}
        <div className="source-panel-footer"><span><span className="live-dot" /> Источник синхронизирован</span><span><ShieldCheck size={13} /> Provenance</span></div>
      </aside>
    </div>
  );
}

function ValueLink({ value, onClick, fallback }: { value: ExtractedValue | undefined; onClick: (provenance: Provenance | null) => void; fallback?: string }) {
  const display = value ? formatValue(value.value) : fallback ?? "—";
  return <button className={`value-link ${value?.status === "review" ? "value-review" : ""} ${value?.status === "missing" ? "value-missing" : ""}`} onClick={() => onClick(value?.provenance ?? null)} title={value?.source_value ? `Исходное значение: ${value.source_value}` : "Источник значения"}>{display}</button>;
}
