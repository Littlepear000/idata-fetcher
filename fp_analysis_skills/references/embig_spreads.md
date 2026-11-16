# embig_spreads: EMBIG sovereign spreads (Bloomberg)

Origin: `fadfp_useful_charts/EMBIG/embig.py` (and the quarterly `coding sample.py`).
Code: `fp_analysis/bloomberg.py::fetch_series("embig_spreads", ...)`. Tool: `fetch_embig_spreads`
(Research stage).

## What it does

1. Reads the team ticker table (`data/embig_tickers.csv`, or the original workbook
   `Bloomberg EMBIG tickers.xlsx`, sheet `filtered_list`).
2. Normalizes tickers (upper case, spaces -> `_`) and queries iData database `IMF.CSF:BBGDL` with key
   `TICKER1+TICKER2+....PX_LAST.D` (daily last price), in chunks of 25 tickers.
3. Averages daily values within each period: `D` none, `W`, `M` (default), `Q`, `A`.
4. Returns one long dataset: source, database, INDICATOR (`EMBIG_SPREAD`), COUNTRY (ISO3; the country
   name when no ISO3 is given, e.g. `Global`), country_name, IFSCODE, ticker, FREQUENCY, TIME_PERIOD,
   OBS_VALUE, UNIT (basis points), n_daily_obs.

## Preconditions

- `imf_datatools` installed and an authorized iData session with access to `IMF.CSF:BBGDL`
  (`idata_utilities.PRIVATE = True` is set by the fetcher).
- The ticker table is filled. **It ships empty**: copy the rows from the team workbook (ticker,
  country, ifscode). ISO3 codes are filled automatically from the team country table (by IFS code,
  else by name), so results line up with WEO Live country codes. Only countries in the table can be fetched.
- Default period starts in 2008-01 (as in the team scripts). Earlier dates may have sparse coverage.

## Limits and pitfalls

- Spreads are in **basis points** over US Treasuries (stripped spread); do not mix with yields.
- Period averages are simple means of available trading days; `n_daily_obs` shows how many days
  entered each value. The current period is an average-to-date.
- An empty result or a missing country is usually an access, ticker or session problem, not proof
  that no data exist; the tool lists countries without data.
- EMBIG index composition changes over time (countries enter and exit); a country's series can start
  late or stop.
