"""
fetch_idata.py — pre-built utility for discovering and retrieving IMF iData series.

The agent calls this via Bash — never write a new script to explore or fetch iData data.

Modes (mutually exclusive, checked in this priority order):
    --expand-group NAME                                 expand a WEO country group into ISO3 codes
    --get-databases KEYWORD                             search database names/descriptions
    --db ID --get-dimensions                             list dimension names, in key order
    --db ID --get-dimension-values DIM [--keyword K]     list valid codes/labels for one dimension
    --db ID --key KEY --start S --end E
        [--format {wide,long}] [--excel] [--output PATH]   fetch and save data

Fetching always produces a file — defaults to wide-format CSV if --format/--excel are omitted.
Refreshable (multi-sheet, country-name-enriched) output is not implemented yet — only
wide and long are supported. See ../references/output-formats.md.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd
import imf_datatools
from imf_datatools import idata_utilities

# Some iData databases are private/restricted and require this flag. Safe to leave on
# for public databases as well.
idata_utilities.PRIVATE = True

SCALE_LABELS = {0: "Units", 3: "Thousands", 6: "Millions", 9: "Billions"}
_UNIT_LABELS = {
    "XDC": "National currency",
    "USD": "US dollars",
    "PCT": "Percent",
    "PC_GDP": "Percent of GDP",
    "PCT_GDP": "Percent of GDP",
    "IX": "Index",
}


def _fetch_data(db: str, key: str, start, end, use_long: bool):
    return idata_utilities.get_idata_data(
        db, key, start=start, end=end, longformat=use_long, debug=False
    )


def fetch_metadata(db: str, key: str):
    """Best-effort scale/unit lookup. Never fatal — returns (None, "") on failure."""
    try:
        rep_key = ".".join(part.split("+")[0] for part in key.split("."))
        meta = idata_utilities.get_idata_metadata(db, rep_key)
        if meta is None or len(meta) == 0:
            return None, ""
        row = meta.iloc[0]
        scale = None
        for col in ("scale", "SCALE"):
            if col in row.index and pd.notna(row[col]):
                scale = int(row[col])
                break
        unit_raw = None
        for col in ("unit", "UNIT", "units", "UNITS", "UNIT_MEASURE", "unit_measure"):
            if col in row.index and pd.notna(row[col]):
                unit_raw = str(row[col])
                break
        unit_label = _UNIT_LABELS.get(unit_raw, unit_raw) if unit_raw else ""
        return scale, unit_label
    except Exception as exc:
        print(f"Warning: metadata lookup failed ({exc}) — SCALE and UNIT will be empty.", file=sys.stderr)
        return None, ""


def validate_output_format(output_path: str, excel: bool) -> list[str]:
    ext = Path(output_path).suffix.lower()
    expected = ".xlsx" if excel else ".csv"
    if ext not in (".csv", ".xlsx"):
        return [f"Output path must end in .csv or .xlsx, got '{ext}'."]
    if ext != expected:
        return [
            f"--excel {'was' if excel else 'was not'} passed but output path ends in "
            f"'{ext}' (expected '{expected}')."
        ]
    return []


def save_output(df: pd.DataFrame, output_path: str, excel: bool) -> None:
    if excel:
        try:
            df.to_excel(output_path, index=False)
            return
        except ImportError as exc:
            fallback = str(Path(output_path).with_suffix(".csv"))
            print(f"Warning: Excel engine unavailable ({exc}); writing CSV to {fallback} instead.", file=sys.stderr)
            df.to_csv(fallback, index=False)
            return
    df.to_csv(output_path, index=False)


def cmd_expand_group(query: str) -> int:
    """Expand a WEO country-group name or code into '+'-joined ISO3 codes, using
    imf_datatools.get_weo_country_groups()/get_weo_country_info() (RES WEO team's official,
    live-queryable group data — not a personal/cached copy)."""
    try:
        groups = imf_datatools.get_weo_country_groups()
    except Exception as exc:
        print(f"ERROR fetching country groups: {exc}", file=sys.stderr)
        return 1

    desc_col = next(
        (c for c in groups.columns if str(c).lower() in ("name", "description", "groupname", "group_name")),
        groups.columns[0] if len(groups.columns) else None,
    )
    if desc_col is None:
        print("ERROR: could not find a group-name column in get_weo_country_groups() output.", file=sys.stderr)
        return 1

    query_norm = query.strip().lower()
    group_codes_upper = {str(c).upper() for c in groups.index}
    if query.strip().upper() in group_codes_upper:
        matches = groups[groups.index.astype(str).str.upper() == query.strip().upper()]
    else:
        matches = groups[groups[desc_col].astype(str).str.lower().str.contains(query_norm, na=False)]

    if len(matches) == 0:
        print(f"No country group found matching '{query}'. Try a different keyword or the exact group code.", file=sys.stderr)
        return 1
    if len(matches) > 1:
        print(f"Multiple groups match '{query}':")
        for code, row in matches.iterrows():
            print(f"  {code} — {row[desc_col]}")
        return 1

    group_code = str(matches.index[0])
    group_name = matches.iloc[0][desc_col]

    try:
        info = imf_datatools.get_weo_country_info()
    except Exception as exc:
        print(f"ERROR fetching country info: {exc}", file=sys.stderr)
        return 1

    if group_code not in info.columns:
        print(
            f"ERROR: group code '{group_code}' ({group_name}) has no matching column in "
            "get_weo_country_info() — verify the two functions' schemas manually.",
            file=sys.stderr,
        )
        return 1

    iso_col = next(
        (c for c in info.columns if str(c).lower() in ("iso3", "isocode", "code", "countrycode", "country")),
        None,
    )
    member_rows = info[info[group_code] == 1]
    codes = member_rows[iso_col].astype(str).tolist() if iso_col else member_rows.index.astype(str).tolist()

    if not codes:
        print(f"'{group_name}' ({group_code}) matched but has no member countries.", file=sys.stderr)
        return 1

    print(f"{group_name} ({group_code}): {len(codes)} countries")
    print("+".join(codes))
    return 0


def cmd_get_databases(keyword: str) -> int:
    try:
        dbs = idata_utilities.get_databases(keyword=keyword)
    except Exception as exc:
        print(f"ERROR searching databases: {exc}", file=sys.stderr)
        return 1
    desc_col = "Description" if "Description" in dbs.columns else dbs.columns[0]
    for db_id, row in dbs.iterrows():
        print(f"{db_id} — {row[desc_col]}")
    return 0


def cmd_get_dimensions(db: str) -> int:
    try:
        dims = idata_utilities.get_dimensions(db)
    except Exception as exc:
        print(f"ERROR fetching dimensions: {exc}", file=sys.stderr)
        return 1
    for dim_name in dims.index:
        print(str(dim_name).upper())
    return 0


def cmd_get_dimension_values(db: str, dimension: str, keyword: str | None) -> int:
    try:
        values = idata_utilities.get_dimension_values(db, dimension, keyword=keyword)
    except Exception as exc:
        print(f"ERROR fetching dimension values: {exc}", file=sys.stderr)
        return 1
    name_col = "Name" if "Name" in values.columns else values.columns[0]
    for code, row in values.iterrows():
        print(f"{row[name_col]} ({code})")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    output_path = args.output or f"idata_{time.strftime('%Y%m%d_%H%M%S')}{'.xlsx' if args.excel else '.csv'}"

    errors = validate_output_format(output_path, args.excel)
    if errors:
        for msg in errors:
            print(f"ERROR: {msg}", file=sys.stderr)
        return 1

    print(
        f"Fetching db={args.db} key={args.key} start={args.start} end={args.end} "
        f"format={args.fmt} -> {output_path}"
    )

    use_long = args.fmt == "long"
    try:
        df = _fetch_data(args.db, args.key, args.start, args.end, use_long)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if df is None or len(df) == 0:
        print("No data returned. Check the key, database identifier, and period.", file=sys.stderr)
        return 1

    scale, unit_label = fetch_metadata(args.db, args.key)

    if df.index.name:
        df = df.reset_index()
    if scale:
        value_cols = df.select_dtypes(include="number").columns
        df[value_cols] = df[value_cols] / (10**scale)
    df["SCALE"] = SCALE_LABELS.get(scale, "")
    if unit_label:
        df["UNIT"] = unit_label

    save_output(df, output_path, args.excel)
    print(f"Saved {len(df)} row(s) to {output_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", help="iData database id, e.g. IMF.RES.WEO:WEO_LIVE")
    parser.add_argument(
        "--expand-group", dest="expand_group", metavar="NAME",
        help=(
            "Expand a WEO country-group name or code (e.g. 'advanced economies', 'G007') into "
            "'+'-joined ISO3 codes ready to paste into a key. No fetch, --db not needed."
        ),
    )
    parser.add_argument(
        "--get-databases", dest="get_databases", metavar="KEYWORD",
        help="Search database names/descriptions for KEYWORD; prints matches, no fetch.",
    )
    parser.add_argument(
        "--get-dimensions", action="store_true",
        help="List dimension names for --db, in key order. No fetch.",
    )
    parser.add_argument(
        "--get-dimension-values", dest="dimension_values", metavar="DIM",
        help="List valid codes/labels for one dimension of --db. No fetch.",
    )
    parser.add_argument("--keyword", help="Filter --get-dimension-values output by keyword.")
    parser.add_argument("--key", help="Dot-separated dimension key for fetching.")
    parser.add_argument("--start", help="Start period, e.g. 2015 or 2015-01.")
    parser.add_argument("--end", help="End period, e.g. 2024 or 2024-12.")
    parser.add_argument(
        "--format", dest="fmt", choices=["wide", "long"], default="wide",
        help="Output format (default: wide).",
    )
    parser.add_argument("--excel", action="store_true", help="Save as .xlsx instead of .csv.")
    parser.add_argument("--output", help="Output file path. Auto-named if omitted.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.expand_group:
        return cmd_expand_group(args.expand_group)

    if args.get_databases:
        return cmd_get_databases(args.get_databases)

    if not args.db:
        parser.error("--db is required (unless using --get-databases).")

    if args.get_dimensions:
        return cmd_get_dimensions(args.db)

    if args.dimension_values:
        return cmd_get_dimension_values(args.db, args.dimension_values, args.keyword)

    if not args.key:
        parser.error("--key is required when fetching data.")

    return cmd_fetch(args)


if __name__ == "__main__":
    sys.exit(main())
