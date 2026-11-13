# Document Linking quality benchmark

Gold labels are based on original Structured Extraction JSON reviewed by a person before model predictions are shown. The evaluation scripts do not generate or adjudicate labels. The single-reviewer MVP is explicitly distinct from an independent multi-expert adjudication.

## Single-reviewer MVP

Prepare one blind packet per configured scenario:

```sh
npm run eval:prepare-annotations -- --mode single --out evaluation/mvp-v1/packets
```

The packets contain every unordered document pair, source paths and SHA-256 hashes, and pending decisions. They contain no labels or model predictions. A human reviewer must inspect the original documents, assign the same real reviewer identity in every packet, and complete every pair. For each supported relationship, record its direction, row correspondences, exact evidence paths and raw values. Record negative and ambiguous decisions explicitly; pending or empty fields are not negative labels.

Compile the completed packets into a frozen MVP gold file:

```sh
npm run eval:compile-annotations -- --mode single --packets evaluation/mvp-v1/packets --out evaluation/mvp-v1/gold.json
```

The output records `review_mode: "single_reviewer"`, the one reviewer identity, source hashes, every reviewed pair, and validated gold relationships. It uses `reviewed_document_pairs`; it does not claim that a second reviewer or adjudicator participated. Source hashes, paths, raw values, reviewer identity, pair coverage, row references, and ambiguity notes are validated before output is written.

Only after the human gold is complete and frozen should an approved evaluation attach prediction files and run the scorer. A measured baseline and model execution require the plan's separate approvals.

## Independent expert mode

The existing two-reviewer plus adjudicator flow remains available:

```sh
npm run eval:prepare-annotations
npm run eval:compile-annotations
```

This default mode preserves the two independent reviewer packets and separate adjudication packet. The compiler requires three distinct, non-placeholder identities per scenario and marks the output `review_mode: "independent_adjudication"`. Use explicit `--mode expert`, `--packets <directory>`, and `--out <file>` when storing its artifacts outside the legacy default paths.

## Scorer inputs and current state

`annotations.template.json` is the scorer-input template. Add the frozen gold labels and prediction paths only after human review; each scenario needs one prediction file or a list of repeated prediction files. The scorer refuses incomplete annotations and reports link precision/recall/F1, direction, row matching, provenance, graph stability, and model usage. Missing usage remains unknown rather than being treated as zero.

Every prediction repeat is scored independently across the same scenarios. The report includes per-scenario and whole-corpus TP/FP/FN, denominators, gates, and the worst-repeat summary. Document relation identity includes relationship type and direction; row correspondences have separate counts, so two row matches do not inflate document-link recall. Duplicate row instances count as row false positives, while duplicate rowless relation entries count as extra document-link false positives.

Before scoring, the tool rechecks the source-file SHA-256 values, the source-bundle hash, the frozen Extraction schema, and each prediction's input-document identities and hashes. A malformed empty object is rejected as an invalid prediction, not scored as an empty graph. Gold evidence must resolve to the exact source path and raw value. Prediction evidence is paired by source and target inside its own matched relation; evidence from another relation cannot satisfy it.

Explicitly negative and ambiguous pairs are checked separately. False accepted links on negative pairs fail their gate; an ambiguous pair with a confirmed link fails its gate and is excluded from ordinary positive P/R. Metrics with no applicable denominator are `null`. A correct empty negative graph has no artificial precision of 1, and its negative-pair gate remains visible. Cost and token usage stay unknown when any required run value is missing.

The report uses the approved Q1 thresholds for link precision/recall/F1, row precision/recall, direction, evidence, negative pairs, and ambiguity. Those are acceptance thresholds, not a claim that any run has passed them. Write a measured baseline only after the gold and execution gates in `.ai-factory/PLAN.md` are satisfied.

No reviewed gold annotations or measured baseline are checked in. The ten scenario descriptions are candidate coverage, not labels. The saved Polza smoke output is a technical integration check, not a quality evaluation. Do not create gold labels from model outputs or summaries.
