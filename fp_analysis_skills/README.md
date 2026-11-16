# FP analysis skills: add-on for the economic-data web app

A self-contained folder that adds **analysis skills** to the Streamlit research app
(`data_retrieving-github`) without changing how the app's own modules work. Copy the folder in,
add a few lines at the three points below, and the app gains:

| Skill | Stage in the app | What the economist gets |
|---|---|---|
| `embig_spreads` | Research (retrieval shortcut) | EMBIG sovereign spreads from Bloomberg, averaged to D/W/M/Q/A, saved as one dataset |
| `bond_yield_10y` | Research (retrieval shortcut) | 10-year government bond yields from Bloomberg, same |
| `r_minus_g` | Analysis (after hand-off) | r, g, r - g by country/year + group statistics + chart table |
| `dspb` | Analysis | Debt-stabilizing primary balance, gap, share of countries below it by group |
| `group_statistics` | Analysis | Mean / weighted mean / percentiles of any indicator by group and year |
| `country_groups` | Background (both stages) | Country codes (ISO3 / IFS / name variants) and the team AE / EM / LIC classification; tool `lookup_team_countries` |

The formulas come from the team scripts in `fadfp_useful_charts` (R minus G, DSPB, EMBIG,
10y bond yield) and the aggregation helpers in `fadfpdata`; each skill's method note names its origin.

## How it fits the app's flow

```
Research (openai_agent)  ->  Review & hand off  ->  Format (formatting_agent)
   + fetch_embig_spreads                         ->  Analysis (fp_analysis.agent)   <- new, optional view
   + fetch_bond_yield_10y
```

- **Research**: three extra tools (EMBIG, 10Y yields, country lookup). They follow the same contract as `external_tool_result`: they set
  `state["frame"]` / `state["frame_lineage"]` and register a `retrieval_id`, so the turn is saved as one
  dataset by `dataset_store.create_dataset`, coverage warnings show in Review, and
  `combine_retrieved_data` can merge EMBIG and yields into one CSV.
- **Analysis**: a separate assistant over the **same hand-off object** the Format view uses. It never
  fetches. Its tools check whether the handed-off datasets hold every input a skill needs and, if not,
  return exactly what to fetch in Research (database, codes, first year). Results are saved as
  ordinary table outputs in `handoff["outputs"]` (with a recipe), so the existing output cards, CSV/Excel
  downloads, ZIP and Workbench inputs work unchanged. Keeping it separate respects the Format rule
  "no aggregation".
- All computation is deterministic pandas code, tested offline. The model only chooses the skill and
  parameters; it never writes the calculation.

## Folder contents

```
fp_analysis_skills/
  SKILL.md                  system prompt of the Analysis assistant (model-facing rules + catalog)
  references/<skill>.md     method notes: formula, required WEO codes, parameters, outputs, limits
  fp_analysis/
    tools.py                tool schemas + dispatch for both stages, configure() hooks
    agent.py                run_analysis_agent: bounded tool loop, same shape as run_formatting_agent
    registry.py             skill catalog and check_requirements (what is missing, what to fetch)
    panel.py                handed-off long datasets -> annual country-year panel (no gap filling)
    fiscal.py               r_minus_g, dspb
    aggregate.py            group_statistics, dspb_summary, chart_table
    bloomberg.py            EMBIG / 10Y yields from iData IMF.CSF:BBGDL (PX_LAST.D, chunks of 25)
    countries.py            country lookup (ISO3 / IFS code / name), aggregates, AE / EM / LIC groups
  knowledge/                country tables built from Country Codes.xlsx + the team dummy file
  scripts/build_country_knowledge.py   rebuilds knowledge/ when either workbook changes
  data/                     team ticker tables (EMBIG: to fill; 10Y: unverified seed rows)
  integration/analysis_view.py   example Streamlit view for the Analysis workspace
  tests/test_skills.py      offline tests (synthetic data, fake Bloomberg fetcher)
```

Dependencies: pandas, numpy (already in the app); `imf_datatools` only for the Bloomberg tools.
Tested with pandas 2.1 / 2.2.

## Integration (three small edits)

**0. Copy and import path.** Put the folder next to `streamlit_app.py` and, near the top of
`streamlit_app.py` (before importing `openai_agent`):

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "fp_analysis_skills"))
```

**1. Research tools** (`openai_agent.py`):

```python
from fp_analysis.tools import (RESEARCH_PROMPT_ADDENDUM, RESEARCH_TOOL_NAMES, RESEARCH_TOOLS,
                               research_tool_result)

SYSTEM_PROMPT += RESEARCH_PROMPT_ADDENDUM      # after SYSTEM_PROMPT is defined
TOOLS.extend(RESEARCH_TOOLS)                   # next to TOOLS.extend(EXTERNAL_TOOLS)

# in _tool_result, before `if name in EXTERNAL_TOOL_NAMES:`
    if name in RESEARCH_TOOL_NAMES:
        return research_tool_result(name, arguments, state)
```

**2. Analysis view** (`streamlit_app.py`): add `"Analysis"` to `VIEWS` and render
`integration/analysis_view.py::render_analysis` for it (copy that file next to `handoff_views.py`).
If you prefer not to add a view, you can call `fp_analysis.agent.run_analysis_agent(history, handoff)`
from anywhere that has a hand-off.

**3. Optional configuration** (once at start-up), only if the defaults do not suit:

```python
from fp_analysis.tools import configure
configure(
    ticker_paths={"embig_spreads": r"...\Bloomberg EMBIG tickers.xlsx"},  # xlsx (sheet filtered_list) or csv
    # fetcher=..., group_expander=..., output_saver=...   defaults: imf_datatools, idata_client.expand_country_group,
    #                                                     dataset_store.save_output
)
```

## Before first use

- **EMBIG ticker table** `data/embig_tickers.csv` ships empty. Fill it from the team workbook
  `Bloomberg EMBIG tickers.xlsx` (sheet `filtered_list`) and add ISO3 codes, or point
  `configure(ticker_paths=...)` at the workbook.
- **10Y ticker table** has nine unverified Bloomberg generic tickers. Run `fetch_bond_yield_10y` once,
  check every country returns data, then mark `verified=yes`.
- **WEO codes.** The fiscal skills expect the WEO Live mnemonics `GGEI`, `GGXWDG`, `NGDP`,
  `GGXWDG_NGDP`, `GGXONLB_NGDP`, `NGDPD`. The Research assistant resolves codes from the live catalog;
  if a code differs there, change it in `fp_analysis/registry.py` (one place).
- **Country groups.** Default groups are the team classification shipped in `knowledge/`
  (Global, AE 43, EM 96, LIC 58, from the dummy file of 2026-01-15); no network needed. Data identified
  by ISO3 (WEO Live), IFS code or country name are all matched. Official WEO groups remain available
  with `groups: ["weo_income"]` through `idata_client.expand_country_group`.
- **Weights.** Fiscal variables are weighted by fiscal-year nominal GDP in USD (`NGDP_FY_USD`, the
  team's `ngdp_fy_usd`); other indicators by `NGDPD`. Confirm the exact WEO Live code of the fiscal-year
  series and, if it differs, change `FISCAL_WEIGHT` in `fp_analysis/registry.py`. When the weight is
  not in the handed-off data, the assistant asks the economist (fetch it / use NGDPD / simple means).
- **Asking the user.** `check_analysis_requirements` returns `questions_for_user` whenever the program
  cannot decide (default weight absent, unknown country code). The assistant asks in its reply and runs
  only after the answer; no extra UI is needed.

## Typical session

1. Research: "Fetch GGEI, GGXWDG, NGDP and NGDPD from WEO Live, all countries, 1999-2030, annual."
   (Adding the fiscal-year USD GDP series here avoids the weight question below.)
   Review, hand off.
2. Analysis: "r - g by income group since 2000, GDP-weighted."
   -> `check_analysis_requirements` asks: "NGDP_FY_USD is not in the data: fetch it, use NGDPD, or simple
   means?" -> economist: "use NGDPD" -> `run_analysis_skill` -> outputs `rminusg_country`,
   `rminusg_groups`, `rminusg_chart` (Global / AE / EM / LIC), ready to download or arrange in Format.
3. If the economist then asks for the DSPB, the check reports `GGXWDG_NGDP` and `GGXONLB_NGDP`
   missing and the assistant says what to fetch in Research.

## Tests

```bash
cd fp_analysis_skills
python -m unittest discover -s tests -v
```

27 offline tests: r - g against hand calculation, lag not crossing a missing year, DSPB and the
outlier rule, weighted means and coverage, requirement checks and user questions, the fiscal-weight
rule, country lookup and income groups, Bloomberg chunking/averaging/labels/ISO3 filling, and both tool
dispatchers (state and hand-off outputs).

## Adding a skill

1. Write the pure function (`fiscal.py` or a new module) and a test.
2. Register a `Skill` in `registry.py` (required codes, lag years, defaults, method note path).
3. Add its branch in `tools._run` (which tables to save).
4. Write `references/<skill_id>.md` and add a row to the catalog in `SKILL.md`.
