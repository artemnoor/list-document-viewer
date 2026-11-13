import postgres from "postgres";
import { readConfig } from "./config";
import { runMigrations } from "./migrate";
import { PostgresStorage } from "./storage";
import { createAnalysisQueue } from "./queue";
import { recoverPendingJobs, startAnalysisWorker } from "./worker";

const config = readConfig(), pool = postgres(config.databaseUrl, { max: 5 });
const storage = new PostgresStorage(pool);
await runMigrations(pool);
const recoveryQueue = createAnalysisQueue(config.redisUrl);
const recovered = await recoverPendingJobs(storage, recoveryQueue);
await recoveryQueue.close();
const { worker, connection } = startAnalysisWorker(config.redisUrl, {
  storage, apiKey: config.polzaApiKey ?? "", maxCalls: config.maxCalls, maxInputTokens: config.maxInputTokens,
  timeoutMs: config.timeoutMs, maxRunMs: config.maxRunMs,
});
console.log(`BullMQ Document Linking worker is ready; recovered ${recovered} pending jobs`);
const shutdown = async () => { await worker.close(); await connection.quit(); await pool.end({ timeout: 5 }); process.exit(0); };
process.once("SIGINT", shutdown); process.once("SIGTERM", shutdown);
