# Gemma 4 live evaluation status

## Status: real Gemma evaluation completed with two timeouts

The requested label is “Gemma 4 30B A4”. Polza's current model catalog exposes the A4B Gemma 4 variant under the exact ID `google/gemma-4-26b-a4b-it`; it also lists `google/gemma-4-31b-it`. Google names the available MoE family member **Gemma 4 26B A4B**, while 31B is a separate dense model ([Google Gemma 4 model overview](https://ai.google.dev/gemma/docs/core.md)). The E2E harness is pinned to the A4B ID and refuses any other configured model.

The live evaluation was run on 14 November 2026 against `google/gemma-4-26b-a4b-it`, using only synthetic data. It completed all ten scenarios at three repeats within the 40-call cap: 31 scenario calls plus one protocol preflight. The provider returned 29 model responses; two calls timed out in the 320-candidate scenario. Across scored responses, mean source F1 was 0.714, formula accuracy was 0.950 (20 scored formulas), and expected-value accuracy was 0.412 (17 scored values). The timeouts were retained as failed attempts and not retried. Detailed metrics are in [`evaluation-summary.json`](../tests/results/live_e2e/evaluation-summary.json); bulky per-repeat raw snapshots are not committed.

After the dimension and response-echo fixes, the same bounded benchmark was repeated: 29 responses, two timeouts, mean source F1 0.810, formula accuracy 0.947 (19 scored), and expected-value accuracy 0.625 (16 scored). Formula scoring treats `add` and `sum` as equivalent when their leaves and count match. See the current aggregate in [`evaluation-summary.json`](../tests/results/live_e2e/evaluation-summary.json).

The 320-candidate case did not pass model evaluation: two of its three attempts timed out. The only returned plan identified the target row but included one extra source and described its Linking relation as human-confirmed even though the fixture marks that relation unreviewed. The engine kept the outcome in manual review with no published value. This run therefore verifies the safety gate, not reliable model performance on the large candidate set.

The evaluation harness has ten synthetic, contract-validated cases with independent golden references prepared under [`tests/results/live_e2e/`](../tests/results/live_e2e/):

1. One act confirms a КФЗ indicator.
2. Two potentially independent acts require a safe independence gate.
3. Act, invoice, and registry duplicate representations.
4. Negative correction.
5. April versus an equal March amount.
6. Gross amount less explicitly included VAT.
7. Missing required invoice and unconfirmed source link.
8. Actual versus planned amount.
9. Similar operations with equal amounts.
10. 320 numeric candidates split into batches.

No source values from real documents were transmitted. The model payload omits numeric values and full provenance; IDs are pseudonymized. All input documents are synthetic.

## Real upstream example check

On 14 November 2026, the rebuilt real request example (`act-2026-0424` plus `kfz-2026-q1`, both upstream Extraction 1.2.0) was sent to the pinned model three times before and once after repairing the example generator. All four calls returned a plan with five included source facts; deterministic local execution of the plan returned `1180300.00`. The engine correctly kept `expected_value=null` and `status=manual_review` because the April act does not match the Q1 target period and the example has no human-confirmed Linking path. Numeric source values and full provenance are omitted from the model payload. The safe run summaries are stored locally under `data/real-llm-*.json` and are not committed.

After adding deterministic dimension filtering, the real act example was run once more. Gemma selected exactly five `amount` facts (no quantity or unit-price facts); deterministic execution again returned `1180300.00`. The publication gate remained `manual_review` for the same period and Linking reasons.

A separate run used all six authentic Extraction fixtures (113 numeric candidates, empty Linking graph) in batches of 40. Prompt 1.0.2 states generic dimension and candidate-accounting requirements. Explicitly incompatible currency/unit facts are now excluded before transmission based only on structured target/fact dimensions; merge independently checks the actual dimensions of model-selected facts. On the rerun, all 91 dimension-compatible candidates were handled in three model responses, selected dimensions were consistently RUB with no unit, and the prior `mixed_units`/`currency_missing` diagnostics disappeared. Result stayed `manual_review` due unprocessed ambiguous facts, period mismatch, and absent human-confirmed Linking. No expected value is published without a human-reviewed Linking path.

When the target indicator and period are derived directly from the upstream KFZ Extraction, the six-document run also completes all three candidate batches. Gemma returned three valid plans with no `ValidationError`; the result remains `manual_review` because the real fixtures contain no human-confirmed Linking path and leave unresolved evidence gaps. The planner now discards only exact echoes of request-only metadata before schema validation; altered or invented fields remain errors.

## Reproduction

After provider billing is available, run from Windows PowerShell:

```powershell
python tests/live_e2e/run_live_evaluation.py --repeat 3 --max-api-calls 40
```

The runner verifies the exact Gemma model ID against `/models` before making a completion. `LLM_MODEL` must equal `google/gemma-4-26b-a4b-it`; any other value is rejected. Preparing the fixtures does not contact the provider:

```powershell
python tests/live_e2e/run_live_evaluation.py --prepare-only
```

The offline replay command is available only after genuine Gemma responses have been saved:

```powershell
python tests/live_e2e/replay_saved_results.py
```

Current run status and the exact provider model IDs observed are in [`evaluation-status.json`](../tests/results/live_e2e/evaluation-status.json) and [`model-catalog.json`](../tests/results/live_e2e/model-catalog.json). No model accuracy, formula score, or financial result is claimed until the live Gemma run completes.
