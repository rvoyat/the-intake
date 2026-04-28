"""
Coordinator agent — orchestrates classifier → prioritizer → escalation logic → responder.
Owns: reasoning chain logging, validation-retry loop, escalation decisions.
Does NOT call specialist tools directly; it calls specialist agents with explicit context.
"""
import json
import logging
import time
from datetime import datetime, timezone

from models.schemas import (
    LeadRequest, RoutingDecision, ClassificationResult, PriorityResult,
    EscalationDecision, EscalationReason, Tier, LeadCategory, ImpactLevel,
)
from config import config
from .classifier import run_classifier
from .prioritizer import run_prioritizer
from .responder import run_responder

logger = logging.getLogger(__name__)


def _decide_escalation(
    classification: ClassificationResult,
    priority: PriorityResult,
) -> EscalationDecision:
    """
    Deterministic escalation rules.
    Category + confidence threshold + impact level — no vague "when unsure" rules.
    """
    thresholds = config.escalation

    if classification.adversarial_flags:
        return EscalationDecision(
            should_escalate=True,
            reason=EscalationReason.ADVERSARIAL_SIGNAL,
            details=f"Adversarial patterns detected: {classification.adversarial_flags}",
        )

    if classification.confidence < thresholds.min_confidence_auto_route:
        return EscalationDecision(
            should_escalate=True,
            reason=EscalationReason.LOW_CONFIDENCE,
            details=(
                f"Confidence {classification.confidence:.2f} is below threshold "
                f"{thresholds.min_confidence_auto_route} for auto-routing."
            ),
        )

    if (
        classification.category == LeadCategory.ENTERPRISE
        and classification.confidence < thresholds.enterprise_min_confidence
    ):
        return EscalationDecision(
            should_escalate=True,
            reason=EscalationReason.HIGH_VALUE_UNCERTAIN,
            details=(
                f"Enterprise lead with confidence {classification.confidence:.2f} "
                f"below enterprise threshold {thresholds.enterprise_min_confidence}."
            ),
        )

    if (
        priority.impact == ImpactLevel.HIGH
        and classification.confidence < thresholds.high_impact_min_confidence
    ):
        return EscalationDecision(
            should_escalate=True,
            reason=EscalationReason.HIGH_VALUE_UNCERTAIN,
            details=f"High-impact lead with insufficient confidence ({classification.confidence:.2f}).",
        )

    if priority.tier != Tier.DISQUALIFY and priority.assigned_rep_id is None:
        return EscalationDecision(
            should_escalate=True,
            reason=EscalationReason.NO_REP_AVAILABLE,
            details="No available rep found for this tier and industry.",
        )

    return EscalationDecision(
        should_escalate=False,
        reason=None,
        details="All thresholds met; auto-routing approved.",
    )


def _validate_routing_decision(decision: RoutingDecision) -> tuple[bool, str]:
    """
    Validates the assembled RoutingDecision against the schema from the Mandate.
    Returns (is_valid, error_message).
    """
    if decision.action not in ("route", "escalate", "disqualify", "request_more_info"):
        return False, f"Invalid action: {decision.action}"

    if decision.action == "route" and not decision.assigned_rep_id:
        return False, "Action is 'route' but no rep assigned."

    if decision.action == "escalate" and not decision.escalation.should_escalate:
        return False, "Action is 'escalate' but escalation flag is False."

    if not (0.0 <= decision.confidence <= 1.0):
        return False, f"Confidence {decision.confidence} out of range."

    if not (0.0 <= decision.lead_score <= 100.0):
        return False, f"Lead score {decision.lead_score} out of range."

    return True, ""


def run_coordinator(lead: LeadRequest) -> RoutingDecision:
    """
    Main coordinator entry point.
    Passes explicit context to each specialist — subagents do not inherit coordinator state.
    Implements validation-retry loop (up to config.escalation.max_retries attempts).
    Logs full reasoning chain for every decision.
    """
    start_time = time.time()
    reasoning_chain = []
    retry_count = 0

    logger.info("coordinator_start", extra={
        "lead_id": lead.lead_id,
        "source": lead.source,
        "timestamp": lead.timestamp,
    })

    lead_context = lead.model_dump()

    reasoning_chain.append(f"[1] Received lead {lead.lead_id} from source '{lead.source}'.")

    classification = run_classifier(lead_context)
    reasoning_chain.append(
        f"[2] Classifier: category='{classification.category}', "
        f"confidence={classification.confidence:.2f}, "
        f"adversarial_flags={classification.adversarial_flags}."
    )

    if classification.adversarial_flags:
        reasoning_chain.append("[3] Adversarial signal detected — skipping prioritizer, forcing escalation.")
        priority = PriorityResult(
            lead_id=lead.lead_id,
            tier=Tier.DISQUALIFY,
            impact=ImpactLevel.LOW,
            lead_score=0.0,
            reasoning="Skipped: adversarial signal in lead content.",
        )
    else:
        priority = run_prioritizer(lead_context, classification.model_dump())
        reasoning_chain.append(
            f"[3] Prioritizer: tier='{priority.tier}', score={priority.lead_score:.1f}, "
            f"rep_id='{priority.assigned_rep_id}', impact='{priority.impact}'."
        )

    escalation = _decide_escalation(classification, priority)
    reasoning_chain.append(
        f"[4] Escalation: should_escalate={escalation.should_escalate}, "
        f"reason='{escalation.reason}', details='{escalation.details}'."
    )

    max_retries = config.escalation.max_retries
    decision = None

    while retry_count <= max_retries:
        responder_output = run_responder(
            lead_context=lead_context,
            classification=classification.model_dump(),
            priority=priority.model_dump(),
            escalation=escalation.model_dump(),
        )

        reasoning_chain.append(
            f"[5.{retry_count + 1}] Responder: action='{responder_output.get('action')}', "
            f"rep='{responder_output.get('assigned_rep_name')}', "
            f"crm_id='{responder_output.get('crm_record_id')}'."
        )

        try:
            candidate = RoutingDecision(
                lead_id=lead.lead_id,
                action=responder_output.get("action", "escalate"),
                assigned_rep_id=responder_output.get("assigned_rep_id"),
                assigned_rep_name=responder_output.get("assigned_rep_name"),
                tier=priority.tier,
                category=classification.category,
                confidence=classification.confidence,
                impact=priority.impact,
                lead_score=priority.lead_score,
                escalation=escalation,
                acknowledgment_draft=(
                    f"{responder_output.get('acknowledgment_subject', '')}\n\n"
                    f"{responder_output.get('acknowledgment_body', '')}"
                ),
                reasoning_chain=reasoning_chain,
                retry_count=retry_count,
            )
        except Exception as e:
            retry_count += 1
            reasoning_chain.append(f"[RETRY {retry_count}] Schema validation error: {e}")
            continue

        is_valid, error_msg = _validate_routing_decision(candidate)
        if is_valid:
            decision = candidate
            break

        retry_count += 1
        reasoning_chain.append(
            f"[RETRY {retry_count}] Validation failed: '{error_msg}'. "
            f"Feeding error back to responder."
        )

        lead_context["_validation_error"] = error_msg

    if decision is None:
        reasoning_chain.append(f"[FAILED] Max retries ({max_retries}) exceeded. Forcing escalation.")
        decision = RoutingDecision(
            lead_id=lead.lead_id,
            action="escalate",
            assigned_rep_id=None,
            assigned_rep_name=None,
            tier=priority.tier if priority else Tier.DISQUALIFY,
            category=classification.category if classification else LeadCategory.UNQUALIFIED,
            confidence=classification.confidence if classification else 0.0,
            impact=priority.impact if priority else ImpactLevel.LOW,
            lead_score=priority.lead_score if priority else 0.0,
            escalation=EscalationDecision(
                should_escalate=True,
                reason=EscalationReason.LOW_CONFIDENCE,
                details="Forced escalation after max retries exceeded.",
            ),
            reasoning_chain=reasoning_chain,
            retry_count=retry_count,
        )

    elapsed = round(time.time() - start_time, 2)
    logger.info("coordinator_complete", extra={
        "lead_id": lead.lead_id,
        "action": decision.action,
        "tier": decision.tier,
        "confidence": decision.confidence,
        "lead_score": decision.lead_score,
        "escalated": decision.escalation.should_escalate,
        "retry_count": retry_count,
        "elapsed_seconds": elapsed,
        "reasoning_chain": decision.reasoning_chain,
    })

    return decision
