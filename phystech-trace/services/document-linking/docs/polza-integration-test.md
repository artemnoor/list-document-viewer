# Polza AI integration records

Model requests are made through the OpenAI-compatible Polza Chat Completions API using only `google/gemma-4-26b-a4b-it`. Costs below are provider-reported observations, not quality measurements.

## Earlier single-request checks

Several short tests authenticated successfully, parsed structured JSON and passed the output contract. A representative earlier request used 1,217 input and 468 output tokens, cost 0.02555864 RUB, and completed in 6.46 seconds. The fixtures were small; these requests did not establish semantic quality.

## Historical full-set observation

Before the current self-hosted runtime, a six-document test made 43 provider calls and reported 1,305,073 input tokens, 119,022 output tokens and 16.25492363 RUB. This observation is retained as history; the expensive run was not repeated during the infrastructure migration.

## Self-hosted UI integration: 2026-11-13

- Browser uploaded Structured Extraction contract and addendum fixtures, created a background analysis, polled status and displayed the saved result and evidence.
- Model returned two relationships in one Polza request.
- Usage: 46,728 input tokens, 1,301 output tokens; reported cost 0.46998328 RUB.
- This was a functional integration check, not an independent quality evaluation.

Run one small live check with `npm run test:polza`. The script does not print or persist the API key. The full test remains opt-in using `POLZA_RUN_FULL_SET=true` and may incur substantial cost.
