import { z } from "zod";
import { adaptDocumentParserResult } from "../parser/document-parser-adapter.mjs";
import { classifyDocument, fieldDefinitions } from "./structured-extraction.mjs";

export const POLZA_BASE_URL = "https://polza.ai/api/v1";
export const POLZA_MODEL = "deepseek/deepseek-v4-flash";

const semanticKeys = ["line_number", "identifier", "description", "unit", "planned_quantity", "actual_quantity", "quantity", "unit_price", "amount", "parameter", "old_value", "new_value", "reason", "unknown"];
const tableRoles = ["metadata", "line_items", "payment_schedule", "amendments", "reference", "summary", "appendix", "table"];
const normalizeClassificationConfidence = (value) => typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1 ? value : null;
const groundedResponseSchema = z.object({
  document_type: z.enum(["kfz_report", "contract", "act", "invoice", "addendum", "registry", "unknown"]),
  classification_confidence: z.preprocess(normalizeClassificationConfidence, z.number().min(0).max(1).nullable()),
  field_candidates: z.array(z.object({
    field_key: z.string().min(1),
    source_element_id: z.string().min(1),
    source_value: z.string().min(1),
    confidence: z.number().min(0).max(1),
  }).strict()),
  table_mappings: z.array(z.object({
    table_id: z.string().min(1),
    role: z.enum(tableRoles),
    confidence: z.number().min(0).max(1),
    columns: z.array(z.object({
      source_element_id: z.string().min(1),
      semantic_key: z.enum(semanticKeys),
      label: z.string().min(1),
      confidence: z.number().min(0).max(1),
    }).strict()),
  }).strict()),
}).strict();

export const polzaJsonSchema = {
  name: "grounded_document_extraction",
  strict: true,
  schema: {
  type: "object",
  additionalProperties: false,
  required: ["document_type", "classification_confidence", "field_candidates", "table_mappings"],
  properties: {
    document_type: { type: "string", enum: ["kfz_report", "contract", "act", "invoice", "addendum", "registry", "unknown"] },
    classification_confidence: { type: ["number", "null"], minimum: 0, maximum: 1 },
    field_candidates: {
      type: "array",
      items: { type: "object", additionalProperties: false, required: ["field_key", "source_element_id", "source_value", "confidence"], properties: {
        field_key: { type: "string" }, source_element_id: { type: "string" }, source_value: { type: "string" }, confidence: { type: "number", minimum: 0, maximum: 1 },
      } },
    },
    table_mappings: {
      type: "array",
      items: { type: "object", additionalProperties: false, required: ["table_id", "role", "confidence", "columns"], properties: {
        table_id: { type: "string" }, role: { type: "string", enum: tableRoles }, confidence: { type: "number", minimum: 0, maximum: 1 },
        columns: { type: "array", items: { type: "object", additionalProperties: false, required: ["source_element_id", "semantic_key", "label", "confidence"], properties: {
          source_element_id: { type: "string" }, semantic_key: { type: "string", enum: semanticKeys }, label: { type: "string" }, confidence: { type: "number", minimum: 0, maximum: 1 },
        } } },
      } },
    },
  },
  },
};

export class PolzaAiError extends Error {
  constructor(message, code = "POLZA_ERROR", status = 502, details = {}) {
    super(message);
    this.name = "PolzaAiError";
    this.code = code;
    this.status = status;
    this.details = {
      provider: details.provider ?? null,
      model: details.model ?? POLZA_MODEL,
      duration_ms: details.duration_ms ?? null,
      validation_status: details.validation_status ?? "not_run",
      reason: details.reason ?? message,
      ...details,
    };
  }
}

export function polzaAiReadiness(env = {}) {
  const configured = Boolean(String(env.POLZA_API_KEY ?? "").trim());
  return { configured, provider: configured ? "polza_ai" : null, base_url: POLZA_BASE_URL, model: POLZA_MODEL, ...(configured ? {} : { required: ["POLZA_API_KEY"] }) };
}

function clipText(value, max = 2400) {
  const text = String(value ?? "");
  return text.length > max ? `${text.slice(0, max)}…[усечено]` : text;
}

export function buildGroundedContext(parsed) {
  const source = adaptDocumentParserResult(parsed);
  const availableElementIds = new Set(source.elements.filter((element) => element.source_available !== false).map((element) => element.id));
  const ruleType = classifyDocument(parsed);
  const budget = { chars: 34000 };
  const tableSourceIds = new Set();
  const tables = [];

  for (const table of source.tables) {
    const headers = (table.header_cells ?? []).map((cell, column_index) => ({ cell, column_index }))
      .filter(({ cell }) => cell.source_available !== false)
      .map(({ cell, column_index }) => {
      tableSourceIds.add(cell.id);
      const sourceIds = [...new Set([cell.id, ...(cell.source_element_ids ?? [])])].filter((id) => availableElementIds.has(id));
      sourceIds.forEach((id) => tableSourceIds.add(id));
      return { source_element_id: cell.id, source_element_ids: sourceIds, column_index, label: clipText(table.headers[column_index] ?? cell.text, 500) };
    });
    const allRows = table.rows ?? [];
    const chosenRows = new Set();
    allRows.slice(0, 8).forEach((_, index) => chosenRows.add(index));
    if (allRows.length) chosenRows.add(allRows.length - 1);
    const firstRowByPage = new Set();
    allRows.forEach((row, index) => {
      const key = `${row.page_no ?? "no-page"}|${row.sheet_name ?? ""}`;
      if (!firstRowByPage.has(key)) { firstRowByPage.add(key); chosenRows.add(index); }
    });
    const rows = [];
    for (const rowIndex of [...chosenRows].sort((a, b) => a - b)) {
      const row = allRows[rowIndex];
      const cells = [];
      for (const cell of row.cells ?? []) {
        tableSourceIds.add(cell.id);
        if (cell.source_available === false || !cell.text && !cell.address) continue;
        const text = clipText(cell.text, 600);
        const cost = text.length + 64;
        if (budget.chars < cost) continue;
        budget.chars -= cost;
        cells.push({ source_element_id: cell.id, text });
      }
      if (cells.length) rows.push({ row_id: row.row_id, page_no: row.page_no ?? null, sheet_name: row.sheet_name ?? null, cells });
    }
    tables.push({ table_id: table.id, title: clipText(table.caption, 300), role: table.role, pages: table.page_numbers ?? [...new Set((table.rows ?? []).map((row) => row.page_no).filter(Number.isFinite))], headers, rows });
  }

  const fields = fieldDefinitions[ruleType.type] ?? Object.values(fieldDefinitions).flat();
  const sourceElements = [];
  for (const element of source.elements) {
    if (element.source_available === false || tableSourceIds.has(element.id) || !element.text.trim()) continue;
    const text = clipText(element.text, 1000);
    if (budget.chars < text.length + 50 || sourceElements.length >= 180) continue;
    budget.chars -= text.length + 50;
    sourceElements.push({ source_element_id: element.id, kind: element.kind, text });
  }

  return {
    document_id: source.document_id,
    detected_type_by_rules: ruleType.type,
    possible_field_keys: fields.map(([key, label, aliases, kind]) => ({ key, label, aliases, kind })),
    source_elements: sourceElements,
    tables,
  };
}

function parseModelResult(payload) {
  const message = payload?.choices?.[0]?.message;
  const candidate = message?.content ?? payload?.result?.response ?? payload?.response ?? payload?.result ?? payload;
  if (typeof candidate === "string") {
    const content = candidate.replace(/<think>[\s\S]*?<\/think>/gi, "").trim();
    const unfenced = content.replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/, "").trim();
    try { return JSON.parse(unfenced); } catch { /* allow provider prose around a JSON object */ }

    // Some OpenAI-compatible providers wrap JSON mode output in prose or a
    // Markdown fence. Find the first complete object without accepting a
    // partial/truncated object; Zod still performs the actual schema check.
    const start = unfenced.indexOf("{");
    if (start >= 0) {
      let depth = 0;
      let inString = false;
      let escaped = false;
      for (let index = start; index < unfenced.length; index++) {
        const char = unfenced[index];
        if (inString) {
          if (escaped) escaped = false;
          else if (char === "\\") escaped = true;
          else if (char === '"') inString = false;
          continue;
        }
        if (char === '"') inString = true;
        else if (char === "{") depth++;
        else if (char === "}" && --depth === 0) {
          try { return JSON.parse(unfenced.slice(start, index + 1)); }
          catch { break; }
        }
      }
    }
    const finishReason = payload?.choices?.[0]?.finish_reason;
    const diagnostic = finishReason === "length" ? " (ответ обрезан лимитом токенов)" : "";
    throw new PolzaAiError(`Polza AI вернул невалидный JSON${diagnostic}`, "POLZA_INVALID_JSON", 502, { finish_reason: finishReason ?? null, output_length: candidate.length });
  }
  if (candidate && typeof candidate === "object") return candidate;
  throw new PolzaAiError("Polza AI вернул пустой ответ", "POLZA_EMPTY_RESPONSE");
}

function timed(promise, ms, provider) {
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new PolzaAiError("Истекло время ожидания Polza AI", "POLZA_TIMEOUT", 504, { provider, validation_status: "not_run" })), ms);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

async function polzaRequest(env, endpoint, body = null) {
  const apiKey = String(env.POLZA_API_KEY ?? "").trim();
  if (!apiKey) throw new PolzaAiError("Polza AI не настроен. Добавьте POLZA_API_KEY в локальные или Worker secrets.", "POLZA_NOT_CONFIGURED", 503, { provider: null });
  const fetcher = env.POLZA_FETCH ?? fetch;
  const response = await fetcher(`${POLZA_BASE_URL}${endpoint}`, {
    method: body === null ? "GET" : "POST",
    headers: { authorization: `Bearer ${apiKey}`, "content-type": "application/json" },
    ...(body === null ? {} : { body: JSON.stringify(body) }),
    signal: AbortSignal.timeout(25_000),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const status = response.status;
    const userStatus = [401, 402, 404, 429].includes(status) ? status : status >= 500 ? 502 : 422;
    const code = status === 401 ? "POLZA_UNAUTHORIZED" : status === 402 ? "POLZA_PAYMENT_REQUIRED" : status === 404 ? "POLZA_MODEL_NOT_FOUND" : status === 429 ? "POLZA_RATE_LIMITED" : status >= 500 ? "POLZA_UPSTREAM_ERROR" : "POLZA_REQUEST_REJECTED";
    const message = payload?.error?.message ?? payload?.message ?? `HTTP ${status}`;
    throw new PolzaAiError(`Polza AI отклонил запрос (${status}): ${message}`, code, userStatus, { provider: "polza_ai", upstream_status: status, reason: message });
  }
  return response.json();
}

async function runPolza(env, body, options = {}) {
  let attempt = 0;
  let useJsonMode = false;
  let lastError;
  while (attempt < (options.maxAttempts ?? 2)) {
    attempt++;
    try {
      const request = { ...body };
      if (useJsonMode) request.response_format = { type: "json_object" };
      return { payload: await polzaRequest(env, "/chat/completions", request), strictSchema: !useJsonMode, attempts: attempt };
    } catch (error) {
      lastError = error;
      if (!useJsonMode && error instanceof PolzaAiError && error.code === "POLZA_REQUEST_REJECTED" && /response_format|json.schema|json_schema|unsupported/i.test(error.message)) {
        useJsonMode = true;
        attempt--;
        continue;
      }
      const status = Number(error?.details?.upstream_status);
      const retryable = !(error instanceof PolzaAiError) || error?.code === "POLZA_NETWORK_ERROR" || error?.code === "POLZA_TIMEOUT" || status === 429 || status >= 500;
      if (!retryable || attempt >= (options.maxAttempts ?? 2)) throw error;
      await new Promise((resolve) => setTimeout(resolve, 200 * attempt));
    }
  }
  throw lastError ?? new PolzaAiError("Polza AI завершил запрос без ответа", "POLZA_EMPTY_RESPONSE");
}

export async function listPolzaModels(env = {}) {
  const payload = await timed(polzaRequest(env, "/models"), 15_000, "polza_ai");
  return payload?.data ?? [];
}

function validateGrounding(result, context, parsed) {
  const source = adaptDocumentParserResult(parsed);
  const elements = new Map(source.elements.map((element) => [element.id, element]));
  const tables = new Map(source.tables.map((table) => [table.id, table]));
  const validFields = new Set(Object.values(fieldDefinitions).flat().map(([key]) => key));
  const fieldCandidates = result.field_candidates.filter((candidate) => {
    const element = elements.get(candidate.source_element_id);
    return validFields.has(candidate.field_key) && element?.source_available !== false && element && String(element.text).includes(candidate.source_value);
  });
  const tableMappings = result.table_mappings.map((mapping) => {
    const table = tables.get(mapping.table_id);
    if (!table) throw new PolzaAiError(`Polza AI сослался на неизвестную таблицу ${mapping.table_id}`, "POLZA_UNGROUNDED_OUTPUT");
  const headerIds = new Set((table.header_cells ?? []).filter((cell) => cell.source_available !== false).flatMap((cell) => [cell.id, ...(cell.source_element_ids ?? [])]));
    const columns = mapping.columns.filter((column) => headerIds.has(column.source_element_id));
    if (columns.length !== mapping.columns.length) throw new PolzaAiError("Polza AI сослался на неизвестный заголовок таблицы", "POLZA_UNGROUNDED_OUTPUT");
    return { ...mapping, columns };
  });
  const availableElementIds = new Set(source.elements.filter((element) => element.source_available !== false).map((element) => element.id));
  const sourceIds = new Set([
    ...context.source_elements.map((element) => element.source_element_id),
    ...context.tables.flatMap((table) => [...table.headers.flatMap((header) => header.source_element_ids ?? [header.source_element_id]), ...table.rows.flatMap((row) => row.cells.map((cell) => cell.source_element_id))]),
  ].filter((id) => availableElementIds.has(id)));
  const groundedFields = fieldCandidates.filter((item) => sourceIds.has(item.source_element_id));
  const groundedTables = tableMappings.map((mapping) => ({
    ...mapping,
    columns: mapping.columns.filter((column) => sourceIds.has(column.source_element_id)),
  }));
  return {
    document_type: result.document_type,
    classification_confidence: result.classification_confidence,
    field_candidates: groundedFields,
    table_mappings: groundedTables,
  };
}

export async function callPolzaForExtraction(parsed, env = {}) {
  const readiness = polzaAiReadiness(env);
  if (!readiness.configured) throw new PolzaAiError("Polza AI не настроен. Добавьте POLZA_API_KEY в локальные или Worker secrets.", "POLZA_NOT_CONFIGURED", 503, { provider: null, validation_status: "not_run" });
  const started = Date.now();
  const context = buildGroundedContext(parsed);
  const input = {
    model: POLZA_MODEL,
    messages: [
      {
        role: "system",
        content: "Ты извлекаешь реквизиты и семантическую структуру финансовых документов на русском языке. Используй только приведённые source_element_id. Для поля верни точную подстроку текста источника, без перефразирования и нормализации. Не придумывай ID, координаты, страницы, адреса ячеек и отсутствующие значения. Для таблиц сопоставляй смысл заголовков; неизвестные колонки помечай unknown, а роли определяй как metadata, line_items, payment_schedule, amendments, reference, summary, appendix или table. Таблицы могут продолжаться на разных страницах внутри одного table_id: используй представительные строки только для понимания схемы, не смешивай разные table_id. Для изменений выделяй parameter, old_value, new_value и reason. Самооценка confidence не является доказательством. Если доказательства нет, не создавай запись. Верни только JSON по схеме.",
      },
      { role: "user", content: JSON.stringify(context) },
    ],
    response_format: { type: "json_schema", json_schema: polzaJsonSchema },
    reasoning: { effort: "none" },
    temperature: 0,
    max_tokens: 4096,
  };
  let raw;
  let strictSchema = true;
  try {
    const response = await timed(runPolza(env, input), 55_000, "polza_ai");
    raw = response.payload;
    strictSchema = response.strictSchema;
  } catch (error) {
    if (error instanceof PolzaAiError) throw new PolzaAiError(error.message, error.code, error.status, { ...error.details, provider: "polza_ai", model: POLZA_MODEL, duration_ms: Date.now() - started });
    const timeout = error?.name === "TimeoutError" || error?.name === "AbortError";
    throw new PolzaAiError(timeout ? "Истекло время ожидания Polza AI" : "Не удалось подключиться к Polza AI", timeout ? "POLZA_TIMEOUT" : "POLZA_NETWORK_ERROR", timeout ? 504 : 502, { provider: "polza_ai", model: POLZA_MODEL, duration_ms: Date.now() - started });
  }
  let parsedResponse;
  try { parsedResponse = groundedResponseSchema.parse(parseModelResult(raw)); }
  catch (error) {
    if (error instanceof PolzaAiError) throw new PolzaAiError(error.message, error.code, error.status, { ...error.details, provider: "polza_ai", model: POLZA_MODEL, duration_ms: Date.now() - started, validation_status: "invalid_json" });
    throw new PolzaAiError("Ответ Polza AI не прошёл локальную проверку выходной схемы", "POLZA_SCHEMA_INVALID", 502, { provider: "polza_ai", model: POLZA_MODEL, duration_ms: Date.now() - started, validation_status: "schema_invalid" });
  }
  let grounded;
  try { grounded = validateGrounding(parsedResponse, context, parsed); }
  catch (error) {
    if (error instanceof PolzaAiError) throw new PolzaAiError(error.message, error.code, error.status, { ...error.details, provider: "polza_ai", model: POLZA_MODEL, duration_ms: Date.now() - started, validation_status: "ungrounded" });
    throw error;
  }
  const sourceColumnCount = (items) => items.reduce((sum, item) => sum + item.columns.length, 0);
  const inputColumnCount = sourceColumnCount(parsedResponse.table_mappings);
  const groundedColumnCount = sourceColumnCount(grounded.table_mappings);
  if (grounded.table_mappings.length !== parsedResponse.table_mappings.length || groundedColumnCount !== inputColumnCount) {
    throw new PolzaAiError("Ответ модели содержал ссылки на отсутствующие или не совпадающие исходные фрагменты", "POLZA_UNGROUNDED_OUTPUT", 502, {
      provider: "polza_ai", model: POLZA_MODEL, duration_ms: Date.now() - started, validation_status: "ungrounded",
      field_candidates_received: parsedResponse.field_candidates.length,
      field_candidates_grounded: grounded.field_candidates.length,
      table_mappings_received: parsedResponse.table_mappings.length,
      table_mappings_grounded: grounded.table_mappings.length,
      table_columns_received: inputColumnCount,
      table_columns_grounded: groundedColumnCount,
    });
  }
  const usage = raw?.usage ?? raw?.result?.usage ?? raw?.meta?.usage ?? null;
  const rejectedFieldCandidates = parsedResponse.field_candidates.length - grounded.field_candidates.length;
  return {
    ...grounded,
    provider: "polza_ai",
    model: POLZA_MODEL,
    called: true,
    response_validated: true,
    validation_status: rejectedFieldCandidates
      ? strictSchema ? "strict_schema_grounded_candidates_filtered" : "json_mode_locally_validated_grounded_candidates_filtered"
      : strictSchema ? "strict_schema_and_grounded" : "json_mode_locally_validated_and_grounded",
    duration_ms: Date.now() - started,
    usage,
  };
}

