"""Rebuild the country background-knowledge tables from the team workbooks.

Inputs (team-maintained, not shipped):
    Country Codes.xlsx   sheets name_to_code, code_to_name, weo_group_code, FIN Query
    Dummy_<date>.xlsx    one row per country/aggregate, one column per dummy category

Outputs (shipped, read by fp_analysis/countries.py):
    knowledge/countries.csv        one row per country: ifscode, iso3, iso2, country, income_group, ae, em, lic
    knowledge/country_aliases.csv  name variant -> ifscode, iso3 (for matching names in user files / tickers)
    knowledge/weo_aggregates.csv   WEO aggregate codes (never treated as countries)

Usage:
    python scripts/build_country_knowledge.py "path/Country Codes.xlsx" "path/Dummy_20260115.xlsx"
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent.parent / "knowledge"
INCOME_LABELS = {"AE": "Advanced Economies", "EM": "Emerging Markets", "LIC": "Low-Income Developing Countries"}


def _int(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").astype("Int64")


def _read(path: Path, sheet: str | int = 0) -> pd.DataFrame:
    # Keep codes such as "NA" (Namibia's ISO2) as text instead of reading them as missing.
    return pd.read_excel(path, sheet_name=sheet, keep_default_na=False, na_values=[""])


def build(codes_path: Path, dummy_path: Path) -> None:
    code_to_name = _read(codes_path, "code_to_name")
    name_to_code = _read(codes_path, "name_to_code")
    weo_groups = _read(codes_path, "weo_group_code")
    fin = _read(codes_path, "FIN Query")
    dummy = _read(dummy_path)

    code_to_name["ifscode"] = _int(code_to_name["ifscode"])
    dummy["ifscode"] = _int(dummy["ifscode"])
    dummy["noagg"] = pd.to_numeric(dummy["noagg"], errors="coerce")
    countries_dummy = dummy[dummy["noagg"] == 1]
    aggregates_dummy = dummy[dummy["noagg"] != 1]

    # Income classification: the income column and the ae/em/lic dummies agree row by row (checked).
    income = countries_dummy[["ifscode", "country", "isocode", "income"]].rename(
        columns={"country": "country_dummy", "income": "income_group"})
    table = code_to_name.merge(income, on="ifscode", how="outer")
    table["country"] = table["country"].fillna(table["country_dummy"])
    table["iso3"] = table["iso3"].fillna(table["isocode"])
    for code in INCOME_LABELS:
        table[code.lower()] = (table["income_group"] == code).astype(int)
    table["in_dummy_file"] = table["ifscode"].isin(countries_dummy["ifscode"]).astype(int)
    table = table[["ifscode", "iso3", "iso2", "country", "income_group", "ae", "em", "lic", "in_dummy_file"]]
    table = table.sort_values("country").reset_index(drop=True)

    aliases = pd.concat([
        name_to_code.assign(source="name_to_code")[["country", "ifscode", "iso3", "source"]],
        code_to_name.assign(source="code_to_name")[["country", "ifscode", "iso3", "source"]],
        dummy[["country", "ifscode", "isocode"]].rename(columns={"isocode": "iso3"}).assign(source="dummy"),
        # FIN Query 'Member Code' is the IMF FIN code, not always ISO3 (e.g. YMN, ROM): keep names only.
        fin.rename(columns={"Member": "country", "Code": "ifscode"})[["country", "ifscode"]].assign(source="fin_query"),
    ], ignore_index=True).rename(columns={"country": "alias"})
    aliases["ifscode"] = _int(aliases["ifscode"])
    iso_by_ifs = table.dropna(subset=["ifscode"]).set_index("ifscode")["iso3"]
    aliases["iso3"] = aliases["iso3"].fillna(aliases["ifscode"].map(iso_by_ifs))
    aliases["alias"] = aliases["alias"].astype(str).str.strip()
    aliases = aliases.drop_duplicates(subset=["alias", "ifscode", "iso3"]).sort_values("alias")

    weo = weo_groups.rename(columns={"group": "name", "iso": "weo_code"})
    weo["ifscode"] = _int(weo["ifscode"])
    extra = aggregates_dummy[["country", "ifscode"]].rename(columns={"country": "name"})
    extra = extra[~extra["ifscode"].isin(weo["ifscode"])].assign(weo_code=lambda f: "G" + f["ifscode"].astype(str))
    aggregates = pd.concat([weo, extra], ignore_index=True)[["name", "weo_code", "ifscode"]]

    OUT.mkdir(exist_ok=True)
    stamp = f"# Built {date.today():%Y-%m-%d} from {codes_path.name} and {dummy_path.name} by scripts/build_country_knowledge.py\n"
    for name, frame in {"countries.csv": table, "country_aliases.csv": aliases, "weo_aggregates.csv": aggregates}.items():
        with open(OUT / name, "w", encoding="utf-8", newline="") as handle:
            handle.write(stamp)
            frame.to_csv(handle, index=False)
    print(table["income_group"].value_counts(dropna=False).to_dict(), len(aliases), len(aggregates))


if __name__ == "__main__":
    build(Path(sys.argv[1]), Path(sys.argv[2]))
