"""Run bounded, real OpenAI-compatible LLM evaluations on synthetic inputs only."""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reconciliation_engine.config import Settings
from reconciliation_engine.facts import extract_facts, numeric_value
from reconciliation_engine.models import ReconciliationRequest
from reconciliation_engine.planner import LLMPlanner
from reconciliation_engine.service import reconcile

from prepare_cases import prepare

RESULTS = ROOT / "tests" / "results" / "live_e2e"
REQUESTED_MODEL_ID = "google/gemma-4-26b-a4b-it"


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _validate_response_models(call_records: list[dict[str, Any]]) -> None:
    for call in call_records:
        if call.get("assistant_content") is None:
            continue
        returned_model = call.get("model_returned")
        if returned_model != REQUESTED_MODEL_ID:
            raise RuntimeError(
                f"Provider returned model {returned_model!r}; refusing to record it as {REQUESTED_MODEL_ID}."
            )


def _runtime_settings() -> Settings:
    configured = Settings()
    polza_key = os.environ.get("POLZA_AI_API_KEY", "")
    api_key = configured.llm_api_key or polza_key
    if not api_key:
        raise RuntimeError("No LLM_API_KEY or POLZA_AI_API_KEY is available in this process.")
    base_url = os.environ.get("LLM_BASE_URL") or ("https://polza.ai/api/v1" if polza_key and not configured.llm_api_key else configured.llm_base_url)
    explicit_model = os.environ.get("LLM_MODEL")
    if not explicit_model and "llm_model" in configured.model_fields_set:
        explicit_model = configured.llm_model
    if explicit_model and explicit_model != REQUESTED_MODEL_ID:
        raise RuntimeError(
            f"This live evaluation is pinned to {REQUESTED_MODEL_ID}; refusing configured LLM_MODEL={explicit_model!r}."
        )
    model = REQUESTED_MODEL_ID
    return Settings(
        llm_enabled=True,
        llm_api_key=api_key,
        llm_base_url=base_url,
        llm_model=model,
        llm_timeout_seconds=configured.llm_timeout_seconds,
        llm_max_candidates=configured.llm_max_candidates,
        llm_trusted_hosts=configured.llm_trusted_hosts,
        result_store_dir=configured.result_store_dir,
    )


def _model_catalog(settings: Settings, output_path: Path | None = None) -> list[str]:
    url = settings.llm_base_url.rstrip("/") + "/models"
    response = httpx.get(url, headers={"Authorization": f"Bearer {settings.llm_api_key}"}, timeout=settings.llm_timeout_seconds, follow_redirects=False)
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data")
    if not isinstance(data, list):
        raise RuntimeError("Provider /models response does not contain a data list.")
    model_ids = sorted({item["id"] for item in data if isinstance(item, dict) and isinstance(item.get("id"), str)})
    if settings.llm_model not in model_ids:
        raise RuntimeError(f"Configured model {settings.llm_model!r} is not present in the provider /models response.")
    _write(output_path or RESULTS / "model-catalog.json", {
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "base_url": settings.llm_base_url,
        "model_count": len(model_ids),
        "selected_model": settings.llm_model,
        "available_gemma_model_ids": [item for item in model_ids if "gemma" in item.casefold()],
        "secret_included": False,
    })
    return model_ids


def _preflight(settings: Settings, output_path: Path | None = None) -> dict[str, Any]:
    payload = {
        "target": {"target_id": "target_001", "label": "Synthetic API preflight", "description": "Protocol check using no source records."},
        "candidates": [],
        "source_groups": [],
        "candidate_count": 0,
        "candidate_batch": {"index": 1, "total_batches": 1, "batch_candidate_count": 0, "total_candidate_count": 0, "all_batches_will_be_reviewed": True},
        "document_date_facts": [],
        "linking_graph": {"relationships": [], "review_required": [], "unlinked_source_groups": [], "validation_diagnostics": []},
        "output_contract": __import__("reconciliation_engine.plans", fromlist=["CalculationPlan"]).CalculationPlan.model_json_schema(),
    }
    planner = LLMPlanner(settings)
    plan = planner._request_plan(payload, sensitive_data=False)
    _validate_response_models(planner.call_records)
    record = {
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "provider": "Polza OpenAI-compatible API" if "polza.ai" in (urlsplit(settings.llm_base_url).hostname or "") else "OpenAI-compatible API",
        "model_requested": settings.llm_model,
        "model_returned": planner.call_records[0].get("model_returned") if planner.call_records else None,
        "synthetic_data_only": True,
        "input_payload": payload,
        "calculation_plan": plan.as_dict(),
        "llm_calls": planner.call_records,
        "secret_included": False,
    }
    _write(output_path or RESULTS / "provider-preflight.json", record)
    return record


def _plan_expression(plan: dict[str, Any] | None) -> Any:
    if not plan or not plan.get("result_step_id"):
        return None
    steps = {item["step_id"]: item for item in plan.get("steps", [])}
    active: set[str] = set()

    def expand(value: str) -> Any:
        if value not in steps:
            return {"fact_id": value}
        if value in active:
            return {"cycle": value}
        active.add(value)
        step = steps[value]
        children = [expand(item) for item in step.get("inputs", [])]
        active.remove(value)
        if step.get("operation") in {"sum", "add"}:
            children.sort(key=lambda item: json.dumps(item, sort_keys=True))
        result = {"operation": step.get("operation"), "inputs": children}
        if step.get("operation") == "round":
            result["scale"] = step.get("scale")
        return result

    return expand(plan["result_step_id"])


def _leaves(expression: Any) -> list[str]:
    if not isinstance(expression, dict):
        return []
    if "fact_id" in expression:
        return [expression["fact_id"]]
    return [fact_id for child in expression.get("inputs", []) for fact_id in _leaves(child)]


def _formula_matches(plan: dict[str, Any] | None, reference: dict[str, Any]) -> bool:
    if not isinstance(plan, dict) or any(
        not isinstance(step, dict)
        or set(step) - {"step_id", "operation", "inputs", "scale"}
        for step in plan.get("steps", [])
    ):
        return False
    expression = _plan_expression(plan)
    if not expression or not isinstance(expression, dict):
        return False
    if (
        expression.get("operation") == "round"
        and expression.get("scale") == (plan or {}).get("rounding_scale")
        and len(expression.get("inputs", [])) == 1
    ):
        expression = expression["inputs"][0]
        if not isinstance(expression, dict):
            return False
    expected = reference["expected_formula"]
    # Validate the expression tree independently of its leaves. A matching
    # operation name and input count must not hide malformed or extra nodes.
    allowed = {"fact_id", "operation", "inputs", "scale"}
    def valid(node: Any) -> bool:
        if not isinstance(node, dict) or set(node) - allowed:
            return False
        if "fact_id" in node:
            return isinstance(node["fact_id"], str) and not any(k in node for k in ("operation", "inputs", "scale"))
        op, inputs = node.get("operation"), node.get("inputs")
        if op == "round":
            return isinstance(node.get("scale"), int) and isinstance(inputs, list) and len(inputs) == 1 and valid(inputs[0])
        return op in {"sum", "add", "subtract", "multiply", "divide"} and isinstance(inputs, list) and len(inputs) >= (1 if op == "sum" else 2) and "scale" not in node and all(valid(child) for child in inputs)
    if not valid(expression):
        return False
    expected_input_count = expected.get("input_count")
    operation = expression.get("operation")
    expected_operation = expected.get("operation")
    equivalent_aggregations = operation in {"sum", "add"} and expected_operation in {"sum", "add"}
    if operation != expected_operation and not equivalent_aggregations:
        # A one-source sum is the identity. LLMs often make target rounding
        # explicit as round(fact, target_scale), while the engine always applies
        # that same final target rounding after executing the formula.
        if not (
            expected_input_count == 1
            and expected.get("operation") in {"sum", "add"}
            and len(_leaves(expression)) == 1
        ):
            return False
    selected = [item.get("fact_id") for item in (plan or {}).get("included", [])]
    if expected_input_count is not None and len(selected) != expected_input_count:
        return False
    if expected_input_count == 1 and expected_operation in {"sum", "add"}:
        return len(_leaves(expression)) == 1
    if expected.get("ordered_keys"):
        facts_by_id = {fact.fact_id: fact for fact in extract_facts(_read(RESULTS / reference["case_id"] / "input.json")["extraction_results"])}
        ordered_leaves = _leaves(expression)
        return [facts_by_id[item].key for item in ordered_leaves if item in facts_by_id] == expected["ordered_keys"]
    if expected.get("input_count") == 1 and operation in {"sum", "add"}:
        return len(_leaves(expression)) == 1
    return len(_leaves(expression)) == expected.get("input_count", len(_leaves(expression)))


def _source_metrics(plan: dict[str, Any] | None, reference: dict[str, Any]) -> dict[str, Any]:
    selected = [item.get("fact_id") for item in (plan or {}).get("included", []) if item.get("fact_id")]
    identified = list(dict.fromkeys([*selected, *((plan or {}).get("unprocessed_fact_ids") or [])]))
    groups = reference["expected_source_groups"]
    def scores(candidates: list[str]) -> tuple[int, int, int, float, float, float, bool]:
        covered = sum(any(fact_id in candidates for fact_id in group) for group in groups)
        represented_candidates = sum(any(fact_id in group for group in groups) for fact_id in candidates)
        false_positives = max(0, len(candidates) - represented_candidates)
        false_negatives = len(groups) - covered
        precision = represented_candidates / (represented_candidates + false_positives) if represented_candidates + false_positives else (1.0 if not groups else 0.0)
        recall = covered / (covered + false_negatives) if covered + false_negatives else 1.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        return covered, false_positives, false_negatives, precision, recall, f1, false_positives == 0 and false_negatives == 0

    covered, false_positives, false_negatives, precision, recall, f1, correct = scores(selected)
    identified_covered, identified_fp, identified_fn, identified_precision, identified_recall, identified_f1, identified_correct = scores(identified)
    duplicate_count = sum(max(0, sum(item in group for item in selected) - 1) for group in groups)
    return {
        "selected_fact_ids": selected,
        "identified_fact_ids": identified,
        "expected_operation_groups": len(groups),
        "represented_groups": covered,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "false_positive_sources": false_positives,
        "missed_operation_groups": false_negatives,
        "false_duplicate_inclusions": duplicate_count,
        "source_selection_correct": correct,
        "source_identification_precision": identified_precision,
        "source_identification_recall": identified_recall,
        "source_identification_f1": identified_f1,
        "identified_operation_groups": identified_covered,
        "unidentified_operation_groups": identified_fn,
        "false_positive_identifications": identified_fp,
        "source_identification_correct": identified_correct,
    }


def _compare(result: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    calculation = result["calculations"][0]
    plan = calculation.get("calculation_plan")
    sources = _source_metrics(plan, reference)
    formula_applicable = bool(plan and plan.get("steps") and plan.get("result_step_id"))
    formula_correct = _formula_matches(plan, reference) if formula_applicable else None
    expected_value = reference.get("expected_value")
    value_correct = calculation.get("status") == "calculated" and calculation.get("expected_value") == expected_value
    gate_code = reference.get("expected_publication_gate")
    actual_codes = {item.get("code") for item in calculation.get("diagnostics", [])}
    gate_observed = not gate_code or gate_code in actual_codes
    safe_abstention = calculation.get("status") != "calculated" and calculation.get("expected_value") is None
    if gate_code == "independence_not_established" and safe_abstention:
        gate_observed = bool(
            plan
            and plan.get("requires_manual_review")
            and plan.get("information_gaps")
            and sources["source_identification_correct"]
        )
    value_applicable = bool(formula_applicable and not gate_code and plan)
    passed = (
        safe_abstention and gate_observed and sources["source_identification_correct"]
        if gate_code else
        sources["source_selection_correct"]
        and sources["false_duplicate_inclusions"] == 0
        and formula_correct is True
        and value_correct
    )
    return {
        **sources,
        "formula_applicable": formula_applicable,
        "formula_correct": formula_correct,
        "calculation_status": calculation.get("status"),
        "expected_value": expected_value,
        "actual_expected_value": calculation.get("expected_value"),
        "value_applicable": value_applicable,
        "value_correct": value_correct,
        "expected_publication_gate": gate_code,
        "publication_gate_observed": gate_observed,
        "safe_abstention": safe_abstention,
        "diagnostic_codes": sorted(actual_codes),
        "plan_source": calculation.get("plan_source"),
        "pass": passed,
    }


def _usage_totals(call_records: list[dict[str, Any]]) -> dict[str, Any]:
    prompt = completion = total = 0
    costs: list[float] = []
    currencies: set[str] = set()
    for call in call_records:
        usage = call.get("usage") or {}
        prompt += int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
        completion += int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0)
        total += int(usage.get("total_tokens", 0) or 0)
        cost = call.get("provider_cost")
        if isinstance(cost, (int, float)):
            costs.append(float(cost))
        currency = call.get("provider_cost_currency")
        if not currency and "cost_rub" in usage:
            currency = "RUB"
        if currency:
            currencies.add(currency)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "provider_cost_total": sum(costs) if costs else None,
        "provider_cost_currency": next(iter(currencies)) if len(currencies) == 1 else ("mixed" if currencies else None),
    }


def _aggregate(case_id: str, repeats: list[dict[str, Any]]) -> dict[str, Any]:
    scored_repeats = [
        item for item in repeats
        if item.get("real_llm_response", any(call.get("assistant_content") for call in item.get("llm_calls", [])))
    ]
    metrics = [item["comparison"] for item in scored_repeats]
    def mean_score(key: str) -> float | None:
        values = [item[key] for item in metrics if item.get(key) is not None]
        return statistics.mean(values) if values else None

    signatures = [json.dumps({"sources": sorted(item["selected_fact_ids"]), "formula": item["formula_correct"], "status": item["calculation_status"], "value": item["actual_expected_value"]}, sort_keys=True) for item in metrics]
    return {
        "case_id": case_id,
        "repeat_count": len(repeats),
        "real_llm_responses": len(scored_repeats),
        "pass_count": sum(item["pass"] for item in metrics),
        "mean_precision": mean_score("precision"),
        "mean_recall": mean_score("recall"),
        "mean_f1": mean_score("f1"),
        "source_identification_precision": mean_score("source_identification_precision"),
        "source_identification_recall": mean_score("source_identification_recall"),
        "source_identification_f1": mean_score("source_identification_f1"),
        "formula_accuracy": mean_score("formula_correct"),
        "formula_scored_repeats": sum(item["formula_applicable"] for item in metrics),
        "value_accuracy": sum(bool(item["value_correct"]) for item in metrics if item["value_applicable"]) / sum(item["value_applicable"] for item in metrics) if any(item["value_applicable"] for item in metrics) else None,
        "value_scored_repeats": sum(item["value_applicable"] for item in metrics),
        "false_duplicate_inclusions": sum(item["false_duplicate_inclusions"] for item in metrics),
        "false_refusals": sum(item["calculation_status"] != "calculated" and not item["expected_publication_gate"] and item["source_selection_correct"] and item["formula_correct"] is True for item in metrics),
        "stable_run_fraction": Counter(signatures).most_common(1)[0][1] / len(signatures) if signatures else None,
        "llm_calls": sum(len(item["llm_calls"]) for item in repeats),
        "real_llm_responses": sum(any(call.get("assistant_content") for call in item["llm_calls"]) for item in repeats),
        "provider_error_calls": sum(sum((call.get("http_status") or 0) >= 400 for call in item["llm_calls"]) for item in repeats),
        "usage": _usage_totals([call for item in repeats for call in item["llm_calls"]]),
        "latency_ms": sum(call.get("duration_ms", 0) for item in repeats for call in item["llm_calls"]),
        "runs": [{"repeat": item["repeat"], "comparison": item["comparison"], "llm_call_count": len(item["llm_calls"]), "real_llm_response": any(call.get("assistant_content") for call in item["llm_calls"])} for item in repeats],
    }


def _select_cases(cases: list[dict[str, Any]], case_ids: list[str] | None) -> list[dict[str, Any]]:
    if not case_ids:
        return cases
    available = {case["reference"]["case_id"] for case in cases}
    unknown = sorted(set(case_ids) - available)
    if unknown:
        raise ValueError(f"Unknown synthetic case ID(s): {', '.join(unknown)}")
    selected = set(case_ids)
    return [case for case in cases if case["reference"]["case_id"] in selected]


def run(repeat_count: int, max_api_calls: int, case_ids: list[str] | None = None) -> dict[str, Any]:
    settings = _runtime_settings()
    all_cases = prepare()
    cases = _select_cases(all_cases, case_ids)
    output_tag = f".targeted-{'-'.join(case['reference']['case_id'] for case in cases)}" if case_ids else ""
    model_ids = _model_catalog(settings, RESULTS / f"model-catalog{output_tag}.json")
    anticipated_calls = 0
    for case in cases:
        request = ReconciliationRequest.model_validate(case["request"])
        target = request.context.targets[0]
        candidates = [fact for fact in extract_facts(request.extraction_results) if fact.document_type != "kfz_report" and fact.document_id != target.kfz_document_id and numeric_value(fact) is not None]
        anticipated_calls += repeat_count * max(1, math.ceil(len(candidates) / max(1, settings.llm_max_candidates)))
    total_budgeted_calls = anticipated_calls + 1
    if total_budgeted_calls > max_api_calls:
        raise RuntimeError(f"Bounded run would require {total_budgeted_calls} paid Chat Completions including one protocol preflight, above --max-api-calls={max_api_calls}; no calls were made.")
    preflight = _preflight(settings, RESULTS / f"provider-preflight{output_tag}.json")

    all_case_summaries = []
    all_calls = list(preflight["llm_calls"])
    for case in cases:
        case_id = case["reference"]["case_id"]
        case_dir = RESULTS / case_id
        request = ReconciliationRequest.model_validate(_read(case_dir / "input.json"))
        reference = _read(case_dir / "golden-reference.json")
        repeat_results = []
        for repeat_index in range(1, repeat_count + 1):
            planner = LLMPlanner(settings)
            started = datetime.now(timezone.utc)
            result = reconcile(request, settings, planner=planner)
            _validate_response_models(planner.call_records)
            calculation = result["calculations"][0]
            comparison = _compare(result, reference)
            call_records = planner.call_records
            all_calls.extend(call_records)
            repeat_result = {
                "case_id": case_id,
                "repeat": repeat_index,
                "started_at": started.isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "request_sha256": result["input_snapshot"]["snapshot_sha256"],
                "provider": "Polza OpenAI-compatible API" if "polza.ai" in (urlsplit(settings.llm_base_url).hostname or "") else "OpenAI-compatible API",
                "model_requested": settings.llm_model,
                "model_returned": next((item.get("model_returned") for item in reversed(call_records) if item.get("model_returned")), None),
                "llm_calls": call_records,
                "calculation_plan": calculation.get("calculation_plan"),
                "reconciliation_result": result,
                "comparison": comparison,
                "synthetic_data_only": True,
                "real_llm_response": bool(call_records and any(item.get("assistant_content") for item in call_records)),
            }
            repeat_path = case_dir / f"repeat-{repeat_index:02d}{output_tag}.json"
            _write(repeat_path, repeat_result)
            repeat_results.append(repeat_result)
            print(f"{case_id} repeat {repeat_index}: calls={len(call_records)} status={calculation['status']} precision={comparison['precision']:.3f} recall={comparison['recall']:.3f} formula={comparison['formula_correct']} value={calculation.get('expected_value')}")
        summary = _aggregate(case_id, repeat_results)
        _write(case_dir / f"metrics{output_tag}.json", summary)
        all_case_summaries.append(summary)

    all_usage = _usage_totals(all_calls)
    observed_comparisons = [
        run_item["comparison"]
        for item in all_case_summaries
        for run_item in item["runs"]
        if run_item["real_llm_response"]
    ]

    def observed_mean(key: str) -> float | None:
        values = [item[key] for item in observed_comparisons if item.get(key) is not None]
        return statistics.mean(values) if values else None

    formula_scores = [item["formula_correct"] for item in observed_comparisons if item.get("formula_applicable")]
    value_scores = [item["value_correct"] for item in observed_comparisons if item.get("value_applicable")]
    evaluation = {
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "provider": "Polza OpenAI-compatible API" if "polza.ai" in (urlsplit(settings.llm_base_url).hostname or "") else "OpenAI-compatible API",
        "base_url": settings.llm_base_url,
        "model_id": settings.llm_model,
        "available_model_count": len(model_ids),
        "scenario_count": len(all_case_summaries),
        "selected_case_ids": [case["reference"]["case_id"] for case in cases],
        "repeat_count": repeat_count,
        "paid_call_limit": max_api_calls,
        "actual_llm_call_count": sum(item["llm_calls"] for item in all_case_summaries),
        "protocol_preflight_call_count": len(preflight["llm_calls"]),
        "real_model_response_count": sum(item["real_llm_responses"] for item in all_case_summaries) + sum(bool(call.get("assistant_content")) for call in preflight["llm_calls"]),
        "provider_error_call_count": sum(item["provider_error_calls"] for item in all_case_summaries) + sum((call.get("http_status") or 0) >= 400 for call in preflight["llm_calls"]),
        "all_calls_used_synthetic_data": True,
        "all_call_records_include_secret": False,
        "overall_mean_precision": observed_mean("precision"),
        "overall_mean_recall": observed_mean("recall"),
        "overall_mean_f1": observed_mean("f1"),
        "overall_source_identification_precision": observed_mean("source_identification_precision"),
        "overall_source_identification_recall": observed_mean("source_identification_recall"),
        "overall_source_identification_f1": observed_mean("source_identification_f1"),
        "overall_formula_accuracy": statistics.mean(formula_scores) if formula_scores else None,
        "formula_scored_response_count": len(formula_scores),
        "overall_value_accuracy": statistics.mean(value_scores) if value_scores else None,
        "value_scored_response_count": len(value_scores),
        "overall_pass_count": sum(item["pass"] for item in observed_comparisons),
        "overall_scored_response_count": len(observed_comparisons),
        "total_false_duplicate_inclusions": sum(item["false_duplicate_inclusions"] for item in all_case_summaries),
        "total_false_refusals": sum(item["false_refusals"] for item in all_case_summaries),
        "total_llm_calls": sum(item["llm_calls"] for item in all_case_summaries) + len(preflight["llm_calls"]),
        "total_provider_cost": all_usage["provider_cost_total"],
        "total_provider_cost_currency": all_usage["provider_cost_currency"],
        "total_prompt_tokens": all_usage["prompt_tokens"],
        "total_completion_tokens": all_usage["completion_tokens"],
        "total_latency_ms": sum(call.get("duration_ms", 0) for call in all_calls),
        "scenarios": all_case_summaries,
    }
    _write(RESULTS / f"evaluation-summary{output_tag}.json", evaluation)
    return evaluation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=3, help="Real model runs per scenario; default 3.")
    parser.add_argument("--max-api-calls", type=int, default=40, help="Hard cap on billed chat-completion calls; model catalog GET is not included.")
    parser.add_argument("--case-id", action="append", help="Run only this synthetic scenario. Repeat the option to select multiple scenarios.")
    parser.add_argument("--prepare-only", action="store_true", help="Write synthetic requests and independent references without model calls.")
    args = parser.parse_args()
    if args.repeat < 1 or args.max_api_calls < 1:
        parser.error("--repeat and --max-api-calls must be positive")
    if args.prepare_only:
        cases = prepare()
        print(f"Prepared {len(cases)} synthetic scenarios. No LLM request was made.")
        return 0
    try:
        evaluation = run(args.repeat, args.max_api_calls, args.case_id)
    except Exception as exc:
        print(f"LIVE EVALUATION NOT COMPLETED: {type(exc).__name__}: {exc}")
        return 2
    def format_metric(value: float | None) -> str:
        return f"{value:.3f}" if value is not None else "n/a"
    print(f"Completed {evaluation['scenario_count']} scenarios, {evaluation['repeat_count']} repeats each, {evaluation['actual_llm_call_count']} scenario calls + {evaluation['protocol_preflight_call_count']} preflight call; mean F1={format_metric(evaluation['overall_mean_f1'])}, formula accuracy={format_metric(evaluation['overall_formula_accuracy'])}, value accuracy={format_metric(evaluation['overall_value_accuracy'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
