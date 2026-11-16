"""Country background knowledge: codes, name variants, income groups, WEO aggregates.

Reads the tables in ``knowledge/`` (built from the team's Country Codes.xlsx and country dummy
file by scripts/build_country_knowledge.py). Used to match whatever identifies a country in the
data (ISO3 as in WEO Live, IFS code as in team files, or a name) and to form the AE / EM / LIC
groups the team uses for group statistics.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"
INCOME_GROUPS = {  # code in the dummy file -> label used in the team charts
    "AE": "Advanced Economies",
    "EM": "Emerging Markets",
    "LIC": "Low-Income Developing Countries",
}
GLOBAL_LABEL = "Global"
_INCOME_ALIASES = {
    "ae": "AE", "advanced": "AE", "advanced economies": "AE", "aes": "AE",
    "em": "EM", "ems": "EM", "emerging markets": "EM", "emerging market economies": "EM",
    "lic": "LIC", "lics": "LIC", "lidc": "LIC", "lidcs": "LIC", "low-income developing countries": "LIC",
    "low income developing countries": "LIC", "low-income countries": "LIC",
}


def _read(name: str) -> pd.DataFrame:
    return pd.read_csv(KNOWLEDGE_DIR / name, comment="#", dtype=str, keep_default_na=False, na_values=[""])


def _key(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text)).strip().casefold()


@lru_cache(maxsize=1)
def tables() -> dict[str, pd.DataFrame]:
    return {"countries": _read("countries.csv"), "aliases": _read("country_aliases.csv"),
            "aggregates": _read("weo_aggregates.csv")}


@lru_cache(maxsize=1)
def _index() -> dict[str, dict[str, dict[str, Any]]]:
    data = tables()
    countries = data["countries"]
    records = {row["ifscode"]: row for row in countries.to_dict("records") if isinstance(row["ifscode"], str)}
    by_iso = {row["iso3"]: row for row in records.values() if isinstance(row["iso3"], str)}
    by_name: dict[str, dict[str, Any]] = {}
    for row in data["aliases"].to_dict("records"):
        target = records.get(row["ifscode"]) or by_iso.get(row["iso3"])
        if target is not None:
            by_name.setdefault(_key(row["alias"]), target)
    aggregates = {}
    for row in data["aggregates"].to_dict("records"):
        for value in (row["weo_code"], row["ifscode"], row["name"]):
            if isinstance(value, str):
                aggregates[_key(value)] = row
    return {"ifs": records, "iso": by_iso, "name": by_name, "aggregate": aggregates}


def lookup(value: Any) -> dict[str, Any] | None:
    """Country record for an ISO3 code, IFS code (int or text) or a known name variant, else None."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    index = _index()
    if re.fullmatch(r"\d+(\.0)?", text):
        return index["ifs"].get(str(int(float(text))))
    if re.fullmatch(r"[A-Za-z]{3}", text) and text.upper() in index["iso"]:
        return index["iso"][text.upper()]
    return index["name"].get(_key(text))


def is_aggregate(value: Any) -> bool:
    """True for WEO aggregate codes/names (World, G110, Advanced Economies, 1201, ...)."""
    text = str(value).strip()
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]
    return _key(text) in _index()["aggregate"] or _key(text) == "world"


def classify(values: Iterable[Any]) -> pd.DataFrame:
    """One row per distinct value: value, kind (country/aggregate/unknown), iso3, ifscode, country, income_group."""
    rows = []
    for value in dict.fromkeys(str(v) for v in values):
        record = lookup(value)
        if record is not None and not is_aggregate(value):
            rows.append({"value": value, "kind": "country", "iso3": record["iso3"], "ifscode": record["ifscode"],
                         "country": record["country"], "income_group": record["income_group"]})
        else:
            rows.append({"value": value, "kind": "aggregate" if is_aggregate(value) else "unknown",
                         "iso3": None, "ifscode": None, "country": None, "income_group": None})
    return pd.DataFrame(rows, columns=["value", "kind", "iso3", "ifscode", "country", "income_group"])


def income_code(name: str) -> str | None:
    """'Advanced Economies' / 'AE' / 'LIDC' ... -> 'AE' / 'EM' / 'LIC'; None if not an income group."""
    text = _key(name)
    if text.upper() in INCOME_GROUPS:
        return text.upper()
    return _INCOME_ALIASES.get(text)


def income_groups(values: Iterable[Any], which: Iterable[str] = ("AE", "EM", "LIC"),
                  include_global: bool = True) -> tuple[dict[str, list[str]], pd.DataFrame]:
    """Group the data's country identifiers by the team income classification.

    Returns ({label: [values as they appear in the data]}, classification frame). ``Global`` is every
    classified country of the data (all of AE + EM + LIC, as ``Dummy().noagg`` in the team scripts).
    """
    info = classify(values)
    groups: dict[str, list[str]] = {}
    countries = info[info["kind"] == "country"]
    if include_global:
        groups[GLOBAL_LABEL] = countries[countries["income_group"].notna()]["value"].tolist()
    for code in which:
        groups[INCOME_GROUPS[code]] = countries[countries["income_group"] == code]["value"].tolist()
    return groups, info
