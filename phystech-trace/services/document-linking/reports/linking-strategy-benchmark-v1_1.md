# Document Linking strategy pilot

Generated: 2026-11-13T08:18:55.604Z
Model: `google/gemma-4-26b-a4b-it` via Polza AI
Plan: `evaluation/strategy-quality-pilot.json`; raw artifacts: `reports/strategy-quality-runs-2026-11-13`.
New-request budget: 10 RUB; reported or estimated calls: 7.254792 RUB; reserved upper bound for requests without returned usage: 0.753939 RUB; total budget exposure: 8.008731 RUB.
Requests attempted: 23; responses with usage: 22; without usage: 1.
Prompt versions: document-linking-system SHA-256 `9c7ac83555cc3fa9d83aed70e18c5d68a9e95b47c959d5de24065e5a48da5a63`; experiment prompts 1.1.0 SHA-256 `bc5ec24601bd0bcaede9a17f3bc054d5907b7662a9da43aa87c7b03768372ea9`.

## Runs

| Bundle | Repeat | Approach | Candidates | Semantic duplicates collapsed | Links emitted | Confirmed | Proposed | Review | Rejected | Diagnostics | Unverified candidates | Evidence pairs | Corrected | Calls | Input / output tokens | Cost (RUB) | Duration (s) | Stability Jaccard |
|---|---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| demo-ambiguous-review-regression | 1 | A | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 1 | 0 | 0 | 2 | 7037 / 898 | 0.101824 | 13.04 | n/a |  |
| demo-ambiguous-review-regression | 1 | B | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 3 | 0 | 0 | 2 | 5972 / 975 | 0.052249 | 6.2 | 0 |  |
| demo-ambiguous-review-regression | 1 | C | 4 | 1 | 0 | 0 | 0 | 0 | 0 | 3 | 3 | 0 | 0 | 5 | 15703 / 3235 | 0.248709 | 44.83 | n/a |  |
| demo-ambiguous-review-regression | 2 | A | 2 | — | — | — | — | — | — | — | — | — | — | 2 | 3526 / 803 | 0.804315 | 11.68 | n/a | Истекло время ожидания Polza (120000 мс) |
| demo-ambiguous-review-regression | 2 | B | 3 | 1 | 0 | 0 | 0 | 0 | 0 | 2 | 2 | 0 | 0 | 2 | 5968 / 934 | 0.050538 | 54.35 | 0 |  |
| demo-ambiguous-review-regression | 2 | C | 4 | — | — | — | — | — | — | — | — | — | — | 3 | 8918 / 7303 | 0.352456 | 96.23 | n/a | Gemma вернула невалидный JSON |
| upstream-contract-addendum-v1_1 | 1 | A | 4 | 0 | 2 | 1 | 0 | 1 | 0 | 2 | 2 | 5 | 0 | 3 | 333626 / 2392 | 2.407477 | 92.51 | n/a |  |
| upstream-contract-addendum-v1_1 | 1 | B | 3 | 0 | 2 | 0 | 0 | 2 | 0 | 3 | 1 | 3 | 0 | 2 | 220579 / 1149 | 1.549762 | 88 | n/a |  |
| upstream-contract-addendum-v1_1 | 1 | C | 4 | — | — | — | — | — | — | — | — | — | — | 2 | 220058 / 1674 | 2.441400 | 41.78 | n/a | BUDGET_STOP: резерв 2.760130 RUB для C.critic превысит лимит 10 RUB (учтено 7.254792 + резерв 0.753939) |

## Comparison

| Strategy | Complete runs | Candidate records | Emitted links | Unverified candidates | Calls | Known run cost (RUB) |
|---|---:|---:|---:|---:|---:|---:|
| A | 2 | 5 | 2 | 3 | 5 | 2.509301 |
| B | 3 | 9 | 2 | 6 | 6 | 1.652549 |
| C | 1 | 4 | 0 | 3 | 5 | 0.248709 |

Counts are model and technical-validation observations, not correctness scores. Precision, recall, F1, direction accuracy, row matching accuracy, false relationships, and missed relationships are reported only after independent adjudication. No predictions are used as gold labels.

Semantic duplicate groups are returned by Gemma; code checks only that candidate indices are well-formed. Original candidates remain in each artifact, and grouped aliases are explicitly recorded. Unsupported statuses are retained as review candidates with their original model status and a diagnostic. Invalid evidence is preserved in diagnostics; a separately valid evidence pair can still support a review-status link.

Repeat stability is a candidate-graph Jaccard and is not a quality metric. Sparse or empty candidate sets can make it uninformative. A strategy is not selected by candidate or link count alone.

Complete-run comparison: A=2, B=3, C=1.
An independent expert gold set is present: no. Even if every strategy has a run, repeat count and expert adjudication are required for a quality conclusion. Winner: not determined.
A budget guard stopped at least one planned request: yes; the rejected preflight request was not sent.

## Raw artifacts

Raw model outputs, prompts hashes, per-call token/cost/time observations, technical diagnostics, and run state are stored under `reports/strategy-quality-runs-2026-11-13`. Each output file is written as calls complete so a partial strategy remains inspectable. No key is saved.

## Limitations

This is a fixed-fixture pilot, not an independently labelled benchmark. Provider-reported usage/cost is used when available; otherwise the runner conservatively estimates cost and holds the preflight reserve for requests without usage. Requests are pre-reserved before sending; a strategy may remain partial if its next call would exceed the selected budget. No unsupported quality claims can be made without the independent annotation packets being completed.

Post-run note: after these calls, the shared system instruction received an additional semantic-deduplication paragraph for strategy A (current SHA-256 `8b31e377cc4d8ce33bc4abba2ba07aaeccaac229bc09c8ab3e28b04a3e29f574`). This exact prompt revision was not evaluated; the run ledger records the prompt hash actually sent. Diagnostics also gained an additive `candidate_status: \"review\"` field after the live calls; the change is unit/contract tested and does not alter their recorded results.
