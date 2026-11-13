export const QUALITY_Q1 = Object.freeze({ calls: 40, inputPerCall: 16000, outputPerCall: 4000, inputTotal: 500000, outputTotal: 100000, runMs: 1200000 });
export type QualityAttempt = { index: number; stage: string; model: string; estimated_input_tokens: number; reserved_output_tokens: number; started_at: string; duration_ms?: number; state: "sending" | "received" | "transport_error"; http_status?: number; raw_output?: unknown; finish_reason?: string; usage?: any; error?: string };
export type QualityLedger = { started_at: string; attempts: QualityAttempt[] };

/** Estimate decoded model-visible text plus a fixed allowance for provider schema and request metadata. */
export function estimateRequestInputTokens(body: any): number {
  const content = Array.isArray(body?.messages) ? body.messages.reduce((sum: number, message: any) => sum + (typeof message?.content === "string" ? message.content.length : 0), 0) : 0;
  return Math.ceil(content / 2) + 200;
}

/** Shared by Extraction and Linking, including transport retries and repair calls. */
export function createQualityTransport(args: { fetcher: typeof fetch; ledger: QualityLedger; save: () => Promise<void>; stage: () => string }) {
  let inFlight = false;
  const totals = () => {
    let input = 0, output = 0, cost = 0; let inputKnown = true, outputKnown = true, costKnown = true;
    const currencies = new Set<string>();
    for (const attempt of args.ledger.attempts) {
      const prompt = attempt.usage?.prompt_tokens, completion = attempt.usage?.completion_tokens;
      input += Number.isFinite(prompt) ? prompt : attempt.estimated_input_tokens;
      output += Number.isFinite(completion) ? completion : attempt.reserved_output_tokens;
      inputKnown &&= Number.isFinite(prompt); outputKnown &&= Number.isFinite(completion);
      const amount = attempt.usage?.cost;
      if (Number.isFinite(amount)) { cost += amount; if (attempt.usage?.cost_currency) currencies.add(attempt.usage.cost_currency); else costKnown = false; }
      else costKnown = false;
    }
    return { calls: args.ledger.attempts.length, accounted_input_tokens: input, accounted_output_tokens: output,
      actual_input_tokens: inputKnown ? input : null, actual_output_tokens: outputKnown ? output : null,
      cost_amount: costKnown && currencies.size === 1 ? cost : null, cost_currency: costKnown && currencies.size === 1 ? [...currencies][0] : null,
      accounting: inputKnown && outputKnown ? "provider_usage" : "includes_conservative_reservations" };
  };
  const fetcher: typeof fetch = async (url, init) => {
    if (String(url) !== "https://polza.ai/api/v1/chat/completions") throw new Error("QUALITY_PROVIDER_ENDPOINT_REJECTED");
    if (inFlight) throw new Error("QUALITY_Q1_INFLIGHT_LIMIT");
    if (args.ledger.attempts.some(attempt => attempt.state === "sending")) throw new Error("QUALITY_UNCERTAIN_PRIOR_SEND_REQUIRES_RECONCILIATION");
    const body = JSON.parse(String(init?.body));
    if (!["google/gemma-4-26b-a4b-it", "deepseek/deepseek-v4-flash"].includes(body.model)) throw new Error("QUALITY_MODEL_REJECTED");
    const estimated = estimateRequestInputTokens(body), reserved = body.max_tokens;
    const used = totals();
    if (!Number.isInteger(reserved) || reserved < 1 || reserved > QUALITY_Q1.outputPerCall || estimated > QUALITY_Q1.inputPerCall) throw new Error("QUALITY_Q1_REQUEST_TOKEN_LIMIT");
    if (used.calls >= QUALITY_Q1.calls || used.accounted_input_tokens + estimated > QUALITY_Q1.inputTotal || used.accounted_output_tokens + reserved > QUALITY_Q1.outputTotal) throw new Error("QUALITY_Q1_RUN_BUDGET_EXCEEDED");
    if (Date.now() - Date.parse(args.ledger.started_at) >= QUALITY_Q1.runMs) throw new Error("QUALITY_Q1_RUN_TIME_LIMIT");
    const attempt: QualityAttempt = { index: used.calls + 1, stage: args.stage(), model: body.model, estimated_input_tokens: estimated, reserved_output_tokens: reserved, started_at: new Date().toISOString(), state: "sending" };
    args.ledger.attempts.push(attempt); inFlight = true;
    const started = Date.now();
    try {
      await args.save();
      const response = await args.fetcher(url, init);
      const payload = await response.clone().json().catch(() => null);
      attempt.state = "received"; attempt.http_status = response.status;
      attempt.raw_output = payload?.choices?.[0]?.message?.content ?? payload?.response ?? null;
      attempt.finish_reason = payload?.choices?.[0]?.finish_reason;
      attempt.usage = payload?.usage ? { ...payload.usage } : undefined;
      if (typeof payload?.cost === "number") attempt.usage = { ...attempt.usage, cost: payload.cost, cost_currency: payload.cost_currency ?? payload.currency ?? attempt.usage?.cost_currency };
      const receivedTotals = totals();
      if (attempt.usage?.prompt_tokens > QUALITY_Q1.inputPerCall || attempt.usage?.completion_tokens > QUALITY_Q1.outputPerCall || receivedTotals.accounted_input_tokens > QUALITY_Q1.inputTotal || receivedTotals.accounted_output_tokens > QUALITY_Q1.outputTotal) throw new Error("QUALITY_PROVIDER_USAGE_EXCEEDED_Q1");
      return response;
    } catch (error: any) { if (attempt.state !== "received") attempt.state = "transport_error"; attempt.error = String(error?.message ?? error); throw error; }
    finally { attempt.duration_ms = Date.now() - started; inFlight = false; await args.save(); }
  };
  return { fetcher, totals };
}
