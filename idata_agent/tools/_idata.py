"""
Lazy access to `imf_datatools` and small DataFrame helpers shared by the tools.

The import is deferred so the package imports (and the unit tests run) on machines without
the IMF SDK. The first real call on such a machine raises IDataEnvironmentError with an
actionable message instead of a bare ImportError.
"""

from __future__ import annotations

from typing import Any


class IDataToolError(Exception):
    """The tool call itself is invalid (bad or missing arguments). The caller can fix and retry."""


class IDataEnvironmentError(Exception):
    """This machine cannot run the tool at all (SDK missing, no network). Retrying won't help."""


def idata_utilities():
    try:
        from imf_datatools import idata_utilities as mod
    except ImportError as exc:  # pragma: no cover - depends on the host machine
        raise IDataEnvironmentError(
            "imf_datatools is not installed or not importable. Run "
            "`python skills/imf-idata-python/scripts/check_environment.py --profile data` and, "
            "on an IMF Windows machine, install with "
            r"`python \\ecnswn12p\ems_shared\pub\datatools\installer.py`."
        ) from exc
    # Some iData databases are internal and require this flag. Harmless for public ones.
    mod.PRIVATE = True
    return mod


def imf_datatools():
    try:
        import imf_datatools as pkg
    except ImportError as exc:  # pragma: no cover
        raise IDataEnvironmentError("imf_datatools is not installed or not importable.") from exc
    return pkg


def normalize_keyword(keyword: Any) -> Any:
    """`imf_datatools` accepts a str or an iterable of str for `keyword`."""
    if keyword is None:
        return None
    if isinstance(keyword, (list, tuple)):
        return [str(k) for k in keyword]
    return str(keyword)


def jsonable(value: Any) -> Any:
    """Make one cell JSON-serialisable: NaN/NaT -> None, dates -> ISO, numpy scalars -> native."""
    if value is None:
        return None
    try:
        import pandas as pd

        if pd.isna(value):
            return None
    except (TypeError, ValueError, ImportError):
        pass
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        return jsonable(value.item())
    return value


def frame_to_records(df, max_rows: int | None = None) -> dict[str, Any]:
    """DataFrame -> {"columns", "rows", "total_rows", "returned_rows", "truncated"}.

    The index is reset into a column first so index values (usually `dates` or the code)
    survive serialisation.
    """
    total = len(df)
    out = df.reset_index()
    columns = [str(c) for c in out.columns]
    truncated = max_rows is not None and total > max_rows
    if truncated:
        out = out.head(max_rows)
    rows = [
        {col: jsonable(val) for col, val in zip(columns, row)}
        for row in out.itertuples(index=False, name=None)
    ]
    return {
        "columns": columns,
        "rows": rows,
        "total_rows": total,
        "returned_rows": len(rows),
        "truncated": truncated,
    }
