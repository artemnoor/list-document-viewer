import type { Sql } from "postgres";
import type { AnalysisProgressState, LinkingResult, Link } from "../src/linking/types";

export type JobStatus = "queued" | "running" | "retrying" | "completed" | "failed";
export type AnalysisJob = {
  id: string; status: JobStatus; idempotency_key: string; payload_hash: string; payload_chunk_count: number;
  progress_json: AnalysisProgressState; attempts: number; lease_expires_at_ms: number | null; last_error: string | null;
  run_id: string | null; result_json: LinkingResult | null; created_at: string; updated_at: string;
};

export class PostgresStorage {
  constructor(readonly sql: Sql) {}
  async health(): Promise<boolean> { await this.sql`SELECT 1`; return true; }
  async rateLimit(bucket: string, limit: number, windowSeconds = 600): Promise<boolean> {
    const rows = await this.sql<{ request_count: number }[]>`
      INSERT INTO api_rate_limits(bucket_key, window_started, request_count) VALUES (${bucket}, now(), 1)
      ON CONFLICT(bucket_key) DO UPDATE SET
        request_count = CASE WHEN api_rate_limits.window_started < now() - (${windowSeconds} * interval '1 second') THEN 1 ELSE api_rate_limits.request_count + 1 END,
        window_started = CASE WHEN api_rate_limits.window_started < now() - (${windowSeconds} * interval '1 second') THEN now() ELSE api_rate_limits.window_started END
      RETURNING request_count`;
    return Number(rows[0].request_count) <= limit;
  }
  async readProgress(payloadHash: string): Promise<AnalysisProgressState | undefined> {
    const rows = await this.sql<{ state_json: AnalysisProgressState }[]>`SELECT state_json FROM analysis_progress WHERE payload_hash=${payloadHash}`;
    const state = rows[0]?.state_json;
    return state && [1, 2].includes(state.version) && Array.isArray(state.completed_fragments) ? state : undefined;
  }
  async saveProgress(payloadHash: string, state: AnalysisProgressState): Promise<void> {
    await this.sql`INSERT INTO analysis_progress(payload_hash, updated_at, state_json) VALUES (${payloadHash}, now(), ${this.sql.json(state)}::jsonb) ON CONFLICT(payload_hash) DO UPDATE SET updated_at=now(), state_json=EXCLUDED.state_json`;
  }
  async findRunByIdempotency(key: string): Promise<{ payload_hash: string; result_json: LinkingResult } | undefined> {
    const rows = await this.sql<{ payload_hash: string; result_json: LinkingResult }[]>`SELECT payload_hash, result_json FROM linking_runs WHERE idempotency_key=${key}`;
    return rows[0];
  }
  async saveRun(result: LinkingResult, key: string, payloadHash: string): Promise<void> {
    await this.sql.begin(async tx => {
      await tx`INSERT INTO linking_runs(id, contract_version, created_at, input_documents_json, result_json, idempotency_key, payload_hash) VALUES(${result.linking_run_id},${result.contract_version},${result.created_at},${tx.json(result.input_documents)}::jsonb,${tx.json(result)}::jsonb,${key},${payloadHash})`;
      for (const link of result.links) await tx`INSERT INTO links(id, run_id, source_document_id, target_document_id, relationship_type, status, confidence, payload_json) VALUES(${link.link_id},${result.linking_run_id},${link.source_document_id},${link.target_document_id},${link.relationship_type},${link.status},${link.confidence},${tx.json(link)}::jsonb)`;
      await tx`DELETE FROM analysis_progress WHERE payload_hash=${payloadHash}`;
    });
  }
  async readRunJson(id: string): Promise<LinkingResult | null> {
    const rows = await this.sql<{ result_json: LinkingResult }[]>`SELECT result_json FROM linking_runs WHERE id=${id}`; return rows[0]?.result_json ?? null;
  }
  async readRun(id: string): Promise<LinkingResult | null> { return this.readRunJson(id); }
  async updateDecision(oldResult: LinkingResult, result: LinkingResult, link: Link): Promise<boolean> {
    return this.sql.begin(async tx => {
      const updated = await tx<{ id: string }[]>`UPDATE linking_runs SET result_json=${tx.json(result)}::jsonb WHERE id=${result.linking_run_id} AND result_json=${tx.json(oldResult)}::jsonb RETURNING id`;
      if (updated.length !== 1) return false;
      await tx`UPDATE links SET status=${link.status}, payload_json=${tx.json(link)}::jsonb WHERE id=${link.link_id} AND run_id=${result.linking_run_id}`;
      return true;
    });
  }
  async findJobByIdempotency(key: string): Promise<Pick<AnalysisJob, "id" | "status" | "payload_hash"> | undefined> {
    const rows = await this.sql<Pick<AnalysisJob, "id" | "status" | "payload_hash">[]>`SELECT id,status,payload_hash FROM analysis_jobs WHERE idempotency_key=${key}`; return rows[0];
  }
  async readJob(id: string): Promise<AnalysisJob | undefined> {
    const rows = await this.sql<AnalysisJob[]>`SELECT id,status,idempotency_key,payload_hash,payload_chunk_count,progress_json,attempts,lease_expires_at_ms,last_error,run_id,result_json,created_at::text,updated_at::text FROM analysis_jobs WHERE id=${id}`; return rows[0];
  }
  async listRecoverableJobIds(): Promise<string[]> {
    const rows = await this.sql<{ id: string }[]>`SELECT id FROM analysis_jobs WHERE status IN ('queued','running','retrying') ORDER BY created_at`;
    return rows.map(row => row.id);
  }
  async createJob(args: { id: string; key: string; payloadHash: string; payload: string }): Promise<void> {
    const chunks: string[] = []; for (let offset = 0; offset < args.payload.length; offset += 100_000) chunks.push(args.payload.slice(offset, offset + 100_000));
    await this.sql.begin(async tx => {
      const initial = { version: 2, started_at: new Date().toISOString(), fragment_budget_tokens: 0, completed_fragments: [], requested_source_fragments: [], context_rounds: 0, calls: 0, input_tokens: 0, output_tokens: 0, cost_amount: 0, has_cost: false };
      await tx`INSERT INTO analysis_jobs(id,status,idempotency_key,payload_hash,payload_chunk_count,progress_json) VALUES(${args.id},'queued',${args.key},${args.payloadHash},${chunks.length},${tx.json(initial)}::jsonb)`;
      for (let index = 0; index < chunks.length; index++) await tx`INSERT INTO analysis_job_payload_chunks(job_id,chunk_index,payload_text) VALUES(${args.id},${index},${chunks[index]})`;
    });
  }
  async readJobPayload(job: AnalysisJob): Promise<string> {
    const rows = await this.sql<{ payload_text: string }[]>`SELECT payload_text FROM analysis_job_payload_chunks WHERE job_id=${job.id} ORDER BY chunk_index`;
    if (rows.length !== job.payload_chunk_count) throw new Error("В сохранённом задании отсутствуют части исходного пакета"); return rows.map(row => row.payload_text).join("");
  }
  async claimJob(id: string, leaseMs: number): Promise<AnalysisJob | undefined> {
    const now = Date.now();
    const rows = await this.sql<AnalysisJob[]>`UPDATE analysis_jobs SET status='running', attempts=attempts+1, lease_expires_at_ms=${now + leaseMs}, updated_at=now(), last_error=NULL
      WHERE id=${id} AND status IN ('queued','retrying','running') AND (status <> 'running' OR lease_expires_at_ms IS NULL OR lease_expires_at_ms < ${now})
      RETURNING id,status,idempotency_key,payload_hash,payload_chunk_count,progress_json,attempts,lease_expires_at_ms,last_error,run_id,result_json,created_at::text,updated_at::text`;
    return rows[0];
  }
  async saveJobProgress(id: string, state: AnalysisProgressState, leaseMs: number): Promise<void> {
    await this.sql`UPDATE analysis_jobs SET progress_json=${this.sql.json(state)}::jsonb, updated_at=now(), lease_expires_at_ms=${Date.now() + leaseMs} WHERE id=${id} AND status='running'`;
  }
  async heartbeatJob(id: string, leaseMs: number): Promise<void> {
    await this.sql`UPDATE analysis_jobs SET lease_expires_at_ms=${Date.now() + leaseMs},updated_at=now() WHERE id=${id} AND status='running'`;
  }
  async completeJob(id: string, result: LinkingResult): Promise<void> {
    await this.sql`UPDATE analysis_jobs SET status='completed',run_id=${result.linking_run_id},result_json=${this.sql.json(result)}::jsonb,completed_at=now(),updated_at=now(),lease_expires_at_ms=NULL,last_error=NULL WHERE id=${id}`;
  }
  async failJob(id: string, error: string, retrying: boolean): Promise<void> {
    await this.sql`UPDATE analysis_jobs SET status=${retrying ? "retrying" : "failed"},last_error=${error.slice(0, 2000)},updated_at=now(),lease_expires_at_ms=NULL WHERE id=${id} AND status <> 'completed'`;
  }
  async resetFailedJob(id: string): Promise<boolean> {
    const rows = await this.sql<{ id: string }[]>`UPDATE analysis_jobs SET status='queued',last_error=NULL,lease_expires_at_ms=NULL,updated_at=now() WHERE id=${id} AND status='failed' RETURNING id`; return rows.length === 1;
  }
  async markRetrying(id: string): Promise<void> { await this.sql`UPDATE analysis_jobs SET status='retrying',updated_at=now() WHERE id=${id} AND status='running'`; }
  async close(): Promise<void> { await this.sql.end({ timeout: 5 }); }
}
