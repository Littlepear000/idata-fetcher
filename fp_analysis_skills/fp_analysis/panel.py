"""Turn retrieved datasets into the annual country-year panel the analysis skills work on.

The research assistant saves every retrieval as a long-format frame with official codes
(one row per observation). The fiscal skills need one row per country and year with one
column per indicator. This module does that reshaping and nothing else: it never fills
gaps, converts units or changes values.
"""

from __future__ import annotations

import re
from typing import Iterable

import pandas as pd

COUNTRY_COLUMNS = ("COUNTRY", "REF_AREA", "ISO3", "iso3", "country", "ifscode", "IFSCODE")
PERIOD_COLUMNS = ("TIME_PERIOD", "dates", "date", "DATE", "year", "YEAR")
INDICATOR_COLUMNS = ("INDICATOR", "indicator", "SERIES", "series")
VALUE_COLUMNS = ("OBS_VALUE", "value", "VALUE")
FREQUENCY_COLUMNS = ("FREQUENCY", "FREQ", "frequency", "freq")
SCALE_COLUMNS = ("SCALE", "scale")

_YEAR = re.compile(r"^\s*(\d{4})\s*$")
_SUB_ANNUAL = re.compile(r"^\s*\d{4}\s*-?\s*[QqMmSsWw]\d{1,2}\s*$")


class PanelError(ValueError):
    """The datasets cannot be turned into an annual country-year panel."""


def _first(frame: pd.DataFrame, candidates: Iterable[str]) -> str | None:
    return next((column for column in candidates if column in frame.columns), None)


def _to_year(values: pd.Series) -> pd.Series:
    """Map period labels or dates to an integer year; refuse sub-annual periods."""
    if pd.api.types.is_integer_dtype(values):
        return values.astype("Int64")
    text = values.astype(str)
    if text.str.match(_SUB_ANNUAL).any():
        raise PanelError(
            "The data are sub-annual (quarterly/monthly periods found). The fiscal skills need annual data: "
            "fetch the annual series (frequency A) instead of converting frequencies here."
        )
    years = text.str.extract(_YEAR, expand=False)
    parsed = pd.to_datetime(text.where(years.isna()), errors="coerce")
    result = pd.to_numeric(years, errors="coerce").fillna(parsed.dt.year)
    if result.isna().any():
        bad = text[result.isna()].unique()[:5].tolist()
        raise PanelError(f"Could not read a year from period values such as {bad}.")
    return result.astype("Int64")


def _check_annual(frame: pd.DataFrame) -> None:
    column = _first(frame, FREQUENCY_COLUMNS)
    if column is None:
        return
    frequencies = set(frame[column].dropna().astype(str).str.upper().unique())
    if frequencies - {"A", "ANNUAL", "Y"}:
        raise PanelError(
            f"Frequency {sorted(frequencies)} found; the fiscal skills need annual data (A). "
            "Fetch the annual series instead of converting frequencies here."
        )


def _long_part(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, set[str]]]:
    country = _first(frame, COUNTRY_COLUMNS)
    period = _first(frame, PERIOD_COLUMNS)
    indicator = _first(frame, INDICATOR_COLUMNS)
    value = _first(frame, VALUE_COLUMNS)
    if not (country and period and indicator and value):
        raise PanelError(
            "Expected long format with country, period, indicator and value columns "
            f"(e.g. COUNTRY, TIME_PERIOD/dates, INDICATOR, OBS_VALUE). Found: {list(map(str, frame.columns))}."
        )
    _check_annual(frame)
    part = pd.DataFrame({
        "country": frame[country].astype(str),
        "year": _to_year(frame[period]),
        "indicator": frame[indicator].astype(str).str.upper(),
        "value": pd.to_numeric(frame[value], errors="coerce"),
    })
    scales: dict[str, set[str]] = {}
    scale = _first(frame, SCALE_COLUMNS)
    if scale is not None:
        labelled = pd.DataFrame({"indicator": part["indicator"], "scale": frame[scale].fillna("").astype(str)})
        for code, group in labelled.groupby("indicator"):
            scales.setdefault(code, set()).update(group["scale"].unique())
    return part, scales


def _wide_part(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, set[str]]]:
    """Accept a frame that is already one row per country-year with indicator columns."""
    country = _first(frame, COUNTRY_COLUMNS)
    period = _first(frame, PERIOD_COLUMNS)
    if not (country and period):
        raise PanelError(f"No country/period columns found in {list(map(str, frame.columns))}.")
    _check_annual(frame)
    ignore = {country, period, *FREQUENCY_COLUMNS, *SCALE_COLUMNS, "UNIT", "unit", "source", "SOURCE"}
    numeric = [column for column in frame.columns
               if column not in ignore and pd.api.types.is_numeric_dtype(frame[column])]
    part = frame[[country, period, *numeric]].copy()
    part.columns = ["country", "year", *[str(column).upper() for column in numeric]]
    part["country"] = part["country"].astype(str)
    part["year"] = _to_year(part["year"])
    long = part.melt(id_vars=["country", "year"], var_name="indicator", value_name="value")
    return long, {}


def to_annual_panel(frames: pd.DataFrame | list[pd.DataFrame]) -> pd.DataFrame:
    """Combine one or more retrieved datasets into a country-year panel.

    Returns a frame with columns ``country``, ``year`` and one column per indicator code
    (upper case). ``panel.attrs["scales"]`` maps each indicator to the SCALE labels seen.
    Raises PanelError for sub-annual data, missing columns, or conflicting duplicates.
    """
    if isinstance(frames, pd.DataFrame):
        frames = [frames]
    parts, scales = [], {}
    for frame in frames:
        if frame is None or frame.empty:
            continue
        is_long = _first(frame, INDICATOR_COLUMNS) and _first(frame, VALUE_COLUMNS)
        part, part_scales = _long_part(frame) if is_long else _wide_part(frame)
        parts.append(part)
        for code, labels in part_scales.items():
            scales.setdefault(code, set()).update(labels)
    if not parts:
        raise PanelError("No non-empty datasets were given.")
    long = pd.concat(parts, ignore_index=True).dropna(subset=["value"])
    long = long.drop_duplicates()
    clashes = long[long.duplicated(subset=["country", "year", "indicator"], keep=False)]
    if not clashes.empty:
        example = clashes[["country", "year", "indicator"]].drop_duplicates().head(5).to_dict("records")
        raise PanelError(
            "Several different values for the same country/year/indicator (another dimension such as unit "
            f"or sector differs, or two datasets overlap with different vintages). Examples: {example}. "
            "Select one series per indicator before running the analysis."
        )
    panel = long.pivot(index=["country", "year"], columns="indicator", values="value").reset_index()
    panel.columns.name = None
    panel = panel.sort_values(["country", "year"], kind="stable").reset_index(drop=True)
    panel.attrs["scales"] = {code: sorted(labels) for code, labels in scales.items()}
    return panel


def lag(panel: pd.DataFrame, column: str, periods: int = 1) -> pd.Series:
    """Value of ``column`` in year t-periods for the same country (NaN when that year is absent).

    Uses an explicit year join rather than a positional shift, so a missing year never makes
    the previous available year look like t-1.
    """
    source = panel[["country", "year", column]].copy()
    source["year"] = source["year"] + periods
    merged = panel[["country", "year"]].merge(source, on=["country", "year"], how="left")
    return pd.Series(merged[column].to_numpy(), index=panel.index, name=f"{column}_l{periods}")
