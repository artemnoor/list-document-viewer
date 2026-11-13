# Controlled Polza quality E2E

This harness is prepared for a separately approved live evaluation. **No paid calls have been made while preparing it.** Running the default command never sends a network request, even when `POLZA_API_KEY` exists.

The tested boundary is committed Parser JSON → real DeepSeek V4 Flash LLM-assisted Extraction → real Gemma 4 26B A4B Linking. This is not a repeat of OCR, Gateway, browser, or deployment checks. `quality-live-full.json` pins five existing demo Parser snapshots (contract, act, invoice, KFZ, registry) and the corresponding frozen Linking fixtures. `quality-live-compact.json` contains the first three. For native PDF/XLSX/DOCX Parser snapshots, supply an additional manifest with the same shape and paths to the existing native fixtures; the extraction inventory regressions separately cover those fixtures.

## Plan without any provider call

From `phystech-trace/services/document-linking`, with installed dependencies:

```powershell
node --import tsx scripts/polza-quality-e2e.ts --manifest evaluation/quality-live-full.json --out reports/quality-plan --repeats 5
```

The result pins byte SHA-256, canonical Parser input hashes, prompt hash, model IDs, Q1 parameters and repeat count. It records nominal Extraction calls and the current pure semantic Linking plan. The latter uses frozen existing Extraction fixtures for planning only: **live extraction outputs are always passed to Linking directly**. Dynamic candidate verification and repair counts cannot be known before the model chooses candidates. A minimum below 40 does not prove that every live output will fit the budget.

Use `--linking-only` to run or plan just Gemma against the frozen committed Extraction fixtures. This mode makes the same-input Linking comparison reproducible and can use existing Linking gold; it is explicitly not a full Extraction+Linking E2E.

## Future live command — requires separate user approval

Only after approval of these documents, the provider exposure, the number of repeats and the expense ceiling, set `POLZA_API_KEY` locally and run:

```powershell
node --import tsx scripts/polza-quality-e2e.ts --manifest evaluation/quality-live-full.json --out reports/quality-approved-live --repeats 5 --live
```

The key is never written to artifacts. No model/endpoint override or rules-only fallback exists. `--live` is a deliberate opt-in, not permission for the agent to run it. Five independent runs can make **up to 200 paid requests in total**; the Q1 limit is 40 across Extraction+Linking **per run**, including failed attempts, transport retries and repairs. Approval should normally start with one repeat, inspect the evidence and actual spend, then approve the remaining exposure explicitly in a fresh output directory. A numeric cost ceiling is not promised without reliable provider pricing.

The shared transport checks before every send:

- Polza endpoint and the two pinned models;
- at most one in-flight request;
- 16000 estimated input tokens, including request/schema overhead, and 4000 reserved output tokens per request;
- 40 calls, 500000 input and 100000 output tokens per run;
- 20 minutes of run wall time.

When usage is missing, conservative token reservations remain charged; missing expense/currency is reported as unknown. Every actual response, including malformed JSON and HTTP errors, and every transport failure stays in the request ledger. A malformed response cannot become a successful empty result.

## Saved evidence and recovery

The output directory contains an automatic `.gitignore` because raw source/model responses belong to the approved local evaluation, not ordinary source commits. It contains:

- `manifest.json` and `plan.json`: frozen inputs, configuration and the preflight estimate;
- `repeat-N/attempts.json`: all attempted sends, raw model outputs, provider usage, reservations, HTTP/transport errors and timing;
- `repeat-N/extraction-checkpoints/`: intermediate results and grounding diagnostics;
- `repeat-N/extraction/`: validated `llm_assisted` outputs;
- `repeat-N/linking-checkpoint.json`: candidate discovery, routing, exact verification and repair progress;
- `repeat-N/input-extractions.json` and `linking-result.json`: exact Linking input snapshot and its checked result;
- `repeat-N/report.json` and `summary.json`: failed/completed states, technical evidence/row-citation checks, model usage/spend and repeat stability.

Use the same flags plus `--resume` to continue an interrupted output directory. Input/prompt/config hashes must match. Completed extraction documents and completed Linking results are reused; Linking partial state is passed to its existing resume mechanism. Completed results are rechecked against their hash and evidence. A ledger entry left in `sending` after a crash is an uncertain external operation; automatic re-send is refused until the previous send is reconciled. A failed extraction document currently restarts from that document when resumed; its prior attempts remain charged to the same 40-call ledger. Its fragment checkpoints remain available for diagnosis, but the harness does not pretend to support fragment-level extraction resume.

## Independent gold and metrics

Without independently completed gold, semantic Precision/Recall/F1 and correctness of meaning remain `null`/not measured. The harness verifies exact values/paths/provenance and row citations using the existing registry/resolvers. This proves technical grounding only. It does not establish that a semantic relationship or row correspondence is correct.

For repeated nonempty proposal graphs it reports document and row Jaccard separately; empty-empty pairs are reported separately with N/A, not stability 1. Failed repeats remain failed and are not silently treated as empty successful graphs.

Optional `--linking-gold <frozen-C02-gold.json>` invokes the unchanged C03 evaluator for a single full-bundle scenario and all requested repeats. Prediction paths are attached to a copy in memory. All original source hashes, reviewer checks, identities and exact-value checks still run. Fresh LLM-assisted Extraction can change the frozen Linking input identities: rejection is reported explicitly rather than rewriting gold. Use `--linking-only` for the exact frozen Linking source corpus.

Optional `--extraction-gold <frozen-C03b-gold.json>` writes a C03b prediction manifest and invokes the existing Extraction evaluator. Artifact hashes, original values, typed values, source paths/provenance, required rows and LLM-required mode are checked by that evaluator. Missing outputs stay failed. No labels are generated from predictions and no scorer thresholds are changed.

All fixtures/gold must be reviewed before predictions are exposed. Compare baseline and candidate under the same frozen inputs, model IDs, prompts, token/call budgets and gold. Preserve both failed baseline runs and every repeat; do not replace the full set with a compact subset to obtain a PASS.

## Offline harness regression

```powershell
node --import tsx --test tests/quality-live-harness.test.ts
```

Tests use an in-process fake transport solely to verify the guards, accounting, raw-response preservation, evidence checks, source pinning and default no-network behavior. They do not stand in for live semantic validation.
