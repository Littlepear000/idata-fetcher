# bond_yield_10y: 10-year government bond yields (Bloomberg)

Origin: `fadfp_useful_charts/10y bond yield/temp.py` (Bloomberg pull through `imf_datatools`),
using the same iData route as EMBIG. Code: `fp_analysis/bloomberg.py::fetch_series("bond_yield_10y", ...)`.
Tool: `fetch_bond_yield_10y` (Research stage).

## What it does

Same mechanics as `embig_spreads`: tickers from `data/bond_yield_10y_tickers.csv`, iData
`IMF.CSF:BBGDL`, key `TICKERS.PX_LAST.D`, chunks of 25, period averages (default monthly from
2008-01). INDICATOR is `GOVT_YIELD_10Y`, UNIT `Percent per annum`.

## Preconditions

- `imf_datatools` with an authorized iData session that can read `IMF.CSF:BBGDL`.
- The ticker table. It ships with **unverified seed rows** for nine advanced economies (Bloomberg
  generic tickers such as `USGG10YR Index`, `GDBR10 Index`). Before relying on them, run the tool once,
  confirm each country returns data, and set `verified=yes`. Add emerging-market tickers as needed.
- Countries not in the table cannot be fetched by this tool; the Research assistant can still look for
  yields in other connected sources (e.g. OECD long-term interest rates, IMF IFS), which are different
  definitions (monthly averages of benchmark bonds) and must be labelled as such.

## Limits and pitfalls

- Generic tickers roll to the current benchmark bond; the series is not a constant-maturity yield.
- Local-currency yields are not comparable across countries without considering inflation and
  currency; real yields or spreads are separate analyses.
- Same averaging and empty-result caveats as `embig_spreads`.
