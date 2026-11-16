# group_statistics: group averages and distribution of one indicator

Origin: `fadfpdata` `ImfFrame.agg_mean` (GDP-weighted group means, the "chart" sheet) and
`ImfFrame.export_agg_detail` (the "detail" sheet). Code: `fp_analysis/aggregate.py::group_statistics`.

## What it computes

For each group and year, over the countries in the group that have a value:
`n_countries`, `mean`, `weighted_mean` (sum(x*w)/sum(w) over countries with both), `median`,
`p10`, `p25`, `p75`, `p90`, `iqr` (p75-p25), `p10_p90`, and `weight_coverage` = weight of countries
with a value / weight of all group countries in the data (%). Also a year x group chart table.

## Requirements

- The indicator (`params.indicator`, a code present in the handed-off data), annual.
- A weight series in the same data unless `weight: "none"`. `auto` (default) follows the team rule:
  `NGDP_FY_USD` (fiscal-year GDP in USD) for fiscal variables (codes starting with `GG`), `NGDPD`
  otherwise. Other reasonable choices the economist may ask for: `PPPGDP` for growth rates, `LP` for
  per-capita measures. Fetch it for the same countries and years; if the default is absent, the
  assistant asks instead of switching silently.
- Group membership: `["income"]` (default: team Global / AE / EM / LIC from the dummy file), a subset
  such as `["EM", "LIC"]`, `["weo_income"]` or other official WEO group names, or `[]` for one group
  "All countries" (every identified country in the data; aggregate rows are left out).

## Limits and pitfalls

- Only indicators in ratios, rates or per-capita terms should be averaged. Averaging levels in
  national currency across countries is meaningless; refuse and suggest the ratio.
- Weighted means use the same-year weight of each country (as in agg_mean).
- Membership is today's classification applied to all years.
- The team groups (dummy file) can differ slightly from WEO's official AE / EMMIE / LIDC; state which
  classification was used.
- Report `weight_coverage` < 90% (or a low `n_countries`) because the average then reflects a
  subset of the group.
