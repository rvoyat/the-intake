"""
PreToolUse hook — hard stop on high-risk write operations.
This is deterministic (no LLM involved): pattern-based blocking before tool execution.
Complements the coordinator's escalation logic (slow stop) with a hard stop.
"""
import json
import re
from pathlib import Path

from config import config

_CRM_PATH = Path(__file__).parent.parent / "data" / "mock_crm.json"

PII_PATTERNS = [
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),               # SSN
    re.compile(r"\b4[0-9]{12}(?:[0-9]{3})?\b"),          # Visa card
    re.compile(r"\b(?:password|passwd|secret)[=:]\s*\S+", re.IGNORECASE),
]

BLOCKED_ROUTE_SUBSTRINGS = [
    "ceo", "board", "legal_direct", "route_to_ceo",
    "route_to_board", "override_routing",
]


def _contains_pii(data: dict) -> list[str]:
    text = json.dumps(data)
    return [p.pattern for p in PII_PATTERNS if p.search(text)]


def _is_frozen_account(domain: str) -> bool:
    try:
        with open(_CRM_PATH) as f:
            crm = json.load(f)
        for company in crm["companies"].values():
            if domain and domain in company.get("domain", ""):
                return "frozen" in company.get("flags", [])
        return False
    except Exception:
        return False


def _is_blocked_route(rep_id: str, routing_metadata: dict) -> bool:
    combined = json.dumps({"rep_id": rep_id, **routing_metadata}).lower()
    return any(sub in combined for sub in BLOCKED_ROUTE_SUBSTRINGS)


def pre_tool_use_hook(tool_name: str, tool_input: dict) -> dict:
    """
    Called before every tool execution.
    Returns {"allowed": True} or {"allowed": False, "reason": "...", "block_code": "..."}.
    Only enforces hard blocks on HIGH_RISK_TOOLS; passes all others through immediately.
    """
    if tool_name not in config.HIGH_RISK_TOOLS:
        return {"allowed": True}

    if tool_name == "log_to_crm":
        domain = tool_input.get("company_domain", "")
        action = tool_input.get("action", "")
        rep_id = tool_input.get("assigned_rep_id", "")
        metadata = tool_input.get("routing_metadata", {})

        if action == "disqualify":
            return {
                "allowed": False,
                "reason": "CRM write blocked: disqualified leads must not be logged.",
                "block_code": "DISQUALIFY_WRITE_BLOCKED",
            }

        if _is_frozen_account(domain):
            return {
                "allowed": False,
                "reason": f"CRM write blocked: account '{domain}' is frozen or under legal review.",
                "block_code": "FROZEN_ACCOUNT",
            }

        pii_hits = _contains_pii(tool_input)
        if pii_hits:
            return {
                "allowed": False,
                "reason": f"CRM write blocked: PII patterns detected in payload: {pii_hits}",
                "block_code": "PII_EXFILTRATION_RISK",
            }

        if _is_blocked_route(rep_id, metadata):
            return {
                "allowed": False,
                "reason": "CRM write blocked: routing target matches known-bad route pattern.",
                "block_code": "BLOCKED_ROUTE",
            }

    if tool_name == "send_rep_notification":
        action = tool_input.get("action", "")
        rep_id = tool_input.get("rep_id", "")

        if action == "disqualify":
            return {
                "allowed": False,
                "reason": "Notification blocked: cannot notify rep for disqualified lead.",
                "block_code": "DISQUALIFY_NOTIFY_BLOCKED",
            }

        if not rep_id or rep_id in config.BLOCKED_ROUTES:
            return {
                "allowed": False,
                "reason": f"Notification blocked: rep_id '{rep_id}' is unknown or blocked.",
                "block_code": "UNKNOWN_REP",
            }

    return {"allowed": True}
