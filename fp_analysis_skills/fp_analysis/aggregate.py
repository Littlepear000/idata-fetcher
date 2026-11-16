"""Group statistics over countries (simple and GDP-weighted), as in fadfpdata's
ImfFrame.agg_mean / export_agg_detail and the summary block of DSPB/dspb.py.

``groups`` maps a group name to the country codes in the panel's ``country`` column
(WEO Live uses ISO3 codes). ``None`` means one group, "All countries", made of every
country in the data.
"""

from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np
import pandas as pd

Groups = Mapping[str, Sequence[str]]


def _groups(frame: pd.DataFrame, groups: Groups | None) -> dict[str, list[str]]:
    if not groups:
        return {"All countries": sorted(frame["country"].astype(str).unique())}
    return {name: [str(code) for code in codes] for name, codes in groups.items()}


def weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    mask = values.notna() & weights.notna()
    total = weights[mask].sum()
    return float((values[mask] * weights[mask]).sum() / total) if total else np.nan


def _years(frame: pd.DataFrame, start_year: int | None, end_year: int | None) -> pd.DataFrame:
    if start_year is not None:
        frame = frame[frame["year"] >= int(start_year)]
    if end_year is not None:
        frame = frame[frame["year"] <= int(end_year)]
    return frame


def group_statistics(frame: pd.DataFrame, value: str, groups: Groups | None = None,
                     weight: str | None = None, start_year: int | None = None,
                     end_year: int | None = None) -> pd.DataFrame:
    """One row per group and year.

    Columns: group, year, n_countries, mean, weighted_mean, median, p10, p25, p75, p90,
    iqr, p10_p90, weight_coverage. weighted_mean / weight_coverage are NaN without a weight;
    weight_coverage is the share (%) of the group's total weight held by countries with a value.
    """
    frame = _years(frame, start_year, end_year)
    rows = []
    for name, members in _groups(frame, groups).items():
        sub = frame[frame["country"].astype(str).isin(members)]
        for year, sub_y in sub.groupby("year"):
            values = sub_y[value]
            has = values.notna()
            row = {
                "group": name, "year": int(year), "n_countries": int(has.sum()),
                "mean": values.mean(), "weighted_mean": np.nan, "median": values.median(),
                "p10": values.quantile(0.10), "p25": values.quantile(0.25),
                "p75": values.quantile(0.75), "p90": values.quantile(0.90), "weight_coverage": np.nan,
            }
            if weight:
                weights = sub_y[weight]
                row["weighted_mean"] = weighted_mean(values, weights)
                total = weights.sum()
                row["weight_coverage"] = float(weights[has].sum() / total * 100) if total else np.nan
            rows.append(row)
    out = pd.DataFrame(rows, columns=["group", "year", "n_countries", "mean", "weighted_mean", "median",
                                      "p10", "p25", "p75", "p90", "weight_coverage"])
    out["iqr"] = out["p75"] - out["p25"]
    out["p10_p90"] = out["p90"] - out["p10"]
    order = list(_groups(frame, groups))
    out["group"] = pd.Categorical(out["group"], categories=order, ordered=True)
    out = out.sort_values(["group", "year"]).reset_index(drop=True)
    out["group"] = out["group"].astype(str)
    return out[["group", "year", "n_countries", "mean", "weighted_mean", "median", "p10", "p25",
                "p75", "p90", "iqr", "p10_p90", "weight_coverage"]]


def chart_table(stats: pd.DataFrame, column: str = "weighted_mean",
                order: Sequence[str] | None = None) -> pd.DataFrame:
    """Year x group table of one statistic (the 'chart' sheet of the team workbooks).

    ``order`` fixes the group columns (a group without countries in the data stays as an empty column).
    """
    table = stats.pivot(index="year", columns="group", values=column)
    table = table.reindex(columns=list(order) if order else list(dict.fromkeys(stats["group"])))
    table.columns.name = None
    return table.reset_index()


def dspb_summary(frame: pd.DataFrame, groups: Groups | None = None, weight: str | None = None,
                 start_year: int | None = None, end_year: int | None = None) -> pd.DataFrame:
    """Per group and year, countries whose primary balance is below the debt-stabilizing level.

    Columns: group, year, n_countries (with a gap value), n_below, share_below (% of n_countries),
    and, among countries below: p25, median, p75, iqr, weighted_mean (weight-averaged gap).
    """
    frame = _years(frame, start_year, end_year)
    rows = []
    for name, members in _groups(frame, groups).items():
        sub = frame[frame["country"].astype(str).isin(members) & frame["pb_gap"].notna()]
        for year, sub_y in sub.groupby("year"):
            below = sub_y[sub_y["pb_gap"] < 0]
            n = sub_y["country"].nunique()
            gaps = below["pb_gap"]
            rows.append({
                "group": name, "year": int(year), "n_countries": int(n), "n_below": int(below["country"].nunique()),
                "share_below": below["country"].nunique() / n * 100 if n else np.nan,
                "p25": gaps.quantile(0.25) if len(gaps) else np.nan,
                "median": gaps.median() if len(gaps) else np.nan,
                "p75": gaps.quantile(0.75) if len(gaps) else np.nan,
                "weighted_mean": weighted_mean(gaps, below[weight]) if weight and len(gaps) else np.nan,
            })
    out = pd.DataFrame(rows, columns=["group", "year", "n_countries", "n_below", "share_below",
                                      "p25", "median", "p75", "weighted_mean"])
    out["iqr"] = out["p75"] - out["p25"]
    return out.sort_values(["year"], kind="stable").reset_index(drop=True)
