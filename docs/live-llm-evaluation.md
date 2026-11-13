# Gemma 4 live evaluation status

## Status: blocked before the first Gemma completion

The requested label is “Gemma 4 30B A4”. Polza's current model catalog exposes the A4B Gemma 4 variant under the exact ID `google/gemma-4-26b-a4b-it`; it also lists `google/gemma-4-31b-it`. Google names the available MoE family member **Gemma 4 26B A4B**, while 31B is a separate dense model ([Google Gemma 4 model overview](https://ai.google.dev/gemma/docs/core.md)). The E2E harness is pinned to the A4B ID and refuses any other configured model.

The available provider key was used only for the model-catalog GET during this Gemma setup. **No completion request has been made with Gemma 4.** An earlier completion attempt with a different model returned HTTP 402 Payment Required. The Gemma E2E run is still waiting for the provider to accept paid completions; the earlier model's outputs were removed and are not presented as Gemma results.

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

No source values from real documents were transmitted. The model payload omits numeric values and full provenance; IDs are pseudonymized. All currently prepared input documents are synthetic.

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
