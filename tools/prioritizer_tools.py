"""
Tools for the Prioritizer specialist.
"""
import json
from pathlib import Path

_CRM_PATH = Path(__file__).parent.parent / "data" / "mock_crm.json"


def _load_crm() -> dict:
    with open(_CRM_PATH) as f:
        return json.load(f)


def assess_firmographics(lead_id: str, domain: str, raw_content: str) -> dict:
    """
    Estimates company size, industry, and revenue band from domain lookup and text.
    Returns firmographic profile for scoring. Does NOT assign a tier — use assign_tier for that.
    """
    try:
        crm = _load_crm()
        content_lower = raw_content.lower()

        company = next(
            (c for c in crm["companies"].values() if domain and domain in c.get("domain", "")),
            None
        )

        if company:
            employees = company.get("employees", 0)
            industry = company.get("industry", "unknown")
        else:
            if any(w in content_lower for w in ["enterprise", "global", "10,000", "5,000"]):
                employees = 5000
            elif any(w in content_lower for w in ["mid-size", "500", "1,000"]):
                employees = 500
            elif any(w in content_lower for w in ["startup", "small", "team of"]):
                employees = 25
            else:
                employees = 100

            industry_map = {
                "fintech": "fintech", "bank": "banking", "insurance": "insurance",
                "pharma": "pharma", "biotech": "biotech",
                "saas": "saas", "software": "technology",
                "manufacturing": "manufacturing", "logistics": "logistics",
                "retail": "retail", "ecommerce": "retail",
            }
            industry = next((v for k, v in industry_map.items() if k in content_lower), "other")

        if employees >= 1000:
            revenue_band = "$50M+"
        elif employees >= 200:
            revenue_band = "$10M–$50M"
        elif employees >= 50:
            revenue_band = "$1M–$10M"
        else:
            revenue_band = "<$1M"

        return {
            "success": True,
            "data": {
                "estimated_employees": employees,
                "industry": industry,
                "revenue_band": revenue_band,
                "crm_known": company is not None,
            }
        }
    except Exception as e:
        return {
            "isError": True,
            "error_code": "FIRMOGRAPHICS_FAILED",
            "message": str(e),
            "guidance": "Provide domain (string) and raw_content (string).",
        }


def evaluate_budget_signals(lead_id: str, raw_content: str, budget_signals: list) -> dict:
    """
    Evaluates strength of budget and timeline signals.
    Returns deal size estimate and urgency score (0–1).
    Requires budget_signals list from extract_lead_signals (classifier output).
    """
    try:
        content_lower = raw_content.lower()
        import re

        value_patterns = [
            (r"\$(\d+)k", lambda m: int(m.group(1)) * 1000),
            (r"\$(\d+),000", lambda m: int(m.group(1)) * 1000),
            (r"\$(\d+)m", lambda m: int(m.group(1)) * 1_000_000),
            (r"(\d+)\s*million", lambda m: int(m.group(1)) * 1_000_000),
        ]

        estimated_value = None
        for pattern, extractor in value_patterns:
            match = re.search(pattern, content_lower)
            if match:
                estimated_value = extractor(match)
                break

        urgency_score = min(len([
            s for s in ["urgent", "asap", "q2", "deadline", "critical", "before june"]
            if s in content_lower
        ]) / 3.0, 1.0)

        budget_strength = min(len(budget_signals) / 3.0, 1.0)

        if estimated_value:
            deal_size = f"${estimated_value:,}"
        elif budget_strength > 0.6:
            deal_size = "estimated >$50k"
        elif budget_strength > 0.3:
            deal_size = "estimated $10k–$50k"
        else:
            deal_size = "unknown"

        return {
            "success": True,
            "data": {
                "budget_strength": round(budget_strength, 2),
                "urgency_score": round(urgency_score, 2),
                "estimated_deal_size": deal_size,
                "explicit_value_found": estimated_value is not None,
            }
        }
    except Exception as e:
        return {
            "isError": True,
            "error_code": "BUDGET_EVAL_FAILED",
            "message": str(e),
            "guidance": "Pass raw_content as string and budget_signals as list from classifier.",
        }


def check_rep_availability(lead_id: str, tier: str, industry: str) -> dict:
    """
    Finds available sales reps matching the required tier and industry.
    Returns a ranked list of available reps. Does NOT assign — use assign_tier for final assignment.
    Tier must be one of: T1_enterprise, T2_mid_market, T3_smb, disqualify.
    """
    try:
        crm = _load_crm()
        candidates = []
        for rep in crm["reps"].values():
            if not rep["available"]:
                continue
            if tier not in rep.get("tier_specialty", []):
                continue
            load_ratio = rep["current_load"] / rep["max_load"]
            industry_match = industry in rep.get("industries", [])
            score = (1 - load_ratio) * 0.4 + rep["quota_attainment"] * 0.4 + (0.2 if industry_match else 0)
            candidates.append({
                "rep_id": rep["id"],
                "name": rep["name"],
                "load_ratio": round(load_ratio, 2),
                "industry_match": industry_match,
                "score": round(score, 3),
            })

        candidates.sort(key=lambda x: x["score"], reverse=True)

        return {
            "success": True,
            "data": {
                "available_reps": candidates[:3],
                "total_candidates": len(candidates),
                "no_reps_available": len(candidates) == 0,
            }
        }
    except Exception as e:
        return {
            "isError": True,
            "error_code": "REP_CHECK_FAILED",
            "message": str(e),
            "guidance": "tier must be one of T1_enterprise, T2_mid_market, T3_smb. industry is a lowercase string.",
        }


def calculate_lead_score(
    lead_id: str,
    firmographics: dict,
    budget_eval: dict,
    classification_confidence: float,
) -> dict:
    """
    Computes a composite lead score (0–100) from firmographic, budget, and classification signals.
    Does NOT determine tier — use assign_tier after this.
    """
    try:
        employees = firmographics.get("estimated_employees", 0)
        revenue_band = firmographics.get("revenue_band", "<$1M")

        size_score = min(employees / 5000 * 40, 40)

        budget_score = budget_eval.get("budget_strength", 0) * 30

        confidence_score = classification_confidence * 20

        urgency_bonus = budget_eval.get("urgency_score", 0) * 10

        total = size_score + budget_score + confidence_score + urgency_bonus

        return {
            "success": True,
            "data": {
                "lead_score": round(min(total, 100), 1),
                "breakdown": {
                    "size_score": round(size_score, 1),
                    "budget_score": round(budget_score, 1),
                    "confidence_score": round(confidence_score, 1),
                    "urgency_bonus": round(urgency_bonus, 1),
                }
            }
        }
    except Exception as e:
        return {
            "isError": True,
            "error_code": "SCORING_FAILED",
            "message": str(e),
            "guidance": "Pass firmographics and budget_eval as output dicts from their tools.",
        }


def assign_tier_and_rep(
    lead_id: str,
    lead_score: float,
    category: str,
    available_reps: list,
) -> dict:
    """
    Maps category + lead_score to a tier and selects the best available rep.
    Returns tier, impact level, and assigned rep. This is the final prioritization decision.
    category must be one of: enterprise, mid_market, smb, partner, spam, unqualified.
    """
    try:
        tier_map = {
            "enterprise": "T1_enterprise",
            "mid_market": "T2_mid_market",
            "smb": "T3_smb",
            "partner": "T2_mid_market",
            "spam": "disqualify",
            "competitor": "disqualify",
            "unqualified": "disqualify",
        }
        tier = tier_map.get(category, "disqualify")

        if lead_score >= 70:
            impact = "high"
        elif lead_score >= 40:
            impact = "medium"
        else:
            impact = "low"

        assigned_rep = available_reps[0] if available_reps else None

        return {
            "success": True,
            "data": {
                "tier": tier,
                "impact": impact,
                "assigned_rep_id": assigned_rep["rep_id"] if assigned_rep else None,
                "assigned_rep_name": assigned_rep["name"] if assigned_rep else None,
                "no_rep_available": assigned_rep is None and tier != "disqualify",
            }
        }
    except Exception as e:
        return {
            "isError": True,
            "error_code": "TIER_ASSIGNMENT_FAILED",
            "message": str(e),
            "guidance": "Pass lead_score (float), category (string), available_reps (list from check_rep_availability).",
        }


PRIORITIZER_TOOL_DEFINITIONS = [
    {
        "name": "assess_firmographics",
        "description": (
            "Estimates company size, industry, and revenue band. "
            "Uses CRM lookup if domain is known, otherwise infers from content. "
            "Does NOT assign a tier — use assign_tier_and_rep for that. Call first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "lead_id": {"type": "string"},
                "domain": {"type": "string"},
                "raw_content": {"type": "string"},
            },
            "required": ["lead_id", "domain", "raw_content"],
        },
    },
    {
        "name": "evaluate_budget_signals",
        "description": (
            "Evaluates budget and urgency signals. Returns deal size estimate and urgency score (0–1). "
            "Requires budget_signals list from classify output. "
            "Does NOT score the lead holistically — use calculate_lead_score for that."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "lead_id": {"type": "string"},
                "raw_content": {"type": "string"},
                "budget_signals": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["lead_id", "raw_content", "budget_signals"],
        },
    },
    {
        "name": "check_rep_availability",
        "description": (
            "Finds available reps matching tier and industry. Returns ranked candidates. "
            "tier must be T1_enterprise, T2_mid_market, or T3_smb. "
            "Does NOT assign — use assign_tier_and_rep for final assignment."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "lead_id": {"type": "string"},
                "tier": {"type": "string"},
                "industry": {"type": "string"},
            },
            "required": ["lead_id", "tier", "industry"],
        },
    },
    {
        "name": "calculate_lead_score",
        "description": (
            "Computes composite lead score (0–100) from firmographics, budget signals, "
            "and classification confidence. Does NOT determine tier. "
            "Call after assess_firmographics and evaluate_budget_signals."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "lead_id": {"type": "string"},
                "firmographics": {"type": "object"},
                "budget_eval": {"type": "object"},
                "classification_confidence": {"type": "number"},
            },
            "required": ["lead_id", "firmographics", "budget_eval", "classification_confidence"],
        },
    },
    {
        "name": "assign_tier_and_rep",
        "description": (
            "Final prioritization step. Maps category + score to tier (T1/T2/T3/disqualify) "
            "and selects the best available rep. Returns tier, impact level, and assigned rep. "
            "Call last, after check_rep_availability and calculate_lead_score."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "lead_id": {"type": "string"},
                "lead_score": {"type": "number"},
                "category": {"type": "string"},
                "available_reps": {"type": "array"},
            },
            "required": ["lead_id", "lead_score", "category", "available_reps"],
        },
    },
]

PRIORITIZER_TOOL_REGISTRY = {
    "assess_firmographics": assess_firmographics,
    "evaluate_budget_signals": evaluate_budget_signals,
    "check_rep_availability": check_rep_availability,
    "calculate_lead_score": calculate_lead_score,
    "assign_tier_and_rep": assign_tier_and_rep,
}
