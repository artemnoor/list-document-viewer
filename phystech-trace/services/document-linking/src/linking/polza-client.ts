export const POLZA_BASE_URL = "https://polza.ai/api/v1";
export const POLZA_MODEL = "google/gemma-4-26b-a4b-it";
const MAX_RETRY_AFTER_MS = 15 * 60 * 1000;

export type PolzaJsonResponse<T = unknown> = { value: T; model: string; finishReason?: string; promptTokens: number; completionTokens: number; cost?: number; currency?: string };

export class PolzaRequestError extends Error {
  constructor(message: string, readonly status: number, readonly retryable: boolean, readonly retryAfterMs?: number) {
    super(message);
    this.name = "PolzaRequestError";
  }
}

function parseRetryAfter(value: string | null, now = Date.now()): number | undefined {
  if (!value) return undefined;
  const seconds = Number(value);
  const milliseconds = Number.isFinite(seconds) && seconds >= 0 ? seconds * 1000 : Date.parse(value) - now;
  if (!Number.isFinite(milliseconds) || milliseconds < 0) return undefined;
  return Math.min(MAX_RETRY_AFTER_MS, Math.ceil(milliseconds));
}

function providerError(status: number, retryAfter: string | null): PolzaRequestError {
  if (status === 401) return new PolzaRequestError("Polza AI отклонил ключ API (HTTP 401)", 401, false);
  if (status === 403) return new PolzaRequestError("Для аккаунта Polza AI нет доступа к модели (HTTP 403)", 403, false);
  if (status === 402) return new PolzaRequestError("Недостаточный баланс Polza AI (HTTP 402)", 402, false);
  if (status === 429) return new PolzaRequestError("Polza AI ограничил частоту запросов (HTTP 429)", 429, true, parseRetryAfter(retryAfter));
  if (status >= 500) return new PolzaRequestError(`Polza AI временно недоступен (HTTP ${status})`, status, true);
  return new PolzaRequestError(`Polza AI отклонил запрос (HTTP ${status})`, status, false);
}

export async function requestPolzaJson<T = unknown>(args: { apiKey: string; model: string; timeoutMs: number; maxTokens: number; systemPrompt: string; userContent: string; onInvalidJsonResponse?: (response: { rawText: string; model: string; promptTokens: number; completionTokens: number; cost?: number; currency?: string }) => Promise<void> | void }): Promise<PolzaJsonResponse<T>> {
  if (args.model !== POLZA_MODEL) throw new PolzaRequestError(`Разрешена только модель ${POLZA_MODEL}`, 400, false);
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), args.timeoutMs);
  try {
    let response: Response;
    try {
      response = await fetch(`${POLZA_BASE_URL}/chat/completions`, {
        method: "POST", signal: controller.signal,
        headers: { Authorization: `Bearer ${args.apiKey}`, "Content-Type": "application/json" },
        body: JSON.stringify({ model: args.model, temperature: 0, max_tokens: args.maxTokens, response_format: { type: "json_object" }, messages: [{ role: "system", content: args.systemPrompt }, { role: "user", content: args.userContent }] }),
      });
    } catch (error: any) {
      if (error?.name === "AbortError") throw new PolzaRequestError(`Истекло время ожидания Polza (${args.timeoutMs} мс)`, 504, true);
      throw new PolzaRequestError("Временная сетевая ошибка при обращении к Polza AI", 503, true);
    }
    if (!response.ok) throw providerError(response.status, response.headers.get("retry-after"));

    let body: any;
    try { body = await response.json(); }
    catch { throw new PolzaRequestError("Polza AI вернул некорректный ответ", 502, true); }
    const usage = body.usage ?? {};
    if (body.model && body.model !== POLZA_MODEL) throw new PolzaRequestError("Polza AI вернул неожиданный ID модели", 502, false);
    let value: T;
    const rawText = body.choices?.[0]?.message?.content || "";
    const cost = typeof usage.cost === "number" ? usage.cost : typeof body.cost === "number" ? body.cost : undefined;
    const currency = usage.cost_currency ?? usage.currency ?? body.cost_currency ?? body.currency;
    try { value = JSON.parse(rawText) as T; }
    catch {
      await args.onInvalidJsonResponse?.({ rawText, model: body.model ?? args.model, promptTokens: Number(usage.prompt_tokens) || 0, completionTokens: Number(usage.completion_tokens) || 0, ...(cost !== undefined ? { cost } : {}), ...(currency ? { currency } : {}) });
      throw new PolzaRequestError("Gemma вернула невалидный JSON", 502, true);
    }
    return { value, model: body.model ?? args.model, finishReason: body.choices?.[0]?.finish_reason, promptTokens: Number(usage.prompt_tokens) || 0, completionTokens: Number(usage.completion_tokens) || 0, ...(cost !== undefined ? { cost } : {}), ...(currency ? { currency } : {}) };
  } finally { clearTimeout(timer); }
}
