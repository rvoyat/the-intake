"""
Shared agent loop. All specialists inherit this pattern.
"""
import json
import logging
from typing import Any

import anthropic

from config import config
from hooks.pre_tool_use import pre_tool_use_hook

logger = logging.getLogger(__name__)


def run_agent_loop(
    system_prompt: str,
    tool_definitions: list[dict],
    tool_registry: dict,
    task_message: str,
    model: str | None = None,
    max_iterations: int = 15,
) -> dict[str, Any]:
    """
    Core agent loop shared by all specialists.
    Runs until stop_reason == 'end_turn' or max_iterations reached.
    Returns {"result": <last text content>, "tool_calls": [...], "iterations": int}.
    """
    client = anthropic.Anthropic(api_key=config.anthropic_api_key)
    model = model or config.models.specialist_model
    messages = [{"role": "user", "content": task_message}]
    tool_call_log = []
    iterations = 0

    while iterations < max_iterations:
        iterations += 1

        response = client.messages.create(
            model=model,
            system=system_prompt,
            tools=tool_definitions,
            messages=messages,
            max_tokens=config.models.max_tokens,
        )

        logger.debug("agent_turn", extra={
            "stop_reason": response.stop_reason,
            "iteration": iterations,
            "model": model,
        })

        assistant_content = response.content
        messages.append({"role": "assistant", "content": assistant_content})

        if response.stop_reason == "end_turn":
            text_blocks = [b.text for b in assistant_content if hasattr(b, "text")]
            return {
                "result": text_blocks[-1] if text_blocks else "",
                "tool_calls": tool_call_log,
                "iterations": iterations,
            }

        if response.stop_reason != "tool_use":
            return {
                "result": "",
                "tool_calls": tool_call_log,
                "iterations": iterations,
                "error": f"Unexpected stop_reason: {response.stop_reason}",
            }

        tool_results = []
        for block in assistant_content:
            if block.type != "tool_use":
                continue

            tool_name = block.name
            tool_input = block.input

            hook_result = pre_tool_use_hook(tool_name, tool_input)
            if not hook_result["allowed"]:
                result_content = json.dumps({
                    "isError": True,
                    "error_code": hook_result.get("block_code", "HOOK_BLOCKED"),
                    "message": hook_result["reason"],
                    "guidance": "This tool call was blocked by the PreToolUse safety hook.",
                })
                logger.warning("tool_blocked", extra={
                    "tool": tool_name,
                    "block_code": hook_result.get("block_code"),
                })
            else:
                fn = tool_registry.get(tool_name)
                if fn is None:
                    result_content = json.dumps({
                        "isError": True,
                        "error_code": "TOOL_NOT_FOUND",
                        "message": f"Tool '{tool_name}' not in registry.",
                        "guidance": "Only call tools listed in the tool definitions.",
                    })
                else:
                    try:
                        raw = fn(**tool_input)
                        result_content = json.dumps(raw)
                    except Exception as e:
                        result_content = json.dumps({
                            "isError": True,
                            "error_code": "TOOL_EXECUTION_ERROR",
                            "message": str(e),
                            "guidance": "Check input types and required fields.",
                        })

            tool_call_log.append({
                "tool": tool_name,
                "input": tool_input,
                "result": json.loads(result_content),
                "blocked": not hook_result["allowed"],
            })

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result_content,
            })

        messages.append({"role": "user", "content": tool_results})

    return {
        "result": "",
        "tool_calls": tool_call_log,
        "iterations": iterations,
        "error": "max_iterations_reached",
    }
