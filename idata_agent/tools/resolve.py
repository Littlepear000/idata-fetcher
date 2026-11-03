"""
Resolve helpers: country groups, series metadata, and a cheap existence check.

    expand_group(name)        -> idata_expand_group
    get_metadata(db, key)     -> idata_get_metadata
    preview(spec)             -> idata_preview

`preview` downloads the frame for the spec's key and time range and returns the first rows
plus the total row count. iData cannot return "just a few rows", so the frame is kept in a
small in-process cache and reused by the executor; preview + fetch costs one download.
"""

from __future__ import annotations

from typing import Any

from ..spec import QuerySpec, coerce_spec
from . import _idata

PREVIEW_ROWS = 5

# (db, key, start, end, layout) -> DataFrame, shared with executor.fetch()
_frame_cache: dict[tuple, Any] = {}


def frame_cache_key(spec: QuerySpec) -> tuple:
    return (spec.database, spec.key, spec.start, spec.end, spec.layout)


def download_frame(spec: QuerySpec, use_cache: bool = True):
    """Run get_idata_data for the spec. Cached per (db, key, start, end, layout)."""
    ck = frame_cache_key(spec)
    if use_cache and ck in _frame_cache:
        return _frame_cache[ck]
    utils = _idata.idata_utilities()
    df = utils.get_idata_data(
        spec.database,
        key=spec.key,
        start=spec.start,
        end=spec.end,
        longformat=(spec.layout == "long"),
    )
    _frame_cache[ck] = df
    return df


# ---------------------------------------------------------------------------------------
# idata_expand_group
# ---------------------------------------------------------------------------------------


def expand_group(query: str) -> dict[str, Any]:
    """Expand a WEO country-group name or code into ISO3 codes using the RES WEO reference tables.

    Caveat carried over from the previous implementation: the column-name detection below was
    written without access to real `get_weo_country_groups()` / `get_weo_country_info()` output.
    Verify it the first time this runs on an IMF-networked machine.
    """
    if not query or not query.strip():
        raise _idata.IDataToolError("'query' is required: a group name or code such as 'advanced economies' or 'G007'.")
    pkg = _idata.imf_datatools()
    groups = pkg.get_weo_country_groups()

    desc_col = next(
        (c for c in groups.columns if str(c).lower() in ("name", "description", "groupname", "group_name")),
        groups.columns[0] if len(groups.columns) else None,
    )
    if desc_col is None:
        raise _idata.IDataToolError("could not find a group-name column in get_weo_country_groups() output")

    q = query.strip()
    if q.upper() in {str(c).upper() for c in groups.index}:
        matches = groups[groups.index.astype(str).str.upper() == q.upper()]
    else:
        matches = groups[groups[desc_col].astype(str).str.lower().str.contains(q.lower(), na=False)]

    if len(matches) == 0:
        return {"query": query, "matched": False, "candidates": [], "iso3": []}
    if len(matches) > 1:
        return {
            "query": query,
            "matched": False,
            "ambiguous": True,
            "candidates": [{"code": str(c), "name": str(r[desc_col])} for c, r in matches.iterrows()],
            "iso3": [],
        }

    group_code = str(matches.index[0])
    group_name = str(matches.iloc[0][desc_col])
    info = pkg.get_weo_country_info()
    if group_code not in info.columns:
        raise _idata.IDataToolError(
            f"group {group_code} ({group_name}) has no matching column in get_weo_country_info(); "
            "verify the two reference tables' schemas manually"
        )
    iso_col = next(
        (c for c in info.columns if str(c).lower() in ("iso3", "isocode", "code", "countrycode", "country")),
        None,
    )
    members = info[info[group_code] == 1]
    codes = members[iso_col].astype(str).tolist() if iso_col else members.index.astype(str).tolist()
    return {
        "query": query,
        "matched": True,
        "group_code": group_code,
        "group_name": group_name,
        "iso3": codes,
        "segment": "+".join(codes),
        "count": len(codes),
    }


# ---------------------------------------------------------------------------------------
# idata_get_metadata
# ---------------------------------------------------------------------------------------


def get_metadata(db: str, key: str, max_rows: int = 50) -> dict[str, Any]:
    if not db or not key:
        raise _idata.IDataToolError("'db' and 'key' are required.")
    utils = _idata.idata_utilities()
    df = utils.get_idata_metadata(db, key)
    if df is None:
        return {"db": db, "key": key, "columns": [], "rows": [], "total_rows": 0, "returned_rows": 0, "truncated": False}
    out = _idata.frame_to_records(df, max_rows=max_rows)
    out.update({"db": db, "key": key})
    return out


def scale_and_unit(db: str, key: str) -> tuple[int | None, str]:
    """Best-effort (scale, unit_label) for the first series of the key. Never raises."""
    unit_labels = {
        "XDC": "National currency",
        "USD": "US dollars",
        "PCT": "Percent",
        "PC_GDP": "Percent of GDP",
        "PCT_GDP": "Percent of GDP",
        "IX": "Index",
    }
    try:
        rep_key = ".".join(part.split("+")[0] for part in key.split("."))
        utils = _idata.idata_utilities()
        meta = utils.get_idata_metadata(db, rep_key)
        if meta is None or len(meta) == 0:
            return None, ""
        row = meta.iloc[0]
        scale = None
        for col in ("scale", "SCALE"):
            if col in row.index and row[col] is not None and str(row[col]) not in ("", "nan"):
                scale = int(float(row[col]))
                break
        unit_raw = None
        for col in ("unit", "UNIT", "units", "UNITS", "UNIT_MEASURE", "unit_measure"):
            if col in row.index and row[col] is not None and str(row[col]) not in ("", "nan"):
                unit_raw = str(row[col])
                break
        return scale, (unit_labels.get(unit_raw, unit_raw) if unit_raw else "")
    except Exception:
        return None, ""


# ---------------------------------------------------------------------------------------
# idata_preview
# ---------------------------------------------------------------------------------------


def preview(spec: QuerySpec | dict | str, rows: int = PREVIEW_ROWS) -> dict[str, Any]:
    """First rows + total count for the spec's query. Confirms data exists before the user confirms."""
    spec = coerce_spec(spec)
    problems = [p for p in spec.validate() if "stage" not in p]
    if problems:
        raise _idata.IDataToolError("spec is not ready for preview: " + "; ".join(problems))
    df = download_frame(spec)
    out = _idata.frame_to_records(df, max_rows=rows)
    out.update({"db": spec.database, "key": spec.key, "start": spec.start, "end": spec.end, "layout": spec.layout})
    if out["total_rows"] == 0:
        out["note"] = (
            "Zero rows. Do not conclude that no data exists. Most likely an invalid code in the "
            "key (re-check with idata_search_values) or, for internal databases, a missing or "
            "expired browser sign-in (about one hour validity)."
        )
    return out
