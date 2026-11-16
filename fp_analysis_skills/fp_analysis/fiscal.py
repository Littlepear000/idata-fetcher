"""Country-level fiscal indicators: r - g and the debt-stabilizing primary balance.

Formulas follow the team scripts in fadfp_useful_charts (R minus G/rminusg.py,
R minus G/rminusg_carlos.py, DSPB/dspb.py). All inputs are annual WEO Live series in a
country-year panel from ``panel.to_annual_panel``. Outputs are percent / percentage points.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .panel import lag

METHODS = ("standard", "contemporaneous")


def _safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    denominator = denominator.where(denominator != 0)
    return numerator / denominator


def _ratio_or_derived(panel: pd.DataFrame, ratio: str, level: str, notes: list[str]) -> pd.Series:
    """Use the published % of GDP series; otherwise level / NGDP * 100 (noted)."""
    if ratio in panel.columns:
        return panel[ratio]
    notes.append(f"{ratio} derived as {level} / NGDP * 100.")
    return _safe_divide(panel[level], panel["NGDP"]) * 100


def r_minus_g(panel: pd.DataFrame, method: str = "standard") -> tuple[pd.DataFrame, list[str]]:
    """Interest-growth differential by country and year.

    standard (default, rminusg.py):
        g = NGDP_t / NGDP_{t-1} - 1
        r = GGEI_t / GGXWDG_{t-1}
        rlessg      = (r - g) / (1 + g) * 100   growth-adjusted, the term that enters debt dynamics
        rlessg_abs  = (r - g) * 100             plain difference
    contemporaneous (rminusg_carlos.py):
        r = GGEI_t / GGXWDG_t, same g; rlessg = rlessg_abs = (r - g) * 100

    Returns (frame, notes). Frame columns: country, year, r, g, rlessg, rlessg_abs
    (r and g in percent). The first year of each country is NaN (needs t-1).
    """
    if method not in METHODS:
        raise ValueError(f"method must be one of {METHODS}.")
    notes: list[str] = []
    g = _safe_divide(panel["NGDP"], lag(panel, "NGDP")) - 1
    if method == "standard":
        r = _safe_divide(panel["GGEI"], lag(panel, "GGXWDG"))
        growth_factor = (1 + g).where((1 + g) != 0)
        rlessg = (r - g) / growth_factor * 100
    else:
        r = _safe_divide(panel["GGEI"], panel["GGXWDG"])
        rlessg = (r - g) * 100
        notes.append("Contemporaneous method: r uses current-year debt and r - g is not growth-adjusted.")
    out = pd.DataFrame({
        "country": panel["country"], "year": panel["year"],
        "r": r * 100, "g": g * 100, "rlessg": rlessg, "rlessg_abs": (r - g) * 100,
    })
    out = out.replace([np.inf, -np.inf], np.nan)
    return out, notes


def dspb(panel: pd.DataFrame, outlier_floor: float | None = -10.0) -> tuple[pd.DataFrame, list[str]]:
    """Debt-stabilizing primary balance and the gap to the actual primary balance.

        dspb   = d_{t-1} * (r - g) / (1 + g)        d = gross debt, % of GDP; r - g standard method
        pb_gap = pb_t - dspb_t                       pb = primary balance, % of GDP

    pb_gap < 0: the primary balance is below the level that stabilizes debt (debt ratio rising).
    Gaps at or below ``outlier_floor`` are set to NaN and flagged (dspb.py uses -10).
    Returns (frame, notes). Frame columns: country, year, rlessg, debt_l1, pb, dspb, pb_gap,
    gap_excluded.
    """
    notes: list[str] = []
    rg, _ = r_minus_g(panel, method="standard")
    debt_ratio = _ratio_or_derived(panel, "GGXWDG_NGDP", "GGXWDG", notes)
    pb = _ratio_or_derived(panel, "GGXONLB_NGDP", "GGXONLB", notes)
    work = panel[["country", "year"]].copy()
    work["_debt"] = debt_ratio.to_numpy()
    debt_l1 = lag(work, "_debt")
    stabilizing = debt_l1 * rg["rlessg"] / 100
    gap = pb - stabilizing
    excluded = pd.Series(False, index=panel.index)
    if outlier_floor is not None:
        excluded = gap <= outlier_floor
        if excluded.any():
            notes.append(f"{int(excluded.sum())} country-year gap(s) at or below {outlier_floor} pp set to "
                         "missing as outliers (gap_excluded = True).")
        gap = gap.mask(excluded)
    out = pd.DataFrame({
        "country": panel["country"], "year": panel["year"], "rlessg": rg["rlessg"],
        "debt_l1": debt_l1, "pb": pb, "dspb": stabilizing, "pb_gap": gap, "gap_excluded": excluded,
    })
    return out.replace([np.inf, -np.inf], np.nan), notes
