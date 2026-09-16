"""
Layer 4 test harness: does a real model actually follow the SKILL.md rules (discover before
querying, ask when a concept is ambiguous, etc.) when given the 5 iData tools?

This is intentionally independent of whatever the final production surface turns out to be
(Anthropic API, Azure OpenAI, Copilot Studio, ...) — it's a minimal CLI loop you can run today
with whichever LLM API key you already have, to sanity-check the *skill design*, not the final
integration.

Usage:
    python test_harness.py "I want fiscal deficit data for US from 2020 to 2026" \\
        --provider anthropic --model claude-sonnet-5 --mock

    python test_harness.py "CPI for Japan and the US since 2015" \\
        --provider openai --model gpt-4o --mock

Flags:
    --provider {anthropic,openai}   which SDK/API to call (both need the matching SDK
                                     installed: `pip install anthropic` or `pip install openai`,
                                     and the matching API key in the environment:
                                     ANTHROPIC_API_KEY or OPENAI_API_KEY).
    --model MODEL                   required — model name (Anthropic) or model/deployment name
                                     (OpenAI/Azure OpenAI).
    --mock                          use a fake in-memory imf_datatools instead of the real
                                     package, so this runs without IMF network access. This is
                                     the default, and the ONLY mode this file can be dry-run
                                     tested in from outside the IMF network.
    --real                          use the real imf_datatools package (must be installed and
                                     running with iData network access — see
                                     references/api_reference.md#installation).
    --include-reference             also concatenate references/api_reference.md into the
                                     system prompt (off by default, matching SKILL.md's
                                     progressive-disclosure design intent).
    --max-turns N                   safety cap on model<->tool round trips (default 8).

What to look for in the trace this prints:
    - Does the model call idata_get_databases / idata_get_dimensions / idata_get_dimension_values
      BEFORE calling idata_get_data, rather than guessing a db/key from training knowledge?
    - When a concept resolves to multiple plausible indicators (the --mock fiscal-deficit
      scenario deliberately returns two candidates), does the model ask the user to
      disambiguate instead of silently picking one?
    - Does it handle a `{"ok": false, ...}` tool result sensibly (e.g. re-checking a code)
      instead of fabricating data?
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from dispatcher import call_tool  # noqa: E402
from tool_schemas import IDATA_TOOLS  # noqa: E402

SKILL_DIR = Path(__file__).parent


# ---------------------------------------------------------------------------------------
# Mock imf_datatools — deliberately includes an ambiguous "fiscal deficit" scenario so you
# can observe whether the model asks for disambiguation instead of guessing.
# ---------------------------------------------------------------------------------------


def install_mock_idata_utilities() -> None:
    import numpy as np
    import pandas as pd

    fake_pkg = types.ModuleType("imf_datatools")
    fake_mod = types.ModuleType("imf_datatools.idata_utilities")

    def get_databases(keyword=None, searchmode="or", refresh=False):
        rows = {
            "IMF.RES.WEO:WEO_LIVE": "World Economic Outlook (WEO) live database",
            "IMF.STA:CPI": "Consumer Price Index",
            "IMF.FAD:GFS": "Government Finance Statistics, fiscal balance and government debt",
        }
        keywords = [keyword] if isinstance(keyword, str) else (keyword or [])
        if keywords:
            combine = all if searchmode == "and" else any
            rows = {
                db: desc
                for db, desc in rows.items()
                if combine(kw.lower() in desc.lower() or kw.lower() in db.lower() for kw in keywords)
            }
        df = pd.DataFrame({"Description": list(rows.values())}, index=list(rows.keys()))
        df.index.name = "db"
        return df

    def get_dimensions(db, keyword=None, searchmode="or", refresh=False):
        return pd.DataFrame(
            {"Description": ["Country", "Indicator", "Frequency"], "Order": [0, 1, 2]},
            index=["COUNTRY", "INDICATOR", "FREQUENCY"],
        )

    def get_dimension_values(db, dimension, keyword=None, searchmode="or", refresh=False):
        if dimension == "COUNTRY":
            return pd.DataFrame(
                {"Name": ["United States", "Japan", "Australia"]}, index=["USA", "JPN", "AUS"]
            )
        if dimension == "INDICATOR":
            candidates = {
                "GGXCNL_NGDP": "General government net lending/borrowing (overall fiscal deficit/surplus), percent of GDP",
                "GGXONLB_NGDP": "General government primary net lending/borrowing (primary fiscal deficit/surplus, excludes interest), percent of GDP",
                "NGDP_RPCH": "Gross domestic product, constant prices, percent change",
                "PCPI": "Consumer price index, period average",
            }
            keywords = [keyword] if isinstance(keyword, str) else (keyword or [])
            if keywords:
                combine = all if searchmode == "and" else any
                candidates = {
                    k: v
                    for k, v in candidates.items()
                    if combine(kw.lower() in v.lower() or kw.lower() in k.lower() for kw in keywords)
                }
            return pd.DataFrame({"Name": list(candidates.values())}, index=list(candidates.keys()))
        return pd.DataFrame({"Name": ["Annual"]}, index=["A"])

    def get_idata_data(db, key, start=None, end=None, longformat=False, panel=None):
        years = list(range(2020, 2027))
        idx = pd.to_datetime([f"{y}-01-01" for y in years])
        col = key
        values = np.round(np.linspace(-8.0, -3.5, num=len(years)), 2)
        df = pd.DataFrame({col: values}, index=idx)
        df.index.name = "dates"
        return df

    def get_idata_metadata(db, key):
        return pd.DataFrame({"unit": ["Percent of GDP"], "scale": [0]})

    fake_mod.get_databases = get_databases
    fake_mod.get_dimensions = get_dimensions
    fake_mod.get_dimension_values = get_dimension_values
    fake_mod.get_idata_data = get_idata_data
    fake_mod.get_idata_metadata = get_idata_metadata
    fake_pkg.idata_utilities = fake_mod
    sys.modules["imf_datatools"] = fake_pkg
    sys.modules["imf_datatools.idata_utilities"] = fake_mod


# ---------------------------------------------------------------------------------------
# Provider-agnostic loop. Each provider adapter turns a raw SDK response into a ModelTurn,
# and knows how to append that turn + the resulting tool results back onto the message list
# in whatever shape its own API expects.
# ---------------------------------------------------------------------------------------


@dataclass
class ToolCallRequest:
    id: str
    name: str
    arguments: dict


@dataclass
class ModelTurn:
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    text: str | None = None


class AnthropicAdapter:
    def __init__(self):
        try:
            import anthropic
        except ImportError as exc:
            raise SystemExit("pip install anthropic  (and set ANTHROPIC_API_KEY)") from exc
        self.client = anthropic.Anthropic()

    @staticmethod
    def to_tools(tools: list[dict]) -> list[dict]:
        return tools  # tool_schemas.py is already in Anthropic's {name, description, input_schema} shape

    def call_model(self, model, system_prompt, messages, tools) -> ModelTurn:
        response = self.client.messages.create(
            model=model,
            max_tokens=1024,
            system=system_prompt,
            tools=self.to_tools(tools),
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        turn = ModelTurn()
        for block in response.content:
            if block.type == "text":
                turn.text = (turn.text or "") + block.text
            elif block.type == "tool_use":
                turn.tool_calls.append(ToolCallRequest(id=block.id, name=block.name, arguments=block.input))
        return turn

    @staticmethod
    def append_tool_results(messages, results: list[tuple[ToolCallRequest, dict]]) -> None:
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": tc.id, "content": json.dumps(result)}
                    for tc, result in results
                ],
            }
        )


class OpenAIAdapter:
    def __init__(self, azure: bool = False):
        try:
            import openai
        except ImportError as exc:
            raise SystemExit("pip install openai") from exc

        if azure:
            endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
            api_key = os.environ.get("AZURE_OPENAI_API_KEY")
            api_version = os.environ.get("AZURE_OPENAI_API_VERSION")
            missing = [
                name
                for name, val in [
                    ("AZURE_OPENAI_ENDPOINT", endpoint),
                    ("AZURE_OPENAI_API_KEY", api_key),
                    ("AZURE_OPENAI_API_VERSION", api_version),
                ]
                if not val
            ]
            if missing:
                raise SystemExit(
                    "Azure OpenAI requires these environment variables, missing: "
                    f"{', '.join(missing)}. Get the exact endpoint URL, key, and API version "
                    "from whoever provisioned your company's Azure OpenAI access — don't guess "
                    "them. --model must then be the Azure *deployment name* (set by your IT "
                    "team), not necessarily the model's public name."
                )
            self.client = openai.AzureOpenAI(
                azure_endpoint=endpoint, api_key=api_key, api_version=api_version
            )
        else:
            if not os.environ.get("OPENAI_API_KEY"):
                raise SystemExit("Set OPENAI_API_KEY (or pass --azure to use Azure OpenAI instead).")
            self.client = openai.OpenAI()

    @staticmethod
    def to_tools(tools: list[dict]) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            }
            for t in tools
        ]

    def call_model(self, model, system_prompt, messages, tools) -> ModelTurn:
        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
            tools=self.to_tools(tools),
        )
        message = response.choices[0].message
        messages.append(message)

        turn = ModelTurn(text=message.content)
        for tc in message.tool_calls or []:
            turn.tool_calls.append(
                ToolCallRequest(id=tc.id, name=tc.function.name, arguments=json.loads(tc.function.arguments))
            )
        return turn

    @staticmethod
    def append_tool_results(messages, results: list[tuple[ToolCallRequest, dict]]) -> None:
        for tc, result in results:
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)})


def build_adapter(provider: str, azure: bool = False):
    if provider == "anthropic":
        return AnthropicAdapter()
    if provider == "openai":
        return OpenAIAdapter(azure=azure)
    raise ValueError(f"unknown provider: {provider}")


def summarize_result(result: dict) -> str:
    if result.get("ok"):
        data = result["data"]
        if isinstance(data, dict) and "total_rows" in data:
            return f"ok, {data['total_rows']} row(s){' (truncated)' if data.get('truncated') else ''}"
        return "ok"
    return f"ERROR [{result['error']['type']}]: {result['error']['message']}"


def run_agent(
    provider: str, model: str, user_message: str, system_prompt: str, max_turns: int, azure: bool = False
) -> str:
    adapter = build_adapter(provider, azure=azure)
    if provider == "openai":
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}]
    else:
        messages = [{"role": "user", "content": user_message}]

    for turn_num in range(1, max_turns + 1):
        print(f"\n--- turn {turn_num} ---")
        turn = adapter.call_model(model, system_prompt, messages, IDATA_TOOLS)
        if turn.text:
            print(f"[assistant text] {turn.text}")
        if not turn.tool_calls:
            return turn.text or ""

        results = []
        for tc in turn.tool_calls:
            print(f"[tool call] {tc.name}({json.dumps(tc.arguments)})")
            result = call_tool(tc.name, tc.arguments)
            print(f"  -> {summarize_result(result)}")
            results.append((tc, result))
        adapter.append_tool_results(messages, results)

    return "[max turns reached without a final answer]"


def build_system_prompt(include_reference: bool) -> str:
    prompt = (SKILL_DIR / "SKILL.md").read_text()
    if include_reference:
        prompt += "\n\n" + (SKILL_DIR / "references" / "api_reference.md").read_text()
    return prompt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("message", help="user request, e.g. 'fiscal deficit data for US from 2020 to 2026'")
    parser.add_argument("--provider", choices=["anthropic", "openai"], default="anthropic")
    parser.add_argument(
        "--azure",
        action="store_true",
        help=(
            "with --provider openai, use Azure OpenAI instead of the plain OpenAI platform API. "
            "Requires AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_API_VERSION env "
            "vars, and --model must be the Azure *deployment name* set by your IT team."
        ),
    )
    parser.add_argument(
        "--model",
        required=True,
        help=(
            "Anthropic: model name (e.g. claude-sonnet-5). Plain OpenAI: model name (e.g. "
            "gpt-4o). Azure OpenAI (--azure): the deployment name, NOT necessarily the model's "
            "public name — confirm the exact string with whoever provisioned access."
        ),
    )
    parser.add_argument("--include-reference", action="store_true")
    parser.add_argument("--max-turns", type=int, default=8)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--mock", action="store_true", default=True, help="use fake iData data (default)")
    mode.add_argument("--real", action="store_true", help="use the real imf_datatools package")
    args = parser.parse_args()

    if args.real:
        print("Using REAL imf_datatools — requires IMF network access and the package installed.")
    else:
        print("Using MOCK imf_datatools (fake data) — no IMF network required.")
        install_mock_idata_utilities()

    system_prompt = build_system_prompt(args.include_reference)
    final_text = run_agent(
        args.provider, args.model, args.message, system_prompt, args.max_turns, azure=args.azure
    )
    print(f"\n=== final answer ===\n{final_text}")


if __name__ == "__main__":
    main()
