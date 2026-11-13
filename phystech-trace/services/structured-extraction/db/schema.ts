import { sql } from "drizzle-orm";
import { index, integer, sqliteTable, text, uniqueIndex } from "drizzle-orm/sqlite-core";

export const documents = sqliteTable("documents", {
  id: text("id").primaryKey(),
  title: text("title").notNull(),
  fileName: text("file_name").notNull(),
  format: text("format").notNull(),
  isDemo: integer("is_demo", { mode: "boolean" }).notNull().default(false),
  parserJson: text("parser_json").notNull(),
  ownerId: text("owner_id"),
  isSynthetic: integer("is_synthetic", { mode: "boolean" }).notNull().default(false),
  inputVersion: integer("input_version").notNull().default(1),
  extractionVersion: integer("extraction_version").notNull().default(0),
  createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updatedAt: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  lastExtractionId: text("last_extraction_id"),
});

export const extractionRuns = sqliteTable("extraction_runs", {
  id: text("id").primaryKey(),
  documentId: text("document_id").notNull().references(() => documents.id, { onDelete: "cascade" }),
  ownerId: text("owner_id"),
  version: integer("version").notNull(),
  documentType: text("document_type").notNull(),
  schemaVersion: text("schema_version").notNull(),
  inputVersion: integer("input_version").notNull().default(1),
  inputHash: text("input_hash").notNull().default(""),
  mode: text("mode").notNull().default("llm_assisted"),
  status: text("status").notNull().default("completed"),
  model: text("model"),
  provider: text("provider"),
  error: text("error"),
  payload: text("payload").notNull(),
  createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (table) => ({
  documentVersion: uniqueIndex("extraction_runs_document_version_uq").on(table.documentId, table.version),
  documentIndex: index("extraction_runs_document_idx").on(table.documentId, table.createdAt),
}));

export const apiRateLimits = sqliteTable("api_rate_limits", {
  id: text("id").primaryKey(),
  ownerId: text("owner_id").notNull(),
  action: text("action").notNull(),
  windowStart: integer("window_start").notNull(),
  requestCount: integer("request_count").notNull().default(1),
}, (table) => ({
  ownerActionWindow: uniqueIndex("api_rate_limits_owner_action_window_uq").on(table.ownerId, table.action, table.windowStart),
}));
