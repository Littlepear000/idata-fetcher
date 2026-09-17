"""
Dispatcher for the iData Python download skill.

Executes tool calls defined in `tool_schemas.py` against the real `imf_datatools` package and
serializes results into JSON-safe structures a chat model can consume as a tool result.

This module is deliberately vendor-neutral: `call_tool()` takes a plain (name: str,
arguments: dict) pair and returns a plain dict. Whatever adapter eventually sits on top for
Anthropic / OpenAI / Copilot is responsible for pulling `name`/`arguments` out of that
provider's tool_use / function_call envelope, calling `call_tool()`, and wrapping the
returned dict back into that provider's tool_result format. None of that provider-specific
shape belongs in here.

Requires: this module must actually run somewhere with `imf_datatools` installed and iData
network access (an IMF-networked machine — see ../references/api_reference.md#installation).
The import is deferred into each handler so this file stays importable/testable elsewhere;
the error only surfaces the first time a tool is actually invoked, not at import time.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd

MAX_INLINE_ROWS = 500  # cap rows returned inline to the model; beyond this we truncate + flag it


class IDataToolError(Exception):
    """Raised when the tool call itself is invalid (bad/missing arguments) — the caller's/
    model's mistake, worth surfacing so it can retry with corrected arguments."""


class IDataEnvironmentError(Exception):
    """Raised when this dispatcher cannot run at all in the current environment (e.g.
    imf_datatools not installed) — not something retrying with different arguments fixes."""


def _import_idata_utilities():
    try:
        from imf_datatools import idata_utilities
    except ImportError as exc:
        raise IDataEnvironmentError(
            "imf_datatools is not installed or not importable in this environment. This tool "
            "must run on a machine with the package installed and iData network access (see "
            "references/api_reference.md#installation)."
        ) from exc
    return idata_utilities


def _normalize_keyword(keyword: Any) -> Any:
    """The underlying functions accept a single str or an iterable of str for `keyword`."""
    if keyword is None:
        return None
    if isinstance(keyword, (list, tuple)):
        return list(keyword)
    return keyword


def _jsonable(value: Any) -> Any:
    """Make one cell value JSON-serializable: NaN/NaT -> None, dates -> ISO strings,
    numpy scalars -> native Python types."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass  # pd.isna can choke on non-scalar values; not expected for a DataFrame cell
    if hasattr(value, "isoformat"):  # datetime.date/datetime, pandas.Timestamp
        return value.isoformat()
    if hasattr(value, "item"):  # numpy scalar (int64, float64, bool_, ...)
        return _jsonable(value.item())
    return value


def _dataframe_to_result(df: "pd.DataFrame", max_rows: int = MAX_INLINE_ROWS) -> dict:
    """Convert a pandas.DataFrame to a JSON-safe dict, with a row-count guard.

    Always resets the index into a column first so index values (usually 'dates') survive
    serialization. Reports the true total row count even when the inline rows are truncated,
    so the caller/model knows data was cut and can narrow the query (e.g. add start/end)
    instead of assuming what it sees is everything.
    """
    total_rows = len(df)
    df_reset = df.reset_index()
    columns = [str(c) for c in df_reset.columns]

    truncated = total_rows > max_rows
    df_out = df_reset.head(max_rows) if truncated else df_reset

    rows = [
        {col: _jsonable(val) for col, val in zip(columns, row)}
        for row in df_out.itertuples(index=False, name=None)
    ]

    return {
        "columns": columns,
        "rows": rows,
        "total_rows": total_rows,
        "returned_rows": len(rows),
        "truncated": truncated,
    }


def _df_or_none_to_result(df, max_rows: int = MAX_INLINE_ROWS):
    if df is None:
        return None
    return _dataframe_to_result(df, max_rows=max_rows)


# ---------------------------------------------------------------------------------------
# Per-tool handlers. Each takes the tool's `arguments` dict (as the model supplied it,
# matching tool_schemas.py's input_schema) and returns a JSON-safe dict on success, or
# raises IDataToolError for a problem this layer can diagnose without calling imf_datatools.
# ---------------------------------------------------------------------------------------


def _handle_get_databases(args: dict) -> dict:
    idata_utilities = _import_idata_utilities()
    df = idata_utilities.get_databases(
        keyword=_normalize_keyword(args.get("keyword")),
        searchmode=args.get("searchmode", "or"),
        refresh=args.get("refresh", False),
    )
    return _dataframe_to_result(df)


def _handle_get_dimensions(args: dict) -> dict:
    if not args.get("db"):
        raise IDataToolError("'db' is required — call idata_get_databases first to find it.")
    idata_utilities = _import_idata_utilities()
    df = idata_utilities.get_dimensions(
        args["db"],
        keyword=_normalize_keyword(args.get("keyword")),
        searchmode=args.get("searchmode", "or"),
        refresh=args.get("refresh", False),
    )
    return _dataframe_to_result(df)


def _handle_get_dimension_values(args: dict) -> dict:
    missing = [k for k in ("db", "dimension") if not args.get(k)]
    if missing:
        raise IDataToolError(
            f"Missing required argument(s): {', '.join(missing)}. Call idata_get_dimensions "
            "first to get valid dimension mnemonics for this database."
        )
    idata_utilities = _import_idata_utilities()
    df = idata_utilities.get_dimension_values(
        args["db"],
        args["dimension"],
        keyword=_normalize_keyword(args.get("keyword")),
        searchmode=args.get("searchmode", "or"),
        refresh=args.get("refresh", False),
    )
    return _dataframe_to_result(df)


def _handle_get_data(args: dict) -> dict:
    missing = [k for k in ("db", "key") if not args.get(k)]
    if missing:
        raise IDataToolError(
            f"Missing required argument(s): {', '.join(missing)}. Resolve the database and "
            "build the query key using the discovery tools before calling idata_get_data."
        )
    if args.get("longformat") and args.get("panel"):
        raise IDataToolError(
            "'longformat' and 'panel' are mutually exclusive — set at most one of them."
        )

    idata_utilities = _import_idata_utilities()
    df = idata_utilities.get_idata_data(
        args["db"],
        key=args["key"],
        start=args.get("start"),
        end=args.get("end"),
        longformat=args.get("longformat", False),
        panel=args.get("panel"),
    )
    result = _dataframe_to_result(df)
    if result["total_rows"] == 0:
        result["note"] = (
            "Zero rows returned. Do not conclude 'no data exists' from this alone — the most "
            "likely causes are an invalid dimension code in `key` (re-check with "
            "idata_get_dimension_values) or, for internal/PRIVATE data, a missing or expired "
            "browser SSO session (~1 hour validity)."
        )
    return result


def _handle_get_metadata(args: dict) -> dict:
    missing = [k for k in ("db", "key") if not args.get(k)]
    if missing:
        raise IDataToolError(f"Missing required argument(s): {', '.join(missing)}.")
    idata_utilities = _import_idata_utilities()
    df = idata_utilities.get_idata_metadata(args["db"], args["key"])
    return _df_or_none_to_result(df)


_HANDLERS = {
    "idata_get_databases": _handle_get_databases,
    "idata_get_dimensions": _handle_get_dimensions,
    "idata_get_dimension_values": _handle_get_dimension_values,
    "idata_get_data": _handle_get_data,
    "idata_get_metadata": _handle_get_metadata,
}


def call_tool(name: str, arguments: dict | None = None) -> dict:
    """Execute one tool call by name and return a JSON-safe result envelope.

    Success:  {"ok": True, "data": <json-safe dict>}
    Failure:  {"ok": False, "error": {"type": str, "message": str}}

    Deliberately never raises for expected failure modes (bad/missing arguments, an unknown
    tool name, imf_datatools not installed, upstream/network errors) — those come back as
    {"ok": False, ...} so an agent loop can react (e.g. surface a permissions message to the
    user, per SKILL.md's troubleshooting rules) instead of the whole turn crashing.
    """
    arguments = arguments or {}
    handler = _HANDLERS.get(name)
    if handler is None:
        return {
            "ok": False,
            "error": {
                "type": "unknown_tool",
                "message": f"No handler registered for tool '{name}'.",
            },
        }

    try:
        data = handler(arguments)
        return {"ok": True, "data": data}
    except IDataToolError as exc:
        return {"ok": False, "error": {"type": "invalid_call", "message": str(exc)}}
    except IDataEnvironmentError as exc:
        return {"ok": False, "error": {"type": "environment_error", "message": str(exc)}}
    except Exception as exc:  # upstream imf_datatools / network / permissions errors
        return {"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}
