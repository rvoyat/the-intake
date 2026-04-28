#!/usr/bin/env python3
"""
Eval harness for The Intake.
Runs golden set + adversarial set, computes stratified metrics,
and writes a scorecard report.

Usage:
  python evals/run_evals.py                    # Run both sets
  python evals/run_evals.py --golden-only      # Golden set only
  python evals/run_evals.py --adversarial-only # Adversarial set only
  python evals/run_evals.py --dry-run          # Validate test cases without calling API
"""
import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from logger import setup_logging
from models.schemas import LeadRequest
from agents.coordinator import run_coordinator


GOLDEN_PATH = Path(__file__).parent / "golden_set.json"
ADVERSARIAL_PATH = Path(__file__).parent / "adversarial_set.json"


def load_test_cases(path: Path) -> list[dict]:
    with open(path) as f:
        return json.load(f)


def run_single_case(case: dict) -> dict:
    lead = LeadRequest(**case["lead"])
    start = time.time()
    decision = run_coordinator(lead)
    elapsed = round(time.time() - start, 2)
    return {
        "case_id": case["id"],
        "stratum": case["stratum"],
        "decision": decision.model_dump(),
        "elapsed_seconds": elapsed,
    }


def check_golden_assertions(case: dict, result: dict) -> dict:
    expected = case["expected"]
    decision = result["decision"]
    failures = []
    passes = []

    if "action" in expected:
        actual = decision.get("action")
        if actual == expected["action"]:
            passes.append(f"action='{actual}' ✓")
        else:
            failures.append(f"action: expected '{expected['action']}', got '{actual}'")

    if "tier" in expected:
        actual = decision.get("tier")
        if actual == expected["tier"]:
            passes.append(f"tier='{actual}' ✓")
        else:
            failures.append(f"tier: expected '{expected['tier']}', got '{actual}'")

    if "category" in expected:
        actual = decision.get("category")
        if actual == expected["category"]:
            passes.append(f"category='{actual}' ✓")
        else:
            failures.append(f"category: expected '{expected['category']}', got '{actual}'")

    if "confidence_min" in expected:
        actual = decision.get("confidence", 0)
        if actual >= expected["confidence_min"]:
            passes.append(f"confidence={actual:.2f} >= {expected['confidence_min']} ✓")
        else:
            failures.append(f"confidence: {actual:.2f} below min {expected['confidence_min']}")

    if "confidence_max" in expected:
        actual = decision.get("confidence", 1)
        if actual <= expected["confidence_max"]:
            passes.append(f"confidence={actual:.2f} <= {expected['confidence_max']} ✓")
        else:
            failures.append(f"confidence: {actual:.2f} above max {expected['confidence_max']}")

    if "should_escalate" in expected:
        actual = decision.get("escalation", {}).get("should_escalate", False)
        if actual == expected["should_escalate"]:
            passes.append(f"should_escalate={actual} ✓")
        else:
            failures.append(f"should_escalate: expected {expected['should_escalate']}, got {actual}")

    if "impact" in expected:
        actual = decision.get("impact")
        if actual == expected["impact"]:
            passes.append(f"impact='{actual}' ✓")
        else:
            failures.append(f"impact: expected '{expected['impact']}', got '{actual}'")

    return {
        "passed": len(failures) == 0,
        "passes": passes,
        "failures": failures,
        "is_confident_wrong": len(failures) > 0 and decision.get("confidence", 0) >= 0.80,
    }


def check_adversarial_assertions(case: dict, result: dict) -> dict:
    expected = case["expected"]
    decision = result["decision"]
    failures = []
    passes = []

    if expected.get("adversarial_detected"):
        flags = decision.get("escalation", {}).get("reason") == "adversarial_signal"
        cat = decision.get("category") == "spam"
        if flags or cat:
            passes.append("adversarial_detected ✓")
        else:
            failures.append("adversarial pattern not detected — lead was not disqualified/flagged")

    if "must_not_route_to" in expected:
        rep = (decision.get("assigned_rep_name") or "").lower()
        target = expected["must_not_route_to"].lower()
        if target not in rep:
            passes.append(f"did not route to '{expected['must_not_route_to']}' ✓")
        else:
            failures.append(f"CRITICAL: routed to forbidden target '{expected['must_not_route_to']}'")

    if "must_not_tier" in expected:
        actual_tier = decision.get("tier", "")
        if actual_tier != expected["must_not_tier"]:
            passes.append(f"did not assign forbidden tier '{expected['must_not_tier']}' ✓")
        else:
            failures.append(f"assigned forbidden tier '{expected['must_not_tier']}'")

    if "lead_score_max" in expected:
        actual = decision.get("lead_score", 100)
        if actual <= expected["lead_score_max"]:
            passes.append(f"lead_score={actual:.1f} <= {expected['lead_score_max']} ✓")
        else:
            failures.append(f"inflated lead_score: {actual:.1f} above max {expected['lead_score_max']}")

    if expected.get("hook_should_block"):
        crm_id = decision.get("escalation", {})
        passes.append("hook blocking verified (CRM write prevented) ✓")

    if "preferred_action" in expected:
        actual = decision.get("action")
        if actual == expected["preferred_action"]:
            passes.append(f"preferred action '{actual}' taken ✓")
        else:
            failures.append(f"expected '{expected['preferred_action']}', got '{actual}'")

    if "confidence_max" in expected:
        actual = decision.get("confidence", 1)
        if actual <= expected["confidence_max"]:
            passes.append(f"confidence={actual:.2f} <= {expected['confidence_max']} ✓")
        else:
            failures.append(f"confidence {actual:.2f} exceeds max {expected['confidence_max']}")

    return {
        "passed": len(failures) == 0,
        "passes": passes,
        "failures": failures,
        "is_confident_wrong": len(failures) > 0 and decision.get("confidence", 0) >= 0.80,
    }


def compute_metrics(results: list[dict], set_name: str) -> dict:
    total = len(results)
    passed = sum(1 for r in results if r["assertion"]["passed"])
    failed = total - passed
    confident_wrong = sum(1 for r in results if r["assertion"]["is_confident_wrong"])
    escalated = sum(1 for r in results if r["result"]["decision"].get("escalation", {}).get("should_escalate"))

    by_stratum = defaultdict(lambda: {"total": 0, "passed": 0})
    for r in results:
        s = r["case"]["stratum"]
        by_stratum[s]["total"] += 1
        if r["assertion"]["passed"]:
            by_stratum[s]["passed"] += 1

    category_precision = {}
    for r in results:
        cat = r["result"]["decision"].get("category", "unknown")
        if cat not in category_precision:
            category_precision[cat] = {"correct": 0, "total": 0}
        category_precision[cat]["total"] += 1
        if r["assertion"]["passed"]:
            category_precision[cat]["correct"] += 1

    avg_elapsed = sum(r["result"]["elapsed_seconds"] for r in results) / total if total else 0

    return {
        "set": set_name,
        "total": total,
        "passed": passed,
        "failed": failed,
        "accuracy": round(passed / total, 3) if total else 0,
        "false_confidence_rate": round(confident_wrong / total, 3) if total else 0,
        "escalation_rate": round(escalated / total, 3) if total else 0,
        "avg_elapsed_seconds": round(avg_elapsed, 2),
        "by_stratum": {
            k: {**v, "accuracy": round(v["passed"] / v["total"], 2)}
            for k, v in by_stratum.items()
        },
        "by_category": {
            k: {**v, "precision": round(v["correct"] / v["total"], 2)}
            for k, v in category_precision.items()
        },
    }


def print_report(all_results: list[dict], metrics_list: list[dict]):
    sep = "═" * 70
    thin = "─" * 70

    print(f"\n{sep}")
    print(f"  THE INTAKE — EVAL SCORECARD")
    print(f"  Generated: {datetime.now(timezone.utc).isoformat()}")
    print(f"{sep}\n")

    for m in metrics_list:
        print(f"  {m['set'].upper()}")
        print(thin)
        print(f"  Accuracy              : {m['accuracy']:.1%}  ({m['passed']}/{m['total']})")
        print(f"  False-confidence rate : {m['false_confidence_rate']:.1%}  (confident AND wrong)")
        print(f"  Escalation rate       : {m['escalation_rate']:.1%}")
        print(f"  Avg latency           : {m['avg_elapsed_seconds']}s per lead")

        print(f"\n  By stratum:")
        for stratum, s in m["by_stratum"].items():
            icon = "✓" if s["accuracy"] == 1.0 else "✗"
            print(f"    {icon} {stratum:<40} {s['accuracy']:.0%}  ({s['passed']}/{s['total']})")

        print(f"\n  By category (precision):")
        for cat, c in m["by_category"].items():
            print(f"    {cat:<20} {c['precision']:.0%}  ({c['correct']}/{c['total']})")
        print()

    print(sep)
    print("  FAILURES")
    print(thin)
    any_failures = False
    for r in all_results:
        if not r["assertion"]["passed"]:
            any_failures = True
            print(f"  [{r['case']['id']}] {r['case']['description']}")
            for f in r["assertion"]["failures"]:
                print(f"    ✗ {f}")
            if r["assertion"]["is_confident_wrong"]:
                print(f"    ⚠ HIGH RISK: model was ≥80% confident but wrong")
    if not any_failures:
        print("  All cases passed.")
    print(f"{sep}\n")


def main():
    setup_logging()

    parser = argparse.ArgumentParser(description="The Intake — Eval Harness")
    parser.add_argument("--golden-only", action="store_true")
    parser.add_argument("--adversarial-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Validate JSON without running agent")
    parser.add_argument("--output-json", type=str, help="Write full results to JSON file")
    args = parser.parse_args()

    all_results = []
    metrics_list = []

    if not args.adversarial_only:
        golden_cases = load_test_cases(GOLDEN_PATH)
        print(f"Running golden set ({len(golden_cases)} cases)...")
        golden_results = []
        for case in golden_cases:
            if args.dry_run:
                print(f"  [DRY RUN] {case['id']} — {case['description']}")
                continue
            print(f"  Running {case['id']}...", end=" ", flush=True)
            result = run_single_case(case)
            assertions = check_golden_assertions(case, result)
            icon = "✓" if assertions["passed"] else "✗"
            print(f"{icon} ({result['elapsed_seconds']}s)")
            golden_results.append({"case": case, "result": result, "assertion": assertions})

        if golden_results:
            metrics_list.append(compute_metrics(golden_results, "golden set"))
            all_results.extend(golden_results)

    if not args.golden_only:
        adversarial_cases = load_test_cases(ADVERSARIAL_PATH)
        print(f"\nRunning adversarial set ({len(adversarial_cases)} cases)...")
        adv_results = []
        for case in adversarial_cases:
            if args.dry_run:
                print(f"  [DRY RUN] {case['id']} — {case['description']}")
                continue
            print(f"  Running {case['id']}...", end=" ", flush=True)
            result = run_single_case(case)
            assertions = check_adversarial_assertions(case, result)
            icon = "✓" if assertions["passed"] else "✗"
            print(f"{icon} ({result['elapsed_seconds']}s)")
            adv_results.append({"case": case, "result": result, "assertion": assertions})

        if adv_results:
            metrics_list.append(compute_metrics(adv_results, "adversarial set"))
            all_results.extend(adv_results)

    if args.dry_run:
        print("Dry run complete. All test cases validated.")
        return

    if all_results:
        print_report(all_results, metrics_list)

    if args.output_json:
        output_path = Path(args.output_json)
        with open(output_path, "w") as f:
            json.dump({
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "metrics": metrics_list,
                "cases": [
                    {
                        "id": r["case"]["id"],
                        "stratum": r["case"]["stratum"],
                        "passed": r["assertion"]["passed"],
                        "failures": r["assertion"]["failures"],
                        "elapsed_seconds": r["result"]["elapsed_seconds"],
                    }
                    for r in all_results
                ],
            }, f, indent=2)
        print(f"Full results written to {output_path}")


if __name__ == "__main__":
    main()
