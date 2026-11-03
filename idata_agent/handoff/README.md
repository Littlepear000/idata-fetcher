# Handoff: the execution side

This folder is **not part of the package**. Nothing imports it. It documents what the
tool-calling harness (the colleague's work) has to provide so that the tools, the QuerySpec and
the skill text in this repository plug in without surprises, and it keeps two reference
implementations that can be merged into that harness or discarded.

## What the harness owns

1. **The model loop.** Send the skill text (`skills/imf-idata-python/SKILL.md`) as the system
   prompt and the tool schemas (`idata_agent.tools.schemas.TOOLS`, or `to_openai_tools()` for the
   IMF gateway / Azure OpenAI) with every request. Receive the model's tool calls, run them,
   return the results, repeat until the model answers in text.

2. **Dispatching a tool call.** Map the tool name to a function with
   `idata_agent.tools.implementation(name)` and call it with the arguments as keyword
   arguments. Wrap the outcome in one envelope the model always sees:

   ```python
   {"ok": True,  "data": <dict>}
   {"ok": False, "error": {"type": "invalid_call" | "environment_error" | "precondition_failed" | <ExceptionName>, "message": str}}
   ```

   `IDataToolError` → `invalid_call` (the model can fix the arguments and retry),
   `IDataEnvironmentError` → `environment_error` (retrying will not help), anything else →
   the exception's class name. Never let an exception propagate into the loop.

3. **`idata_fetch`.** Not implemented in this package. Contract:
   - Input: a QuerySpec dict (`idata_agent.spec.coerce_spec` turns it into an object).
   - Refuse unless `spec.missing_for_execution()` returns an empty list. Return
     `{"ok": False, "error": {"type": "precondition_failed", "message": "; ".join(problems)}}`
     otherwise. This is the code-level guard behind "confirm before execute".
   - Run the Python query only: `idata_agent.tools.resolve.download_frame(spec)` returns the
     DataFrame (and reuses the one `idata_preview` already downloaded).
   - Attach `SCALE` and `UNIT` (`idata_agent.tools.resolve.scale_and_unit(db, key)`), save to
     `spec.output_dir` or the user's Downloads as `spec.default_filename()`, in
     `spec.file_format` (csv / xlsx / dta), plus a sidecar `<file>.spec.json`. Column
     conventions are in `skills/imf-idata-python/references/output-formats.md`.
   - Return `{"path", "sidecar", "rows", "columns", "scale", "unit", "preview", "warnings", "spec"}`
     with `spec.stage == "executed"`.
   - Run it in a child process started directly with the IMF-managed interpreter
     (`C:\ProgramData\Python3\python.exe`, no shell: IMF Windows has no bash), so a blocking
     browser sign-in cannot freeze the UI.

4. **`ask_user`.** Never executed. Intercept it, render the question and options in the UI,
   and feed the user's answer back to the model as the tool result.

5. **Stage changes.** Only the user's confirmation sets `spec.stage = "confirmed"`. The model
   may set `draft`, `resolving`, `resolved`; the harness owns the transition to `confirmed`.

6. **Logging.** Record every tool call and result per session (the "retrieval path" shown to
   the user) and append confirmed indicator picks as `{"db", "dimension", "phrase", "code"}` to
   `idata_agent/knowledge/lookup_review.jsonl` for the team to review into the lookup table.

## Reference implementations in this folder

| File | What it is |
|---|---|
| `dispatcher_reference.py` | A `call_tool(name, args)` with the envelope above and the fetch precondition. Written before the ownership split; imports paths that no longer exist, so treat it as a sketch. |
| `executor_reference.py` | A full `idata_fetch`: scale/unit, csv/xlsx/dta saving with Stata-safe column names, sidecar, and `fetch_in_subprocess`. Same caveat. |

Both were tested against `idata_agent/evals/mock_idata.py` before the split and can be
revived by fixing the imports.
