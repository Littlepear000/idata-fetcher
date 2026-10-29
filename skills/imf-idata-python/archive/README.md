# Archived files

Earlier designs kept for reference. Nothing here is imported by the current code.

| File | Status |
|---|---|
| `tool_schemas.py` | Promoted and extended into `idata_agent/tools/schemas.py` (nine tools, spec-based fetch, provider conversion helpers). |
| `dispatcher.py` | Promoted into `idata_agent/tools/dispatcher.py`, now with stage preconditions (`idata_fetch` refuses an unconfirmed spec). |
| `test_harness.py` | Its mock `imf_datatools` became `idata_agent/evals/mock_idata.py`. The provider loop (Anthropic / OpenAI / Azure / IMF gateway envelopes) is the starting point for the agent core's provider adapter, still to be written. |
| `fetch_idata.py` | The CLI script of the previous skill version. Its scale/unit logic, output validation and `--expand-group` moved into `idata_agent/tools/executor.py` and `idata_agent/tools/resolve.py`; the CLI is now `python -m idata_agent.cli`. |

Why the direction changed: the first version assumed the skill would run inside a host agent
(Claude Code, Copilot CLI) and shelled out to `fetch_idata.py`. The project is now a standalone
chat application with its own front end, and the IMF gateway was confirmed to generate tool
calls, so the custom tool-calling design came back on the critical path. The skill text
(`../SKILL.md`) is written to serve both: hosts run the tools through `idata_agent.cli`, the
harness calls `idata_agent.tools.dispatcher.call_tool` directly.
