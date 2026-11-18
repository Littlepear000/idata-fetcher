"""Rebuild knowledge/embig_tickers.csv from the team workbook "Bloomberg EMBIG tickers.xlsx".

Input (team-maintained, not shipped):
    Bloomberg EMBIG tickers.xlsx   sheet filtered_list: ticker, country, ifscode
    (sheets full_list / with_formula are Bloomberg search dumps and are not used)

Output (shipped, read by fp_analysis/bloomberg.py and the research prompt):
    knowledge/embig_tickers.csv    ticker, country, country_name, iso3, ifscode, income_group, active, verified, note

ISO3, the standard country name and the team income group come from knowledge/countries.csv
(matched by IFS code, then by name), so EMBIG data line up with WEO Live country codes.
Run scripts/build_country_knowledge.py first if the country workbooks changed.

Usage:
    python scripts/build_embig_tickers.py "path/Bloomberg EMBIG tickers.xlsx"
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fp_analysis.countries import lookup  # noqa: E402

OUT = ROOT / "knowledge" / "embig_tickers.csv"
GLOBAL_IFS = "1"   # the workbook codes the EMBIG Global composite as IFS 1 (the WEO "World" code)


def _note(ticker: str, ifscode: str) -> str:
    if ifscode == GLOBAL_IFS:
        return "EMBIG Global composite (all index countries); not a country"
    if not ticker.upper().startswith("JP"):
        return "ticker is not a J.P. Morgan EMBIG code; check it is an EMBIG sovereign spread"
    return ""


def build(workbook: Path) -> pd.DataFrame:
    sheet = pd.read_excel(workbook, sheet_name="filtered_list", dtype=str, keep_default_na=False)
    sheet.columns = [str(column).strip().lower() for column in sheet.columns]
    rows = []
    for item in sheet.itertuples(index=False):
        ticker = str(item.ticker).strip()        # keep inner spacing: it is part of the iData code
        if not ticker:
            continue
        ifscode = str(item.ifscode).strip().removesuffix(".0")
        record = None if ifscode == GLOBAL_IFS else (lookup(ifscode) or lookup(item.country))
        rows.append({
            "ticker": ticker,
            "country": str(item.country).strip(),                       # name as written in the workbook
            "country_name": record["country"] if record else str(item.country).strip(),
            "iso3": record["iso3"] if record else "",
            "ifscode": ifscode,
            "income_group": (record.get("income_group") or "") if record else "",
            "active": 1,
            "verified": "yes",                                         # team list used by EMBIG/embig.py
            "note": _note(ticker, ifscode) if record or ifscode == GLOBAL_IFS
                    else "country not found in knowledge/countries.csv",
        })
    table = pd.DataFrame(rows)
    with open(OUT, "w", encoding="utf-8", newline="") as handle:
        handle.write(f"# Built {date.today():%Y-%m-%d} from {workbook.name} (sheet filtered_list) "
                     "by scripts/build_embig_tickers.py\n")
        handle.write("# J.P. Morgan EMBIG sovereign stripped spreads (basis points), Bloomberg PX_LAST via iData "
                     "IMF.CSF:BBGDL. Edit the workbook and rebuild, or set active=0 to skip a row.\n")
        table.to_csv(handle, index=False)
    return table


if __name__ == "__main__":
    result = build(Path(sys.argv[1]))
    print(len(result), "tickers;", result["income_group"].replace("", "-").value_counts().to_dict())
    flagged = result[result["note"] != ""]
    if not flagged.empty:
        print(flagged[["ticker", "country", "note"]].to_string(index=False))
