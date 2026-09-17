---
name: imf-idata-python
description: Use when the user wants to fetch, pull, download, or load an IMF data series (e.g. WEO, CPI, IFS) from the iData platform in Python. Covers database/dimension discovery, ambiguity resolution, key construction, and wide/long CSV/Excel output via the pre-built fetch_idata.py utility.
---

# IMF iData (Python)

Fetch IMF time series from iData through the pre-built `scripts/fetch_idata.py` utility.

## Runtime

Use the company Python on IMF Windows; do not create or use virtual/Conda environments.
Before executing the utility, read the [runtime contract](references/runtime.md) for
installed-skill paths, interpreter selection, and installation policy. Resolve scripts from the
loaded skill directory, not the user's working directory.

## Never write a new script

A pre-built fetch utility already exists (`scripts/fetch_idata.py`). Never write ad-hoc Python
to explore or fetch iData data — always invoke this script via Bash.

## Private data access

`fetch_idata.py` sets `idata_utilities.PRIVATE = True` automatically at import time, every run —
you don't need to do anything extra to access restricted/internal databases.

## Workflow

**Fast path:** if the database, complete dimension order, every dimension value, and the time
range are already confirmed (e.g. repeating an earlier query), skip straight to
[Fetch](#6-fetch) — output format never needs confirming, see [Step 5](#5-output-format).

### 1. Find the database

If you don't already know the exact database id, search:

```bash
python "<SKILL_DIR>/scripts/fetch_idata.py" --get-databases "<keyword>"
```

Never guess a database id from memory or from general economics naming conventions.

### 2. Read the dimensions

```bash
python "<SKILL_DIR>/scripts/fetch_idata.py" --db "<database_id>" --get-dimensions
```

This prints the dimension names in the exact order they must appear in the key. **Do not
assume a database has the same dimensions as another one** — e.g. WEO_LIVE has 3
(`COUNTRY`/`INDICATOR`/`FREQUENCY`), CPI has 5. Always use the exact names this prints — don't
assume names like `COUNTRY` or `FREQUENCY`; some databases use `REF_AREA`, `SERIES`, `TICKER`,
etc.

### 3. Resolve each dimension value

For each dimension you need to filter on — including the indicator/concept the user asked
about — check its valid values before using it in a key:

```bash
python "<SKILL_DIR>/scripts/fetch_idata.py" --db "<database_id>" --get-dimension-values "<DIM>" --keyword "<concept>"
```

**Auto-resolve vs. ask-user rules:**

| Situation | Action |
|---|---|
| Dimension has exactly one valid value | Auto-resolve silently; use it without asking |
| User already specified the dimension | Use their value; validate it against `--get-dimension-values` |
| Multiple values and user didn't specify | Ask the user — don't list all options upfront |
| `start`/`end` not specified | **Always ask** — never assume or default |

If the user asks "what options are there for X?", run `--get-dimension-values <DIM>` and present
the results in readable form (e.g. "Annual (A), Quarterly (Q), Monthly (M)"), not as a raw code
dump.

**Never guess or hardcode a dimension value.** If a keyword search on the indicator/concept
dimension returns several plausible candidates (e.g. "fiscal deficit" matching both an overall
balance and a primary balance indicator), show the candidates with a short distinguishing note
for each and ask the user to pick — never pick one silently.

**Country groups:** if the user names a WEO group instead of specific countries (e.g. "advanced
economies", "G20"), expand it first:

```bash
python "<SKILL_DIR>/scripts/fetch_idata.py" --expand-group "<name or group code>"
```

This doesn't need `--db`. It prints the matched group name/code and a `+`-joined list of ISO3
codes — paste that list directly into the country dimension of your key. If the name matches
more than one group, it prints the candidates instead of guessing; ask the user which one they
meant. Never hand-write or guess a group's membership yourself.

### 4. Build the key

Dot-separated, one field per dimension, in the exact order from `--get-dimensions`:

- `+` combines multiple values within one dimension: `USA+GBR.NGDP_RPCH.A`
- A blank (consecutive dots) selects all values for that dimension: `.NGDP_RPCH.A`
- The number of dot-separated fields must exactly match the number of dimensions — never add
  or drop dots.

### 5. Output format

Don't ask the user to choose a format — default to **wide** layout as **CSV**
(see [output formats](references/output-formats.md)) and generate the file. Only deviate if the
user has stated a preference (e.g. "as Excel", "long format") — use theirs instead of the
default, and reuse it for the rest of the conversation without asking again.

### 6. Fetch

```bash
python "<SKILL_DIR>/scripts/fetch_idata.py" --db "<database_id>" --key "<dot.separated.key>" --start "<period>" --end "<period>" --output "<path>"
```

Defaults to wide-format CSV. Add `--format long` for long layout, and/or `--excel` for `.xlsx`
instead of `.csv`. Always pass `--output` with a path in the user's own workspace (see
[runtime](references/runtime.md)), not this skill's installed directory.

**Always use this script — never call `imf_datatools` directly or return raw SDK output.**

For failures, diagnose from the printed error before retrying — don't wrap a call that already
retries internally in another retry loop. Report a partial/warned result as incomplete rather
than silently treating it as success.

## Troubleshooting

`fetch_idata.py` returns data only if the user has access to it — it never grants permissions.
An empty/no-data result is usually one of:

1. An invalid dimension value in the key — re-check with `--get-dimension-values`, don't just
   retry the same key.
2. A permissions issue with the specific database.
3. For unusual/experimental databases, missing or incomplete metadata (scale/unit will be
   blank — not fatal, but worth mentioning to the user).

For problems installing or importing `imf_datatools` itself, see
[runtime](references/runtime.md) and run `scripts/check_environment.py` before assuming the SDK
is broken.

## Reference

Full function signatures behind `fetch_idata.py` (`get_databases`, `get_dimensions`,
`get_dimension_values`, `get_idata_data`, `get_idata_metadata`) are in
[references/api_reference.md](references/api_reference.md) — load it when you need a
parameter's exact default or an edge case this file doesn't cover.

## Sources

- `documents/imf_datatools_doc.pdf` — "Documentation for the IMF datatools" (Datatools Team,
  2026-07-14), Chapter 3.2–3.3.
- `documents/idata_codebook_v1.docx` — "Codebook to Extract Economic and Financial Data in
  Idata", Python section.
