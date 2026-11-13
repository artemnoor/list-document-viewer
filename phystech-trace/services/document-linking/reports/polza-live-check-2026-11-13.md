# Live Polza / Gemma check

Date: 2026-11-13  
Provider: Polza AI  
Model: `google/gemma-4-26b-a4b-it`  
Endpoint: `https://polza.ai/api/v1/chat/completions`

The Windows environment key was used only for the requests. This report contains no key, document content, or raw model response. Inputs were the repository's demo fixtures and Structured Extraction 1.2.0 fixtures.

## Completed requests

| Scenario | Calls | Input / output tokens | Cost | Duration | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| Demo ambiguous pair, live smoke | 1 | 1,456 / 570 | 0.03119957 RUB | 13.778 s | Output contract valid |
| Structured contract + addendum, direct run A | 1 | 46,728 / 1,195 | 0.47144576 RUB | 12.053 s | Output contract valid; 0 links; 2 evidence diagnostics |
| Structured contract + addendum, direct run B | 1 | 46,728 / 1,275 | 0.28088500 RUB | 10.878 s | Output contract valid; 2 accepted links; no diagnostics |
| Structured contract + addendum through Compose API → BullMQ → Worker → PostgreSQL | 1 | 46,765 / 1,161 | 0.44133069 RUB | 21.191 s | Job completed; API idempotent replay returned HTTP 200; output persisted; 0 links; 3 evidence diagnostics |
| Demo ambiguous pair, repeat smoke after full-set context handling change | 1 | 1,455 / 572 | 0.03853555 RUB | 6.401 s | Output contract valid; 0 links; 1 evidence diagnostic |
| Structured contract + addendum, direct run C | 1 | 46,728 / 1,199 | 0.55187374 RUB | 4.442 s | Output contract valid; 0 links; 3 evidence diagnostics |

Known reported cost for these six completed requests: **1.81527031 RUB**. Polza did not expose usage/cost metadata for the first exploratory request, which returned a context request that the then-current implementation rejected. Its cost is therefore unknown and is excluded from this total.

## Findings

- The provider accepted the configured model and returned JSON that passed the output contract in all six completed runs.
- The real API → BullMQ → Worker → PostgreSQL flow completed, persisted the result, and returned the existing job on an idempotent retry.
- Repeated runs on the same two-document pair did not produce consistent graph results: one run yielded two technically accepted links; three other runs yielded no accepted links and two or three evidence diagnostics. This is a small smoke sample, not an independent quality evaluation.
- The diagnostics mainly involved model supplied paths/provenance and row citations that could not be verified against the source JSON. Such proposals were not accepted as links.
- The first live response requested original context despite receiving the full set. The engine was updated to provide requested exact fragments alongside the full set and to checkpoint/resume that pass. Mocked regression coverage exercises this path; later live requests completed without requiring a second call.
- No independent expert labels were used. Precision, recall, F1, direction accuracy, and line-level quality remain unmeasured.

## Evidence-reference implementation check

These small live requests were run during the reference-registry and correction-loop changes. Only the final rows below represent the final code state; intermediate iterations are listed to account for the complete provider-reported spend. No document contents or credentials are included.

| Final-code path | Calls | Input / output tokens | Cost | Result |
| --- | ---: | ---: | ---: | --- |
| Direct Gemma, contract + addendum | 2 | 222,128 / 1,986 | 0.86604725 RUB | Output contract valid; 1 link passed technical validation, 0 links marked review, 2 technical evidence diagnostics |
| Docker Compose API → BullMQ → Worker → Gemma → PostgreSQL → API | 2 | 4,400 / 741 | 0.07183773 RUB | Job completed and persisted; 0 links, 1 diagnostic; API returned the result |
| Docker Compose browser UI upload → job → result display | 2 | 4,638 / 818 | 0.08006061 RUB | UI displayed the completed result and model usage; 0 links, 1 diagnostic |

The direct contract/addendum result changed the unstable prior sample in one run: prior direct checks ranged from zero links with two or three evidence diagnostics to two links with none. The reference-based run landed at one technically accepted link and two diagnostics. This is not a quality score and does not establish repeat-run stability; the independent benchmark still has no gold annotations. The remaining diagnostics concerned row/path correspondence and unavailable provenance, so those proposals were withheld instead of represented as accepted evidence.

The final-code paths above total 6 model calls, 231,166 input tokens, 3,545 output tokens, and 1.01794559 RUB. Across all implementation iterations in this task, Polza reported 5.80788017 RUB total for 12 model calls across seven small analyses. The full-set multi-document benchmark was not run.
