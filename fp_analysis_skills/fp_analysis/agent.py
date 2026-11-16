"""Optional: a bounded tool loop for an "Analysis" workspace, mirroring run_formatting_agent.

The system prompt is SKILL.md (the model-facing skill document next to this package), so
editing the skill text changes the agent's behaviour without touching code.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .tools import ANALYSIS_TOOLS, analysis_tool_result

MAX_TOOL_CALLS = 16
SKILL_PATH = Path(__file__).resolve().parent.parent / "SKILL.md"


def system_prompt() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


def _message_dict(message: Any) -> dict[str, Any]:
    return message if isinstance(message, dict) else message.model_dump(exclude_none=True)


def run_analysis_agent(
    history: list[dict[str, str]],
    handoff: dict[str, Any],
    model: str = "gpt-5.6-terra",
    on_tool_call: Callable[[str], None] | None = None,
    persist: bool = True,
    client: Any = None,
) -> dict[str, Any]:
    """Run the analysis assistant over a hand-off; outputs land in handoff['outputs']."""
    if client is None:
        from openai_agent import get_imf_openai_client  # the web app's gateway client
        client = get_imf_openai_client()
    catalog = [{"dataset_id": item["id"], "title": item["title"], "rows": item["rows"]} for item in handoff["datasets"]]
    messages = [
        {"role": "system", "content": system_prompt()},
        {"role": "system", "content": f"Hand-off {handoff['id']} datasets: {json.dumps(catalog)}"},
    ]
    messages.extend({"role": item["role"], "content": item["content"]} for item in history)
    tool_path: list[str] = []
    changed: list[str] = []
    calls = 0
    while True:
        response = client.chat.completions.create(
            model=model, messages=messages, tools=ANALYSIS_TOOLS, tool_choice="auto", parallel_tool_calls=False,
        )
        if not response.choices:
            raise RuntimeError("The IMF AI gateway returned no response choices.")
        assistant = _message_dict(response.choices[0].message)
        messages.append(assistant)
        tool_calls = assistant.get("tool_calls", [])
        if not tool_calls:
            return {"answer": assistant.get("content") or "I couldn't complete the analysis.",
                    "path": tool_path, "outputs": changed}
        if calls + len(tool_calls) > MAX_TOOL_CALLS:
            raise RuntimeError(f"The analysis assistant reached its maximum of {MAX_TOOL_CALLS} steps.")
        for call in tool_calls:
            calls += 1
            function = call.get("function", {})
            name = str(function.get("name", ""))
            if on_tool_call:
                on_tool_call(name)
            try:
                result = analysis_tool_result(name, json.loads(function.get("arguments") or "{}"), handoff,
                                              persist=persist)
                tool_path.append(f"{name}: completed")
                for item in result.get("outputs", []) if isinstance(result, dict) else []:
                    if item.get("output") and item["output"] not in changed:
                        changed.append(item["output"])
            except Exception as exc:
                result = {"error": str(exc)}
                tool_path.append(f"{name}: {exc}")
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""),
                             "content": json.dumps(result, default=str)})
