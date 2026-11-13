# Gemma 4 live E2E evaluation

This opt-in harness evaluates the reconciliation engine using ten synthetic scenarios and independent golden references. It is pinned to the provider model ID `google/gemma-4-26b-a4b-it` (Gemma 4 26B A4B). It rejects a different `LLM_MODEL` setting and rejects responses that do not identify that exact model. Polza's catalog currently lists this A4B variant and the separate dense `google/gemma-4-31b-it` model; the requested label “Gemma 4 30B A4” is not a literal model ID in the catalog.

The harness first performs a free `GET /models`, then a protocol preflight completion, then evaluates scenarios. The paid completion hard cap defaults to 40, including preflight. Ten scenarios at three repeats require at most 34 calls when `LLM_MAX_CANDIDATES=300`, because the 320-candidate scenario uses two batches per repeat. Only synthetic data is sent.

## Run on Windows PowerShell

When `POLZA_AI_API_KEY` exists in the process environment, the runner uses Polza automatically. The key is read from the environment and is never written to output files. Run:

```powershell
python tests/live_e2e/run_live_evaluation.py --repeat 3 --max-api-calls 40
```

The runner verifies that `google/gemma-4-26b-a4b-it` is present in `/models` before sending a completion. An explicit `LLM_MODEL` from the process environment or `.env` must match this ID. Each successful completion must also report the exact same model ID; an absent or different response ID is rejected.

Prepare and validate the synthetic cases without contacting the provider:

```powershell
python tests/live_e2e/run_live_evaluation.py --prepare-only
```

`pytest` does not invoke the live API. It tests case construction, contracts, scoring rules, and the Gemma model lock. Provider status and catalog metadata are stored in `tests/results/live_e2e/`; credentials are never included.

## Current status

The model catalog was verified, and ten synthetic inputs and independent references are prepared. An earlier completion attempt with a different model returned HTTP 402. No Gemma completion has been made, so no Gemma accuracy or financial result is claimed. See [`docs/live-llm-evaluation.md`](../../docs/live-llm-evaluation.md) and `tests/results/live_e2e/evaluation-status.json`.

After provider billing accepts requests, the command above runs the evaluation. Offline replay is enabled only after a completed evaluation summary identifies the pinned Gemma model and all saved responses pass model-ID checks:

```powershell
python tests/live_e2e/replay_saved_results.py
```
