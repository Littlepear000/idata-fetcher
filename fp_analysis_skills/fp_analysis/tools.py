"""Tool schemas and dispatch for the analysis skills, shaped like the web app's own tools.

Two entry points, one per stage of the app:

* Research stage (retrieval shortcuts): ``RESEARCH_TOOLS`` + ``research_tool_result(name, args, state)``.
  Same contract as the app's ``external_tool_result``: sets ``state["frame"]`` and
  ``state["frame_lineage"]`` and registers a ``retrieval_id`` in ``state["retrieved_frames"]``,
  so the turn is saved as one dataset and works with ``combine_retrieved_data``.

* Analysis stage (after hand-off): ``ANALYSIS_TOOLS`` + ``analysis_tool_result(name, args, handoff)``.
  Same contract as ``formatting_agent.tool_result``: reads ``handoff["datasets"]`` and adds
  table outputs to ``handoff["outputs"]`` (name, kind="table", description, recipe, frame, ...),
  so the existing Format/ZIP/Workbench views show and download them unchanged.

Nothing here calls the language model or imports the app at module load.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Callable

import numpy as np
import pandas as pd

from . import aggregate, bloomberg, countries, fiscal
from .panel import PanelError, to_annual_panel
from .registry import catalog, check_requirements, get_skill

_PREVIEW_ROWS = 15
_OUTPUT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,50}$")
_ISO3 = re.compile(r"^[A-Z]{3}$")
WEO_INCOME_GROUPS = ["Advanced Economies", "Emerging Market and Middle-Income Economies",
                     "Low-Income Developing Countries"]

# --------------------------------------------------------------------------------------------
# Configuration hooks (set once by the app; defaults work inside the web app's folder)
# --------------------------------------------------------------------------------------------
_config: dict[str, Any] = {"fetcher": None, "ticker_paths": {}, "group_expander": None, "output_saver": None}


def configure(*, fetcher: Callable | None = None, ticker_paths: dict[str, str] | None = None,
              group_expander: Callable[[str], dict] | None = None,
              output_saver: Callable[[dict, dict], None] | None = None) -> None:
    """Inject dependencies. All optional.

    fetcher(database, key, start, end) -> DataFrame   default: imf_datatools.get_idata_data
    ticker_paths {"embig_spreads": path, "bond_yield_10y": path}   default: ../data/*.csv
    group_expander(name) -> {"countries": [...]}       default: idata_client.expand_country_group
    output_saver(handoff, output)                     default: dataset_store.save_output
    """
    for key, value in {"fetcher": fetcher, "ticker_paths": ticker_paths, "group_expander": group_expander,
                       "output_saver": output_saver}.items():
        if value is not None:
            _config[key] = value


def _records(frame: pd.DataFrame, rows: int = _PREVIEW_ROWS) -> list[dict[str, Any]]:
    clean = frame.head(rows).replace([np.inf, -np.inf], np.nan)
    return json.loads(clean.round(3).to_json(orient="records", date_format="iso"))


def _fn(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties,
                       "required": required if required is not None else list(properties),
                       "additionalProperties": False},
    }}


_NULLABLE_STR = {"type": ["string", "null"]}
_COUNTRIES = {"type": ["array", "null"], "items": {"type": "string"},
              "description": "Country names, ISO3 or IFS codes; null for every ticker in the team table."}
_FREQ = {"type": "string", "enum": ["D", "W", "M", "Q", "A"],
         "description": "Averaging of daily values: D none, W weekly, M monthly (default), Q quarterly, A annual."}

# --------------------------------------------------------------------------------------------
# Research stage: retrieval shortcuts
# --------------------------------------------------------------------------------------------
RESEARCH_TOOLS = [
    _fn("fetch_embig_spreads",
        "Skill embig_spreads. Download J.P. Morgan EMBIG sovereign spreads (basis points) from Bloomberg "
        "via iData IMF.CSF:BBGDL using the team ticker list, averaged from daily PX_LAST to the requested "
        "frequency. Use directly when the economist asks for EMBIG / EMBI spreads; no database discovery needed.",
        {"frequency": _FREQ, "start_period": _NULLABLE_STR, "end_period": _NULLABLE_STR, "countries": _COUNTRIES}),
    _fn("fetch_bond_yield_10y",
        "Skill bond_yield_10y. Download generic 10-year government bond yields (percent) from Bloomberg via "
        "iData IMF.CSF:BBGDL using the team ticker list, averaged from daily PX_LAST to the requested "
        "frequency. Use directly when the economist asks for 10-year (sovereign/government) bond yields.",
        {"frequency": _FREQ, "start_period": _NULLABLE_STR, "end_period": _NULLABLE_STR, "countries": _COUNTRIES}),
]
RESEARCH_TOOL_NAMES = {tool["function"]["name"] for tool in RESEARCH_TOOLS}
_RESEARCH_SERIES = {"fetch_embig_spreads": "embig_spreads", "fetch_bond_yield_10y": "bond_yield_10y"}

RESEARCH_PROMPT_ADDENDUM = """
RETRIEVAL SKILLS (fixed recipes, prefer them over discovery for these two series):
- EMBIG / EMBI Global sovereign spreads -> fetch_embig_spreads.
- 10-year government / sovereign bond yields -> fetch_bond_yield_10y.
Both read daily Bloomberg PX_LAST through iData (IMF.CSF:BBGDL) for the tickers in the team table and
average them to the requested frequency (default monthly, from 2008). Confirm frequency, period and
countries if the economist did not state them; otherwise use the defaults and say so. Report the unit
(basis points for EMBIG, percent for yields), the averaging, the latest period and any country without
data. Countries absent from the ticker table cannot be fetched by these tools: say so, do not guess
tickers. For r - g, debt-stabilizing primary balance or group statistics, fetch the annual WEO Live
inputs listed by the analysis skill and tell the economist to hand them off to Analysis.
COUNTRY GROUPS: lookup_team_countries gives the team country table (ISO3, IFS code, name variants) and the
team income groups AE / EM / LIC. When the economist asks for "EMs", "LICs" or "advanced economies"
without naming a classification, use the team groups (state it); use official WEO groups when asked.
For group averages of fiscal variables also fetch the fiscal-year nominal GDP in US dollars (team weight,
NGDP_FY_USD); search the indicator catalog for it and ask the economist if no exact match is found.
For other indicators fetch NGDPD as weight. If you cannot decide between definitions, ask.
"""


def research_tool_result(name: str, arguments: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    if name == "lookup_team_countries":
        return lookup_team_countries(arguments)
    series = _RESEARCH_SERIES.get(name)
    if series is None:
        raise ValueError(f"Unsupported tool: {name}")
    frame, lineage = bloomberg.fetch_series(
        series,
        frequency=arguments.get("frequency") or "M",
        start_period=arguments.get("start_period") or None,
        end_period=arguments.get("end_period") or None,
        countries=arguments.get("countries") or None,
        ticker_path=_config["ticker_paths"].get(series),
        fetcher=_config["fetcher"],
    )
    if frame.empty:
        return {"source": lineage["source"], "request": lineage["request"], "count": 0, "available": False,
                "observations": [], "note": "No observations returned. This may be an access/session issue, "
                                            "not proof that the series does not exist."}
    state["frame"] = frame
    retrieved = state.setdefault("retrieved_frames", {})
    retrieval_id = f"retrieval_{len(retrieved) + 1}"
    lineage = [{**lineage, "retrieval_id": retrieval_id}]
    retrieved[retrieval_id] = {"frame": frame.copy(), "source": lineage[0]["source"],
                               "request": lineage[0]["request"], "lineage": lineage}
    state["frame_lineage"] = lineage
    latest = frame.groupby("country_name")["TIME_PERIOD"].max()
    return {
        "skill_id": series, "source": lineage[0]["source"], "request": lineage[0]["request"],
        "retrieval_id": retrieval_id, "count": len(frame), "unit": frame["UNIT"].iloc[0],
        "countries": int(frame["COUNTRY"].nunique()),
        "period_range": [frame["TIME_PERIOD"].min(), frame["TIME_PERIOD"].max()],
        "latest_period_by_country": {k: v for k, v in list(latest.items())[:40]},
        "countries_without_data": lineage[0]["coverage"].get("missing_requested_areas", {}).get("country", []),
        "full_dataset_in_table_and_download": True,
        "observations": _records(frame, 20),
        "preview_notice": "The full dataframe is in the table/download; do not print every row.",
    }


# --------------------------------------------------------------------------------------------
# Analysis stage: run skills on handed-off datasets
# --------------------------------------------------------------------------------------------
_DATASET_IDS = {"type": "array", "items": {"type": "string"}, "minItems": 1,
                "description": "Handed-off dataset ids that hold the inputs (they are combined)."}
_PARAMS = {
    "type": "object",
    "description": "Skill parameters; omit any to use the defaults from list_analysis_skills.",
    "properties": {
        "start_year": {"type": ["integer", "null"]}, "end_year": {"type": ["integer", "null"]},
        "groups": {"type": ["array", "null"], "items": {"type": "string"},
                   "description": "Default ['income'] = team classification (Global, AE, EM, LIC from the "
                                  "country dummy file). Also 'AE' / 'EM' / 'LIC' individually, ['weo_income'] "
                                  "(official WEO AE / EMMIE / LIDC) or other official WEO group names. "
                                  "Empty list = country-level output only."},
        "weight": {"type": ["string", "null"],
                   "description": "'auto' (default: NGDP_FY_USD for fiscal variables, NGDPD otherwise), "
                                  "an indicator code in the data, or 'none' for simple means."},
        "method": {"type": ["string", "null"], "enum": ["standard", "contemporaneous", None]},
        "measure": {"type": ["string", "null"], "enum": ["rlessg_abs", "rlessg", None],
                    "description": "r_minus_g: which column the group statistics use."},
        "indicator": {"type": ["string", "null"], "description": "group_statistics: indicator code."},
        "outlier_floor": {"type": ["number", "null"], "description": "dspb: gaps at/below this are dropped."},
    },
    "additionalProperties": False,
}
COUNTRY_TOOL = _fn(
    "lookup_team_countries",
    "Background knowledge: the team country table (ISO3, IFS code, name variants) and income classification "
    "(AE / EM / LIC from the team country dummy file). Give names/codes to identify them, a group to list its "
    "members, or both null for the group sizes. Use it to build country lists for retrieval and to explain groups.",
    {"query": {"type": ["array", "null"], "items": {"type": "string"}},
     "group": {"type": ["string", "null"], "enum": ["AE", "EM", "LIC", None]}})


def lookup_team_countries(arguments: dict[str, Any]) -> dict[str, Any]:
    table = countries.tables()["countries"]
    result: dict[str, Any] = {"source": "team Country Codes.xlsx + country dummy file (knowledge/countries.csv)"}
    query = arguments.get("query") or []
    if query:
        info = countries.classify(query)
        result["matches"] = info.to_dict("records")
        result["unmatched"] = info[info["kind"] == "unknown"]["value"].tolist()
    group = arguments.get("group")
    if group:
        members = table[table["income_group"] == group][["iso3", "ifscode", "country"]]
        result["group"] = {"code": group, "label": countries.INCOME_GROUPS[group], "count": len(members),
                           "iso3": members["iso3"].tolist(), "members": members.to_dict("records")}
    if not query and not group:
        result["groups"] = {code: {"label": label, "count": int((table["income_group"] == code).sum())}
                            for code, label in countries.INCOME_GROUPS.items()}
    return result


ANALYSIS_TOOLS = [
    COUNTRY_TOOL,
    _fn("list_analysis_skills", "List the analysis skills with required indicators and default parameters.", {}),
    _fn("list_handed_off_datasets", "List handed-off datasets with ids, titles, columns and indicator codes.", {}),
    _fn("check_analysis_requirements",
        "Check whether the selected handed-off datasets contain everything a skill needs (indicators, annual "
        "frequency, lag year, weight). Returns what is missing and exactly what to fetch in Research.",
        {"skill_id": {"type": "string"}, "dataset_ids": _DATASET_IDS, "params": _PARAMS}),
    _fn("run_analysis_skill",
        "Run a tested analysis skill on handed-off datasets. Saves table outputs (country level, group "
        "statistics, chart table) with a recipe. Refuses when requirements are missing.",
        {"skill_id": {"type": "string"}, "dataset_ids": _DATASET_IDS,
         "output_name": {"type": "string", "description": "Short lowercase name, e.g. rminusg_weo."},
         "params": _PARAMS}),
]
ANALYSIS_TOOL_NAMES = {tool["function"]["name"] for tool in ANALYSIS_TOOLS}
RESEARCH_TOOLS.append(COUNTRY_TOOL)
RESEARCH_TOOL_NAMES.add("lookup_team_countries")


def _dataset(handoff: dict[str, Any], dataset_id: str) -> dict[str, Any]:
    for dataset in handoff["datasets"]:
        if dataset["id"] == dataset_id:
            return dataset
    raise ValueError(f"Unknown dataset_id {dataset_id!r}. Use list_handed_off_datasets.")


def _indicator_codes(frame: pd.DataFrame) -> list[str]:
    for column in ("INDICATOR", "indicator"):
        if column in frame.columns:
            return sorted(frame[column].dropna().astype(str).str.upper().unique().tolist())[:60]
    return []


def _panel(handoff: dict[str, Any], dataset_ids: list[str]) -> pd.DataFrame:
    return to_annual_panel([_dataset(handoff, dataset_id)["frame"] for dataset_id in dataset_ids])


def _resolve_groups(names: list[str] | None, panel: pd.DataFrame, warnings: list[str]) -> dict[str, list[str]] | None:
    """Map group names to the country identifiers used in the data.

    'income' (default) and AE / EM / LIC use the team dummy file; 'weo_income' and other names use the
    official WEO country-group list through the configured expander.
    """
    values = panel["country"].astype(str).unique()
    if not names:
        info = countries.classify(values)
        return {"All countries": info[info["kind"] == "country"]["value"].tolist()}
    lowered = [str(name).strip() for name in names]
    if [name.casefold() for name in lowered] == ["income"]:
        groups, _ = countries.income_groups(values)
        return groups
    codes = [countries.income_code(name) for name in lowered]
    if all(codes):
        groups, _ = countries.income_groups(values, which=codes, include_global=False)
        union = sorted(set().union(*groups.values()))
        return {"All countries (in selected groups)": union, **groups} if len(groups) > 1 else groups
    if [name.casefold() for name in lowered] == ["weo_income"]:
        lowered = WEO_INCOME_GROUPS
    expander = _config["group_expander"]
    if expander is None:
        try:
            from idata_client import expand_country_group as expander  # the web app's own helper
        except ImportError as exc:
            raise RuntimeError("Official WEO group expansion is unavailable here; use the team groups "
                               "(groups: ['income']) or configure(group_expander=...).") from exc
    available = set(values)
    groups: dict[str, list[str]] = {}
    for name in lowered:
        members = [str(code) for code in expander(name)["countries"]]
        absent = sorted(set(members) - available)
        if absent:
            warnings.append(f"{name}: {len(absent)} member(s) not in the data, e.g. {absent[:8]}.")
        groups[name] = sorted(set(members) & available)
    union = sorted(set().union(*groups.values())) if groups else []
    return {"All countries (in selected groups)": union, **groups}


def _store(handoff: dict[str, Any], name: str, frame: pd.DataFrame, description: str,
           recipe: dict[str, Any], dataset_ids: list[str], persist: bool) -> dict[str, Any]:
    if handoff.setdefault("outputs", {}).get(name, {}).get("kind") == "workbook":
        raise ValueError(f"{name!r} is a workbook; choose another output name.")
    frame = frame.replace([np.inf, -np.inf], np.nan).reset_index(drop=True)
    output = {
        "name": name, "kind": "table", "description": description,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "recipe": recipe,
        "datasets_used": sorted(dataset_ids), "rows": len(frame), "columns": [str(c) for c in frame.columns],
        "empty_cells": int(frame.isna().sum().sum()), "frame": frame,
    }
    handoff["outputs"][name] = output
    if persist:
        saver = _config["output_saver"]
        if saver is None:
            try:
                from dataset_store import save_output as saver  # the web app's own writer
            except ImportError:
                saver = None
        if saver is not None:
            saver(handoff, output)
    return output


def _years(frame: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    if params.get("start_year") is not None:
        frame = frame[frame["year"] >= int(params["start_year"])]
    if params.get("end_year") is not None:
        frame = frame[frame["year"] <= int(params["end_year"])]
    return frame.reset_index(drop=True)


def _run(skill_id: str, panel: pd.DataFrame, params: dict[str, Any], warnings: list[str],
         weight: str | None) -> tuple[dict[str, tuple[pd.DataFrame, str]], list[str]]:
    """Return {suffix: (frame, description)} and method notes. ``weight`` comes from the requirement check."""
    weight = weight if weight and weight in panel.columns else ""
    groups = _resolve_groups(params.get("groups"), panel, warnings) if (
        params.get("groups") or skill_id == "group_statistics") else None
    span = {"start_year": params.get("start_year"), "end_year": params.get("end_year")}
    for name, members in (groups or {}).items():
        if not members:
            warnings.append(f"Group '{name}' has no countries in the data; its columns stay empty.")
    tables: dict[str, tuple[pd.DataFrame, str]] = {}

    if skill_id == "r_minus_g":
        result, notes = fiscal.r_minus_g(panel, method=params.get("method") or "standard")
        inputs = panel[["country", "year", "GGEI", "GGXWDG", "NGDP"] + ([weight] if weight else [])]
        country = _years(inputs.merge(result, on=["country", "year"]), params)
        tables["country"] = (country, "r - g by country and year (percent). r = GGEI_t / GGXWDG_t-1, "
                                      "g = nominal GDP growth; rlessg = (r-g)/(1+g), rlessg_abs = r-g.")
        if groups:
            measure = params.get("measure") or "rlessg_abs"
            stats = aggregate.group_statistics(country, measure, groups, weight or None, **span)
            tables["groups"] = (stats, f"Group statistics of {measure} by year.")
            column = "weighted_mean" if weight else "mean"
            tables["chart"] = (aggregate.chart_table(stats, column, list(groups)), f"{column} of {measure}, year x group.")
        return tables, notes

    if skill_id == "dspb":
        result, notes = fiscal.dspb(panel, outlier_floor=params.get("outlier_floor", -10.0))
        extra = panel[["country", "year"] + ([weight] if weight else [])]
        country = _years(extra.merge(result, on=["country", "year"]), params)
        tables["country"] = (country, "Debt-stabilizing primary balance (dspb = d_t-1 (r-g)/(1+g)) and "
                                      "pb_gap = actual primary balance - dspb, % of GDP.")
        if groups:
            tables["summary"] = (aggregate.dspb_summary(country, groups, weight or None, **span),
                                 "Per group/year: share of countries with pb_gap < 0 and distribution of "
                                 "their gaps (weighted_mean uses the weight).")
            means = []
            for column in ("pb", "dspb", "pb_gap"):
                stats = aggregate.group_statistics(country, column, groups, weight or None, **span)
                stats = stats[["group", "year", "weighted_mean" if weight else "mean"]]
                means.append(stats.rename(columns={stats.columns[-1]: column}).set_index(["group", "year"]))
            tables["group_means"] = (pd.concat(means, axis=1).reset_index(),
                                     "Group averages of pb, dspb and pb_gap (weighted when a weight is set).")
        return tables, notes

    if skill_id == "group_statistics":
        indicator = str(params["indicator"]).upper()
        stats = aggregate.group_statistics(panel, indicator, groups, weight or None, **span)
        tables["stats"] = (stats, f"Group statistics of {indicator} by year.")
        column = "weighted_mean" if weight else "mean"
        tables["chart"] = (aggregate.chart_table(stats, column, list(groups)), f"{column} of {indicator}, year x group.")
        return tables, []

    raise ValueError(f"Skill {skill_id!r} does not run in the analysis stage.")


def analysis_tool_result(name: str, arguments: dict[str, Any], handoff: dict[str, Any],
                         persist: bool = True) -> dict[str, Any]:
    if name == "lookup_team_countries":
        return lookup_team_countries(arguments)
    if name == "list_analysis_skills":
        return {"skills": [item for item in catalog() if item["stage"] in {"analysis", "background"}],
                "retrieval_skills_in_research": [item["skill_id"] for item in catalog() if item["stage"] == "research"]}
    if name == "list_handed_off_datasets":
        return {"handoff_id": handoff["id"], "datasets": [
            {"dataset_id": item["id"], "title": item["title"], "rows": item["rows"], "columns": item["columns"],
             "indicators": _indicator_codes(item["frame"]), "warnings": item.get("warnings", [])}
            for item in handoff["datasets"]]}

    skill = get_skill(str(arguments["skill_id"]))
    params = {**skill.params, **{k: v for k, v in (arguments.get("params") or {}).items() if v is not None}}
    dataset_ids = [str(item) for item in arguments["dataset_ids"]]
    try:
        panel = _panel(handoff, dataset_ids)
    except PanelError as exc:
        return {"ok": False, "skill_id": skill.id, "error": str(exc)}
    check = check_requirements(skill.id, panel, params)

    if name == "check_analysis_requirements":
        return {**check, "countries": int(panel["country"].nunique()),
                "years": [int(panel["year"].min()), int(panel["year"].max())], "params": params}

    if name == "run_analysis_skill":
        if not check["ok"]:
            return {**check, "executed": False,
                    "message": "Nothing was computed. Ask the economist the questions_for_user and/or tell them "
                               "what to fetch (fetch_in_research), then rerun with their answer in params."}
        base = str(arguments["output_name"]).strip().lower()
        if not _OUTPUT_NAME.fullmatch(base):
            raise ValueError("output_name: 1-51 letters, digits, '_' or '-'.")
        warnings = list(check["warnings"])
        tables, notes = _run(skill.id, panel, params, warnings, check.get("weight"))
        recipe = {"skill_id": skill.id, "params": params, "dataset_ids": dataset_ids,
                  "method_note": skill.reference, "origin": skill.origin}
        saved = []
        for suffix, (frame, description) in tables.items():
            output = _store(handoff, f"{base}_{suffix}", frame, f"[{skill.title}] {description}",
                            recipe, dataset_ids, persist)
            saved.append({"output": output["name"], "rows": output["rows"], "columns": output["columns"],
                          "empty_cells": output["empty_cells"], "preview": _records(frame)})
        return {"ok": True, "executed": True, "skill_id": skill.id, "outputs": saved,
                "notes": notes, "warnings": warnings, "params": params}

    raise ValueError(f"Unsupported tool: {name}")
