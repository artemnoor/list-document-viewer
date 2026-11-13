"""Re-run stored real-LLM plans through the local engine without calling a provider."""

from __future__ import annotations

import hashlib
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reconciliation_engine.config import Settings
from reconciliation_engine.facts import extract_facts
from reconciliation_engine.models import ConfirmedDecision, ReconciliationRequest
from reconciliation_engine.planner import LLMPlanner
from reconciliation_engine.plans import CalculationPlan
from reconciliation_engine.service import bind_decision_to_request, reconcile

from run_live_evaluation import REQUESTED_MODEL_ID, RESULTS, _aggregate, _compare, _read, _write


class RecordedPlanPlanner:
    """Provide an already-recorded genuine model plan to the normal service path."""

    def __init__(self, plan: CalculationPlan) -> None:
        self.saved_plan = plan

    def plan(self, *args: Any, **kwargs: Any) -> CalculationPlan:  # type: ignore[no-redef]
        return self.saved_plan


def _sha256(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _run_stored_plan(request: ReconciliationRequest, plan: CalculationPlan) -> dict[str, Any]:
    settings = Settings(llm_enabled=True, llm_api_key="offline-recorded-plan")
    return reconcile(request, settings, planner=RecordedPlanPlanner(plan))


def _replay_case(case_id: str) -> dict[str, Any]:
    case_dir = RESULTS / case_id
    request = ReconciliationRequest.model_validate(_read(case_dir / "input.json"))
    reference = _read(case_dir / "golden-reference.json")
    repeat_records: list[dict[str, Any]] = []
    replay_runs: list[dict[str, Any]] = []

    for repeat_index in range(1, 4):
        original = _read(case_dir / f"repeat-{repeat_index:02d}.json")
        if original.get("model_requested") != REQUESTED_MODEL_ID or original.get("model_returned") != REQUESTED_MODEL_ID:
            raise RuntimeError(f"Refusing to replay a non-{REQUESTED_MODEL_ID} model response in {case_id} repeat {repeat_index}.")
        plan_data = original.get("calculation_plan")
        if plan_data is None:
            result = original["reconciliation_result"]
            replayed = False
            replay_note = "No model plan existed: provider returned HTTP 402, so no engine replay could be performed."
            stored_calculation = result["calculations"][0]
            compact_result = {
                "reconciliation_id": result["reconciliation_id"],
                "input_snapshot": result["input_snapshot"],
                "calculation": {
                    "status": stored_calculation["status"],
                    "expected_value": stored_calculation["expected_value"],
                    "diagnostic_codes": sorted({item["code"] for item in stored_calculation["diagnostics"]}),
                },
            }
        else:
            plan = CalculationPlan.model_validate(plan_data)
            result = _run_stored_plan(request, plan)
            replayed = True
            replay_note = "Stored genuine model plan re-executed offline through the patched service and validation path."
            compact_result = result

        comparison = _compare(result, reference)
        repeat_records.append({
            "repeat": repeat_index,
            "comparison": comparison,
            "llm_calls": original.get("llm_calls", []),
            "real_llm_response": bool(original.get("real_llm_response")),
        })
        replay_runs.append({
            "repeat": repeat_index,
            "replayed": replayed,
            "replay_note": replay_note,
            "request_sha256": original.get("request_sha256"),
            "real_llm_response": bool(original.get("real_llm_response")),
            "assistant_response_sha256": hashlib.sha256(
                (original["llm_calls"][0].get("assistant_content") or "").encode("utf-8")
            ).hexdigest() if original.get("llm_calls") else None,
            "plan_sha256": _sha256(plan_data) if plan_data is not None else None,
            "comparison": comparison,
            "reconciliation_result": compact_result,
        })

    metrics = _aggregate(case_id, repeat_records)
    metrics["replay_provider_calls"] = 0
    metrics["replay_type"] = "offline_reexecution_of_stored_real_llm_plans"
    _write(case_dir / "metrics.post-fix.json", metrics)
    _write(case_dir / "post-fix-replay.json", {
        "case_id": case_id,
        "synthetic_data_only": True,
        "replay_provider_calls": 0,
        "metrics": metrics,
        "runs": replay_runs,
    })
    return metrics


def _policy_mode_evaluation() -> dict[str, Any]:
    single_case = "01_single_act"
    single_dir = RESULTS / single_case
    base_request = ReconciliationRequest.model_validate(_read(single_dir / "input.json"))
    original = _read(single_dir / "repeat-01.json")
    plan = CalculationPlan.model_validate(original["calculation_plan"])
    target = base_request.context.targets[0]
    selected_fact_ids = [item.fact_id for item in plan.included]
    facts_by_id = {fact.fact_id: fact for fact in extract_facts(base_request.extraction_results)}
    target_document_ids = {target.kfz_document_id}
    selected_links = []
    linking = json.loads(json.dumps(base_request.linking_result))
    for link in linking.get("links", []):
        for fact_id in selected_fact_ids:
            fact = facts_by_id[fact_id]
            if (
                link.get("relationship_type") == "supports_indicator"
                and fact.document_id in {link.get("source_document_id"), link.get("target_document_id")}
                and bool(target_document_ids & {link.get("source_document_id"), link.get("target_document_id")})
                and (not fact.row_id or fact.row_id in {link.get("source_row_id"), link.get("target_row_id")})
            ):
                link["status"] = "confirmed"
                link["verification_status"] = "not_reviewed"
                selected_links.append(link["link_id"])
                break
    if not selected_links:
        raise RuntimeError("Could not find the recorded plan's target support link for confirmation replay.")
    linking["review_required"] = [
        *linking.get("review_required", []),
        *[
            {"link_id": link_id, "reason": "Offline policy replay: link needs human confirmation.", "candidate_document_ids": [facts_by_id[selected_fact_ids[0]].document_id, target.kfz_document_id]}
            for link_id in selected_links
        ],
    ]
    unconfirmed_request = base_request.model_copy(update={"linking_result": linking, "prior_decisions": []})

    automatic_result = _run_stored_plan(unconfirmed_request, plan)
    accepted_fact_ids = list(dict.fromkeys(selected_fact_ids))
    decision = ConfirmedDecision(
        decision_id="offline-policy-confirmation",
        target_id=target.target_id,
        reviewer_id="synthetic-evaluator",
        confirmed_at=datetime.now(timezone.utc),
        plan=plan.as_dict(),
        accepted_fact_ids=accepted_fact_ids,
        accepted_link_ids=selected_links,
    )
    bound_decision = bind_decision_to_request(unconfirmed_request, decision, plan)
    confirmed_request = unconfirmed_request.model_copy(update={"prior_decisions": [bound_decision]})
    confirmed_result = reconcile(confirmed_request, Settings(llm_enabled=False))

    missing_case = "07_missing_document_link"
    missing_dir = RESULTS / missing_case
    missing_request = ReconciliationRequest.model_validate(_read(missing_dir / "input.json"))
    missing_plan = CalculationPlan.model_validate(_read(missing_dir / "repeat-01.json")["calculation_plan"])
    insufficient_result = _run_stored_plan(missing_request, missing_plan)

    auto_calc = automatic_result["calculations"][0]
    confirmed_calc = confirmed_result["calculations"][0]
    insufficient_calc = insufficient_result["calculations"][0]
    if auto_calc["status"] == "calculated" or auto_calc["expected_value"] is not None:
        raise AssertionError("Unconfirmed Linking path unexpectedly produced a publishable value.")
    if "source_applicability_unverified" not in {item["code"] for item in auto_calc["diagnostics"]}:
        raise AssertionError("Automatic replay did not enforce human-confirmed source applicability.")
    expected_value = _read(single_dir / "golden-reference.json")["expected_value"]
    if confirmed_calc["status"] != "calculated" or confirmed_calc["expected_value"] != expected_value:
        raise AssertionError("Snapshot-bound human confirmation did not produce the independently expected value.")
    if not confirmed_calc["used_sources"] or not all(source.get("provenance") and source.get("human_confirmation") for source in confirmed_calc["used_sources"]):
        raise AssertionError("Confirmed calculation is missing source provenance or confirmation evidence.")
    if insufficient_calc["status"] not in {"manual_review", "insufficient_data"} or insufficient_calc["expected_value"] is not None:
        raise AssertionError("Insufficient-evidence replay published a value.")

    return {
        "synthetic_data_only": True,
        "live_llm_calls_added": 0,
        "real_llm_plan_source": {
            "case_id": single_case,
            "repeat": 1,
            "model_id": original["model_returned"],
            "assistant_response_sha256": hashlib.sha256(original["llm_calls"][0]["assistant_content"].encode("utf-8")).hexdigest(),
            "plan_sha256": _sha256(plan.as_dict()),
        },
        "mode_a_automatic_without_link_confirmation": {
            "explanation": "The authentic saved LLM plan was replayed against its support link after changing its review status to machine-confirmed/not-human-confirmed. No prior decision was supplied.",
            "request_snapshot_sha256": automatic_result["input_snapshot"]["snapshot_sha256"],
            "status": auto_calc["status"],
            "expected_value": auto_calc["expected_value"],
            "diagnostic_codes": sorted({item["code"] for item in auto_calc["diagnostics"]}),
            "reconciliation_result": automatic_result,
        },
        "mode_b_snapshot_bound_human_confirmation": {
            "explanation": "The same LLM plan and modified Linking snapshot were confirmed with accepted fact/link IDs and binding hashes, then executed by the Decimal engine.",
            "request_snapshot_sha256": confirmed_result["input_snapshot"]["snapshot_sha256"],
            "confirmed_decision_sha256": bound_decision.decision_sha256,
            "status": confirmed_calc["status"],
            "expected_value": confirmed_calc["expected_value"],
            "reference_value": expected_value,
            "formula": confirmed_calc["formula"],
            "used_sources": confirmed_calc["used_sources"],
            "calculation_trace": confirmed_calc["steps"],
            "reconciliation_result": confirmed_result,
        },
        "mode_c_missing_required_document": {
            "explanation": "The authentic saved model abstention was replayed for the case whose required invoice is absent and whose act is unlinked.",
            "request_snapshot_sha256": insufficient_result["input_snapshot"]["snapshot_sha256"],
            "status": insufficient_calc["status"],
            "expected_value": insufficient_calc["expected_value"],
            "diagnostic_codes": sorted({item["code"] for item in insufficient_calc["diagnostics"]}),
            "reconciliation_result": insufficient_result,
        },
    }


def run() -> dict[str, Any]:
    summary_path = RESULTS / "evaluation-summary.json"
    if not summary_path.is_file():
        raise RuntimeError(f"No completed {REQUESTED_MODEL_ID} live evaluation exists to replay yet.")
    original_summary = _read(summary_path)
    if original_summary.get("model_id") != REQUESTED_MODEL_ID:
        raise RuntimeError(
            f"Refusing to replay model {original_summary.get('model_id')!r}; expected {REQUESTED_MODEL_ID}."
        )
    scenario_ids = sorted(path.name for path in RESULTS.iterdir() if path.is_dir() and (path / "golden-reference.json").is_file())
    scenario_metrics = [_replay_case(case_id) for case_id in scenario_ids]
    policy_modes = _policy_mode_evaluation()
    model_metrics = []
    for case_id in scenario_ids:
        case_dir = RESULTS / case_id
        for repeat_index in range(1, 4):
            original = _read(case_dir / f"repeat-{repeat_index:02d}.json")
            replay = _read(case_dir / "post-fix-replay.json")["runs"][repeat_index - 1]
            if original.get("real_llm_response"):
                model_metrics.append(replay["comparison"])

    def mean(key: str) -> float | None:
        values = [item[key] for item in model_metrics if item.get(key) is not None]
        return statistics.mean(values) if values else None

    formula_scores = [item["formula_correct"] for item in model_metrics if item.get("formula_applicable")]
    value_scores = [item["value_correct"] for item in model_metrics if item.get("value_applicable")]
    summary = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "replay_type": "offline re-execution of saved genuine model plans through the patched engine; no provider calls",
        "baseline_commit": "dfaf8563e4cde349abf3ea143972a7582d9d18e0",
        "live_run_prompt_version": "1.0.0",
        "current_prompt_version": "1.0.1",
        "current_prompt_sha256": hashlib.sha256((ROOT / "prompts" / "calculation-plan.v1.0.1.txt").read_bytes()).hexdigest(),
        "provider": original_summary["provider"],
        "model_id": original_summary["model_id"],
        "available_model_count": original_summary["available_model_count"],
        "scenario_count": len(scenario_ids),
        "repeats_per_scenario": 3,
        "scenarios_with_real_model_responses": sum(item["real_llm_responses"] > 0 for item in scenario_metrics),
        "real_model_responses": len(model_metrics),
        "provider_402_repeats_without_model_reply": sum(item["provider_error_calls"] for item in scenario_metrics),
        "additional_live_llm_calls": 0,
        "original_total_llm_calls_including_preflight": original_summary["total_llm_calls"],
        "total_provider_cost": original_summary["total_provider_cost"],
        "total_provider_cost_currency": "RUB" if original_summary["total_provider_cost"] is not None else None,
        "total_prompt_tokens": original_summary["total_prompt_tokens"],
        "total_completion_tokens": original_summary["total_completion_tokens"],
        "overall_source_selection_precision": mean("precision"),
        "overall_source_selection_recall": mean("recall"),
        "overall_source_selection_f1": mean("f1"),
        "overall_source_identification_precision": mean("source_identification_precision"),
        "overall_source_identification_recall": mean("source_identification_recall"),
        "overall_source_identification_f1": mean("source_identification_f1"),
        "overall_formula_accuracy": statistics.mean(formula_scores) if formula_scores else None,
        "formula_scored_model_responses": len(formula_scores),
        "overall_published_value_accuracy": statistics.mean(value_scores) if value_scores else None,
        "published_value_scored_model_responses": len(value_scores),
        "overall_pass_count": sum(item["pass"] for item in model_metrics),
        "overall_scored_model_responses": len(model_metrics),
        "false_duplicate_inclusions": sum(item["false_duplicate_inclusions"] for item in scenario_metrics),
        "false_refusals": sum(item["false_refusals"] for item in scenario_metrics),
        "policy_modes": {key: {name: value for name, value in data.items() if name != "reconciliation_result"} for key, data in policy_modes.items() if isinstance(data, dict)},
        "scenarios": scenario_metrics,
    }
    _write(RESULTS / "evaluation-summary.post-fix.json", summary)
    _write(RESULTS / "policy-mode-evaluation.json", policy_modes)
    return summary


if __name__ == "__main__":
    result = run()
    print(
        f"Replayed {result['real_model_responses']} genuine model responses offline; "
        f"additional live calls=0; formula accuracy={result['overall_formula_accuracy']:.3f}; "
        f"published value accuracy={result['overall_published_value_accuracy']:.3f}"
    )
