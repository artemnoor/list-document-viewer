import { sql } from "drizzle-orm";
import { apiRateLimits } from "../../db/schema.ts";
import { rateWindow } from "./policy.mjs";

export async function consumeRateLimit(db, ownerId, action, limit, windowSeconds, nowSeconds = Math.floor(Date.now() / 1000)) {
  const windowStart = rateWindow(nowSeconds, windowSeconds);
  await db.insert(apiRateLimits).values({
    id: globalThis.crypto.randomUUID(),
    ownerId: String(ownerId),
    action,
    windowStart,
    requestCount: 1,
  }).onConflictDoUpdate({
    target: [apiRateLimits.ownerId, apiRateLimits.action, apiRateLimits.windowStart],
    set: { requestCount: sql`${apiRateLimits.requestCount} + 1` },
  });
  const [row] = await db.select({ requestCount: apiRateLimits.requestCount })
    .from(apiRateLimits)
    .where(sql`${apiRateLimits.ownerId} = ${String(ownerId)} AND ${apiRateLimits.action} = ${action} AND ${apiRateLimits.windowStart} = ${windowStart}`)
    .limit(1);
  return { allowed: Number(row?.requestCount ?? 0) <= limit, count: Number(row?.requestCount ?? 0), limit, resets_at: windowStart + windowSeconds };
}
