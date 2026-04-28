"""
The Loop — human override signal → labeled examples store → eval set + few-shot examples.

When a human reviewer overrides an agent routing decision, that signal is captured here.
Two outputs:
  1. Appended to labeled_examples.json (feeds the eval golden set)
  2. Few-shot examples extracted for the coordinator's classifier prompt (improves classification)

This closes the loop: the agent gets better with every human correction.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_EXAMPLES_PATH = Path(__file__).parent / "labeled_examples.json"
_FEW_SHOT_PATH = Path(__file__).parent / "classifier_few_shot.json"

MAX_FEW_SHOT_EXAMPLES = 20


def _load_json(path: Path) -> list:
    if not path.exists():
        return []
    with open(path) as f:
        return json.load(f)


def _save_json(path: Path, data: list):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def capture_human_override(
    lead_id: str,
    lead_content: str,
    original_decision: dict,
    human_decision: dict,
    reviewer_id: str,
    notes: str = "",
) -> dict:
    """
    Called when a human reviewer overrides the agent's routing decision.

    original_decision: the agent's RoutingDecision.model_dump()
    human_decision: {"action": "route", "tier": "T1_enterprise", "assigned_rep_id": "rep-001", ...}
    reviewer_id: identifier of the human who made the override

    Returns the labeled example that was stored.
    """
    original_action = original_decision.get("action")
    human_action = human_decision.get("action")
    original_category = original_decision.get("category")
    human_category = human_decision.get("category", original_category)

    example = {
        "id": f"override-{lead_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        "source": "human_override",
        "lead_id": lead_id,
        "lead_content_snippet": lead_content[:300],
        "agent_decision": {
            "action": original_action,
            "category": original_category,
            "tier": original_decision.get("tier"),
            "confidence": original_decision.get("confidence"),
        },
        "human_decision": human_decision,
        "correction": {
            "action_changed": original_action != human_action,
            "category_changed": original_category != human_category,
            "tier_changed": original_decision.get("tier") != human_decision.get("tier"),
        },
        "reviewer_id": reviewer_id,
        "notes": notes,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    examples = _load_json(_EXAMPLES_PATH)
    examples.append(example)
    _save_json(_EXAMPLES_PATH, examples)

    _update_few_shot_examples(example)

    logger.info("override_captured", extra={
        "lead_id": lead_id,
        "original_action": original_action,
        "human_action": human_action,
        "category_corrected": example["correction"]["category_changed"],
        "reviewer_id": reviewer_id,
    })

    return example


def _update_few_shot_examples(override: dict):
    """
    When the agent misclassified a lead, extract it as a few-shot example
    for the classifier's system prompt. Category corrections are most valuable.
    """
    if not override["correction"].get("category_changed"):
        return

    few_shot = _load_json(_FEW_SHOT_PATH)

    new_example = {
        "content_snippet": override["lead_content_snippet"],
        "correct_category": override["human_decision"].get("category"),
        "incorrect_category": override["agent_decision"].get("category"),
        "lesson": (
            f"This lead looks like '{override['agent_decision']['category']}' "
            f"but is actually '{override['human_decision']['category']}'. "
            f"Notes from reviewer: {override['notes']}"
            if override["notes"]
            else (
                f"This lead is '{override['human_decision']['category']}', "
                f"not '{override['agent_decision']['category']}'."
            )
        ),
        "added_at": override["timestamp"],
    }

    few_shot.append(new_example)

    if len(few_shot) > MAX_FEW_SHOT_EXAMPLES:
        few_shot = few_shot[-MAX_FEW_SHOT_EXAMPLES:]

    _save_json(_FEW_SHOT_PATH, few_shot)


def get_few_shot_block() -> str:
    """
    Returns formatted few-shot examples for injection into the classifier system prompt.
    Call this when constructing the classifier's task message to include recent corrections.
    Returns empty string if no examples exist yet.
    """
    few_shot = _load_json(_FEW_SHOT_PATH)
    if not few_shot:
        return ""

    lines = ["\n\n## Recent corrections from human reviewers (learn from these)\n"]
    for i, ex in enumerate(few_shot[-5:], 1):
        lines.append(f"{i}. Lead: \"{ex['content_snippet']}\"")
        lines.append(f"   Lesson: {ex['lesson']}\n")

    return "\n".join(lines)


def export_to_eval_set(output_path: Path | None = None) -> list[dict]:
    """
    Converts labeled override examples into golden set format for run_evals.py.
    Useful for adding high-quality human-labeled cases to the eval harness.
    Returns list of eval cases in golden_set.json format.
    """
    examples = _load_json(_EXAMPLES_PATH)
    eval_cases = []

    for ex in examples:
        human = ex["human_decision"]
        if not human.get("action"):
            continue

        case = {
            "id": ex["id"],
            "stratum": f"human_override_{human.get('category', 'unknown')}",
            "description": f"Human override: {ex['agent_decision']['action']} → {human['action']}",
            "lead": {
                "lead_id": ex["lead_id"],
                "source": "unknown",
                "raw_content": ex["lead_content_snippet"],
                "metadata": {"source": "unknown", "content": ex["lead_content_snippet"][:100]},
                "timestamp": ex["timestamp"],
            },
            "expected": {
                "action": human["action"],
                **({"tier": human["tier"]} if "tier" in human else {}),
                **({"category": human["category"]} if "category" in human else {}),
            },
        }
        eval_cases.append(case)

    if output_path:
        _save_json(Path(output_path), eval_cases)
        logger.info("eval_cases_exported", extra={"count": len(eval_cases), "path": str(output_path)})

    return eval_cases


def get_override_stats() -> dict:
    """Returns summary statistics about captured overrides."""
    examples = _load_json(_EXAMPLES_PATH)
    if not examples:
        return {"total": 0}

    action_corrections = sum(1 for e in examples if e["correction"]["action_changed"])
    category_corrections = sum(1 for e in examples if e["correction"]["category_changed"])
    tier_corrections = sum(1 for e in examples if e["correction"]["tier_changed"])

    return {
        "total": len(examples),
        "action_corrections": action_corrections,
        "category_corrections": category_corrections,
        "tier_corrections": tier_corrections,
        "correction_rate": round(action_corrections / len(examples), 2),
    }
