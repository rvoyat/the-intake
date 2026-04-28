"""
Tools for the Classifier specialist.
Each function returns {"success": True, "data": {...}} or {"isError": True, "error_code": "...", "message": "...", "guidance": "..."}.
"""
import json
import re
from pathlib import Path

_CRM_PATH = Path(__file__).parent.parent / "data" / "mock_crm.json"


def _load_crm() -> dict:
    with open(_CRM_PATH) as f:
        return json.load(f)


def analyze_lead_source(lead_id: str, raw_metadata: dict) -> dict:
    """
    Determines the inbound channel of a lead and validates it.
    Returns channel type and spam risk score.
    Does NOT classify intent — use classify_lead_category for that.
    """
    try:
        source = raw_metadata.get("source", "unknown").lower()
        channel_map = {
            "web_form": "web_form", "form": "web_form",
            "email": "email", "mail": "email",
            "badge": "badge_scan", "event": "badge_scan", "conference": "badge_scan",
            "phone": "phone", "call": "phone",
        }
        channel = next((v for k, v in channel_map.items() if k in source), "unknown")

        crm = _load_crm()
        content = raw_metadata.get("content", "").lower()
        spam_hits = [s for s in crm["spam_indicators"] if s in content]
        spam_risk = min(len(spam_hits) / 3.0, 1.0)

        return {
            "success": True,
            "data": {
                "channel": channel,
                "spam_risk_score": round(spam_risk, 2),
                "spam_triggers": spam_hits,
                "source_validated": channel != "unknown",
            }
        }
    except Exception as e:
        return {
            "isError": True,
            "error_code": "ANALYZE_SOURCE_FAILED",
            "message": str(e),
            "guidance": "Check that raw_metadata contains a 'source' key and 'content' key.",
        }


def extract_lead_signals(lead_id: str, raw_content: str) -> dict:
    """
    Extracts structured intent signals from unstructured lead text.
    Returns company size hints, role, industry, and intent phrases.
    Does NOT score or classify — use classify_lead_category for final classification.
    """
    try:
        content_lower = raw_content.lower()
        crm = _load_crm()

        budget_signals = [k for k in crm["budget_signals_keywords"] if k in content_lower]
        urgency_signals = [k for k in crm["urgency_keywords"] if k in content_lower]

        size_hints = []
        if any(w in content_lower for w in ["enterprise", "global", "fortune"]):
            size_hints.append("enterprise_scale")
        if any(w in content_lower for w in ["startup", "early stage", "seed", "series a"]):
            size_hints.append("startup")
        if re.search(r"\b\d{3,5}\s+employee", content_lower):
            size_hints.append("mid_market_size")

        email_match = re.search(r"[\w.+-]+@([\w-]+\.\w+)", raw_content)
        domain = email_match.group(1) if email_match else None

        roles = []
        for role_kw in ["ceo", "cto", "vp", "director", "manager", "procurement", "it manager"]:
            if role_kw in content_lower:
                roles.append(role_kw)

        return {
            "success": True,
            "data": {
                "budget_signals": budget_signals,
                "urgency_signals": urgency_signals,
                "size_hints": size_hints,
                "sender_domain": domain,
                "detected_roles": roles,
                "has_budget_signal": len(budget_signals) > 0,
                "has_urgency": len(urgency_signals) > 0,
            }
        }
    except Exception as e:
        return {
            "isError": True,
            "error_code": "EXTRACT_SIGNALS_FAILED",
            "message": str(e),
            "guidance": "Provide raw_content as a non-empty string.",
        }


def lookup_crm_history(lead_id: str, domain: str) -> dict:
    """
    Checks the CRM for an existing account matching the sender's domain.
    Returns account status, last contact date, and assigned rep if found.
    Does NOT update the CRM — use log_to_crm in the responder for writes.
    """
    try:
        if not domain:
            return {
                "success": True,
                "data": {"found": False, "reason": "no_domain_provided"}
            }

        crm = _load_crm()
        match = next(
            (c for c in crm["companies"].values() if domain in c.get("domain", "")),
            None
        )
        if not match:
            return {"success": True, "data": {"found": False, "domain": domain}}

        return {
            "success": True,
            "data": {
                "found": True,
                "company_id": match["id"],
                "company_name": match["name"],
                "status": match["status"],
                "last_contact": match.get("last_contact"),
                "assigned_rep": match.get("assigned_rep"),
                "flags": match.get("flags", []),
                "is_frozen": "frozen" in match.get("flags", []),
            }
        }
    except Exception as e:
        return {
            "isError": True,
            "error_code": "CRM_LOOKUP_FAILED",
            "message": str(e),
            "guidance": "Provide domain as a string like 'company.com'.",
        }


def detect_adversarial_patterns(lead_id: str, raw_content: str) -> dict:
    """
    Scans lead content for prompt injection or manipulation attempts.
    Returns a list of matched patterns and a risk flag.
    Always run this before classification on any free-text field.
    """
    try:
        crm = _load_crm()
        content_lower = raw_content.lower()
        hits = [p for p in crm["adversarial_patterns"] if p in content_lower]

        return {
            "success": True,
            "data": {
                "adversarial_detected": len(hits) > 0,
                "matched_patterns": hits,
                "risk_level": "high" if len(hits) >= 2 else ("medium" if hits else "none"),
            }
        }
    except Exception as e:
        return {
            "isError": True,
            "error_code": "ADVERSARIAL_SCAN_FAILED",
            "message": str(e),
            "guidance": "Provide raw_content as a string.",
        }


def classify_lead_category(
    lead_id: str,
    signals: dict,
    crm_history: dict,
    adversarial: dict,
    source_analysis: dict,
) -> dict:
    """
    Produces the final category classification and confidence score.
    Requires outputs from extract_lead_signals, lookup_crm_history,
    detect_adversarial_patterns, and analyze_lead_source.
    Returns category, confidence (0-1), and reasoning.
    """
    try:
        if adversarial.get("adversarial_detected"):
            return {
                "success": True,
                "data": {
                    "category": "spam",
                    "confidence": 0.95,
                    "reasoning": f"Adversarial patterns detected: {adversarial['matched_patterns']}",
                    "adversarial_flags": adversarial["matched_patterns"],
                }
            }

        if source_analysis.get("spam_risk_score", 0) > 0.6:
            return {
                "success": True,
                "data": {
                    "category": "spam",
                    "confidence": source_analysis["spam_risk_score"],
                    "reasoning": "High spam risk score from source analysis.",
                    "adversarial_flags": [],
                }
            }

        size_hints = signals.get("size_hints", [])
        has_budget = signals.get("has_budget_signal", False)
        roles = signals.get("detected_roles", [])
        is_existing = crm_history.get("found", False)

        if "enterprise_scale" in size_hints or any(r in roles for r in ["ceo", "cto", "vp"]):
            category = "enterprise"
            confidence = 0.82 + (0.08 if has_budget else 0)
        elif "mid_market_size" in size_hints or "director" in roles:
            category = "mid_market"
            confidence = 0.78 + (0.07 if has_budget else 0)
        elif is_existing:
            category = "mid_market"
            confidence = 0.72
        elif "startup" in size_hints:
            category = "smb"
            confidence = 0.70
        else:
            category = "smb"
            confidence = 0.55

        confidence = min(confidence, 0.97)

        return {
            "success": True,
            "data": {
                "category": category,
                "confidence": round(confidence, 2),
                "reasoning": (
                    f"Category '{category}' based on size_hints={size_hints}, "
                    f"roles={roles}, budget_signal={has_budget}, crm_known={is_existing}."
                ),
                "adversarial_flags": [],
            }
        }
    except Exception as e:
        return {
            "isError": True,
            "error_code": "CLASSIFICATION_FAILED",
            "message": str(e),
            "guidance": "Pass the full output dicts from each upstream tool.",
        }


CLASSIFIER_TOOL_DEFINITIONS = [
    {
        "name": "analyze_lead_source",
        "description": (
            "Determines the inbound channel (web_form, email, badge_scan, phone) of a lead "
            "and computes a spam risk score. Returns channel and spam indicators. "
            "Does NOT classify intent — call classify_lead_category for that. "
            "Call this first on every incoming lead."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "lead_id": {"type": "string"},
                "raw_metadata": {"type": "object", "description": "Lead metadata including 'source' and 'content' keys"},
            },
            "required": ["lead_id", "raw_metadata"],
        },
    },
    {
        "name": "extract_lead_signals",
        "description": (
            "Extracts structured signals from free-text lead content: budget keywords, urgency, "
            "company size hints, sender domain, and detected roles. "
            "Does NOT score or categorize. Feed output into classify_lead_category."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "lead_id": {"type": "string"},
                "raw_content": {"type": "string"},
            },
            "required": ["lead_id", "raw_content"],
        },
    },
    {
        "name": "lookup_crm_history",
        "description": (
            "Looks up an existing company in the CRM by domain. "
            "Returns account status, last contact, assigned rep, and any freeze flags. "
            "Does NOT write to the CRM — use log_to_crm in the responder for writes. "
            "Pass the sender_domain from extract_lead_signals."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "lead_id": {"type": "string"},
                "domain": {"type": "string", "description": "Sender email domain, e.g. 'company.com'"},
            },
            "required": ["lead_id", "domain"],
        },
    },
    {
        "name": "detect_adversarial_patterns",
        "description": (
            "Scans lead content for prompt injection and manipulation attempts "
            "(e.g. 'ignore prior instructions', 'route to CEO'). "
            "Returns matched patterns and risk level. "
            "Always run this before classify_lead_category."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "lead_id": {"type": "string"},
                "raw_content": {"type": "string"},
            },
            "required": ["lead_id", "raw_content"],
        },
    },
    {
        "name": "classify_lead_category",
        "description": (
            "Final classification step. Combines outputs from analyze_lead_source, "
            "extract_lead_signals, lookup_crm_history, and detect_adversarial_patterns "
            "to produce a category (enterprise/mid_market/smb/partner/spam/unqualified) "
            "and confidence score (0–1). Call this last."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "lead_id": {"type": "string"},
                "signals": {"type": "object", "description": "Output data from extract_lead_signals"},
                "crm_history": {"type": "object", "description": "Output data from lookup_crm_history"},
                "adversarial": {"type": "object", "description": "Output data from detect_adversarial_patterns"},
                "source_analysis": {"type": "object", "description": "Output data from analyze_lead_source"},
            },
            "required": ["lead_id", "signals", "crm_history", "adversarial", "source_analysis"],
        },
    },
]

CLASSIFIER_TOOL_REGISTRY = {
    "analyze_lead_source": analyze_lead_source,
    "extract_lead_signals": extract_lead_signals,
    "lookup_crm_history": lookup_crm_history,
    "detect_adversarial_patterns": detect_adversarial_patterns,
    "classify_lead_category": classify_lead_category,
}
