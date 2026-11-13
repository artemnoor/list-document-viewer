# Gemma relationship quality benchmark

This benchmark requires independent expert labels. Do not use Gemma responses, previous predictions, or model-generated summaries to create the gold set. Review the original Structured Extraction documents first, preferably with two annotators and an adjudication pass. Keep reviewers blind to predictions until labels are frozen.

## Run protocol

1. Use the candidate bundles listed in `scenarios.json`; the focus statements are coverage hypotheses, not labels. Independent reviewers must verify and, where needed, revise the scenario focus after inspecting the source JSON. Keep the source JSON and its hashes with the benchmark release.
2. For each bundle, annotate all supported relationships, their direction, row IDs, and source/target evidence paths and raw values. An empty `gold_links` array is meaningful only after the reviewers confirm there are no supported links.
3. Run the same model configuration and prompt multiple times. Save each complete Document Linking JSON result outside the source fixture directory.
4. Add the prediction paths as `predictions_files` in `annotations.json`; the first run is scored against gold and all runs contribute to pairwise graph stability and usage/cost totals.
5. Set `annotations_complete` to `true` only after independent review and adjudication, then run `npm run eval:links -- evaluation/annotations.json --out evaluation/report.json`.

The scorer reports link precision/recall/F1, direction accuracy, row matching, provenance accuracy, false relationships, pairwise graph Jaccard stability, model request count, tokens, and provider-reported cost. If cost is missing for any run, the total cost is reported as `null` rather than treating missing usage as zero.

## Current state

No independent gold annotations are checked in. Therefore benchmark precision, recall, F1, direction, row, and provenance accuracy have not been measured. The Polza live smoke report is a technical integration check, not an evaluation dataset. The ten scenario descriptions in `scenarios.json` are a coverage plan, not labels.
# Independent evaluation and live strategy pilot

`annotations.template.json` and `annotations.schema.json` are the human gold-label format. Reviewers must label the source documents independently, before seeing model outputs. The pilot fixtures and Gemma responses are not gold labels.

## Prepare independent expert labels

Run `npm run eval:prepare-annotations` to regenerate `annotation-packets/` from the ten real Structured Extraction bundles listed in `scenarios.json`. It validates every source bundle, records SHA-256 hashes, and creates two blind reviewer packets plus a separate adjudication packet for each bundle. The packet set covers 27 document appearances and all unordered document pairs. It does not contain model predictions or prefilled labels.

Reviewers decide every document pair as `supported`, `not_supported`, or `ambiguous`; for each supported relation they record direction, open relationship type, row correspondences, exact supporting and contradicting paths/values, and uncertainty. The adjudicator reviews disagreements against the source JSON and freezes the labels. Keep the independent packets and adjudicated copy as the audit trail. A pending empty relationship list is not a negative label. Do not set `annotations_complete` until all pairs in all ten bundles have been reviewed and adjudicated.

The packet manifest records source hashes so a benchmark can be reproduced against the exact same extraction outputs. Model predictions remain in `reports/` and must not be shown to annotators until the labels are frozen.

To run the bounded Polza pilot on the fixtures in `strategy-pilot.json`, set `POLZA_API_KEY` (or the Windows-compatible `POLZA_AI_API_KEY`) and run `npm run eval:strategies`. The script writes raw model responses, per-call usage/diagnostics, an aggregate ledger, and `reports/linking-strategy-benchmark.md`. It resumes completed runs without repeating them and keeps a 10 RUB total exposure cap. A request whose cost/usage is absent retains its preflight reserve. The earlier pilot directory is immutable historical data; use a new plan and output directory for a new budget window and record those choices in its plan/ledger.

To calculate precision/recall/F1 after independent annotation, use `npm run eval:links -- evaluation/annotations.json`. The evaluator refuses incomplete labels. Add the independently reviewed prediction artifact paths to each scenario; never produce or adjudicate gold labels with Gemma.

The current pilot uses actual Structured Extraction 1.2.0 outputs and a smaller ambiguity fixture. Its limited, incomplete run set cannot determine a winning architecture. Evidence formatting and status-formatting failures are retained as review candidates; semantic duplicate grouping is requested from Gemma and never inferred from a fixed relationship-type dictionary.
