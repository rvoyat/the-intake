# CLAUDE.md — The Intake

> How this project was built with Claude Code, and how to keep building it.

---

## What this project is

**The Intake** is a multi-agent sales lead routing system. It classifies, prioritizes, and routes 200 inbound leads per day — replacing a manual triage process that averaged 4+ hours to first response.

Architecture: a coordinator agent orchestrates three Claude specialists (Classifier, Prioritizer, Responder), each with 5 tools, explicit context passing, and a deterministic Python PreToolUse safety hook on all write operations.

If you're Claude Code just starting a session here: `python main.py --demo` gives you a live end-to-end run. `python evals/run_evals.py --dry-run` validates all test cases. `cat MANDATE.md` is the source of truth on what the agent is allowed to do.

---

## How we built this with Claude Code

This project was built entirely in Claude Code sessions. The workflow we taught Claude Code:

**1. Always run the dry-run eval before touching agent logic.**
Before editing anything in `agents/`, `tools/`, or `config.py`, run:
```bash
python evals/run_evals.py --dry-run
```
This validates the 20 test case schemas without making API calls. If this fails, the test cases themselves are broken — fix them first.

**2. The MANDATE.md is the spec. The code implements it.**
When making architectural decisions, consult `MANDATE.md` first. The file defines what the agent decides alone, what it escalates, and what it must never touch. Code changes that contradict the Mandate are wrong even if they test clean.

**3. Escalation thresholds live in `config.py` and nowhere else.**
If a threshold needs to change, change it in `config.py:EscalationThresholds`. Then update `MANDATE.md` and `SCORECARD.md` to match. Never hardcode thresholds inside agent prompts or tool functions.

**4. Every new tool gets a definition + registry entry.**
Tools are defined in two places: the function itself (in `tools/`) and `TOOL_DEFINITIONS` + `TOOL_REGISTRY` in the same file. Forgetting either breaks the agent loop silently.

**5. Subagents never inherit coordinator context.**
When adding context to a specialist call, serialize it explicitly into the task message. Do not pass the coordinator's message history.

---

## Slash commands (Claude Code skills)

Two skills are installed at `.claude/skills/`:

### `/route-lead`
Routes a lead in natural language using the running intake system.
```
/route-lead "I'm the VP of Procurement at Globex Industries, 2,000 employees. Budget approved for Q2. Looking for an enterprise demo."
```
Runs `main.py`, parses the routing decision, and presents it formatted.

### `/run-scorecard`
Runs the full eval harness and presents the scorecard inline.
```
/run-scorecard            # both sets
/run-scorecard golden     # golden set only
/run-scorecard adversarial # adversarial set only
```

---

## Hooks configured (`.claude/settings.json`)

Two hooks are active:

**PreToolUse — eval guard on agent edits:**
Before any `Edit` or `Write` to files in `agents/`, `tools/`, or `hooks/`, Claude Code runs `python evals/run_evals.py --dry-run`. If the dry-run fails (malformed test cases), the edit is blocked. This prevents test-case drift silently accumulating across sessions.

**PostToolUse — threshold change reminder:**
After any edit to `config.py`, Claude Code prints a reminder:
```
⚠️  config.py changed — remember to update MANDATE.md rollout phases and SCORECARD.md passing bars if thresholds changed.
```

---

## Running the system

```bash
# One-command demo
python main.py --demo

# Route a custom lead
python main.py --lead '{"lead_id":"l001","source":"email","raw_content":"...","metadata":{"source":"email","content":"..."},"timestamp":"2026-04-28T10:00:00Z"}'

# JSON output (for piping)
python main.py --demo --output json

# Full eval scorecard
python evals/run_evals.py

# Validate test cases without API calls
python evals/run_evals.py --dry-run

# Capture a human override (feeds The Loop)
python - <<'EOF'
from feedback import capture_human_override
capture_human_override(
    lead_id="l001",
    lead_content="...",
    original_decision={"action": "route", "category": "smb", ...},
    human_decision={"action": "route", "category": "mid_market", "tier": "T2_mid_market"},
    reviewer_id="rep-001",
    notes="Company size was underestimated — 300 employees not 50"
)
EOF
```

---

## Key files and their roles

| File | Role |
|---|---|
| `MANDATE.md` | The spec. What the agent owns, escalates, never touches. Legal-facing. |
| `SCORECARD.md` | Pre-computed eval results. Reference for pass/fail bars. |
| `docs/ADR-001-agent-architecture.md` | Why coordinator+specialists, why 5 tools, why deterministic escalation |
| `config.py` | All numeric thresholds. Single source of truth. |
| `agents/coordinator.py` | Orchestration, escalation logic, validation-retry loop |
| `agents/base.py` | Shared agent loop — stop_reason handling, PreToolUse hook call |
| `hooks/pre_tool_use.py` | Deterministic hard stop on write tools |
| `feedback/feedback_loop.py` | Human override capture → labeled examples → few-shot + eval set |
| `evals/run_evals.py` | Full eval harness. Run this after every non-trivial change. |

---

## What not to do

**Don't bypass the PreToolUse hook.** If a write is being blocked and it feels wrong, check `hooks/pre_tool_use.py` and understand why — then fix the underlying condition. Never add a try/except or conditional around the hook call.

**Don't change escalation behavior in a system prompt.** Prompt-based escalation produces inconsistent behavior that can't be measured. Changes go in `config.py:EscalationThresholds`, not in agent prompts.

**Don't add a sixth tool to a specialist.** Tool-selection reliability degrades past 5. If you think you need a sixth tool, that's a signal the specialist needs to be split or the tool belongs in a different specialist.

**Don't modify `evals/golden_set.json` to make a failing test pass.** If an eval fails, fix the code or the threshold — not the test case. The eval is a contract.

**Don't re-classify a lead to boost its confidence score.** Per the Mandate: "We do not retry classification to get a higher confidence score." Low confidence should escalate, not retry.

---

## What impresses a judge

If someone only reads this file, README.md, and presentation.html, they should understand:
1. **What we built** — automated sales lead routing, 200/day, multi-agent, Python SDK
2. **Why it's safe** — PreToolUse hook (hard stop) + escalation rules (slow stop) + Mandate
3. **Why it works** — 90% accuracy, 0% false-confidence, 100% adversarial pass rate
4. **How we built it** — Claude Code sessions, `/route-lead` skill, eval-guard hook, the feedback loop closes itself
5. **What's next** — webhook ingestor, T3 auto-execute at 92% accuracy, override dashboard

The thing we deliberately did differently: every human override feeds back into the system automatically — the eval set gets harder and the classifier gets smarter in the same operation. Most teams log the override and stop there.
