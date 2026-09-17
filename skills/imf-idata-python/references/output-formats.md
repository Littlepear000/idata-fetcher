# Output formats

`fetch_idata.py --format` supports **wide** and **long** only. A multi-sheet, country-name-enriched
"refreshable" Excel format (matching what some sibling IMF tools produce) is **not yet
implemented** — don't tell a user it's available.

**Default:** if `--format`/`--excel` are omitted, the script produces **wide-format CSV**. Never
withhold or delay generating this file to ask the user which format they want — only use a
different format when the user has actually stated a preference.

## Wide

Dates as rows, one column per resolved series (dot-separated `Series_Code`-style column
names), plus:

| Column | Present when | Source |
|---|---|---|
| `dates` | Always | Reset from the index |
| one column per series | Always | Raw API column names |
| `SCALE` | Always | Human-readable label from `SCALE_LABELS` (`Units`/`Thousands`/`Millions`/`Billions`); empty string if scale metadata is unavailable. Values are already divided by `10^scale` when scale > 0. |
| `UNIT` | When metadata has unit info | Decoded unit string (e.g. `National currency`, `Percent`); column omitted when the database has no unit metadata |

Saved as `.csv` by default, `.xlsx` with `--excel`.

## Long

One row per observation:

| Column | Source |
|---|---|
| one column per queried dimension | Raw dimension codes |
| `dates` | Observation date |
| `OBS_VALUE` | Observation value, divided by `10^scale` when scale > 0 |
| `SCALE` | Same convention as wide |
| `UNIT` | Same convention as wide |

Saved as `.csv` by default, `.xlsx` with `--excel`.

## Not yet implemented

- Refreshable multi-sheet Excel workbook with per-indicator tabs.
- `COUNTRY` / `ISO3` / `IFSCODE` lookup columns (would need a country-group reference file this
  skill doesn't yet have).
- `--indicator-dim` (only meaningful for refreshable's per-indicator sheet naming).
