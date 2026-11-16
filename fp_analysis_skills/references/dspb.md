# dspb: debt-stabilizing primary balance

Origin: `fadfp_useful_charts/DSPB/dspb.py`. Code: `fp_analysis/fiscal.py::dspb`,
`fp_analysis/aggregate.py::dspb_summary`.

## Definition

The primary balance that keeps the gross debt ratio constant from t-1 to t:

```
dspb_t   = d_t-1 * (r_t - g_t) / (1 + g_t)       d = GGXWDG_NGDP (% of GDP); r, g as in r_minus_g (standard)
pb_gap_t = pb_t - dspb_t                          pb = GGXONLB_NGDP (% of GDP)
```

`pb_gap < 0`: the primary balance is below the stabilizing level, so the debt ratio rises (ignoring
stock-flow adjustments). `pb_gap > 0`: debt ratio falls.

## Requirements

| Code (WEO Live) | Label | Why |
|---|---|---|
| `GGEI`, `GGXWDG`, `NGDP` | see r_minus_g | r and g |
| `GGXWDG_NGDP` | Gross debt, % of GDP | d_t-1. If absent, derived as GGXWDG / NGDP * 100 (warning) |
| `GGXONLB_NGDP` | Primary net lending/borrowing, % of GDP | pb. If absent and `GGXONLB` is present, derived as GGXONLB / NGDP * 100 (warning) |
| `NGDP_FY_USD` | Nominal GDP, fiscal year, US dollars | weight for group figures (fiscal-variable rule) |

Annual data from `start_year - 1`; same countries for all series; level series in one request.
Derived ratios use calendar-year GDP and can differ from the published ratio for countries that
report on a fiscal-year basis; prefer fetching the published ratios.

## Parameters

| Name | Default | Notes |
|---|---|---|
| `start_year`, `end_year` | 2000, none | |
| `groups` | `["income"]` | team Global / AE / EM / LIC; `["weo_income"]`; `[]` for country level only |
| `weight` | `auto` = `NGDP_FY_USD` | if absent, the assistant asks: fetch it, use `NGDPD`, or `none` |
| `outlier_floor` | -10 | gaps at or below it are set to missing and flagged (`gap_excluded`), as in dspb.py; `null` keeps all |

## Outputs

- `<name>_country`: country, year, (weight), rlessg, debt_l1, pb, dspb, pb_gap, gap_excluded.
- `<name>_summary`: per group/year, n_countries with a gap, n_below and share_below (%)
  of countries with pb_gap < 0, and among those: p25, median, p75, iqr, weighted_mean of the gap.
- `<name>_group_means`: weighted (or simple) group averages of pb, dspb and pb_gap.

## Limits and pitfalls

- The share uses countries **with a gap value** as denominator. dspb.py divided by all countries in
  the group-year rows, including those with missing gaps; shares here can be slightly higher.
- The outlier rule drops only very negative gaps (deficits far beyond the stabilizing level); it is
  a presentation choice, not a data correction. Always report how many were excluded.
- The formula ignores stock-flow adjustments, exchange-rate valuation of FX debt and privatization
  receipts; it is the standard simplified debt-dynamics identity.
- When g is close to -100% the term is undefined and left empty.
