"""
Dispatcher: execute one tool call by name and return a JSON-safe envelope.

    call_tool("idata_search_values", {"db": ..., "dimension": ..., "phrase": ...})
    -> {"ok": True, "data": {...}}
    -> {"ok": False, "error": {"type": "...", "message": "..."}}

Never raises for expected failures (bad arguments, unknown tool, SDK missing, upstream errors):
an agent loop should react to the message, not crash.

Stage preconditions live here, not only in the prompt:
- idata_preview and render_code need a spec that validates (stage may be anything).
- idata_fetch additionally needs stage == "confirmed". A call that skips the user's confirmation
  comes back as {"ok": False, "error": {"type": "precondition_failed", ...}} listing what is missing.
- ask_user is not executed here; the core turns it into a UI event. Calling it through the
  dispatcher returns a clear error so a misconfigured harness is noticed immediately.
"""

from __future__ import annotations

import traceback
from typing import Any, Callable

from ..codegen.render import render
from ..spec import coerce_spec
from . import _idata
from .discovery import find_databases, get_dimensions, list_values, search_values
from .executor import fetch
from .resolve import expand_group, get_metadata, preview


def _require(args: dict, *names: str) -> None:
    missing = [n for n in names if args.get(n) in (None, "", [])]
    if missing:
        raise _idata.IDataToolError(f"missing required argument(s): {', '.join(missing)}")


def _h_find_databases(a: dict) -> dict:
    return find_databases(a.get("keyword"), a.get("searchmode", "or"), a.get("refresh", False))


def _h_get_dimensions(a: dict) -> dict:
    _require(a, "db")
    return get_dimensions(a["db"], a.get("refresh", False))


def _h_search_values(a: dict) -> dict:
    _require(a, "db", "dimension", "phrase")
    return search_values(a["db"], a["dimension"], a["phrase"], hints=a.get("hints"), limit=int(a.get("limit", 15)), refresh=a.get("refresh", False))


def _h_list_values(a: dict) -> dict:
    _require(a, "db", "dimension")
    return list_values(a["db"], a["dimension"], a.get("refresh", False))


def _h_expand_group(a: dict) -> dict:
    _require(a, "query")
    return expand_group(a["query"])


def _h_get_metadata(a: dict) -> dict:
    _require(a, "db", "key")
    return get_metadata(a["db"], a["key"], int(a.get("max_rows", 50)))


def _h_preview(a: dict) -> dict:
    _require(a, "spec")
    return preview(a["spec"], int(a.get("rows", 5)))


def _h_render_code(a: dict) -> dict:
    _require(a, "spec")
    return render(a["spec"])


def _h_fetch(a: dict) -> dict:
    _require(a, "spec")
    spec = coerce_spec(a["spec"])
    problems = spec.missing_for_execution()
    if problems:
        raise PreconditionFailed("idata_fetch refused: " + "; ".join(problems))
    return fetch(spec)


def _h_ask_user(a: dict) -> dict:
    raise _idata.IDataToolError(
        "ask_user is a UI event, not an executable tool. The agent core must intercept it and "
        "render the question to the user; it should never reach the dispatcher."
    )


class PreconditionFailed(Exception):
    pass


HANDLERS: dict[str, Callable[[dict], dict]] = {
    "idata_find_databases": _h_find_databases,
    "idata_get_dimensions": _h_get_dimensions,
    "idata_search_values": _h_search_values,
    "idata_list_values": _h_list_values,
    "idata_expand_group": _h_expand_group,
    "idata_get_metadata": _h_get_metadata,
    "idata_preview": _h_preview,
    "render_code": _h_render_code,
    "idata_fetch": _h_fetch,
    "ask_user": _h_ask_user,
}


def call_tool(name: str, arguments: dict | None = None, debug: bool = False) -> dict[str, Any]:
    arguments = dict(arguments or {})
    handler = HANDLERS.get(name)
    if handler is None:
        return {"ok": False, "error": {"type": "unknown_tool", "message": f"no tool named {name!r}"}}
    try:
        return {"ok": True, "data": handler(arguments)}
    except PreconditionFailed as exc:
        return {"ok": False, "error": {"type": "precondition_failed", "message": str(exc)}}
    except _idata.IDataToolError as exc:
        return {"ok": False, "error": {"type": "invalid_call", "message": str(exc)}}
    except _idata.IDataEnvironmentError as exc:
        return {"ok": False, "error": {"type": "environment_error", "message": str(exc)}}
    except Exception as exc:  # upstream SDK / network / permissions
        err = {"type": type(exc).__name__, "message": str(exc)}
        if debug:
            err["traceback"] = traceback.format_exc()
        return {"ok": False, "error": err}
