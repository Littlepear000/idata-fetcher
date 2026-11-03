# Output formats

`idata_fetch` writes one file per confirmed QuerySpec. `layout` selects the shape, `file_format`
the container. Defaults: **long** layout, **csv** format, saved to the user's Downloads folder
(or `spec.output_dir`). Never delay the file to ask about format; use a stated preference and
keep it for the rest of the conversation.

A sidecar `<file>.spec.json` is written beside every file. It holds the executed spec (database,
dimensions with phrases and labels, key, dates) so the file can be traced and re-run later.

## File name

`{DB}_{segment per dimension}_{start}-{end}.{ext}`, e.g.
`WEO_LIVE_USA+JPN_NGDP_RPCH+PCPIPCH_A_2015-2026.csv`. A segment longer than 40 characters
(many countries) is shortened and suffixed with a short hash. An open dimension appears as `ALL`.

## Long (`layout: "long"`, default)

One row per observation: one column per queried dimension (raw codes), `dates`, `OBS_VALUE`,
plus `SCALE` (`Units` / `Thousands` / `Millions` / `Billions`; values already divided by
`10**scale`) and `UNIT` (when metadata has it). In generated Stata code, long layout uses
`panel(<first dimension>)`; in Python and R it is `longformat=True`.

## Wide (`layout: "wide"`)

Dates as rows, one column per resolved series.

| Column | Present | Source |
|---|---|---|
| `dates` | always | the DatetimeIndex, start of period (2020Q2 → 2020-04-01) |
| one column per series | always | raw API column names, e.g. `USA.NGDP_RPCH.A` |
| `SCALE` | always | `Units` / `Thousands` / `Millions` / `Billions` from metadata; empty if unknown. Values are already divided by `10**scale` when scale > 0. |
| `UNIT` | when metadata has it | decoded unit, e.g. `Percent`, `National currency` |

## Containers (`file_format`)

| Format | Python save line | Stata save line | R save line | Notes |
|---|---|---|---|---|
| `csv` | `df.to_csv(path)` | `export delimited using "path", replace` | `write.csv(df, "path")` | default |
| `xlsx` | `df.to_excel(path)` | `export excel using "path", firstrow(variables) replace` | `openxlsx::write.xlsx(...)` | needs `openpyxl`; the executor falls back to CSV with a warning if it is missing |
| `dta` | `df.to_stata(path)` | `save "path", replace` | `haven::write_dta(...)` | column names are made Stata-safe (letters, digits, `_`, max 32 chars); renames are reported in `warnings` |

## Not implemented

- The multi-sheet, country-name-enriched "refreshable" Excel workbook some sibling IMF tools
  produce. Do not tell a user it is available.
- `COUNTRY` / `ISO3` / `IFSCODE` lookup columns in the output.
