# Phystech Trace full-pipeline integration report

Updated: 2026-11-14

## Current unified chain — supersedes earlier gated status below

Following the user's instruction to connect the entire chain for manual frontend review, Verification was imported with `git subtree` from `b1d025e738fbf5ff1b447c49608527d580ff489d`. Both engines retain their complete source, standalone API, contracts, tests and upstream history. Compose now starts all five modules. Gateway passes the unchanged saved Extraction 1.2.0 and Linking 1.2.0 snapshots plus the real Reconciliation 1.0.0 result into Verification's native `ReconciliationEngine10Adapter`. Verification 1.2.0 is validated against its published schema, reread in project scope, and stored in PostgreSQL as well as the engine's persistent SQLite volume. Reconciliation uses its existing persistent volume. Both stages have separate retry and read endpoints.

The frontend now shows five stage cards and a **Сверка** tab containing reported/expected values, difference, decision reasons, evidence, calculation plans and full result links. Model-labeled `confirmed` links that are still `not_reviewed` can now be reviewed by the actual user. Link decisions invalidate both downstream results; adding a document invalidates the previous bundle's results. Verification retry reuses saved Reconciliation rather than calling paid upstream stages. Reprocessing a saved bundle reuses Extraction and Linking. Reconciliation planning is enabled by default and still obeys the existing per-project external-model consent. Verification explanations remain deterministic, with its optional LLM disabled.

### Actual HTTP smoke example

- Project: `ab5f2d87-1759-450d-a3dd-38c33b9ec91f` (`Synthetic E2E 20261113-152545`), three source documents.
- Frontend: `http://localhost:8080/?project=ab5f2d87-1759-450d-a3dd-38c33b9ec91f&tab=verification`.
- Saved Parser, Extraction and Linking inputs were reused; no mocks or fabricated human decisions were used in this HTTP run.
- Gateway processed Reconciliation, obtained a genuine Polza plan, then submitted its real result to Verification.
- Reconciliation ID: `91a272018ef4719051def4dba679e924`.
- Verification ID: `ver_3fae25be79e233489643c27f`, `overall_status=insufficient_data`, three unresolved indicators, zero proven mismatches. A successful `matched` calculation is not claimed.
- All five Gateway stage states are `completed`; this means processing finished, independently of the financial conclusion. The UI labels the project **Обработан** and separately displays **Недостаточно данных**.
- Exact result JSON equality was checked through Gateway and both engines after restarting Gateway, Reconciliation and Verification. All health dependencies report `ok`.
- Recreating Gateway exposed a stale Nginx upstream IP causing frontend 502 responses. The frontend now resolves Gateway through Docker DNS with a short cache; frontend HTTP returned 200 after Gateway was recreated again.
- Browser navigation to the example and the Сверка tab was checked with Playwright, with zero console errors. Local screenshot: `output/playwright/unified-chain-front.png` at the repository root.

Saved evidence: `tests/e2e/results/unified-chain-smoke.json`, `unified-chain-reconciliation.json`, `unified-chain-verification.json`.

### Checks and remaining quality limits

Verification's complete suite: **72 passed**. Gateway downstream contract, retry, evidence-forwarding and invalidation regressions: **11 passed**. Frontend typecheck/production build, Compose build/start, all health checks and persisted-result rereads passed. Cross-service tests compare the exact parsed published schemas for Extraction, Linking, native Reconciliation and Verification.

The earlier upstream hash failure was caused by Git's Windows newline conversion. Restoring the original Git blob bytes and disabling text conversion for imported Verification JSON files makes every original pinned hash pass unchanged. The hashes, fixtures and expected outputs were not changed.

This iteration added one real Reconciliation planner request: 4,557 input + 451 output = **5,008 tokens**, **0.06461336 RUB**. The recorded cumulative request count is now **139 / 150**, known cumulative spend **20.32764969 RUB**, plus the one earlier unaudited planner call described in the historical section. No new Extraction/Linking or Verification model requests were made in this iteration.

All five modules are connected and available for manual frontend testing. Evidence quality remains limited: this example correctly stays insufficient rather than producing a proven expected amount. Case19's saved KFZ Extraction is `unknown` with empty fields and no monetary target; it cannot produce a calculation without correcting that upstream Extraction. No claim is made that the original broad matched/mismatch scenario matrix has passed.

## Historical staged implementation notes

## Source revisions

| Repository / module | Ref | Source commit |
| --- | --- | --- |
| `list-document-viewer` integration base | `feat/phystech-trace-quality` | `2d8e7485dfd33e34e809df4562388b3946592ddf` |
| `phystech-trace-reconciliation-engine` | `master` | `024b010c696e916acb845f7e68bc92d9010ff41f` |
| `phystech-trace-verification-engine` | `main` | `b1d025e738fbf5ff1b447c49608527d580ff489d` |
| Document Parser, as pinned by the integration base | — | `e6bb15e1fd4581d810d3426ea6558c9bb61231f6` |
| Structured Extraction, as pinned by the integration base | — | `1e922e284805f2c1b343b4cb369813c8073b67dd` |
| Document Linking, as pinned by the integration base | — | `28a3662cc0597093ad6264f70f591db19c37e061` |

The working branch is `feat/phystech-trace-full-pipeline`, based directly on the fetched quality branch. The Reconciliation Engine has been imported with `git subtree`; its upstream history is retained. Verification has not yet been imported because the Reconciliation acceptance gate is incomplete.

## Architecture and current integration

The existing Parser, Extraction, Linking, Gateway and Vue application remain separate services. Reconciliation is now a standalone Compose service on the internal network, with its durable result store in the `reconciliation-results` volume. Gateway sends the saved Extraction 1.2.0 documents and saved Linking 1.2.0 result to the upstream engine, reads the result back by ID, and saves the result and stage state in PostgreSQL. Gateway health reports all five backend services. A project-scoped Reconciliation read endpoint is available at `/api/projects/{project_id}/reconciliation`.

Gateway selects amount targets only from explicit currency/amount wrappers in the saved KФЗ extraction. If the same evidence is represented as both a field and an indicator, it binds the target to the indicator pointer when both share the same source locator; the engine deduplicates that evidence in favor of the indicator fact. Unknown amount basis and economic measure remain `unspecified`. External Reconciliation calls default to disabled and require the project’s existing external-LLM consent before the engine can call Polza.

Reconciliation result IDs now bind the exact input snapshot, human decisions, planner enabled/model/prompt profile and an engine fingerprint over executable Python modules, published schemas and package metadata. The service checks for an existing result before constructing the planner, so an identical replay does not call the model again. Model request/response audit records, hashes, usage, provider cost and errors are stored in a project-scoped sidecar endpoint, separate from the unchanged Reconciliation 1.0.0 result schema.

## Checks and observed outcomes

| Check | Result |
| --- | --- |
| Original Reconciliation Engine `pytest -q` before integration | Passed |
| Reconciliation Engine `pytest -q` after identity, audit and replay fixes | Passed |
| Reconciliation Engine `pytest -q` after saved-result retry, resolved-diagnostic, and full code-fingerprint regressions | Passed |
| Gateway reconciliation and retry regression tests | 5 passed |
| Gateway and shared contract tests | 12 passed after making schema identity checks insensitive to CRLF/LF line endings while comparing parsed JSON exactly |
| Document Linking offline suite after evidence corrections | 86 passed, 0 failed, 5 skipped |
| Document Linking production build | Passed: typecheck, Vite, API, worker, migration and config-check bundles |
| `python -m py_compile` for Gateway and regression test | Passed |
| `docker compose config --quiet` | Passed |
| Docker build for Reconciliation Engine and Gateway | Passed |
| Compose health and Gateway `/health` | Passed; Parser, Extraction, Linking and Reconciliation reported `ok` |
| Saved synthetic project through Gateway → Reconciliation → saved result reread | Completed; latest Reconciliation 1.0.0 result ID `84bda9c121f2934b21abf70e451a7015`, using saved Linking run `351caa01-1e97-467d-ad60-a26820069274` |
| Reconciliation container restart and result/audit reread | Passed; result and LLM audit sidecar remained available |
| Repeated Gateway reconciliation request with the same input | Returned the same result; audit call count stayed at 1 |

The first saved synthetic run exposed a target pointer mismatch: the Gateway selected `#/fields/reported_total`, while the engine canonicalized duplicate evidence to `#/indicators/0/extracted`. A regression test now covers the canonical pointer selection. The resulting request then reached the LLM planner.

The live Polza planner response did not support a calculation. It identified candidate totals from the registry and act but also found `review` links, `source_text_value_mismatch`, `invalid_link_metadata`, and four unprocessed facts in the initial attempt. The preserved audit response in the engine sidecar describes ambiguity between two registry facts and explicitly requests manual review. The final saved result is therefore `manual_review`, `expected_value=null`, with zero used sources and 30 excluded sources. No expected financial value was invented.

The older saved Linking run `e15ffbb3-eede-4906-bee7-1317cf518c3b` is also preserved in Linking history: 3 model calls, 136,447 input tokens, 3,656 output tokens, provider-reported cost `1.77043655 RUB`. It is the pre-fix run that produced active provenance and text-value review findings. The later fresh run `351caa01-1e97-467d-ad60-a26820069274` is separate and is the run used by the latest Reconciliation result.

Review of those saved Linking diagnostics found two deterministic validator defects. `evidence-registry.ts` compared a nested numeric amount such as `1180300.00` against formatted source text rather than checking the wrapper’s actual `source_value`. The evidence correction loop also replaced an entire Link object when the model supplied only changed evidence, dropping otherwise valid `status` and `confidence`. Both now have offline regression tests. A fresh real Linking run over the existing saved synthetic Extraction results completed through Gateway as run `351caa01-1e97-467d-ad60-a26820069274`: 3 model calls, 137,912 input tokens, 3,798 output tokens, provider-reported cost `1.84840702 RUB`; all 896 evidence references were processed. Three proposals were corrected against source references. One remains `review_required` because its row provenance does not match. Its 3 model-labeled `confirmed` links all retain `verification_status=not_reviewed`, so Reconciliation does not treat them as human-confirmed.

A live retry uncovered a Gateway orchestration bug: `stage=reconciliation` reran Linking with its initial idempotency key and replaced the fresh saved result with the older run. The retry path now skips Linking and validates/uses the project’s saved Linking result directly. The fresh run was recovered from Linking’s run history and restored to this synthetic project without another provider call; a regression covers the stage selection. The latest Gateway retry’s result snapshot records the same Linking run ID as the saved project result.

The Reconciliation Engine had two related diagnostic handling defects. It treated Linking diagnostics with `resolution=corrected` or `withdrawn` as active blockers and sent those resolved diagnostics to the planner. Both calculation validation and planner payload construction now omit resolved diagnostics while retaining unresolved review findings. New regression tests cover each boundary. With the restored fresh Linking result, the latest real Polza call used 5,139 total tokens and cost `0.06186852 RUB`; the audited response no longer cites the resolved `source_text_value_mismatch` or `invalid_link_metadata` findings. The result remains correctly `manual_review`, with `expected_value=null`, zero used sources, and 30 excluded sources. Remaining blockers include an unresolved row-provenance relationship, an unverifiable period for a selected value, and no row-aware human-confirmed path. No `matched` result is claimed.

One earlier live planner request ran before the audit sidecar was added. Its result is preserved, but provider usage/cost for that individual request cannot be recovered. The two audited planner requests cost `0.07770343 RUB` (5,638 tokens) and `0.06186852 RUB` (5,139 tokens). Together with the two preserved Linking runs, the known subtotal is 8 calls and `3.75841552 RUB`; one earlier planner call is additional with unrecoverable usage/cost. The prior Reconciliation request replay did not incur another call. Reconciliation LLM calls are disabled in the current Compose container. The targeted run reused saved Parser and Extraction outputs; only the bounded fresh Linking run and two audited Reconciliation planner calls were added during this integration check.

The Verification repository’s original `pytest -q` run has one baseline failure in `test_upstream_source_commits_and_schema_hashes_are_pinned`: the checked-in manifest expects SHA-256 `fca942339fee08c3d577891cec78343c8958d88d1896f01ad055881d6ad50be6` for its Extraction schema, while the checked-in file hashes to `9c976a36f103843dd5c93a7e9daf5d8361e43db4ab2d0b64f02732c42aba5bb7`. Other recorded source test output passed. This mismatch is not silently corrected or accepted as a passing source suite.

The pre-existing, untracked synthetic `tests/e2e/data/case19` package was inspected before any model prediction. Its README specifies the Q1-to-May 2026 source window and the answer workbook records the Stage 3 KФЗ total as `11,580,377.40 RUB`, supported value `11,567,877.40 RUB`, and a `12,500.00 RUB` mismatch in code 0800. It identifies a duplicate act, a June-period act, and an act from a different contract as excluded evidence. The package is unchanged and was not yet sent through the five-stage pipeline; these values are reference expectations, not E2E results.

## Readiness by module

| Module | Status | Evidence / remaining work |
| --- | --- | --- |
| Document Parser | Partially ready | Existing integration report records Parser tests and live HTTP use; broad pipeline acceptance has not been repeated on this branch. |
| Structured Extraction | Partially ready | Existing integration report records its tests and saved 1.2.0 outputs; the saved results were consumed by Reconciliation here. |
| Document Linking | Partially ready | Two validator root causes were fixed with regressions and the service rebuilt. A fresh saved-input API run processed all references; three proposals were corrected and one remains in review for a row-provenance mismatch. Model `confirmed` labels remain `not_reviewed`. |
| Reconciliation Engine | Partially ready | Full upstream suite passes; Compose/Gateway integration, persistence, reread, audited real Polza planning, and resolved-diagnostic filtering are exercised. The latest result correctly remains `manual_review`; sufficient evidence and an independently verified positive calculation are still required. |
| Verification Engine | Blocked on Reconciliation gate | Not yet imported or connected. Its upstream suite has the pinned-hash failure above; native `ReconciliationEngine10Adapter` integration and Gateway/UI evidence remain untested. |

## Remaining acceptance work

Stage 1 is not complete: there is not yet a positive real-source Reconciliation calculation with independently sufficient evidence. The fresh Linking result still has an unresolved row-level provenance issue and has no human-confirmed path; the engine correctly withholds an expected value. Per the staged acceptance criteria, Verification integration and five-stage E2E have not started. No `matched` result is claimed. The current worktree must also be committed and pushed after the remaining modules and scenarios are implemented.

## Case19 controlled live run

The synthetic case19 package was uploaded through Gateway after fixing its Unicode filename encoding. It contains 23 source files; the byte-identical duplicate act was deduplicated, leaving 22 stored documents (the KFZ workbook plus 21 source documents). The Gateway project is `0fd998d0-c25e-4bfa-b672-284c3ad33acd`. The saved Parser results were consumed by Structured Extraction and Linking rather than rerunning Parser or rebuilding simplified inputs.

| Stage / evidence | Observed result |
| --- | --- |
| Parser upload and persistence | 22 documents stored; one duplicate source file removed by content deduplication |
| Structured Extraction 1.2.0 | 22 real Polza calls; 109,721 tokens; provider cost `1.48233391 RUB`; 7 `act`, 1 `invoice`, 14 `unknown`; 11 documents flagged for review |
| Document Linking 1.2.0 | Saved run `8570cd58-ad92-44ef-9900-14ba53a4abb2`; complete after 107 real calls, 835,425 input tokens, 188,379 output tokens, provider cost `15.02228690 RUB` |
| Linking saved result | 21 links, 13 `status=confirmed` but all 13 have `verification_status=not_reviewed`, 3 proposed, 5 review; 8 review-required items; 3 diagnostics corrected and 2 remain `review_required` for `row_provenance_mismatch` |
| Reconciliation and Verification on case19 | Not run. The Reconciliation acceptance gate is still unmet; no link has human-confirmed provenance. Reconciliation LLM planning remains disabled in Compose. Verification remains unimported and gated. |

The live Linker job initially exposed truncated discovery batches, invalid route citations, oversized candidate context, and repeated source follow-ups. The runner now recovers omitted fragments with separate requests, groups route work within bounded tasks, validates and replays persisted responses through the current validators, derives only exact source references from cited navigation anchors, caps candidate evidence, and safely closes repeated follow-ups as `insufficient_evidence`. Checkpoints compact only pending verification work and preserve already completed responses. These recovery paths are covered by offline regression tests. The final case19 Linker result still cannot establish review-grade provenance: model-labeled confirmed links remain explicitly unreviewed, and the remaining row citations fail validation. This is a quality failure, not a positive Reconciliation input.

The gold workbook remains unchanged and was never uploaded. It records reported `11,580,377.40 RUB`, independently supported `11,567,877.40 RUB`, and a `12,500.00 RUB` discrepancy in code 0800. These are reference values only; the live model output did not calculate or validate them. Excluded gold items include the duplicate act, a June-period act, and an act for another contract. The run therefore does not establish either `matched` or a proven numeric `mismatch`.

The Gateway filename fix percent-encodes raw Unicode names in multipart headers while retaining the file extension. A regression test covers this; the original upload error created only an empty draft and incurred no paid calls. The existing draft was reused after the fix.

### Final checks and budget

After the Linker runtime fixes, `npm test` passed 87 tests with 0 failures and 5 existing skips; `npm run typecheck` and `npm run build` passed. Gateway reconciliation regression tests passed 6/6. Earlier in this integration, the Reconciliation Engine suite, compose validation, Docker builds and service health checks also passed as recorded above.

The counted total is 138 paid requests: 9 earlier Linking/Reconciliation requests, 22 case19 Extraction requests, and 107 case19 Linking requests. Known provider-reported spend is `20.26303633 RUB`, plus one earlier planner request whose individual provider usage and cost were not captured before the audit sidecar existed. Current-run Linker usage is fully captured above. No new paid request was started after the case19 Linking run completed. Known total is far below the `100 RUB` cap; exact total spend cannot be reconstructed for that one unaudited planner call. Total request count remains below the 150-call cap.

## Updated readiness

| Module | Status | Current evidence |
| --- | --- | --- |
| Document Parser | Partially ready | Case19 uploaded through Gateway; duplicate source deduplicated; 22 documents persisted. |
| Structured Extraction | Partially ready | Case19 saved 1.2.0 output from 22 real requests; 14 unknown classifications and 11 review flags limit downstream evidence. |
| Document Linking | Partially ready | Case19 live run completed and persisted; 13 model-confirmed labels are all `not_reviewed`, 8 items need review, and 2 row-provenance diagnostics remain unresolved. |
| Reconciliation Engine | Partially ready; acceptance gate blocked | Full source suite and earlier Gateway integration/persistence/audit checks pass. Case19 has not been sent to planning because its evidence lacks a human-confirmed path. Prior real planner output correctly remained `manual_review`. No positive calculated case is demonstrated. |
| Verification Engine | Blocked on Stage 1 | Not imported or connected because the required positive Reconciliation scenario has not passed. The upstream pinned-schema hash mismatch also remains unresolved. |

The work therefore stops at the explicit Stage 1 acceptance gate. Completing Stage 2–3, including Verification import and the required matched, proven mismatch, and review E2E scenarios, requires new source evidence with valid row-level provenance and genuine human review where required. No confirmation was fabricated and no gold expectation was changed.
