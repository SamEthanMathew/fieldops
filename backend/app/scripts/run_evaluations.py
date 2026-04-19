from __future__ import annotations

import json
from pathlib import Path

from app.engine import SimulationSession
from app.hospital_intel import HospitalIntelAgent
from app.logistics import LogisticsAgent
from app.overwatch import OverwatchAgent
from app.rag import LocalProtocolRag
from app.scenario_loader import load_scenario
from app.triage import TriageAgent


ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "docs" / "results"

THRESHOLDS = {
    "triage_accuracy":      {"min": 0.95, "label": "Triage Accuracy ≥ 95%"},
    "accuracy_RED":         {"min": 0.95, "label": "RED Accuracy ≥ 95%  (fatal if missed)"},
    "accuracy_YELLOW":      {"min": 0.90, "label": "YELLOW Accuracy ≥ 90%"},
    "accuracy_GREEN":       {"min": 0.85, "label": "GREEN Accuracy ≥ 85%"},
    "transport_match_score":{"min": 0.90, "label": "Transport Match ≥ 90%"},
    "hospital_load_gini":   {"max": 0.30, "label": "Hospital Load Gini ≤ 0.30"},
    "survival_proxy_score": {"min": 0.90, "label": "Survival Proxy ≥ 90%"},
}


def build_confusion_matrix(session: SimulationSession) -> dict[str, dict[str, int]]:
    cats = ["RED", "YELLOW", "GREEN", "BLACK"]
    matrix: dict[str, dict[str, int]] = {gt: {pred: 0 for pred in cats} for gt in cats}
    for patient in session.state.patients.values():
        gt = patient.ground_truth_triage
        pred = getattr(patient.triage_category, "value", patient.triage_category)
        if gt and pred and gt in matrix and pred in matrix:
            matrix[gt][pred] += 1
    return matrix


def evaluate_thresholds(metrics: dict) -> list[dict]:
    results = []
    for key, spec in THRESHOLDS.items():
        if key.startswith("accuracy_"):
            cat = key.split("_", 1)[1]
            value = metrics.get("accuracy_by_category", {}).get(cat, 0.0)
        else:
            value = metrics.get(key, 0.0)

        if "min" in spec:
            passed = value >= spec["min"]
            threshold_str = f"≥ {spec['min']:.0%}"
        else:
            passed = value <= spec["max"]
            threshold_str = f"≤ {spec['max']:.2f}"

        results.append({
            "metric": key,
            "label": spec["label"],
            "threshold": threshold_str,
            "value": round(value, 3),
            "pass": passed,
        })
    return results


def print_pass_fail_table(scenario_id: str, results: list[dict]) -> None:
    col1, col2, col3, col4 = 44, 12, 10, 6
    sep = f"+{'-'*col1}+{'-'*col2}+{'-'*col3}+{'-'*col4}+"
    header = f"| {'Metric':<{col1-2}} | {'Threshold':<{col2-2}} | {'Value':<{col3-2}} | {'':>{col4-2}} |"
    print(f"\n{'='*74}")
    print(f"  SCENARIO: {scenario_id}")
    print(f"{'='*74}")
    print(sep)
    print(header)
    print(sep)
    all_pass = True
    for r in results:
        status = "PASS" if r["pass"] else "FAIL"
        if not r["pass"]:
            all_pass = False
        print(f"| {r['label']:<{col1-2}} | {r['threshold']:<{col2-2}} | {r['value']:<{col3-2}.3f} | {status:>{col4-2}} |")
    print(sep)
    verdict = "ALL PASS ✓" if all_pass else "FAILURES DETECTED ✗"
    print(f"  Verdict: {verdict}")


def print_confusion_matrix(matrix: dict[str, dict[str, int]]) -> None:
    cats = ["RED", "YELLOW", "GREEN", "BLACK"]
    col = 9
    print(f"\n  Confusion Matrix (rows=ground truth, cols=predicted):")
    header = f"  {'GT\\Pred':<8} " + " ".join(f"{c:>{col}}" for c in cats)
    print(header)
    print(f"  {'-'*60}")
    for gt in cats:
        row = f"  {gt:<8} " + " ".join(f"{matrix[gt].get(pred, 0):>{col}}" for pred in cats)
        print(row)
    print()


def run_scenario(scenario_id: str) -> dict:
    session = SimulationSession(
        scenario=load_scenario(scenario_id),
        triage_agent=TriageAgent(LocalProtocolRag()),
        hospital_intel=HospitalIntelAgent(),
        logistics=LogisticsAgent(),
        overwatch=OverwatchAgent(),
    )
    for minute in range(1, session.scenario.duration_minutes + 1):
        session._process_minute(minute)
        for dispatch_id in list(session.state.pending_approvals):
            session.approve_dispatch_sync(dispatch_id)

    fm = session.state.metrics.model_dump(mode="json")
    threshold_results = evaluate_thresholds(fm)
    confusion = build_confusion_matrix(session)

    print_pass_fail_table(scenario_id, threshold_results)
    print_confusion_matrix(confusion)

    return {
        "scenario_id": scenario_id,
        "fieldops_metrics": fm,
        "baseline_metrics": session.state.baseline.final_metrics.model_dump(mode="json"),
        "threshold_results": threshold_results,
        "confusion_matrix": confusion,
        "overall_pass": all(r["pass"] for r in threshold_results),
    }


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    results = [
        run_scenario(s)
        for s in ["bridge-collapse-light", "bridge-collapse-standard", "bridge-collapse-heavy"]
    ]
    output_path = OUTPUT / "evaluation_results.json"
    output_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nWrote {output_path}")
    overall = all(r["overall_pass"] for r in results)
    print(f"OVERALL SUITE: {'PASS ✓' if overall else 'FAIL ✗'}\n")


if __name__ == "__main__":
    main()
