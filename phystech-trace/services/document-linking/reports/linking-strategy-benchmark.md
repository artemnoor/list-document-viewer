# Document Linking strategy pilot

Generated: 2026-11-13T07:33:40.754Z
Model: `google/gemma-4-26b-a4b-it` via Polza AI
New-request budget: 10 RUB; reported or estimated calls: 8.110558 RUB; reserved upper bound for requests without returned usage: 1.151962 RUB; total budget exposure: 9.262520 RUB.
Requests attempted: 33; responses with usage: 31; without usage: 2.
Prompt versions: document-linking-system SHA-256 `ff99509e616a5ff75d66e2561b6e5d97e590a7f27b14d4bfb57fc517b1fd7637`; experiment prompts 1.0.0 SHA-256 `11bcd57b57481b68eddee36dc249a09b952140d7620448ebd2832bcdc66d1edc`.

## Runs

| Bundle | Repeat | Approach | Candidates | Links emitted | Confirmed | Proposed | Review | Rejected | Diagnostics | Evidence pairs | Corrected | Calls | Input / output tokens | Cost (RUB) | Duration (s) | Stability Jaccard |
|---|---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| upstream-contract-addendum | 1 | A | 1 | 1 | 1 | 0 | 0 | 0 | 2 | 2 | 0 | 2 | 222181 / 1708 | 2.467393 | 34.07 | n/a |  |
| upstream-contract-addendum | 1 | B | 4 | 3 | 2 | 0 | 1 | 0 | 2 | 5 | 0 | 2 | 220348 / 1172 | 2.425380 | 13.79 | n/a |  |
| upstream-contract-addendum | 1 | C | 4 | — | — | — | — | — | — | — | — | 1 | 109945 / 742 | 0.956273 | 29.97 | n/a | BUDGET_STOP: резерв 2.728012 RUB для C.independent-agent-2 превысит лимит 10 RUB (учтено 4.892773 + резерв 2.728012) |
| demo-ambiguous-no-evidence | 1 | A | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 2 | 7474 / 1228 | 0.123587 | 5.67 | 0.1667 |  |
| demo-ambiguous-no-evidence | 1 | B | 3 | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 2 | 5688 / 1245 | 0.068376 | 17.11 | 0.0667 |  |
| demo-ambiguous-no-evidence | 1 | C | 7 | — | — | — | — | — | — | — | — | 3 | 5258 / 1521 | 0.685988 | 6.87 | n/a | Gemma вернула невалидный JSON |
| demo-ambiguous-no-evidence | 2 | A | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 1 | 3 | 10600 / 1244 | 0.156682 | 5.31 | 0.1667 |  |
| demo-ambiguous-no-evidence | 2 | B | 3 | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 2 | 5610 / 765 | 0.084130 | 12.54 | 0.0667 |  |
| demo-ambiguous-no-evidence | 2 | C | 6 | 0 | 0 | 0 | 0 | 0 | 6 | 0 | 0 | 5 | 15709 / 3961 | 0.223212 | 116.27 | n/a |  |
| demo-ambiguous-no-evidence | 3 | A | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 2 | 6841 / 834 | 0.134959 | 12.12 | 0.1667 |  |
| demo-ambiguous-no-evidence | 3 | B | 4 | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 2 | 5806 / 1107 | 0.094917 | 10.43 | 0.0667 |  |
| demo-ambiguous-no-evidence | 3 | C | 4 | — | — | — | — | — | — | — | — | 3 | 5258 / 1217 | 0.659446 | 5.88 | n/a | Истекло время ожидания Polza (120000 мс) |

## Comparison

On the actual Structured Extraction contract/addendum set, A emitted one confirmed relationship with two diagnostics. B emitted three relationships (two confirmed and one review) from four candidates, also with two diagnostics. These are model outputs, not correctness findings: there is no independent label to determine whether B found an omission or added a false relation. C completed its first independent pass on this large set (one request, one candidate, 0.956273 RUB) but the second independent request was stopped by the preflight budget guard; this is not a completed C result.

On the four-document demo bundle (which intentionally lacks source provenance), A emitted no links in all three runs. B emitted 3, 3, and 4 candidates, with no links passing evidence checks. Its candidate-graph mean pairwise Jaccard is 0.0667. A's mean candidate-graph Jaccard is 0.1667. Those low values show unstable candidate sets in this tiny sample; neither is a quality metric. The accepted graphs are empty for both, so their accepted-link stability alone would be trivially 1.

C completed one demo run: it unioned six candidates, the critic requested one debate round, and the evidence pass emitted zero links because the fixture had no usable provenance. That run used five requests, 15,709 input and 3,961 output tokens, 0.223212 RUB, and 116.27 seconds. The same strategy also had one malformed-JSON run and one timeout run. Compared with B's two requests / 0.068–0.095 RUB / 10–17 seconds per run, this is a clear cost and latency increase in the pilot, but the lack of gold labels and provenance means it does not show whether critic/debate improves correctness.

The historic baseline report recorded 0–2 accepted links on repeated contract/addendum runs. Current A produced one confirmed link plus two diagnostics, consistent with the most recent earlier result (one accepted, two diagnostics). B's larger output has not been independently checked. No correct, false, or missed relationship examples can be designated without annotators; the observed A/B relationship-type disagreement is preserved in the raw artifacts for blind review.

## Interpretation

Precision, recall, F1, direction accuracy, row matching accuracy, false relationships and missed relationships are not measured: this repository has no independently adjudicated gold labels for these exact bundles. Model output is not treated as gold.

Evidence diagnostics are technical failures/warnings retained with candidate records; they do not establish semantic false positives. An accepted relationship means only that its cited evidence passed the available technical registry/provenance checks. Candidate counts and emitted links are not labels of correctness.

Repeat stability is a candidate-graph Jaccard across runs, using accepted and diagnostically retained proposals for A and all discovered candidates for B/C. Empty or sparse graphs can make Jaccard uninformative; it is not a quality metric.

There is not a comparable repeated sample across all three strategies, and no winner is determined.

A budget guard stopped at least one planned request: yes; the rejected preflight request was not sent.
Additional live smoke/integration requests run during npm test: 4 requests, 1.182177 RUB; these are included in the budget ledger but not in A/B/C row metrics.

## Raw artifacts

Each JSON file in `reports/strategy-benchmark-runs/` records model responses when returned to the client, technical diagnostics, prompt version, per-call token/cost/time data, attempts, and run state. One invalid-JSON response in the first C demo attempt predates the raw-error observer hook and its text was not retained; its conservative preflight reserve remains in the ledger. Timed-out requests also have no response body. No key is saved.

## Limitations

This is a small pilot on fixed fixture inputs, not an independently labelled benchmark. Reported costs from Polza are used when available; requests with no usage because of invalid JSON or timeout retain their full preflight reserve as a conservative cost bound. Rates are twice the published Polza model page prices (input 14.52 RUB/M, output 79.8 RUB/M). A request is pre-reserved before sending; a strategy may remain partial if the remaining budget is insufficient.

## Follow-up pilot: status/evidence handling (prompt 1.1.0)

Generated: 2026-11-13. This is an additional experiment directory and budget window; the original pilot files and numbers above were not edited. The run used status/row-id instructions and strategy prompts 1.1.0, including LLM-directed semantic duplicate groups for B/C. Technical format errors preserve proposals as review/unverified records. Gemma returns semantic duplicate groups; application code validates only their indices and does not use a relationship-type synonym list. After the run, the shared A system prompt also gained an instruction to describe a semantic relation once; its current SHA-256 is `8b31e377cc4d8ce33bc4abba2ba07aaeccaac229bc09c8ab3e28b04a3e29f574`. That post-run instruction is not represented by the calls here; the run ledger records the prompt hash actually sent.

The independent annotation workflow now has ten source-pinned packets, described in `evaluation/annotation-packets/README.md`. They are still unadjudicated, so no precision/recall/F1 or relationship correctness values can be computed.

| Bundle | Repeat | Strategy | Candidate records | LLM duplicate groups collapsed | Links emitted | Confirmed | Review | Diagnostics / unverified | Evidence pairs | Requests | Input / output tokens | Cost or reserve (RUB) | Seconds | Outcome |
|---|---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Small ambiguous demo | 1 | A | 1 | 0 | 0 | 0 | 0 | 1 / 1 | 0 | 2 | 7,037 / 898 | 0.101824 | 13.04 | complete |
| Small ambiguous demo | 1 | B | 3 | 0 | 0 | 0 | 0 | 3 / 3 | 0 | 2 | 5,972 / 975 | 0.052249 | 6.20 | complete |
| Small ambiguous demo | 1 | C | 4 | 1 | 0 | 0 | 0 | 3 / 3 | 0 | 5 | 15,703 / 3,235 | 0.248709 | 44.83 | complete |
| Small ambiguous demo | 2 | A | 2 | — | — | — | — | — | — | 2 | 3,526 / 803 | 0.804315 incl. timeout reserve | 11.68 observed | Polza timeout |
| Small ambiguous demo | 2 | B | 3 | 1 | 0 | 0 | 0 | 2 / 2 | 0 | 2 | 5,968 / 934 | 0.050538 | 54.35 | complete |
| Small ambiguous demo | 2 | C | 4 | — | — | — | — | — | — | 3 | 8,918 / 7,303 | 0.352456 | 96.23 | invalid JSON; saved raw response |
| Actual SE 1.2.0 contract + addendum | 1 | A | 4 | 0 | 2 | 1 | 1 | 2 / 2 | 5 | 3 | 333,626 / 2,392 | 2.407477 | 92.51 | complete |
| Actual SE 1.2.0 contract + addendum | 1 | B | 3 | 0 | 2 | 0 | 2 | 3 / 1 | 3 | 2 | 220,579 / 1,149 | 1.549762 | 88.00 | complete |
| Actual SE 1.2.0 contract + addendum | 1 | C | 4 after exact duplicate union | — | — | — | — | — | — | 2 | 220,058 / 1,674 | 2.441400 | 41.78 | only independent agents completed; budget stopped before critic |

This run attempted 23 Polza requests: 22 returned usage, and one timed out without usage. Reported/estimated spend was 7.254792 RUB; the timeout retained a 0.753939 RUB reserve. Total exposure was 8.008731 RUB against the 10 RUB cap. The next C critic call was rejected by the preflight guard and was not sent. No paid requests were made by unit or contract tests.

On the same actual two-document bundle, A emitted two links (one confirmed, one review) and two diagnostics; B emitted two review links and three diagnostics from three candidates. C's two independent passes each returned four entries with the same displayed relationship labels, but C did not reach critic, evidence selection, or technical validation. Thus C's apparent union is not an evaluated graph, and its candidate count cannot be compared as correctness. The new A/B result differs from the old pilot (A: one confirmed; B: three emitted, two confirmed and one review); prompt and validator behavior changed, and neither result has expert labels. This difference does not prove that one version or strategy is more accurate.

Concrete technical diagnostics from the actual run: B returned row IDs that did not match the selected source/target evidence references; A reported an OCR/source-text mismatch for a price-change proposal and missing/mismatched provenance for another proposal. These describe evidence-format/verification outcomes only. They do not establish whether those relationships are true or false, and no omitted relationship can be called a miss without expert labels.

The small bundle has no reliable source provenance. A/B emitted no links, and all completed small-bundle candidates remained unverified. C's first run used five requests, collapsed one Gemma-declared semantic duplicate group, and still had three unverified candidates. In the second repeat A timed out and C returned invalid JSON. Therefore repeat coverage is incomplete and does not establish stable quality. B's candidate graph Jaccard on its two small-bundle runs was 0; this measures only output repeatability, not correctness.

The artifacts under `reports/strategy-quality-runs-2026-11-13/` contain full model response bodies, per-call usage/cost/duration, diagnostics, prompt/code hashes, failures, and the budget ledger. The historical directory `reports/strategy-benchmark-runs/` remains unchanged.

### What this pilot can and cannot answer

- **B vs A correctness:** unknown. On one actual bundle, their accepted counts match at two, but their statuses/evidence differ. No adjudicated labels identify correct, false, or missed links.
- **Whether C finds omissions:** unknown. The independent agents returned the same visible relationship labels in the one real bundle; C stopped before critic and evidence checking.
- **Critic and debate value:** not measured. The real C critic was not sent; the completed small C run included critic/debate behavior, but lacks provenance and gold labels.
- **Cost/time:** measured for the calls above. B cost 1.549762 RUB and took 88 seconds on the real bundle; A cost 2.407477 RUB and took 92.51 seconds. C's 2.441400 RUB is only for its two independent calls and is not a completed strategy cost.
- **Recommendation:** no winner. Keep A as the production strategy and use these as diagnostics only until independent annotation and matched repeated A/B/C runs are available.

The request budget was respected. A complete A/B/C comparison on the actual bundle was not possible within the remaining reserved budget: the C critic was blocked before send. Do not interpret partial C as zero links or a failed quality result.

Post-run code note: diagnostics now expose additive `candidate_status: \"review\"` in the existing output contract so the UI labels preserved technical candidates as review items. This display/schema addition was unit and contract tested after the live calls; it does not retroactively change their recorded results or hashes.
