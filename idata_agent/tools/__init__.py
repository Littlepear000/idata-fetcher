"""
The tool layer: the only code that imports `imf_datatools`.

    discovery.py   idata_find_databases, idata_list_databases, idata_get_dimensions,
                   idata_search_values, idata_list_values
    resolve.py     idata_expand_group, idata_get_metadata, idata_preview
    schemas.py     JSON schemas for every tool, in a provider-neutral shape
    cache.py       the local cache of the catalogue and of every dimension's value list (90 days)

Execution (`idata_fetch`) and the model <-> tool loop (dispatching a tool call to one of these
functions, enforcing the stage preconditions, turning `ask_user` into a UI event) are NOT in
this package. They belong to the tool-calling harness; see ../handoff/README.md.

`IMPLEMENTATIONS` maps each tool name to the plain function that implements it, so the harness
can wire its dispatcher without guessing. Every function takes keyword arguments matching the
tool's input_schema and returns a JSON-serialisable dict, or raises
`_idata.IDataToolError` (bad call) / `_idata.IDataEnvironmentError` (SDK missing).
"""

from __future__ import annotations

from typing import Callable

from . import discovery, resolve

IMPLEMENTATIONS: dict[str, Callable | None] = {
    "idata_find_databases": discovery.find_databases,
    "idata_list_databases": discovery.list_databases,
    "idata_get_dimensions": discovery.get_dimensions,
    "idata_search_values": discovery.search_values,
    "idata_list_values": discovery.list_values,
    "idata_expand_group": resolve.expand_group,
    "idata_get_metadata": resolve.get_metadata,
    "idata_preview": resolve.preview,
    "render_code": None,  # idata_agent.codegen.render.render (imported lazily to avoid a cycle)
    "idata_fetch": None,  # harness-owned; must enforce QuerySpec.missing_for_execution()
    "ask_user": None,  # harness-owned UI event
}


def implementation(name: str) -> Callable | None:
    if name == "render_code":
        from ..codegen.render import render

        return render
    return IMPLEMENTATIONS.get(name)
