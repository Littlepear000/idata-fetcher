# imf_datatools — iData Python API reference

Detailed reference backing `../SKILL.md`. Only iData-related functions and Python installation are
covered; other datatools resources (DMXe, Haver, SQL, World Bank, BIS, EcOS mapping, R, Stata) are
intentionally omitted since they are out of scope for this skill.

**Note:** `../scripts/fetch_idata.py` is the supported way to call these functions — see
`../SKILL.md`. This file documents the underlying `imf_datatools` functions it wraps, for when a
parameter's exact default or an edge case isn't covered by the script's own `--help` or the
workflow in `SKILL.md`.

## Installation (one-time, per machine)

1. Install the latest Python from the Fund Software Center.
2. Open Command Prompt and run:
   ```
   python \\ecnswn12p\ems_shared\pub\datatools\installer.py
   ```
   This installs the latest stable release and can be re-run any time to update.
3. Verify:
   ```
   python
   import imf_datatools
   exit()
   ```
   No error output means installation succeeded.
4. Optional — latest development/experimental version:
   ```
   python \\ecnswn12p\ems_shared\pub\datatools\installer.py dev
   ```

On Econometric Support servers, prefer a pre-built environment (request access via
`EconometricSupport@imf.org`); if setting up manually, copy
`\\ecnswn12p\ems_shared\pub\datatools\stable\v1.1.6\imf_datatools\imf_datatools` into the target
virtual environment's `lib\site-packages`.

If a call fails or returns nothing unexpectedly, this is a data-access/permissions question, not
an installation question — see the Troubleshooting section of `../SKILL.md`.

## Core iData functions

All of the below live in `imf_datatools.idata_utilities` and are also re-exported at the top level
of `imf_datatools`.

### `get_databases(keyword=None, searchmode='or', refresh=False, debug=False)`

Returns a `pandas.DataFrame` of available iData datasets (index = database id, e.g.
`IMF.STA:CPI`). Cached in-memory after first call for the session.

- `keyword`: a `str` or iterable of `str`, filters on dataset name/description (case-insensitive).
- `searchmode`: `'or'` (default, matches any keyword) or `'and'` (must match all keywords).
- `refresh`: force re-fetch instead of using the in-memory cache.

```python
from imf_datatools import idata_utilities
datasets = idata_utilities.get_databases()
cpi_like = idata_utilities.get_databases(keyword=['cpi', 'price'])
```

### `get_dimensions(db: str, keyword=None, searchmode='or', refresh=False, debug=False)`

Returns a `pandas.DataFrame` describing the dimensions of database `db`: mnemonic, human-readable
description, and order (0-indexed — the order in which values must appear in a query key). Cached
per-session; `refresh=True` to force re-fetch.

```python
db = 'IMF.STA:CPI'
dims = idata_utilities.get_dimensions(db)
# Description               Dimension            Order
# COUNTRY                   Country              0
# INDEX_TYPE                Index type           1
# COICOP_1999                Expenditure Category 2
# TYPE_OF_TRANSFORMATION    Type of Transformation 3
# FREQUENCY                 Frequency            4
```

### `get_dimension_values(db, dimension, keyword=None, searchmode='or', refresh=False, debug=False)`

Returns a `pandas.DataFrame` of valid values (index) and descriptions (`Name` column) for a given
dimension of `db`. Cached per-session; `refresh=True` to force re-fetch. `keyword`/`searchmode`
filter on the value code or description, same semantics as `get_databases`.

```python
db = 'IMF.STA:CPI'
countries = idata_utilities.get_dimension_values(db, 'COUNTRY')
republics = idata_utilities.get_dimension_values(db, 'COUNTRY', keyword='republic')
republic_or_kingdom = idata_utilities.get_dimension_values(
    db, 'COUNTRY', keyword=['republic', 'kingdom'], searchmode='or'
)
```

### `get_idata_data(db: str, key, start=None, end=None, params=None, longformat=False, panel=None, debug=False)`

The main data-retrieval call.

- `db`: exact database id from `get_databases()`.
- `key`: `str` concatenating one value (or `+`-joined multiple values) per dimension, separated by
  `.`, in the order given by `get_dimensions(db)`. Leave a dimension's segment empty to mean "all
  values" for that dimension.
- `start` / `end`: period strings like `'2020'`, `'2020-01'`, `'2020Q2'`. For `end`, only a
  full-period date includes that period for monthly/lower frequencies (`end='2020-05'` or
  `'2020-05-31'` include May 2020; `end='2020-05-30'` does not).
- `longformat`: if `True`, returns one row per (dimension combination × date) with columns for each
  queried dimension plus `dates` and `OBS_VALUE`, instead of one column per series.
- `panel`: name of a dimension to pivot rows on (grouped by that dimension and `dates`, remaining
  dimensions collapsed into the column names). Mutually exclusive with `longformat=True`.
- `params`: reserved for resource-specific extra parameters (mirrors the pattern used by other
  datatools resources); not typically needed for standard iData queries.

```python
db = 'IMF.STA:CPI'
key = 'USA+JPN.CPI._T..M'          # TYPE_OF_TRANSFORMATION left open

df_wide = idata_utilities.get_idata_data(db, key=key)
df_long = idata_utilities.get_idata_data(db, key=key, longformat=True)
df_panel = idata_utilities.get_idata_data(db, key=key, panel='COUNTRY')
```

### `get_idata_metadata(db: str, key, debug=False)`

Returns a `pandas.DataFrame` of metadata associated with the resolved series (varies by database —
e.g. for WEO: `primary_domestic_currency`, `methodology`, `base_year`, `country_update_date`,
`scale`, `unit`; for CPI: `access_sharing_level`, `security_classification`, `common_reference_period`,
etc.). `key` uses the same dot/`+` syntax as `get_idata_data`, with open dimensions matching all
their values.

```python
db = 'IMF.RES:WEO'
meta = idata_utilities.get_idata_metadata(db, key='.NGDP.')   # NGDP, all countries, all freqs
```

## Country/group reference helpers

Not iData-query functions per se, but commonly needed alongside iData WEO data to interpret country
group codes (e.g. `G001` = World, `G163` = Euro Area) or to merge in country classifications.

```python
import imf_datatools
groups = imf_datatools.get_weo_country_groups()   # sheet "2. Country Groups" from RES WEO Excel
countryinfo = imf_datatools.get_weo_country_info()  # sheet "5. Group Dummies (iData)"
ebv = imf_datatools.get_ebv_country_info()          # EBV + World Bank merged country info
```

`../scripts/fetch_idata.py --expand-group "<name or code>"` wraps `get_weo_country_groups()` +
`get_weo_country_info()` to turn a group name into a `+`-joined ISO3 list — see `../SKILL.md`.
**Caveat:** its column-name detection (which column holds the group description, which holds
ISO3 codes) was written defensively without being able to inspect a real
`get_weo_country_info()`/`get_weo_country_groups()` result — verify against real output the
first time this runs on an IMF-networked machine, and adjust the column-matching in
`cmd_expand_group()` if the actual schema differs.

All three accept `save=False`; pass `save=True` to also write the result to a local file.

## Notes on data conventions

- All retrieved time series are indexed by `pd.DatetimeIndex`, dated to the **start** of the
  period (e.g. 2020Q2 → `2020-04-01`, Feb 2020 → `2020-02-01`, annual 2019 → `2019-01-01`).
- The library returns data **as-is from iData**, without reshaping into a uniform cross-resource
  interface — this is intentional (see PDF §3, introductory note), so dimension names/counts differ
  per database and must be discovered per-database rather than assumed.
