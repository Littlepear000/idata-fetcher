# country_groups: country codes and income groups (background knowledge)

Not an analysis on its own: reference data that the other skills rely on whenever results are
grouped by country. Code: `fp_analysis/countries.py`. Tool: `lookup_team_countries` (available in
both the Research and the Analysis assistants).

## Sources and tables

| File in `knowledge/` | Built from | Content |
|---|---|---|
| `countries.csv` | `Country Codes.xlsx` sheet `code_to_name` + the team country dummy file | one row per country: `ifscode` (IMF IFS code), `iso3`, `iso2`, `country`, `income_group` (AE / EM / LIC), dummies `ae`, `em`, `lic`, `in_dummy_file` |
| `country_aliases.csv` | sheets `name_to_code`, `code_to_name`, and dummy-file names | name variant -> `ifscode`, `iso3` (e.g. "Afghanistan, I.S. of" -> 512 / AFG) |
| `weo_aggregates.csv` | sheet `weo_group_code` + aggregate rows of the dummy file | WEO aggregate codes (G110, G1201, 1, ...), which are never treated as countries |

Rebuild after either workbook changes:
`python scripts/build_country_knowledge.py "Country Codes.xlsx" "Dummy_<date>.xlsx"`.

Codes: **ISO3** is the code WEO Live uses for countries; **IFS code** is the numeric IMF code used in
the team's files (`ifscode`). The lookup accepts either, or a known name variant, so data identified
by any of them can be grouped.
The workbook's `FIN Query` sheet is obsolete and is not used.

## Income groups (team classification, dummy file of 2026-01-15)

| Code | Label in outputs | Countries |
|---|---|---|
| AE | Advanced Economies | 43 |
| EM | Emerging Markets | 96 |
| LIC | Low-Income Developing Countries | 58 |
| - | Global | every classified country in the data (AE + EM + LIC), as `Dummy().noagg` |

`groups: ["income"]` (the default of every analysis skill) produces Global, AE, EM, LIC.
`["AE", "EM"]` selects some of them. `["weo_income"]` instead uses the **official WEO** groups
(Advanced Economies, Emerging Market and Middle-Income Economies, Low-Income Developing Countries)
through the app's WEO country-group expansion; membership can differ slightly from the team file.
State which classification was used.

Not classified (left out of income groups, reported as a warning): Anguilla, Montserrat (in the
dummy file without an income group); Korea DPR and Serbia and Montenegro (in the code table only).

## Pitfalls

- The classification is today's list applied to all years (no historical reclassification).
- Kosovo is `KOS` in the team tables. If a dataset uses another code (e.g. `UVK`/`XKX`), the lookup
  reports it as unknown and the assistant asks the user.
- Identifiers not found in the tables are never guessed: the requirement check returns a question
  for the user (which country is it, or leave it out).
- The dummy file has many other categories (regions, G20, euro area, PRGT, FCS, Fiscal Monitor MSA
  samples, ...). They are not loaded yet; add them to the build script when a skill needs them.
