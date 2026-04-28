# ADR-001: Coordinator + Specialist Agent Architecture

**Status:** Accepted  
**Date:** 2026-04-28  
**Deciders:** Engineering, Product  
**Supersedes:** N/A

---

## Context

We needed to automate triage and routing of 200 inbound sales leads per day. The options were:

1. A single monolithic agent with all tools
2. A coordinator agent orchestrating dedicated specialist subagents
3. A chain of deterministic rules with no LLM

Option 1 (monolithic) was eliminated early: a single agent with 15 tools has significantly degraded tool-selection reliability compared to an agent with 4–5 tools. Tool-selection accuracy is empirically better when each agent has a narrow, focused tool set.

Option 3 (pure rules) was eliminated because the input is unstructured free text across three channels with high signal variability. A rules engine can't reliably classify "we have a Q2 budget approved for something in your space" as an enterprise lead without LLM-level language understanding.

This ADR records the decision to use Option 2.

---

## Decision

We use a **coordinator + three specialist subagents** architecture with explicit context passing.

```
┌─────────────────────────────────────────────────────────┐
│                    COORDINATOR                           │
│                                                          │
│  loop:                                                   │
│    1. call Classifier subagent (explicit context)        │
│    2. call Prioritizer subagent (explicit context)       │
│    3. apply deterministic escalation rules               │
│    4. call Responder subagent (explicit context)         │
│    5. validate RoutingDecision schema                    │
│    6. if invalid → retry (max 3x) with error fed back    │
│    7. log reasoning_chain                                │
│                                                          │
│  stop_reason handling:                                   │
│    "end_turn"   → extract result, continue flow          │
│    "tool_use"   → execute tools, append results, loop    │
│    other        → log error, surface to coordinator      │
└─────────────────────────────────────────────────────────┘

     │                    │                    │
     ▼                    ▼                    ▼
┌──────────┐       ┌────────────┐      ┌──────────────┐
│CLASSIFIER│       │PRIORITIZER │      │  RESPONDER   │
│          │       │            │      │              │
│ 5 tools  │       │  5 tools   │      │   5 tools    │
│          │       │            │      │  (2 guarded) │
└──────────┘       └────────────┘      └──────────────┘
     │                    │                    │
     ▼                    ▼                    ▼
  category           tier + score       routing decision
  confidence         rep assignment     + CRM write
  signals            impact level       + rep notify
```

---

## Agent Loop Detail

Each specialist runs the same shared loop (`agents/base.py`):

```
messages = [{"role": "user", "content": <task_with_explicit_context>}]

while iterations < MAX:
    response = claude.messages.create(model, system, tools, messages)

    if response.stop_reason == "end_turn":
        return extract_text(response)          # done

    if response.stop_reason == "tool_use":
        for each tool_use block:
            result = pre_tool_use_hook(tool, input)   # hard stop check
            if blocked:
                return structured_error
            result = tool_registry[tool_name](**input)
            append tool_result to messages
        continue loop                          # feed results back

    log_error(stop_reason)
    return error_result                        # unexpected stop
```

The loop terminates on `end_turn`. Every other `stop_reason` is an error condition that surfaces to the coordinator, not silently retried.

---

## Why Specialist Subagents Do Not Inherit Coordinator Context

Each specialist is invoked with its full context embedded in the task message. The coordinator's message history is **not passed** to specialists.

**Why:** Claude's Task subagents don't inherit coordinator context by design. If they did:
- The specialist's input would grow with every coordinator turn
- Earlier coordinator reasoning could contaminate the specialist's output
- Debugging a bad classification would require replaying the entire coordinator history

**Consequence:** Every specialist call must be self-contained. If a specialist needs upstream data (e.g., the prioritizer needs the classification result), that data is serialized into the task message explicitly.

---

## Why 4–5 Tools Per Specialist

Tool-selection reliability is a function of tool count. Empirically, agents with more than 5–6 tools show measurably higher rates of:
- Calling the wrong tool for a given intent
- Calling tools in the wrong order
- Skipping tools that are required by the output contract

We capped at 5 tools per specialist. If a sixth tool is needed, the right question is whether that work belongs in a different specialist.

---

## Why the Escalation Logic Lives in the Coordinator, Not Specialist Agents

The coordinator applies deterministic escalation rules after receiving structured outputs from the classifier and prioritizer. The specialists do not decide whether to escalate.

**Why:** Escalation is a cross-cutting policy concern. Putting it inside a specialist would mean:
- The same logic duplicated across specialists
- A specialist that's wrong about escalation propagates to the coordinator unchecked
- Changing the threshold requires touching every specialist

The coordinator is the only component that has both the classification AND the priority in scope simultaneously, making it the right place for rules that depend on both.

---

## Why Deterministic Escalation Rules, Not Prompt-Based

The escalation rules use explicit numeric thresholds (confidence < 0.75, enterprise < 0.85, etc.) enforced in Python, not expressed as LLM instructions.

**Why:** Prompt-based escalation instructions ("escalate when you're not sure") produce inconsistent behavior because:
- The model's interpretation of "not sure" varies across calls
- Small changes in the system prompt can shift the threshold unpredictably
- A labeled eval set cannot reliably measure compliance with a vague rule

Deterministic rules produce consistent escalation behavior that can be measured, tested, and changed deliberately.

---

## Why the PreToolUse Hook Is Separate From Prompt Instructions

The hook in `hooks/pre_tool_use.py` blocks write tools before they execute. It does not ask the LLM to decline.

**Why:** Prompt-based constraints can be bypassed — by prompt injection in the lead content, by model drift between versions, or by edge cases the prompt didn't anticipate. The hook is executed in Python before the tool function is called. It cannot be overridden by anything in the input.

The hook is a **hard stop**. Escalation logic is a **slow stop**. Both are needed: the hook catches what prompt instructions miss; escalation catches what the hook's pattern-matching misses.

---

## Consequences

**Positive:**
- Each specialist is independently testable with its own eval cases
- Tool descriptions are narrow and precise — easier to write correctly
- Reasoning chain is decomposable — each phase's contribution is logged separately
- Escalation thresholds are in one place (config.py) and change atomically

**Negative:**
- Coordinator has to serialize context for each subagent call — more tokens per lead
- Adding a new specialist requires updating the coordinator's orchestration logic
- Latency is higher than a monolithic agent (3 sequential LLM calls minimum)

**Mitigations:**
- Token cost is acceptable at 200 leads/day; revisit at 2,000/day
- Coordinator orchestration logic is contained in one file (coordinator.py)
- Latency is partially offset by the speed gain from using haiku-class models for specialists
