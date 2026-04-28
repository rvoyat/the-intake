#!/usr/bin/env python3
"""
The Intake — Sales Lead Routing Agent
Entry point: processes a single lead from CLI or piped JSON.

Usage:
  python main.py --lead '{"lead_id": "...", "source": "web_form", ...}'
  echo '{"lead_id": "..."}' | python main.py --stdin
  python main.py --demo          # Run with a built-in demo lead
"""
import argparse
import json
import sys
from datetime import datetime, timezone

from logger import setup_logging
from models.schemas import LeadRequest, LeadSource
from agents.coordinator import run_coordinator


DEMO_LEAD = {
    "lead_id": "demo-001",
    "source": "web_form",
    "raw_content": (
        "Hi, I'm the VP of Procurement at Meridian Financial Group (2,000 employees). "
        "We're evaluating enterprise solutions for our Q2 2026 digital transformation initiative. "
        "Budget is approved ($150k range). Looking to start a pilot by June. "
        "Please connect me with your enterprise team."
    ),
    "metadata": {
        "source": "web_form",
        "content": "enterprise procurement vp budget approved q2",
        "form_id": "contact-enterprise",
        "ip_country": "US",
    },
    "timestamp": datetime.now(timezone.utc).isoformat(),
}


def main():
    setup_logging()

    parser = argparse.ArgumentParser(description="The Intake — Sales Lead Routing Agent")
    parser.add_argument("--lead", type=str, help="JSON string of the lead request")
    parser.add_argument("--stdin", action="store_true", help="Read lead JSON from stdin")
    parser.add_argument("--demo", action="store_true", help="Run with built-in demo lead")
    parser.add_argument("--output", choices=["json", "pretty"], default="pretty",
                        help="Output format")
    args = parser.parse_args()

    if args.demo:
        raw = DEMO_LEAD
    elif args.stdin:
        raw = json.load(sys.stdin)
    elif args.lead:
        raw = json.loads(args.lead)
    else:
        parser.print_help()
        sys.exit(1)

    if "timestamp" not in raw:
        raw["timestamp"] = datetime.now(timezone.utc).isoformat()
    if "source" not in raw:
        raw["source"] = "unknown"

    lead = LeadRequest(**raw)
    decision = run_coordinator(lead)

    if args.output == "json":
        print(json.dumps(decision.model_dump(), indent=2, default=str))
    else:
        _print_pretty(decision)


def _print_pretty(decision):
    sep = "─" * 60
    print(f"\n{sep}")
    print(f"  THE INTAKE — Routing Decision")
    print(f"{sep}")
    print(f"  Lead ID    : {decision.lead_id}")
    print(f"  Action     : {decision.action.upper()}")
    print(f"  Category   : {decision.category}")
    print(f"  Tier       : {decision.tier}")
    print(f"  Score      : {decision.lead_score:.1f}/100")
    print(f"  Confidence : {decision.confidence:.0%}")
    print(f"  Impact     : {decision.impact}")
    if decision.assigned_rep_name:
        print(f"  Assigned   : {decision.assigned_rep_name} ({decision.assigned_rep_id})")
    if decision.escalation.should_escalate:
        print(f"  Escalation : {decision.escalation.reason} — {decision.escalation.details}")
    if decision.retry_count:
        print(f"  Retries    : {decision.retry_count}")
    print(f"{sep}")
    print(f"  Reasoning Chain:")
    for step in decision.reasoning_chain:
        print(f"    {step}")
    if decision.acknowledgment_draft:
        print(f"{sep}")
        print(f"  Acknowledgment Draft:")
        for line in decision.acknowledgment_draft.split("\n"):
            print(f"    {line}")
    print(f"{sep}\n")


if __name__ == "__main__":
    main()
