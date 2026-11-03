"""
idata_agent — tool layer for the iData query agent.

Layout (see docs/architecture_simple_en.html):

    spec.py          QuerySpec: the structured "query sheet" the agent fills, confirms, executes
    tools/           the nine tools the model may call, plus the dispatcher and the codebook cache
    codegen/         deterministic rendering of a confirmed QuerySpec into Python / Stata / R
    knowledge/       team-maintained data files: lookup table, abbreviation table, cached lists
    cli.py           every tool as a subcommand, JSON in / JSON out (used by skill hosts and tests)
    evals/           mock imf_datatools package and seed test cases
    tests/           offline unit tests (run: python -m unittest discover idata_agent/tests)

Only `tools/` imports `imf_datatools`, and only lazily, so the rest of the package imports and
tests cleanly on a machine without the IMF SDK.
"""

__version__ = "0.4.0"
