"""
Tools for the Responder specialist.
log_to_crm and send_rep_notification are HIGH RISK write operations guarded by PreToolUse hook.
"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

_CRM_PATH = Path(__file__).parent.parent / "data" / "mock_crm.json"


def _load_crm() -> dict:
    with open(_CRM_PATH) as f:
        return json.load(f)


def lookup_rep_profile(lead_id: str, rep_id: str) -> dict:
    """
    Retrieves full profile for a sales rep by ID.
    Returns name, email, specializations, and current load.
    Does NOT check availability — use check_rep_availability in the prioritizer for that.
    """
    try:
        crm = _load_crm()
        rep = crm["reps"].get(rep_id)
        if not rep:
            return {
                "isError": True,
                "error_code": "REP_NOT_FOUND",
                "message": f"No rep found with id '{rep_id}'",
                "guidance": "Use check_rep_availability to get valid rep IDs first.",
            }
        return {
            "success": True,
            "data": {
                "rep_id": rep["id"],
                "name": rep["name"],
                "email": rep["email"],
                "tier_specialty": rep["tier_specialty"],
                "industries": rep["industries"],
                "current_load": rep["current_load"],
                "available": rep["available"],
            }
        }
    except Exception as e:
        return {
            "isError": True,
            "error_code": "REP_LOOKUP_FAILED",
            "message": str(e),
            "guidance": "Provide rep_id as a string.",
        }


def generate_routing_decision(
    lead_id: str,
    tier: str,
    category: str,
    confidence: float,
    impact: str,
    lead_score: float,
    rep_id: str,
    rep_name: str,
    escalation_needed: bool,
    escalation_reason: str,
) -> dict:
    """
    Assembles the final structured routing decision.
    Returns action (route/escalate/disqualify/request_more_info) with full metadata.
    This is a read/assembly operation — it does NOT write to the CRM.
    """
    try:
        if escalation_needed:
            action = "escalate"
        elif tier == "disqualify":
            action = "disqualify"
        elif confidence < 0.50:
            action = "request_more_info"
        else:
            action = "route"

        return {
            "success": True,
            "data": {
                "action": action,
                "tier": tier,
                "category": category,
                "confidence": confidence,
                "impact": impact,
                "lead_score": lead_score,
                "assigned_rep_id": rep_id if action == "route" else None,
                "assigned_rep_name": rep_name if action == "route" else None,
                "escalation_needed": escalation_needed,
                "escalation_reason": escalation_reason,
                "decision_timestamp": datetime.now(timezone.utc).isoformat(),
            }
        }
    except Exception as e:
        return {
            "isError": True,
            "error_code": "ROUTING_DECISION_FAILED",
            "message": str(e),
            "guidance": "All required fields must be non-null.",
        }


def draft_acknowledgment_email(
    lead_id: str,
    action: str,
    rep_name: str,
    tier: str,
    sender_name: str,
) -> dict:
    """
    Drafts an automated acknowledgment email for the lead sender.
    Returns subject and body text. Does NOT send — only drafts.
    action must be one of: route, escalate, disqualify, request_more_info.
    """
    try:
        templates = {
            "route": (
                f"Thanks for reaching out, {sender_name or 'there'}.",
                f"Your inquiry has been reviewed and assigned to {rep_name}, "
                "who will be in touch within one business day."
            ),
            "escalate": (
                f"Thanks for reaching out, {sender_name or 'there'}.",
                "Your inquiry requires additional review by our team. "
                "A senior representative will follow up within 4 business hours."
            ),
            "disqualify": (
                f"Thank you for your message.",
                "We've reviewed your inquiry and don't believe we're the right fit at this time."
            ),
            "request_more_info": (
                f"Thanks for your interest.",
                "To ensure we connect you with the right team, could you share "
                "a bit more about your company and specific needs?"
            ),
        }

        subject_prefix, body = templates.get(action, templates["request_more_info"])

        return {
            "success": True,
            "data": {
                "subject": f"Re: Your inquiry — {subject_prefix}",
                "body": body,
                "send_immediately": action in ("route", "request_more_info"),
            }
        }
    except Exception as e:
        return {
            "isError": True,
            "error_code": "DRAFT_FAILED",
            "message": str(e),
            "guidance": "action must be route, escalate, disqualify, or request_more_info.",
        }


def log_to_crm(
    lead_id: str,
    company_domain: str,
    action: str,
    assigned_rep_id: str,
    tier: str,
    lead_score: float,
    routing_metadata: dict,
) -> dict:
    """
    HIGH RISK WRITE. Records the routing decision in the CRM.
    Blocked by PreToolUse hook for frozen accounts, known-bad routes, and PII exfil patterns.
    Do NOT call on disqualified leads. Do NOT call if company is flagged as frozen.
    Returns crm_record_id on success.
    """
    try:
        record = {
            "record_id": f"crm-{uuid.uuid4().hex[:8]}",
            "lead_id": lead_id,
            "company_domain": company_domain,
            "action": action,
            "assigned_rep_id": assigned_rep_id,
            "tier": tier,
            "lead_score": lead_score,
            "logged_at": datetime.now(timezone.utc).isoformat(),
            "metadata": routing_metadata,
            "definition_version": "1.0.0",
        }
        return {
            "success": True,
            "data": {
                "crm_record_id": record["record_id"],
                "logged_at": record["logged_at"],
                "message": f"Lead {lead_id} logged to CRM as '{action}'.",
            }
        }
    except Exception as e:
        return {
            "isError": True,
            "error_code": "CRM_WRITE_FAILED",
            "message": str(e),
            "guidance": "Verify all required fields are present and non-null.",
        }


def send_rep_notification(
    lead_id: str,
    rep_id: str,
    rep_email: str,
    tier: str,
    lead_summary: str,
    action: str,
) -> dict:
    """
    HIGH RISK WRITE. Sends a routing notification to the assigned rep.
    Blocked by PreToolUse hook if rep_id is unknown or action is disqualify.
    Only call after log_to_crm succeeds.
    Returns notification_id on success.
    """
    try:
        if action == "disqualify":
            return {
                "isError": True,
                "error_code": "INVALID_ACTION",
                "message": "Cannot notify a rep for a disqualified lead.",
                "guidance": "Only call send_rep_notification for route or escalate actions.",
            }

        notification_id = f"notif-{uuid.uuid4().hex[:8]}"
        return {
            "success": True,
            "data": {
                "notification_id": notification_id,
                "sent_to": rep_email,
                "subject": f"[{tier}] New lead assigned: {lead_id}",
                "summary": lead_summary,
                "sent_at": datetime.now(timezone.utc).isoformat(),
            }
        }
    except Exception as e:
        return {
            "isError": True,
            "error_code": "NOTIFICATION_FAILED",
            "message": str(e),
            "guidance": "Ensure rep_email is valid and action is route or escalate.",
        }


RESPONDER_TOOL_DEFINITIONS = [
    {
        "name": "lookup_rep_profile",
        "description": (
            "Retrieves full profile for a sales rep by ID: name, email, specializations, load. "
            "Does NOT check availability — use check_rep_availability (prioritizer) first. "
            "Call before drafting acknowledgment or logging."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "lead_id": {"type": "string"},
                "rep_id": {"type": "string"},
            },
            "required": ["lead_id", "rep_id"],
        },
    },
    {
        "name": "generate_routing_decision",
        "description": (
            "Assembles the final structured routing decision (route/escalate/disqualify/request_more_info). "
            "Read-only assembly — does NOT write to CRM. "
            "Call after all classifier and prioritizer outputs are available."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "lead_id": {"type": "string"},
                "tier": {"type": "string"},
                "category": {"type": "string"},
                "confidence": {"type": "number"},
                "impact": {"type": "string"},
                "lead_score": {"type": "number"},
                "rep_id": {"type": "string"},
                "rep_name": {"type": "string"},
                "escalation_needed": {"type": "boolean"},
                "escalation_reason": {"type": "string"},
            },
            "required": ["lead_id", "tier", "category", "confidence", "impact",
                         "lead_score", "rep_id", "rep_name", "escalation_needed", "escalation_reason"],
        },
    },
    {
        "name": "draft_acknowledgment_email",
        "description": (
            "Drafts an automated acknowledgment email for the lead sender. "
            "Returns subject and body only — does NOT send. "
            "action must be route, escalate, disqualify, or request_more_info."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "lead_id": {"type": "string"},
                "action": {"type": "string"},
                "rep_name": {"type": "string"},
                "tier": {"type": "string"},
                "sender_name": {"type": "string"},
            },
            "required": ["lead_id", "action", "rep_name", "tier", "sender_name"],
        },
    },
    {
        "name": "log_to_crm",
        "description": (
            "HIGH RISK WRITE. Records routing decision in the CRM. "
            "Blocked automatically for frozen accounts and known-bad routes. "
            "Do NOT call for disqualified leads. "
            "Call only after generate_routing_decision confirms action."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "lead_id": {"type": "string"},
                "company_domain": {"type": "string"},
                "action": {"type": "string"},
                "assigned_rep_id": {"type": "string"},
                "tier": {"type": "string"},
                "lead_score": {"type": "number"},
                "routing_metadata": {"type": "object"},
            },
            "required": ["lead_id", "company_domain", "action", "assigned_rep_id",
                         "tier", "lead_score", "routing_metadata"],
        },
    },
    {
        "name": "send_rep_notification",
        "description": (
            "HIGH RISK WRITE. Notifies assigned rep of new lead. "
            "Only call after log_to_crm succeeds. "
            "Blocked for disqualified leads and unknown rep IDs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "lead_id": {"type": "string"},
                "rep_id": {"type": "string"},
                "rep_email": {"type": "string"},
                "tier": {"type": "string"},
                "lead_summary": {"type": "string"},
                "action": {"type": "string"},
            },
            "required": ["lead_id", "rep_id", "rep_email", "tier", "lead_summary", "action"],
        },
    },
]

RESPONDER_TOOL_REGISTRY = {
    "lookup_rep_profile": lookup_rep_profile,
    "generate_routing_decision": generate_routing_decision,
    "draft_acknowledgment_email": draft_acknowledgment_email,
    "log_to_crm": log_to_crm,
    "send_rep_notification": send_rep_notification,
}
