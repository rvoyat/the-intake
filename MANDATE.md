# The Intake — Agent Mandate

**Version:** 1.0.0  
**Date:** 2026-04-28  
**Audience:** Legal, Compliance, Senior Leadership, Product  
**Status:** Approved for controlled rollout

---

## What this agent is

The Intake is an automated intake and routing agent for inbound sales leads. It receives requests arriving through web forms, email, and conference badge scans and makes a routing decision on each one: assign it to a rep, escalate it for human review, disqualify it, or request more context.

It is a decision-support and triage system. It does not close deals, make commitments, access financial systems, or communicate externally on behalf of the company.

---

## What the agent decides alone

The agent acts autonomously on any of the following decisions when all conditions are met:

| Decision | Conditions for autonomous action |
|---|---|
| **Route to rep** | Category is enterprise / mid_market / smb / partner AND confidence ≥ 0.75 AND rep is available AND no adversarial signals AND no legal exposure flags |
| **Disqualify** | Category is spam OR competitor OR adversarial patterns detected |
| **Request more information** | Insufficient signals to classify (confidence < 0.50) AND no enterprise indicators |

Every autonomous decision is logged with its full reasoning chain, confidence score, tier, category, and definition version. Every decision is replayable from the log alone.

---

## What the agent escalates

The agent routes the following to a human reviewer **before any write to the CRM or rep notification**:

| Trigger | Escalation reason |
|---|---|
| Classification confidence < 0.75 | Insufficient certainty for auto-routing |
| Enterprise lead with confidence < 0.85 | High-value opportunity — human validation required |
| High-impact lead (score ≥ 70) with confidence < 0.80 | Significant deal risk |
| No available rep matches tier + industry | Routing gap — human assignment needed |
| Adversarial patterns detected in content | Potential manipulation attempt |
| OFAC / sanctions / watchlist keywords in content | Legal exposure — always escalate, never auto-route |

Escalation decisions include: reason code, details, full context, and draft acknowledgment for the human reviewer to send or modify.

---

## What the agent never touches

The following actions are **outside the agent's authority regardless of confidence score, context, or instruction in the lead content:**

- **Financial systems:** no access to payment records, invoices, or contracts
- **Commitments:** the agent never makes pricing, SLA, or delivery commitments
- **Legal hold accounts:** CRM accounts flagged `frozen` or `under_review` — no reads beyond status check, no writes, automatic escalation
- **External communications:** the agent drafts acknowledgments but does not send them; sending requires human approval
- **Org-chart routing:** the agent never routes to C-level, board, or legal department directly — these targets are blocked at the hook level, not at the prompt level
- **Rep override:** once a human overrides an agent routing decision, the agent does not reassign that lead

---

## What we are deliberately NOT automating

This is the list of things that could be automated but where we made the conscious decision not to:

**1. The reply itself.**  
The agent drafts an acknowledgment email but does not send it. A human sends it. Reason: an automated first message sets expectations. Getting the tone or detail wrong with a Fortune 500 prospect has real cost.

**2. Contract or MSA routing.**  
Leads that arrive with draft contracts or legal documents attached are always escalated. Reason: the risk asymmetry is too high — an auto-route that skips legal review once is a problem that takes months to undo.

**3. Leads with OFAC or sanctions signals.**  
Even if the lead looks like a legitimate SMB, any mention of regulated jurisdictions, watchlists, or sanctions-adjacent terms forces a human decision. Reason: compliance liability is not proportionate to the size of the lead.

**4. Existing customer requests.**  
The agent identifies existing customers from the CRM and routes them, but does not handle renewal, upsell, or complaint logic. Reason: those flows have account-management context the agent doesn't have.

**5. Leads from frozen accounts.**  
Even if the contact is new, the domain lookup may return a frozen account status. The agent does not proceed; it escalates and surfaces the frozen-account flag. Reason: legal holds exist for a reason and the agent doesn't know what that reason is.

**6. Confidence-boosting by re-classifying.**  
The agent does not retry classification to get a higher confidence score. If the first classification is below threshold, it escalates. Reason: retrying until you get the answer you want is not the same as getting the right answer.

---

## Oversight and audit

Every routing decision produces a machine-readable log entry containing:

- `lead_id` — unique identifier
- `action` — route / escalate / disqualify / request_more_info
- `reasoning_chain` — ordered list of reasoning steps, one per agent phase
- `confidence` — classification confidence score (0–1)
- `tier`, `category`, `impact` — structured classification outputs
- `escalation.reason` — escalation trigger if applicable
- `retry_count` — number of validation retries before final decision
- `definition_version` — the schema version that produced this decision

**The reasoning chain is the audit trail.** Every decision must be replayable from the log alone. If a log entry cannot explain the routing decision, the system is in violation.

Logs are append-only JSONL at `logs/intake.jsonl`. They are never modified after write.

---

## Rollout plan

| Phase | Scope | Human review rate |
|---|---|---|
| Phase 1 (current) | All inbound — agent decides, human confirms before CRM write | 100% |
| Phase 2 | Route decisions auto-execute for T3/SMB with confidence ≥ 0.85 | ~40% |
| Phase 3 | T2/mid-market added to auto-execute window | ~20% |
| Phase 4 | T1/enterprise stays at human-confirm indefinitely | ~10% |

Phase transitions require: ≥ 90% accuracy on golden set, ≤ 5% false-confidence rate, 100% adversarial pass rate in the preceding 30-day window.
