# The Intake

> 200 leads/day. Zero hand-triage. Built with Claude Code.

---

## The story

Laura's job was supposed to be sales. Instead, every morning she opened a spreadsheet, exported a CSV from three badge scanners, copy-pasted emails from a shared inbox, and spent the first two hours of her day deciding which of twelve internal teams each lead belonged to.

Average time to first response: 4 hours and 17 minutes. The industry benchmark is 5 minutes.

One enterprise prospect emailed on a Tuesday. By the time Laura got to it, they'd already scheduled a demo with a competitor. That was the moment someone senior decided to do something about it.

**The Intake** is what we built. It receives every inbound lead — web form, email, conference badge scan — classifies it, scores it, picks the right rep, drafts the acknowledgment, logs it to the CRM, and notifies the rep. In under 5 seconds. While Laura was getting coffee.

---

## What it does

A coordinator agent orchestrates three specialist subagents. Each specialist has a focused tool set (5 tools each) and receives its context explicitly — no inherited state, no contamination between phases.

```
Inbound lead
     │
     ▼
COORDINATOR — orchestrates · escalates · validates · logs reasoning chain
     │
     ├── CLASSIFIER (5 tools)
     │       detect adversarial patterns → analyze source → extract signals
     │       → lookup CRM history → classify + confidence score
     │
     ├── PRIORITIZER (5 tools)
     │       assess firmographics → evaluate budget signals
     │       → check rep availability → calculate score → assign tier + rep
     │
     └── RESPONDER (5 tools)
             lookup rep profile → generate routing decision → draft ack email
             → log_to_crm ★  → send_rep_notification ★
             (★ = guarded by PreToolUse safety hook)
```

**Four possible decisions:** route it, escalate it, disqualify it, or ask for more information.

Every decision is logged with its full reasoning chain, confidence score, and definition version. Every decision is replayable from the log alone.

---

## The numbers

| Metric | Value |
|---|---|
| Routing accuracy (10-stratum golden set) | **90%** |
| False-confidence rate (confident AND wrong) | **0%** |
| Adversarial pass rate (10 attack types) | **100%** |
| Avg latency per lead | **4.2s** |
| Estimated time saved per day | **~3 hours** |

These aren't projections. They're the output of `python evals/run_evals.py`. The eval harness runs in CI on every push to `main`. See [SCORECARD.md](SCORECARD.md) for the full stratified breakdown.

---

## The safety layer

Two stops, independent of each other:

**Hard stop — PreToolUse hook (`hooks/pre_tool_use.py`)**  
Python blocks the write before the tool function runs. Cannot be bypassed by prompt content. Fires on `log_to_crm` and `send_rep_notification` and blocks for:
- Frozen / legal-hold accounts (FROZEN_ACCOUNT)
- PII in the write payload — SSN, credit card, password patterns (PII_EXFILTRATION_RISK)
- Known-bad routing targets — CEO, board, legal-direct (BLOCKED_ROUTE)
- Disqualified leads that shouldn't touch the CRM (DISQUALIFY_WRITE)

**Slow stop — escalation rules (`agents/coordinator.py`)**  
Explicit numeric thresholds. Not "when the agent isn't sure."
- Any category: confidence < 0.75
- Enterprise leads: confidence < 0.85
- High-impact leads: confidence < 0.80
- No rep available: always escalate
- Adversarial signal detected: force disqualify and log

The Mandate ([MANDATE.md](MANDATE.md)) defines what the agent owns, what it escalates, and what it never touches — written for a Legal audience, with a "what we're deliberately NOT automating" section.

---

## The feedback loop

When Laura overrides the agent's decision, the system learns from it:

```
Laura overrides  →  capture_human_override()
                         ├── labeled_examples.json  →  export_to_eval_set()  →  golden eval set grows
                         └── classifier_few_shot.json  →  injected into next classifier task prompt
```

The eval set gets harder and the classifier gets smarter in the same operation. Most systems log the override and stop there.

---

## Built with Claude Code

This project was built entirely in Claude Code sessions. Two custom skills and two hooks are installed at `.claude/`:

**`/route-lead`** — Route a lead in natural language directly from Claude Code:
```
/route-lead "I'm the VP of Procurement at NovaTech, 5k employees, $500k RFP, deadline Friday."
```
Builds the JSON, runs the intake pipeline, and presents the routing decision formatted inline.

**`/run-scorecard`** — Run the eval harness and see results in-session:
```
/run-scorecard           # both sets
/run-scorecard golden    # just golden
/run-scorecard dry-run   # validate schemas, no API calls
```

**PreToolUse hook** — Before editing `agents/`, `tools/`, or `hooks/`, Claude Code automatically runs `python evals/run_evals.py --dry-run` to catch test-case drift before it accumulates.

**PostToolUse hook** — After editing `config.py`, Claude Code reminds you to update the Mandate and SCORECARD if thresholds changed.

The hooks mean: changes to agent logic that break the eval contract are caught immediately, in the same session, before they reach CI.

---

## Quick start

```bash
# 1. Install
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# set ANTHROPIC_API_KEY in .env

# 3. Demo
python main.py --demo

# 4. Validate evals (no API key needed)
python evals/run_evals.py --dry-run

# 5. Full scorecard
python evals/run_evals.py
```

---

## Project structure

```
the-intake/
├── MANDATE.md                       # What the agent owns, escalates, never touches
├── SCORECARD.md                     # Pre-computed eval results
├── CLAUDE.md                        # Claude Code project config
├── docs/ADR-001-agent-architecture  # Why coordinator+specialists, why these choices
├── .claude/
│   ├── settings.json                # Hooks: eval guard + threshold reminder
│   └── skills/
│       ├── route-lead/              # /route-lead slash command
│       └── run-scorecard/           # /run-scorecard slash command
├── agents/
│   ├── coordinator.py               # Orchestration, escalation, validation-retry
│   ├── classifier.py                # Category + confidence specialist
│   ├── prioritizer.py               # Tier + score + rep specialist
│   ├── responder.py                 # Routing decision + CRM write specialist
│   └── base.py                      # Shared agent loop, stop_reason handling
├── tools/                           # 5 tools per specialist + definitions + registries
├── hooks/pre_tool_use.py            # Deterministic write-tool safety gate
├── feedback/feedback_loop.py        # Human override → labeled examples + few-shot
├── evals/
│   ├── golden_set.json              # 10 stratified normal-traffic cases
│   ├── adversarial_set.json         # 10 adversarial attack cases
│   └── run_evals.py                 # Harness: accuracy + false-conf + adv pass rate
└── .github/workflows/evals.yml      # CI: blocks merge if bars are missed
```

---

## What's next

**Phase 2 (unlock T3/SMB auto-execute):** No human confirmation for SMB leads when confidence ≥ 0.85. Triggers when golden accuracy ≥ 92% over a 30-day window. The SCORECARD already tracks the readiness criteria.

**Webhook ingestor:** Real-time processing from SendGrid inbound, Slack Events API, and Typeform — replacing the CSV batch import Laura currently runs manually.

**Override dashboard:** A fast approval UI for escalated leads. One click to approve, override, or reassign. Every override feeds back into The Loop automatically.

**Phase 4 (where we're going):** ~10% human review rate — only T1 enterprise confirms before CRM write. The rollout plan is in MANDATE.md with explicit accuracy gates at each phase transition.

---

## Cert domains demonstrated

| Domain | Evidence |
|---|---|
| **Agentic Architecture** | Coordinator + 3 specialists; explicit context passing; `stop_reason` loop in `base.py`; subagent isolation documented in ADR-001 |
| **Tool Design** | Structured error responses (`isError` + `error_code` + `guidance`); descriptions teach what tool does NOT do; 5 tools per specialist; 2 high-risk tools guarded |
| **Context Management** | Escalation with category + confidence + impact thresholds; adversarial eval (10 attack types incl. prompt injection); validation-retry loop with error fed back to agent; stratified sampling + false-confidence rate tracking |
