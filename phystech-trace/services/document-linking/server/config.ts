import "dotenv/config";

const MIB = 1024 * 1024;
const weakSecretFragments = ["replace-with", "change-me", "changeme", "local-development", "your-secret", "example", "password", "default", "test-token"];

export class ConfigurationError extends Error {
  constructor(message: string) { super(message); this.name = "ConfigurationError"; }
}

function positiveInteger(env: NodeJS.ProcessEnv, name: string, fallback: number, min: number, max: number): number {
  const raw = env[name];
  if (raw === undefined || raw === "") return fallback;
  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value < min || value > max) throw new ConfigurationError(`${name} must be an integer from ${min} to ${max}`);
  return value;
}

export function validateStrongSecret(name: string, value: string | undefined): asserts value is string {
  if (!value || value.length < 32 || new Set(value).size < 12 || weakSecretFragments.some(fragment => value.toLowerCase().includes(fragment))) {
    throw new ConfigurationError(`${name} must be a unique secret of at least 32 characters; example and default values are not allowed`);
  }
}

export function validateProductionSecrets(env: NodeJS.ProcessEnv): void {
  validateStrongSecret("POSTGRES_PASSWORD", env.POSTGRES_PASSWORD);
  if (!/^[A-Za-z0-9_-]+$/.test(env.POSTGRES_PASSWORD)) {
    throw new ConfigurationError("POSTGRES_PASSWORD must use URL-safe characters (letters, numbers, _ or -)");
  }
  validateStrongSecret("API_BEARER_TOKEN", env.API_BEARER_TOKEN);
  if (env.POSTGRES_PASSWORD === env.API_BEARER_TOKEN) throw new ConfigurationError("POSTGRES_PASSWORD and API_BEARER_TOKEN must be different secrets");
}

export function readConfig(env: NodeJS.ProcessEnv = process.env) {
  const production = env.NODE_ENV === "production";
  if (production) validateStrongSecret("API_BEARER_TOKEN", env.API_BEARER_TOKEN);

  const databaseUrl = env.DATABASE_URL ?? "postgres://document_linking:document_linking@127.0.0.1:5432/document_linking";
  const redisUrl = env.REDIS_URL ?? "redis://127.0.0.1:6379";
  if (production) {
    let db: URL;
    let redis: URL;
    try { db = new URL(databaseUrl); redis = new URL(redisUrl); }
    catch { throw new ConfigurationError("DATABASE_URL and REDIS_URL must be valid URLs"); }
    if (!['postgres:', 'postgresql:'].includes(db.protocol) || !db.username || !db.password) throw new ConfigurationError("DATABASE_URL must include PostgreSQL credentials");
    const databasePassword = decodeURIComponent(db.password);
    validateStrongSecret("DATABASE_URL password", databasePassword);
    if (env.POSTGRES_PASSWORD && databasePassword !== env.POSTGRES_PASSWORD) throw new ConfigurationError("DATABASE_URL credentials must match POSTGRES_PASSWORD");
    if (databasePassword === env.API_BEARER_TOKEN) throw new ConfigurationError("DATABASE_URL password and API_BEARER_TOKEN must be different secrets");
    if (!['redis:', 'rediss:'].includes(redis.protocol)) throw new ConfigurationError("REDIS_URL must use redis:// or rediss://");
  }

  const maxRequestMb = positiveInteger(env, "MAX_REQUEST_SIZE_MB", 32, 1, 256);
  const maxDocumentMb = positiveInteger(env, "MAX_DOCUMENT_SIZE_MB", 16, 1, 256);
  const maxDocumentSetMb = positiveInteger(env, "MAX_DOCUMENT_SET_SIZE_MB", 30, 1, 256);
  const maxDocuments = positiveInteger(env, "MAX_DOCUMENTS", 100, 1, 500);
  if (maxDocumentMb > maxDocumentSetMb || maxDocumentSetMb > maxRequestMb) throw new ConfigurationError("MAX_DOCUMENT_SIZE_MB must be <= MAX_DOCUMENT_SET_SIZE_MB <= MAX_REQUEST_SIZE_MB");

  return {
    production,
    port: positiveInteger(env, "PORT", 3000, 1, 65535),
    host: env.HOST ?? "0.0.0.0",
    databaseUrl,
    redisUrl,
    apiToken: env.API_BEARER_TOKEN,
    polzaApiKey: env.POLZA_API_KEY ?? env.POLZA_AI_API_KEY,
    llmEnabled: env.LLM_ENABLED !== "false",
    requireExternalLlmConsent: env.REQUIRE_EXTERNAL_LLM_CONSENT === "true",
    maxCalls: positiveInteger(env, "LLM_MAX_CALLS_PER_RUN", 52, 1, 52),
    timeoutMs: positiveInteger(env, "LLM_TIMEOUT_MS", 90_000, 1_000, 120_000),
    maxInputTokens: positiveInteger(env, "LLM_MAX_INPUT_TOKENS", 180_000, 1_000, 230_000),
    maxRunMs: positiveInteger(env, "LLM_MAX_RUN_MS", 900_000, 10_000, 900_000),
    pgPoolSize: positiveInteger(env, "PG_POOL_SIZE", 10, 1, 100),
    maxRequestBytes: maxRequestMb * MIB,
    maxDocumentBytes: maxDocumentMb * MIB,
    maxDocumentSetBytes: maxDocumentSetMb * MIB,
    maxDocuments,
  };
}
