import { serve } from "@hono/node-server";
import postgres from "postgres";
import { createApp } from "./app";
import { readConfig } from "./config";
import { runMigrations } from "./migrate";
import { createAnalysisQueue } from "./queue";
import { PostgresStorage } from "./storage";

const config = readConfig(), pool = postgres(config.databaseUrl, { max: config.pgPoolSize });
const storage = new PostgresStorage(pool), queue = createAnalysisQueue(config.redisUrl);
await runMigrations(pool);
const app = createApp({ storage, queue, config });
const server = serve({ fetch: app.fetch, port: config.port, hostname: config.host }, info => console.log(`Document Linking API listening on http://${info.address}:${info.port}`));
const shutdown = async () => { server.close(); await queue.close(); await pool.end({ timeout: 5 }); process.exit(0); };
process.once("SIGINT", shutdown); process.once("SIGTERM", shutdown);
