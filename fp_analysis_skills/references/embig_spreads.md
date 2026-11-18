# embig_spreads: EMBIG sovereign spreads (Bloomberg)

Origin: `fadfp_useful_charts/EMBIG/embig.py` (and the quarterly `coding sample.py`).
Code: `fp_analysis/bloomberg.py::fetch_series("embig_spreads", ...)`. Tool: `fetch_embig_spreads`
(Research stage).

## What it does

1. Reads the team ticker table `knowledge/embig_tickers.csv` (or, if configured, the original
   workbook `Bloomberg EMBIG tickers.xlsx`, sheet `filtered_list`).
2. Normalizes tickers exactly as `embig.py` (upper case, each space -> `_`, so the padded
   `JPSSGBY  Index` becomes `JPSSGBY__INDEX`) and queries iData database `IMF.CSF:BBGDL` with key
   `TICKER1+TICKER2+....PX_LAST.D` (daily last price), in chunks of 25 tickers.
3. Averages daily values within each period: `D` none, `W`, `M` (default), `Q`, `A`.
4. Returns one long dataset: source, database, INDICATOR (`EMBIG_SPREAD`), COUNTRY (ISO3; the country
   name when no ISO3 is given, e.g. `Global`), country_name, IFSCODE, ticker, FREQUENCY, TIME_PERIOD,
   OBS_VALUE, UNIT (basis points), n_daily_obs.

## Preconditions

- `imf_datatools` installed and an authorized iData session with access to `IMF.CSF:BBGDL`
  (`idata_utilities.PRIVATE = True` is set by the fetcher).
- Only countries in the ticker table can be fetched (see Coverage). `countries` accepts names, ISO3,
  IFS codes, `Global`, or the team income groups `AE` / `EM` / `LIC`.
- Default period starts in 2008-01 (as in the team scripts). Earlier dates may have sparse coverage.

## Coverage (team ticker table, background knowledge)

`knowledge/embig_tickers.csv` is built from the team workbook `Bloomberg EMBIG tickers.xlsx`, sheet
`filtered_list` (the sheets `full_list` and `with_formula` are Bloomberg search dumps and are not used),
by `scripts/build_embig_tickers.py`. ISO3, the standard country name and the team income group are added
from `knowledge/countries.csv`. Columns: ticker, country (as in the workbook), country_name, iso3,
ifscode, income_group, active, verified, note.

63 tickers: the **EMBIG Global composite** (`JPEGCOMP Index`, IFS code 1, not a country) and 62 countries:

| Team group | n | Countries (ISO3) |
|---|---|---|
| EM | 48 | AGO ARG ARM AZE BLR BLZ BOL BRA CHL CHN COL CRI DOM ECU EGY SLV GAB GTM HUN IND JAM JOR KAZ LBN MYS MEX MNG MAR NAM OMN PAK PAN PRY PER PHL POL ROU RUS ZAF LKA SUR TTO TUN TUR UKR URY VEN VNM |
| LIC | 10 | CIV GHA HND MOZ NGA PNG RWA SEN TJK ZMB |
| AE | 4 | HRV LVA LTU SVK (now advanced economies; kept for history) |

Not every EM or LIC has an EMBIG spread: a group average of EMBIG covers only these countries, so say
so when reporting "EM spreads". Ticker families differ (`JPSSG..` sovereign spread, `JPEG..SS`,
`JPGCRWID` for Rwanda); Vietnam uses `ELI GVIT Index`, which is not a J.P. Morgan code: check its
level against other spreads before relying on it. Rebuild after the workbook changes:
`python scripts/build_embig_tickers.py "Bloomberg EMBIG tickers.xlsx"`.

## Limits and pitfalls

- Spreads are in **basis points** over US Treasuries (stripped spread); do not mix with yields.
- Period averages are simple means of available trading days; `n_daily_obs` shows how many days
  entered each value. The current period is an average-to-date.
- An empty result or a missing country is usually an access, ticker or session problem, not proof
  that no data exist; the tool lists countries without data.
- EMBIG index composition changes over time (countries enter and exit); a country's series can start
  late or stop.
