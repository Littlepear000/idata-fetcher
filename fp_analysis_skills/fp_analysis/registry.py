"""Catalog of analysis skills and the precondition check behind each one.

A skill declares what it needs (indicator codes in WEO Live, annual frequency, enough years,
country groups) so the agent can say *before* running anything whether the handed-off data
are sufficient, and if not, exactly what to fetch in Research.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

WEO_LIVE = "IMF.RES.WEO:WEO_LIVE"
BLOOMBERG_DB = "IMF.CSF:BBGDL"


@dataclass(frozen=True)
class Requirement:
    code: str                       # indicator code as it appears in the panel (WEO Live mnemonic)
    label: str
    role: str                       # why the skill needs it
    derive_from: tuple[str, ...] = ()   # codes that can stand in for it (see method notes)


@dataclass(frozen=True)
class Skill:
    id: str
    title: str
    stage: str                      # "research" (retrieval shortcut), "analysis" (runs on handed-off data)
                                    # or "background" (reference knowledge used by the others)
    summary: str
    reference: str                  # method note, relative to the skill folder
    required: tuple[Requirement, ...] = ()
    weight: Requirement | None = None   # needed only for group aggregates
    frequency: str = "A"
    lag_years: int = 0              # extra years before the first output year that must be fetched
    min_years: int = 1
    database: str = WEO_LIVE
    origin: str = ""                # the team script this skill was built from
    params: dict[str, Any] = field(default_factory=dict)  # parameter -> default


GGEI = Requirement("GGEI", "General government interest expense (national currency)",
                   "numerator of the effective interest rate r")
GGXWDG = Requirement("GGXWDG", "General government gross debt (national currency)",
                     "denominator of r (previous year's stock)")
NGDP = Requirement("NGDP", "Gross domestic product, current prices (national currency)",
                   "nominal growth g")
GGXWDG_NGDP = Requirement("GGXWDG_NGDP", "General government gross debt (% of GDP)",
                          "previous year's debt ratio d(t-1)", derive_from=("GGXWDG", "NGDP"))
GGXONLB_NGDP = Requirement("GGXONLB_NGDP", "General government primary net lending/borrowing (% of GDP)",
                           "actual primary balance pb", derive_from=("GGXONLB", "NGDP"))
NGDPD = Requirement("NGDPD", "Gross domestic product, current prices (US dollars)",
                    "GDP weight for group averages of non-fiscal indicators")
# Fiscal-year nominal GDP in US dollars: the team's weight for fiscal variables (ngdp_fy_usd in the
# team scripts). The code below is the team's variable name; the Research assistant must confirm the
# exact WEO Live code from the indicator catalog, and the user decides if it cannot be found.
FISCAL_WEIGHT = "NGDP_FY_USD"
DEFAULT_WEIGHT = "NGDPD"
NGDP_FY_USD = Requirement(FISCAL_WEIGHT, "Nominal GDP, fiscal year, US dollars",
                          "GDP weight for group averages of fiscal variables")
FISCAL_PREFIXES = ("GG", "CG", "PS", "NFPS")


def default_weight(indicator: str | None) -> str:
    """Team rule: fiscal variables are weighted by fiscal-year USD GDP, everything else by NGDPD."""
    code = str(indicator or "").upper()
    return FISCAL_WEIGHT if code.startswith(FISCAL_PREFIXES) or code in {"RLESSG", "RLESSG_ABS", "DSPB", "PB_GAP"} \
        else DEFAULT_WEIGHT

SKILLS: dict[str, Skill] = {skill.id: skill for skill in (
    Skill(
        id="country_groups",
        title="Country codes and income groups (background knowledge)",
        stage="background",
        summary="Team country table (ISO3 / IFS code / name variants) and the AE / EM / LIC classification "
                "from the team country dummy file. Used by every group statistic; queried with "
                "lookup_team_countries.",
        reference="references/country_groups.md",
        database="knowledge/countries.csv",
        frequency="",
        origin="Country Codes.xlsx; Dummy_20260115.xlsx (columns income / ae / em / lic)",
    ),
    Skill(
        id="bond_yield_10y",
        title="10-year government bond yields (Bloomberg)",
        stage="research",
        summary="Download generic 10-year sovereign yields from Bloomberg via iData, average to the "
                "requested frequency, one long dataset with country codes.",
        reference="references/bond_yield_10y.md",
        frequency="D",
        database=BLOOMBERG_DB,
        origin="fadfp_useful_charts/10y bond yield/temp.py",
        params={"frequency": "M", "start_period": "2008-01-01", "end_period": None, "countries": None},
    ),
    Skill(
        id="embig_spreads",
        title="EMBIG sovereign spreads (Bloomberg)",
        stage="research",
        summary="Download J.P. Morgan EMBIG sovereign spreads from Bloomberg via iData using the team's "
                "ticker list, average to the requested frequency, one long dataset with country codes.",
        reference="references/embig_spreads.md",
        frequency="D",
        database=BLOOMBERG_DB,
        origin="fadfp_useful_charts/EMBIG/embig.py",
        params={"frequency": "M", "start_period": "2008-01-01", "end_period": None, "countries": None},
    ),
    Skill(
        id="r_minus_g",
        title="Interest-growth differential (r - g)",
        stage="analysis",
        summary="Effective interest rate on public debt minus nominal GDP growth, by country and year, "
                "with optional GDP-weighted group averages.",
        reference="references/r_minus_g.md",
        required=(GGEI, GGXWDG, NGDP),
        weight=NGDP_FY_USD,
        lag_years=1,
        min_years=2,
        origin="fadfp_useful_charts/R minus G/rminusg.py",
        params={"method": "standard", "start_year": 2000, "end_year": None, "groups": ["income"],
                "weight": "auto", "measure": "rlessg_abs"},
    ),
    Skill(
        id="dspb",
        title="Debt-stabilizing primary balance (DSPB) and gap",
        stage="analysis",
        summary="Primary balance that keeps the debt ratio constant, the gap between the actual primary "
                "balance and it, and group summaries of countries below the stabilizing level.",
        reference="references/dspb.md",
        required=(GGEI, GGXWDG, NGDP, GGXWDG_NGDP, GGXONLB_NGDP),
        weight=NGDP_FY_USD,
        lag_years=1,
        min_years=2,
        origin="fadfp_useful_charts/DSPB/dspb.py",
        params={"start_year": 2000, "end_year": None, "groups": ["income"], "weight": "auto",
                "outlier_floor": -10.0},
    ),
    Skill(
        id="group_statistics",
        title="Group statistics for one indicator",
        stage="analysis",
        summary="Per group and year: simple mean, GDP-weighted mean, median, 10th/25th/75th/90th "
                "percentiles, IQR and 10-90 range, number of countries and weight coverage.",
        reference="references/group_statistics.md",
        weight=NGDPD,
        origin="fadfpdata ImfFrame.agg_mean / export_agg_detail",
        params={"indicator": None, "start_year": None, "end_year": None, "groups": ["income"], "weight": "auto"},
    ),
)}


def catalog() -> list[dict[str, Any]]:
    """Short description of every skill, for the model and for the interface."""
    return [{
        "skill_id": skill.id, "title": skill.title, "stage": skill.stage, "summary": skill.summary,
        "required_indicators": [req.code for req in skill.required],
        "database": skill.database, "frequency": skill.frequency, "defaults": skill.params,
    } for skill in SKILLS.values()]


def get_skill(skill_id: str) -> Skill:
    try:
        return SKILLS[skill_id]
    except KeyError:
        raise ValueError(f"Unknown skill {skill_id!r}. Known: {sorted(SKILLS)}.") from None


def _coverage(panel: pd.DataFrame, code: str) -> dict[str, Any]:
    present = panel.dropna(subset=[code])
    return {"countries": int(present["country"].nunique()),
            "first_year": int(present["year"].min()) if not present.empty else None,
            "last_year": int(present["year"].max()) if not present.empty else None}


def check_requirements(skill_id: str, panel: pd.DataFrame, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Say whether ``panel`` can feed the skill, and what to fetch if it cannot.

    Returns ``ok``, ``present`` (with coverage), ``derived`` (requirements that will be computed
    from other codes, with a warning), ``missing``, ``warnings`` and, when something is missing,
    ``fetch_in_research``: the database, codes, frequency and first year to retrieve.
    """
    skill = get_skill(skill_id)
    params = {**skill.params, **(params or {})}
    if skill.stage != "analysis":
        return {"ok": True, "skill_id": skill_id, "note": f"{skill.stage.title()} skill: no handed-off data needed."}
    columns = set(panel.columns) - {"country", "year"}
    required = list(skill.required)
    if skill_id == "group_statistics":
        if not params.get("indicator"):
            return {"ok": False, "skill_id": skill_id, "missing": [],
                    "warnings": ["Parameter 'indicator' is required: which indicator code to summarise?"],
                    "available_indicators": sorted(columns)}
        indicator = str(params["indicator"]).upper()
        required = [Requirement(indicator, indicator, "the indicator to summarise")]

    present, derived, missing, warnings = {}, [], [], []
    for req in required:
        if req.code in columns:
            present[req.code] = _coverage(panel, req.code)
        elif req.derive_from and set(req.derive_from) <= columns:
            derived.append(req.code)
            warnings.append(f"{req.code} not in the data; it will be derived from {' / '.join(req.derive_from)} "
                            "(calendar-year ratio; may differ from the published ratio for fiscal-year countries).")
        else:
            missing.append({"code": req.code, "label": req.label, "role": req.role})

    questions: list[str] = []
    weight_choice = str(params.get("weight") or "none").strip()
    wants_groups = bool(params.get("groups")) or skill_id == "group_statistics"
    weight_code = ""
    if wants_groups and weight_choice.lower() != "none":
        driver = str(params.get("indicator") or "") if skill_id == "group_statistics" else "GG"
        weight_code = default_weight(driver) if weight_choice.lower() == "auto" else weight_choice.upper()
        if weight_code in columns:
            present[weight_code] = _coverage(panel, weight_code)
        elif weight_choice.lower() == "auto":
            alternatives = [code for code in (FISCAL_WEIGHT, DEFAULT_WEIGHT) if code in columns and code != weight_code]
            questions.append(
                f"Group averages are weighted by {weight_code} by default "
                f"({'fiscal-year USD GDP for fiscal variables' if weight_code == FISCAL_WEIGHT else 'USD GDP'}), "
                "but it is not in the handed-off data. Fetch it in Research and hand off again"
                + (f", or use {' / '.join(alternatives)} which is in the data" if alternatives else "")
                + ", or use simple (unweighted) means (weight: none)?")
        else:
            missing.append({"code": weight_code, "label": "weight for group averages",
                            "role": "the weight the economist chose; fetch it or choose another"})
    if wants_groups:
        from .countries import classify  # local import keeps registry light
        info = classify(panel["country"].unique())
        unknown = info[info["kind"] == "unknown"]["value"].tolist()
        aggregates = info[info["kind"] == "aggregate"]["value"].tolist()
        if aggregates:
            warnings.append(f"Aggregate rows {aggregates[:8]} are excluded from country groups.")
        if unknown:
            questions.append(f"These country identifiers are not in the team country table: {unknown[:15]}. "
                             "Which countries are they (or should they be left out of the groups)?")
        unclassified = info[(info["kind"] == "country") & info["income_group"].isna()]["country"].tolist()
        if unclassified:
            warnings.append(f"No AE/EM/LIC classification in the dummy file for {unclassified}; "
                            "they are left out of the income groups.")

    for code, labels in (panel.attrs.get("scales") or {}).items():
        if len(labels) > 1:
            warnings.append(f"{code} has mixed SCALE labels {labels}; re-fetch it in one consistent unit.")
    level_codes = [code for code in ("GGEI", "GGXWDG", "NGDP") if code in present]
    level_scales = {code: tuple((panel.attrs.get("scales") or {}).get(code, [])) for code in level_codes}
    if len({scale for scale in level_scales.values() if scale}) > 1:
        warnings.append(f"Level series have different SCALE labels {level_scales}; ratios would be wrong. "
                        "Fetch GGEI, GGXWDG and NGDP together in one request.")

    start_year = params.get("start_year")
    if start_year and skill.lag_years:
        for code in ("GGXWDG", "NGDP", "GGXWDG_NGDP"):
            info = present.get(code)
            if info and info["first_year"] is not None and info["first_year"] > int(start_year) - skill.lag_years:
                warnings.append(f"{code} starts in {info['first_year']}; year {start_year} needs "
                                f"{int(start_year) - skill.lag_years}, so the first output year will be missing.")

    years = panel["year"].dropna().unique()
    if len(years) < skill.min_years:
        missing.append({"code": "years", "label": f"at least {skill.min_years} consecutive years",
                        "role": "lagged terms need the previous year"})

    result = {"ok": not missing and not questions, "skill_id": skill_id, "present": present,
              "derived": derived, "missing": missing, "warnings": warnings, "weight": weight_code or None,
              "questions_for_user": questions}
    if missing:
        codes = [item["code"] for item in missing if item["code"] != "years"]
        first = (int(start_year) - skill.lag_years) if start_year else None
        result["fetch_in_research"] = {
            "database": skill.database, "indicators": codes, "frequency": skill.frequency,
            "start_year": first, "countries": "same countries as the existing dataset",
            "note": "Fetch these in the Research workspace (annual, same countries), hand off again "
                    "together with the existing dataset, then rerun this skill.",
        }
    return result
