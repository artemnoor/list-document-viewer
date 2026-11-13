import { readdir, readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import postgres from "postgres";

function getDatabaseUrl(): string {
  const url = process.env.DATABASE_URL;
  if (!url) throw new Error("DATABASE_URL is required to run PostgreSQL migrations");
  return url;
}

export async function runMigrations(sql = postgres(getDatabaseUrl())) {
  await sql.begin(async tx => {
    await tx`SELECT pg_advisory_xact_lock(719402611)`;
    await tx`CREATE TABLE IF NOT EXISTS schema_migrations(version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())`;
    const directory = resolve(process.cwd(), "migrations/postgres");
    const files = (await readdir(directory)).filter(name => name.endsWith(".sql")).sort();
    for (const file of files) {
      const version = file.replace(/\.sql$/, "");
      const applied = await tx<{ version: string }[]>`SELECT version FROM schema_migrations WHERE version=${version}`;
      if (applied.length) continue;
      await tx.unsafe(await readFile(resolve(directory, file), "utf8"));
      await tx`INSERT INTO schema_migrations(version) VALUES(${version})`;
    }
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const sql = postgres(getDatabaseUrl());
  runMigrations(sql).then(() => console.log("PostgreSQL migrations are current")).catch(error => { console.error("PostgreSQL migration failed:", error); process.exitCode = 1; }).finally(() => sql.end({ timeout: 5 }));
}
