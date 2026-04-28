---
name: route-lead
description: Routes an inbound sales lead through The Intake agent system. Use when the user provides a lead description and wants to see the routing decision — category, tier, assigned rep, confidence score, and reasoning chain. Accepts natural language or structured input. Invoke with /route-lead followed by the lead description.
---

# Route Lead

Routes a sales lead through the full multi-agent intake pipeline and presents the decision.

## How to run

1. Extract from the user's input:
   - `lead_id`: generate one if not given (e.g. `cli-001`)
   - `source`: infer from context (`web_form`, `email`, `badge_scan`, `phone`) or default to `web_form`
   - `raw_content`: the full text of the lead
   - `metadata.content`: a short keyword summary of the content

2. Build the JSON payload and run:
```bash
python main.py --lead '<JSON>' --output json
```

3. Parse the JSON output and present the decision as:

```
Lead: <lead_id>
Action: ROUTE / ESCALATE / DISQUALIFY / REQUEST MORE INFO
Category: <category>  |  Tier: <tier>  |  Score: <score>/100
Confidence: <X>%  |  Impact: <impact>
Assigned rep: <name> (<id>) — or "none" if escalated
Escalation: <reason if escalated>

Reasoning chain:
  [1] ...
  [2] ...
  ...

Acknowledgment draft:
  <draft text>
```

4. If the action is DISQUALIFY, add a one-line note on why.
5. If the action is ESCALATE, show the escalation reason and suggest what a human reviewer should check.

## Error handling

- If `main.py` fails (missing API key, network error), show the error and suggest: `cp .env.example .env` and set `ANTHROPIC_API_KEY`.
- If the user provides very little content (< 10 words), warn that confidence will be low and the agent may return `request_more_info`.

## Example

User: `/route-lead "I'm the CTO at NovaTech, 5,000 employees. We have an RFP deadline Friday for a $500k deal. Need enterprise team ASAP."`

Expected output:
```
Lead: cli-001
Action: ROUTE
Category: enterprise  |  Tier: T1_enterprise  |  Score: 87.3/100
Confidence: 94%  |  Impact: high
Assigned rep: Sarah Chen (rep-001)

Reasoning chain:
  [1] Received lead cli-001 from source 'web_form'
  [2] Classifier: category='enterprise', confidence=0.94, adversarial_flags=[]
  [3] Prioritizer: tier='T1_enterprise', score=87.3, rep_id='rep-001', impact='high'
  [4] Escalation: should_escalate=False — all thresholds met
  [5.1] Responder: action='route', rep='Sarah Chen', crm_id='crm-a3f2d1b0'

Acknowledgment draft:
  Thanks for reaching out. Your inquiry has been assigned to Sarah Chen,
  who will be in touch within one business day.
```
