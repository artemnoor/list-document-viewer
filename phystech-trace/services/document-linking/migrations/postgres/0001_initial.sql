CREATE TABLE IF NOT EXISTS api_rate_limits (
  bucket_key text PRIMARY KEY,
  window_started timestamptz NOT NULL DEFAULT now(),
  request_count integer NOT NULL CHECK (request_count >= 0)
);

CREATE TABLE IF NOT EXISTS analysis_progress (
  payload_hash text PRIMARY KEY,
  updated_at timestamptz NOT NULL DEFAULT now(),
  state_json jsonb NOT NULL
);

CREATE TABLE IF NOT EXISTS linking_runs (
  id uuid PRIMARY KEY,
  contract_version text NOT NULL,
  created_at timestamptz NOT NULL,
  input_documents_json jsonb NOT NULL,
  result_json jsonb NOT NULL,
  idempotency_key text NOT NULL UNIQUE,
  payload_hash text NOT NULL
);
CREATE INDEX IF NOT EXISTS linking_runs_payload_hash_idx ON linking_runs(payload_hash);

CREATE TABLE IF NOT EXISTS links (
  id uuid PRIMARY KEY,
  run_id uuid NOT NULL REFERENCES linking_runs(id) ON DELETE CASCADE,
  source_document_id text NOT NULL,
  target_document_id text NOT NULL,
  relationship_type text NOT NULL,
  status text NOT NULL,
  confidence double precision NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
  payload_json jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS links_run_id_idx ON links(run_id);

CREATE TABLE IF NOT EXISTS analysis_jobs (
  id uuid PRIMARY KEY,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  status text NOT NULL CHECK (status IN ('queued','running','retrying','completed','failed')),
  idempotency_key text NOT NULL UNIQUE,
  payload_hash text NOT NULL,
  payload_chunk_count integer NOT NULL CHECK (payload_chunk_count > 0),
  progress_json jsonb NOT NULL,
  attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  lease_expires_at_ms bigint,
  last_error text,
  run_id uuid REFERENCES linking_runs(id),
  result_json jsonb,
  completed_at timestamptz
);
CREATE INDEX IF NOT EXISTS analysis_jobs_status_idx ON analysis_jobs(status, updated_at);
CREATE INDEX IF NOT EXISTS analysis_jobs_payload_hash_idx ON analysis_jobs(payload_hash);

CREATE TABLE IF NOT EXISTS analysis_job_payload_chunks (
  job_id uuid NOT NULL REFERENCES analysis_jobs(id) ON DELETE CASCADE,
  chunk_index integer NOT NULL CHECK (chunk_index >= 0),
  payload_text text NOT NULL,
  PRIMARY KEY(job_id, chunk_index)
);
