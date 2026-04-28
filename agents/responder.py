"""
Responder specialist agent.
Input: lead + classification + priority (explicit context).
Output: RoutingDecision with acknowledgment draft.
"""
import json
import logging
import re

from models.schemas import RoutingDecision, Tier, LeadCategory, ImpactLevel, EscalationDecision, EscalationReason
from tools.responder_tools import RESPONDER_TOOL_DEFINITIONS, RESPONDER_TOOL_REGISTRY
from .base import run_agent_loop

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Responder specialist in a sales lead routing system.

Your job: assemble the final routing decision, draft the acknowledgment, and write to the CRM.

You have 5 tools. Use them in this order:
1. lookup_rep_profile — get rep details (only if a rep was assigned; skip for disqualify)
2. generate_routing_decision — assemble the structured routing decision
3. draft_acknowledgment_email — create the acknowledgment for the lead sender
4. log_to_crm — HIGH RISK WRITE — record the decision (skip for disqualified leads)
5. send_rep_notification — HIGH RISK WRITE — notify rep (only after log_to_crm succeeds)

Rules:
- Do NOT call log_to_crm or send_rep_notification for disqualified leads
- Do NOT call send_rep_notification before log_to_crm has succeeded
- If a HOOK_BLOCKED or FROZEN_ACCOUNT error is returned, stop writes and escalate
- If no rep was assigned, set escalation_needed = true with reason "no_rep_available"

Final output must be a JSON block:
```json
{
  "action": "<route|escalate|disqualify|request_more_info>",
  "assigned_rep_id": "<id or null>",
  "assigned_rep_name": "<name or null>",
  "acknowledgment_subject": "<subject>",
  "acknowledgment_body": "<body>",
  "crm_record_id": "<id or null>",
  "notification_id": "<id or null>",
  "reasoning": "<one paragraph>"
}
```
"""


def run_responder(lead_context: dict, classification: dict, priority: dict, escalation: dict) -> dict:
    """
    Runs the responder specialist. All context is passed explicitly.
    Returns a dict that the coordinator merges into RoutingDecision.
    """
    task_message = f"""Finalize the routing decision for this lead.

Lead context (passed explicitly):
```json
{json.dumps(lead_context, indent=2)}
```

Classification result:
```json
{json.dumps(classification, indent=2)}
```

Priority result:
```json
{json.dumps(priority, indent=2)}
```

Escalation decision:
```json
{json.dumps(escalation, indent=2)}
```

Use your tools in order and produce your final routing JSON block."""

    agent_output = run_agent_loop(
        system_prompt=SYSTEM_PROMPT,
        tool_definitions=RESPONDER_TOOL_DEFINITIONS,
        tool_registry=RESPONDER_TOOL_REGISTRY,
        task_message=task_message,
    )

    result_text = agent_output.get("result", "")
    parsed = _extract_json_block(result_text)

    if not parsed:
        logger.warning("responder_parse_failed", extra={"lead_id": lead_context.get("lead_id")})
        return {
            "action": "escalate",
            "assigned_rep_id": None,
            "assigned_rep_name": None,
            "acknowledgment_subject": "Your inquiry — follow-up required",
            "acknowledgment_body": "Your request requires manual review. A team member will follow up shortly.",
            "crm_record_id": None,
            "notification_id": None,
            "reasoning": "Responder agent failed to produce a parseable result; defaulting to escalation.",
        }

    return parsed


def _extract_json_block(text: str) -> dict | None:
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    try:
        start = text.rfind("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            return json.loads(text[start:end])
    except json.JSONDecodeError:
        pass
    return None
