"""
Prioritizer specialist agent.
Input: lead context + classification result (explicit, not inherited).
Output: PriorityResult.
"""
import json
import logging
import re

from models.schemas import PriorityResult, Tier, ImpactLevel
from tools.prioritizer_tools import PRIORITIZER_TOOL_DEFINITIONS, PRIORITIZER_TOOL_REGISTRY
from .base import run_agent_loop

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Prioritizer specialist in a sales lead routing system.

Your job: given a classified lead, assess its business value, assign a tier, and select the best rep.

Tiers: T1_enterprise, T2_mid_market, T3_smb, disqualify.
Impact levels: high (score ≥ 70), medium (score 40–69), low (score < 40).

You have 5 tools. Use them in this order:
1. assess_firmographics — estimate company size, industry, revenue band
2. evaluate_budget_signals — assess budget strength and urgency (use budget_signals from classification context)
3. check_rep_availability — find available reps matching the expected tier and industry
4. calculate_lead_score — compute composite score (0–100)
5. assign_tier_and_rep — finalize tier, impact, and rep assignment

Rules:
- Never assign a rep for disqualified leads (spam, competitor, unqualified)
- Pass .data contents between tools, not wrapper objects
- If no reps are available, still complete the scoring and flag no_rep_available

Final output must be a JSON block:
```json
{
  "tier": "<tier>",
  "impact": "<high|medium|low>",
  "lead_score": <float>,
  "estimated_deal_size": "<string>",
  "urgency_signals": ["<signal>", ...],
  "assigned_rep_id": "<id or null>",
  "reasoning": "<one paragraph>"
}
```
"""


def run_prioritizer(lead_context: dict, classification: dict) -> PriorityResult:
    """
    Runs the prioritizer specialist. Context is passed explicitly.
    classification is the .dict() output of ClassificationResult.
    """
    task_message = f"""Prioritize this sales lead and assign a rep.

Lead context (passed explicitly):
```json
{json.dumps(lead_context, indent=2)}
```

Classification result (from Classifier specialist):
```json
{json.dumps(classification, indent=2)}
```

Use your tools in order and produce your final priority JSON block."""

    agent_output = run_agent_loop(
        system_prompt=SYSTEM_PROMPT,
        tool_definitions=PRIORITIZER_TOOL_DEFINITIONS,
        tool_registry=PRIORITIZER_TOOL_REGISTRY,
        task_message=task_message,
    )

    result_text = agent_output.get("result", "")
    parsed = _extract_json_block(result_text)

    if not parsed:
        logger.warning("prioritizer_parse_failed", extra={"lead_id": lead_context.get("lead_id")})
        return PriorityResult(
            lead_id=lead_context["lead_id"],
            tier=Tier.DISQUALIFY,
            impact=ImpactLevel.LOW,
            lead_score=0.0,
            reasoning="Prioritizer agent did not return a parseable result.",
        )

    return PriorityResult(
        lead_id=lead_context["lead_id"],
        tier=Tier(parsed.get("tier", "disqualify")),
        impact=ImpactLevel(parsed.get("impact", "low")),
        lead_score=float(parsed.get("lead_score", 0.0)),
        estimated_deal_size=parsed.get("estimated_deal_size"),
        urgency_signals=parsed.get("urgency_signals", []),
        assigned_rep_id=parsed.get("assigned_rep_id"),
        reasoning=parsed.get("reasoning", ""),
    )


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
