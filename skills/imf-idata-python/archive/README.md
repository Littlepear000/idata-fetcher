# Archived: custom LLM-API harness

These three files are an earlier design: a custom JSON-schema tool-calling harness (Anthropic
and OpenAI/Azure OpenAI/IMF-gateway variants) that let a model call iData through function
calling, with a Python dispatcher executing those calls against `imf_datatools` directly.

They're superseded by the primary approach now used in this skill: a `SKILL.md` plus
`scripts/fetch_idata.py`, invoked via the host agent's own Bash tool (Claude Code, GitHub
Copilot CLI, or any other Agent-Skills-compatible host). That approach needs no custom model
client, no gateway auth code, and — since it never imports `openai`/`anthropic` — never hits
the `aiohttp`/`openai` version-conflict bug that blocked the custom-harness path on an IMF
Windows machine.

**Files here:**
- `tool_schemas.py` — 5 iData tools as Anthropic-format JSON schemas (portable to OpenAI's
  function-calling format with a small wrapper).
- `dispatcher.py` — executes a `(tool_name, arguments)` call against `imf_datatools`,
  serializing pandas DataFrames to JSON. Tested with mocked `imf_datatools`; never run against
  the real package (no IMF network access from the dev environment this was built in).
- `test_harness.py` — a CLI agent loop wiring a real Anthropic/OpenAI/Azure OpenAI/IMF-gateway
  client to those tools, for watching whether a model follows the skill's rules (discover
  before guessing, ask when ambiguous).

**When to revive this:** only if it turns out IMF does *not* provision Claude Code, GitHub
Copilot CLI, or another Agent-Skills-compatible host — i.e. if the only way to reach an LLM at
all is a custom API client. If that's the case, this stack already solves the auth/tool-calling
problem; the newer `fetch_idata.py` script can likely still be reused as the thing `dispatcher.py`
shells out to or reimplements, since its metadata (scale/unit) logic is architecture-independent.
