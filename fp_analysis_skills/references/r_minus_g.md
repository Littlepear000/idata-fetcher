# r_minus_g: interest-growth differential

Origin: `fadfp_useful_charts/R minus G/rminusg.py` (standard) and `rminusg_carlos.py` (contemporaneous).
Code: `fp_analysis/fiscal.py::r_minus_g`.

## Definition

| Term | Formula | Unit |
|---|---|---|
| g | NGDP_t / NGDP_t-1 - 1 | % (nominal GDP growth, national currency) |
| r (standard) | GGEI_t / GGXWDG_t-1 | % (effective interest rate on last year's debt stock) |
| rlessg | (r - g) / (1 + g) | pp, growth-adjusted: the term that multiplies d_t-1 in debt dynamics |
| rlessg_abs | r - g | pp, plain difference (used for the team chart in the latest script) |

`method: "contemporaneous"` divides interest by the **same year's** debt (r = GGEI_t / GGXWDG_t) and
reports the plain difference only. It is an approximation kept for comparability with older charts.

## Requirements

| Code (WEO Live) | Label | Why |
|---|---|---|
| `GGEI` | General government interest expense, national currency | numerator of r |
| `GGXWDG` | General government gross debt, national currency | denominator of r (t-1) |
| `NGDP` | GDP, current prices, national currency | g |
| `NGDP_FY_USD` | Nominal GDP, fiscal year, US dollars | weight for group averages (fiscal-variable rule); confirm its WEO Live code in the indicator catalog |

- **Annual** frequency. Same countries for all three series.
- **One extra year**: output year Y needs Y-1 for `GGXWDG` and `NGDP`. Fetch from `start_year - 1`.
- The three level series must share the same currency and SCALE. Fetch them **in one request** so
  the iData client divides them by the same scale; the check warns if SCALE labels differ.
- The codes above are the WEO mnemonics used by the team; confirm them in the indicator catalog when
  fetching (the Research assistant resolves every code).

## Parameters

| Name | Default | Notes |
|---|---|---|
| `method` | `standard` | or `contemporaneous` |
| `start_year`, `end_year` | 2000, none | output years |
| `groups` | `["income"]` | team Global / AE / EM / LIC (see country_groups); `["weo_income"]` for official WEO groups; `[]` for country level only |
| `weight` | `auto` = `NGDP_FY_USD` | as in the team scripts (`ngdp_fy_usd`). If it is not in the data the assistant asks: fetch it, use `NGDPD`, or `none` (simple means). |
| `measure` | `rlessg_abs` | column summarised by group: `rlessg_abs` or `rlessg` |

## Outputs

- `<name>_country`: country, year, GGEI, GGXWDG, NGDP, (weight), r, g, rlessg, rlessg_abs.
- `<name>_groups`: group, year, n_countries, mean, weighted_mean, median, p10, p25, p75,
  p90, iqr, p10_p90, weight_coverage.
- `<name>_chart`: year x group, weighted mean (or mean without weight). With the default
  groups the columns are Global, Advanced Economies, Emerging Markets, Low-Income Developing Countries.

## Limits and pitfalls

- r is an implicit average cost of the whole debt stock, not a marginal or market rate. It moves
  slowly and is distorted when debt is restructured, revalued (FX-denominated debt) or when interest
  is recorded on an accrual basis different from the debt valuation.
- Debt near zero gives extreme r; values where GGXWDG_t-1 = 0 are left empty. Large outliers
  (e.g. hyperinflation, Venezuela in the FM table) are **not** removed automatically; mention them
  when they drive group averages.
- Projection years (after WEO's latest actual year) are projections; say so.
- A missing year breaks the lag: the following year is empty rather than lagged over the gap.
