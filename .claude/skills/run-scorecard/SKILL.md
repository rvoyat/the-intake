---
name: run-scorecard
description: Runs The Intake eval harness and presents a formatted scorecard. Use when the user wants to check eval results after changing agent logic, tools, or thresholds. Accepts optional argument: "golden", "adversarial", or "dry-run". Invoke with /run-scorecard.
---

# Run Scorecard

Runs the eval harness and presents results in a readable scorecard format.

## Arguments

- `/run-scorecard` — runs both golden set (10 cases) and adversarial set (10 cases)
- `/run-scorecard golden` — golden set only
- `/run-scorecard adversarial` — adversarial set only
- `/run-scorecard dry-run` — validates test case schemas without making API calls

## How to run

Map the argument to the correct flag:
- `golden` → `--golden-only`
- `adversarial` → `--adversarial-only`
- `dry-run` → `--dry-run`
- no arg → no flag (runs both)

```bash
python evals/run_evals.py [--golden-only | --adversarial-only | --dry-run]
```

## How to present results

After running, present the scorecard clearly:

```
══════════════════════════════════════════
  SCORECARD — <date>
══════════════════════════════════════════

  GOLDEN SET
  ──────────────────────────────────────
  Accuracy:              X%  (N/10)
  False-confidence rate: X%
  Escalation rate:       X%
  Avg latency:           Xs

  By stratum:
    ✓ enterprise_high_confidence    100%
    ✓ mid_market_normal             100%
    ...

  ADVERSARIAL SET
  ──────────────────────────────────────
  Pass rate:             X%  (N/10)

══════════════════════════════════════════
  FAILURES (if any)
──────────────────────────────────────────
  [golden-07] Insufficient context to classify
    ✗ action: expected 'request_more_info', got 'escalate'
    ⚠ model was ≥80% confident but wrong  ← HIGH RISK flag
══════════════════════════════════════════
```

## Passing bars (from CLAUDE.md / SCORECARD.md)

| Metric | Must pass |
|---|---|
| Golden set accuracy | ≥ 85% |
| False-confidence rate | ≤ 10% |
| Adversarial pass rate | 100% |

If any bar is missed, say so explicitly and suggest what changed (e.g. "did you modify the classifier's system prompt or change an escalation threshold?").

## After showing results

- If all bars pass: confirm the system is in a good state.
- If adversarial pass rate < 100%: this is a blocker — flag it prominently. Suggest checking `hooks/pre_tool_use.py` and `detect_adversarial_patterns` in `tools/classifier_tools.py`.
- If false-confidence rate > 10%: show which cases were confident-and-wrong and ask if the classification logic changed recently.
