# idata_agent

The Python side of the iData query agent: the QuerySpec contract, the tools the model may call,
deterministic code generation, and the team-maintained knowledge files. The model-facing rules
live next door in `skills/imf-idata-python/SKILL.md`.

## How the two top-level folders relate

```
skills/imf-idata-python/      what the MODEL reads
  SKILL.md                    the rules: stages, when to ask, how to resolve, what to show
  references/                 SDK signatures, output columns, runtime policy

idata_agent/                  what the PROGRAM runs
  spec.py                     QuerySpec: the query sheet both sides share
  tools/                      the functions behind the tool names used in SKILL.md
  codegen/                    render a confirmed spec into Python / Stata / R
  knowledge/                  lookup table, abbreviation table (data, versioned)
  cli.py                      the tools as shell commands (JSON out)
  evals/, tests/              mock SDK, seed cases, offline tests
  handoff/                    contract + reference code for the harness side (not imported)
```

They are parallel because they are two different kinds of artefact with two different readers.
The skill folder is text the language model is given (as the system prompt of the custom
harness, or loaded by a host such as Claude Code that understands the Agent Skills layout).
This folder is code. They reference each other by name: SKILL.md names the tools and the CLI
commands; `tools/schemas.py` repeats each tool's key rule in its description. Neither imports
the other.

## Ownership

| Area | Owner | Where |
|---|---|---|
| Architecture, QuerySpec, tool design, skill text, knowledge files, codegen | this repository (architecture side) | `spec.py`, `tools/`, `codegen/`, `knowledge/`, `skills/` |
| Model loop, tool-call dispatch, `idata_fetch`, `ask_user` UI event, logging, front end | tool-calling harness (colleague) | separate code base; contract in `handoff/README.md` |

Merge point: the harness calls `idata_agent.tools.implementation(name)(**args)` for every tool
that has an implementation here, enforces `QuerySpec.missing_for_execution()` before fetching,
and sends `skills/imf-idata-python/SKILL.md` as the system prompt.

## Try it

```bash
python -m unittest discover -s idata_agent/tests -t .          # offline, mock SDK
python -m idata_agent.cli find-databases --phrase "weo live"    # real iData, IMF machine
python -m idata_agent.cli search-values --db IMF.RES.WEO:WEO_LIVE --dimension INDICATOR --phrase "real GDP growth"
```

Defaults: long layout, CSV, the user's Downloads folder, Python shown first. The database is
never guessed: if the user did not name one, the agent asks; what they say ("WEO", "cpi") is
fuzzy-matched against the catalogue and confirmed with them.
