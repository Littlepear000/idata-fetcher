---
name: imf-idata-python
description: Rules and workflow for downloading IMF economic/financial data from the iData platform in Python, using the internal imf_datatools package (get_databases, get_dimensions, get_dimension_values, get_idata_data, get_idata_metadata). Use this whenever an agent needs to fetch, query, or download data (e.g. WEO, CPI, IFS) from IMF's iData system via Python — not for Stata/R, and not for other datatools resources (DMXe, Haver, SQL, World Bank, BIS, EcOS).
---

# IMF iData Download Skill (Python)

## Purpose and scope

This skill covers **one thing only**: downloading data from the IMF **iData** platform in **Python**,
using the `imf_datatools` package. iData is the Fund-wide data system (since 2025) that replaced
EcOS, EDI, data.imf.org, and Data Mapper.

Out of scope for this skill (do not use these unless the task explicitly asks for them): Stata/R
usage, DMXe file read/write, Haver, SQL, World Bank, BIS, and EcOS-to-iData mapping. See
`references/api_reference.md` if one of those is ever needed later.

## The golden rule: discover, don't guess

**Never hand-write a database name, dimension name, or dimension value from memory or intuition.**
iData databases each have their own, different set of dimensions (some have 3, some have 5+), and
codes are not always intuitive (e.g. countries are ISO3, but country *groups* are codes like `G163`
for the Euro Area). Wrong guesses silently return empty results rather than raising a clear error.

Always resolve unknowns through the API first, in this order:

1. `get_databases()` → find the exact database id (e.g. `IMF.STA:CPI`, `IMF.RES.WEO:WEO_LIVE`).
2. `get_dimensions(db)` → find out how many dimensions the database has, their mnemonics, and their
   order. **Do not assume a database follows `country.indicator.frequency`** — that only happens to
   be true for WEO_LIVE. CPI, for example, has 5 dimensions.
3. `get_dimension_values(db, dimension)` → find the valid codes for each dimension before using them
   in a query key.

Only after these three are known should `get_idata_data()` be called.

## Standard workflow

```python
from imf_datatools import idata_utilities

# 1. Find the database
dbs = idata_utilities.get_databases(keyword='CPI')          # search by keyword
db = 'IMF.STA:CPI'                                           # exact id, once confirmed

# 2. Find the dimensions and their order (do this once per database)
dims = idata_utilities.get_dimensions(db)
# -> e.g. COUNTRY(0), INDEX_TYPE(1), COICOP_1999(2), TYPE_OF_TRANSFORMATION(3), FREQUENCY(4)

# 3. Find valid codes for each dimension you need to filter on
countries = idata_utilities.get_dimension_values(db, 'COUNTRY')
countries_subset = idata_utilities.get_dimension_values(db, 'COUNTRY', keyword='republic')

# 4. Build the query key: one value per dimension, in dimension order, joined by '.'
#    - '+' between multiple values within a dimension
#    - leave a dimension blank (nothing between the dots) to mean "all values"
key = 'USA+JPN.CPI._T..M'   # TYPE_OF_TRANSFORMATION left open -> all transformations returned

# 5. Download
df = idata_utilities.get_idata_data(db, key=key, start='2015', end='2024-12')
```

`import imf_datatools; imf_datatools.get_idata_data(...)` (top-level) and
`from imf_datatools import idata_utilities; idata_utilities.get_idata_data(...)` (submodule) are
equivalent — the top-level package re-exports the same functions. Either style is fine; be
consistent within one script.

## Query key syntax

| Symbol | Meaning |
|---|---|
| `.` | Separates dimensions, in the exact order returned by `get_dimensions(db)` |
| `+` | Multiple values within one dimension, e.g. `AUS+BEN` |
| *(empty)* | Leave a dimension open — matches all its values, e.g. `.NGDP.` |

The number of dot-separated segments **must match the number of dimensions of that specific
database** — confirm with `get_dimensions(db)` first; never reuse the 3-segment
`country.indicator.freq` shape assumed for WEO across other databases.

## Output shape options (`get_idata_data`)

- Default (wide): one column per resolved series, dates as the index.
- `longformat=True`: one row per (dimension values × date), with an `OBS_VALUE` column. Good for
  tidy/long downstream processing or when the query resolves to many series.
- `panel=<dimension>`: rows grouped by that dimension and `dates`, remaining dimensions collapsed
  into column names. Mutually exclusive with `longformat=True`.
- `start=` / `end=`: strings like `'2020'`, `'2020-01'`, `'2020Q2'`. **Gotcha:** for `end`, only a
  full-period date (e.g. `'2020-05'` or `'2020-05-31'`) includes that period for monthly/lower
  frequencies — `end='2020-05-30'` will *not* include May 2020.

## Authentication and session rules

- Public iData data does not require special setup beyond installation.
- **Internal/restricted data** (e.g. `WEO_LIVE` before publication) requires setting
  `idata_utilities.PRIVATE = True` before calling any data-retrieval function, in the same session.
- Accessing internal data triggers a **browser-based SSO authentication popup** ("click IMF User").
  This is an interactive, human-in-the-loop step — **an autonomous agent cannot complete it on its
  own**. When a task needs `PRIVATE = True` data:
  1. Check whether a valid authenticated session already exists (e.g. a prior successful call in
     the same run/session).
  2. If not, stop and tell the user a browser window needs to be completed for authentication
     before the download can proceed — do not silently retry or fabricate data.
- Each authenticated session is valid for **about one hour**. After that, calls will need
  re-authentication (another browser popup). Long-running or scheduled downloads of internal data
  should account for this — batch calls within a session window rather than assuming an unattended
  multi-hour run will keep working.

## Caching / refresh behavior

`get_databases()`, `get_dimensions()`, and `get_dimension_values()` cache their results in memory
for the current Python session after the first call — repeated calls are free. Pass `refresh=True`
only when you specifically need to pick up changes made upstream since the session started (e.g. a
newly published database or a corrected dimension list); don't set it by default.

## Error handling and troubleshooting

- `imf_datatools` returns data **only if the user has access to it**; it does not grant or manage
  permissions itself. If a call returns empty or `None` where data is expected, the most likely
  causes, in order, are:
  1. A dimension value or database id that doesn't actually exist for that database (re-verify with
     `get_dimensions`/`get_dimension_values` rather than guessing again).
  2. A permissions issue — the user's account doesn't have access to that (internal) resource.
  3. For internal data, an expired or missing authentication session (see above).
- Do not silently swallow an empty result and report success — surface it, and if it may be a
  permissions issue, say so rather than guessing.
- For persistent problems unrelated to the above, the human contact point is
  `Datatools-Support@imf.org` / Econometric Support — an agent should surface this contact rather
  than trying to work around it.

## Do / don't checklist

- **Do** call `get_databases` → `get_dimensions` → `get_dimension_values` before every new
  database/query pattern the agent hasn't already resolved in this session.
- **Do** reuse dimension/value lookups already done in-session instead of re-querying.
- **Do** pick `longformat=True` when the result of a query is not naturally a single well-defined
  table (e.g. an open dimension resolving to many series) and the caller needs tidy data.
- **Do** stop and ask the user when internal (`PRIVATE=True`) data needs fresh authentication.
- **Don't** invent database ids, dimension mnemonics, or dimension values from prior knowledge of
  EcOS, WEO Excel files, or general economics naming conventions.
- **Don't** assume every database has the same 3 dimensions as WEO_LIVE.
- **Don't** treat an empty/`None` result as "no data exists" without checking permissions/dimension
  validity first.
- **Don't** reach for DMXe/Haver/SQL/World Bank/BIS/EcOS-mapping functions for this skill's tasks —
  out of scope here (see `references/api_reference.md` if genuinely needed).

## Worked example

Annual GDP growth and CPI for Australia and Benin from WEO_LIVE (3-dimension database:
`COUNTRY.INDICATOR.FREQUENCY`):

```python
from imf_datatools import idata_utilities

idata_utilities.PRIVATE = True   # WEO_LIVE is internal; requires browser SSO the first time

db = 'IMF.RES.WEO:WEO_LIVE'
isocode = 'AUS+BEN'
varlist = 'NGDP_RPCH+PCPI'
freq = 'A'

df = idata_utilities.get_idata_data(
    db,
    key=f'{isocode}.{varlist}.{freq}',
    longformat=True,
)
```

Monthly CPI (all-items index) for the US and Japan from a 5-dimension database, leaving the
transformation dimension open to get index level, month-over-month %, and year-over-year % at once:

```python
from imf_datatools import idata_utilities

db = 'IMF.STA:CPI'
dims = idata_utilities.get_dimensions(db)   # confirm dimension order/count first
# COUNTRY(0), INDEX_TYPE(1), COICOP_1999(2), TYPE_OF_TRANSFORMATION(3), FREQUENCY(4)

key = 'USA+JPN.CPI._T..M'   # TYPE_OF_TRANSFORMATION left open
df = idata_utilities.get_idata_data(db, key=key)
```

## Reference

Full function signatures and parameters (`get_databases`, `get_dimensions`, `get_dimension_values`,
`get_idata_data`, `get_idata_metadata`, country-info helpers, installation steps) are in
`references/api_reference.md` — load it when a parameter's exact default or edge-case behavior is
needed and this file doesn't already cover it.

## Sources

- `documents/imf_datatools_doc.pdf` — "Documentation for the IMF datatools" (Datatools Team,
  2026-07-14), Chapter 3.2–3.3.
- `documents/idata_codebook_v1.docx` — "Codebook to Extract Economic and Financial Data in Idata",
  Python section (this is the source for the `PRIVATE` flag and the browser-auth/1-hour-session
  behavior, which the PDF does not mention — treat as the more operational, install-and-auth-focused
  of the two sources).
