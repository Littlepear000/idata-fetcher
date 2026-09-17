"""
Tool schemas for the iData Python download skill.

These define, in Anthropic Messages API tool-use format (`name` / `description` /
`input_schema`), the subset of `imf_datatools.idata_utilities` functions an agent is allowed
to call for this skill: the three "discovery" functions plus data/metadata retrieval.

Design notes (why the schemas look the way they do):
- Each `description` restates the relevant rule from ../SKILL.md inline. Tool descriptions are
  visible to the model at call time even if the rest of SKILL.md has scrolled out of context, so
  the ordering rule ("discover before you query") is duplicated here deliberately.
- `debug` and `params` from the underlying Python functions are intentionally left out of (or
  trimmed from) the schemas below to keep the surface small — they're implementation/debugging
  knobs, not decisions an LLM caller should be making.
- Tool names are prefixed `idata_` to leave room for sibling tool sets (haver_*, dmxe_*, ...) if
  this project later expands beyond iData, per ../SKILL.md's stated scope.
- This file only defines *schemas* (what the model may call and with what arguments). It does not
  implement the dispatcher that executes a tool call against the real `imf_datatools` package and
  serializes the resulting pandas.DataFrame back to the model — that's the next layer to build.

Mapping from tool name to the underlying Python call (for the future dispatcher):
    idata_get_databases       -> imf_datatools.idata_utilities.get_databases
    idata_get_dimensions      -> imf_datatools.idata_utilities.get_dimensions
    idata_get_dimension_values -> imf_datatools.idata_utilities.get_dimension_values
    idata_get_data            -> imf_datatools.idata_utilities.get_idata_data
    idata_get_metadata        -> imf_datatools.idata_utilities.get_idata_metadata
"""

IDATA_TOOLS = [
    {
        "name": "idata_get_databases",
        "description": (
            "Search the iData catalog for available databases (e.g. 'IMF.STA:CPI', "
            "'IMF.RES.WEO:WEO_LIVE'). This is always the first step for any new query — never "
            "invent or recall a database id from general knowledge or from EcOS-era names. "
            "Filter with `keyword` (matches database name/description, case-insensitive) to "
            "narrow down candidates, e.g. keyword=['fiscal', 'deficit']. Results are cached for "
            "the session; only pass refresh=true if you specifically need to pick up a database "
            "published after this session started."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "anyOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}},
                    ],
                    "description": (
                        "One or more keywords to filter database names/descriptions on "
                        "(case-insensitive substring match). Omit to list all databases."
                    ),
                },
                "searchmode": {
                    "type": "string",
                    "enum": ["or", "and"],
                    "default": "or",
                    "description": (
                        "'or' (default): match a database if it contains ANY keyword. "
                        "'and': match only if it contains ALL keywords."
                    ),
                },
                "refresh": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "Force re-fetching the database list instead of using this session's "
                        "cached copy. Rarely needed."
                    ),
                },
            },
            "required": [],
        },
    },
    {
        "name": "idata_get_dimensions",
        "description": (
            "Get the dimensions of a specific iData database: their mnemonics, human-readable "
            "descriptions, and the order they must appear in when building a query key. Always "
            "call this before constructing a key for a database you haven't already inspected in "
            "this session — different databases have different numbers and orders of dimensions "
            "(e.g. WEO_LIVE has 3: COUNTRY.INDICATOR.FREQUENCY; CPI has 5). Never assume a "
            "database follows the same dimension layout as another one."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "db": {
                    "type": "string",
                    "description": (
                        "Exact database id as returned by idata_get_databases, e.g. 'IMF.STA:CPI'."
                    ),
                },
                "keyword": {
                    "anyOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}},
                    ],
                    "description": (
                        "Optional keyword(s) to filter dimensions by mnemonic or description, "
                        "useful for databases with many dimensions."
                    ),
                },
                "searchmode": {
                    "type": "string",
                    "enum": ["or", "and"],
                    "default": "or",
                },
                "refresh": {
                    "type": "boolean",
                    "default": False,
                    "description": "Force re-fetch instead of using the session cache.",
                },
            },
            "required": ["db"],
        },
    },
    {
        "name": "idata_get_dimension_values",
        "description": (
            "Get the valid values (codes) and their descriptions for one dimension of an iData "
            "database — e.g. valid COUNTRY codes, or valid INDICATOR codes. Always call this to "
            "confirm a code before using it in a query key; do not guess a country, indicator, or "
            "other dimension code from memory (ISO3 country codes are usually safe, but indicator "
            "mnemonics and country-group codes like 'G163' are not intuitive and must be looked "
            "up). Use `keyword` to search by description when you only know the concept in plain "
            "language, e.g. dimension='INDICATOR', keyword='deficit'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "db": {
                    "type": "string",
                    "description": "Exact database id, e.g. 'IMF.STA:CPI'.",
                },
                "dimension": {
                    "type": "string",
                    "description": (
                        "Dimension mnemonic to look up values for, as returned by "
                        "idata_get_dimensions (e.g. 'COUNTRY', 'INDICATOR', 'FREQUENCY')."
                    ),
                },
                "keyword": {
                    "anyOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}},
                    ],
                    "description": (
                        "Optional keyword(s) to filter candidate values by their code or "
                        "description (case-insensitive substring match). Use this to resolve a "
                        "plain-language concept (e.g. 'fiscal deficit') to candidate codes — if "
                        "multiple plausible candidates come back, ask the user to disambiguate "
                        "rather than picking one arbitrarily."
                    ),
                },
                "searchmode": {
                    "type": "string",
                    "enum": ["or", "and"],
                    "default": "or",
                },
                "refresh": {
                    "type": "boolean",
                    "default": False,
                    "description": "Force re-fetch instead of using the session cache.",
                },
            },
            "required": ["db", "dimension"],
        },
    },
    {
        "name": "idata_get_data",
        "description": (
            "Download iData time series data for a specific database and query key. Only call "
            "this after: (1) idata_get_databases confirmed the database id, (2) idata_get_dimensions "
            "confirmed the dimension order/count for that exact database, and (3) idata_get_dimension_values "
            "confirmed every code used in `key`. The key is a '.'-separated string with one segment "
            "per dimension in the order from idata_get_dimensions; use '+' to combine multiple "
            "values within one dimension (e.g. 'USA+JPN'); leave a segment empty to mean 'all "
            "values' for that dimension (e.g. 'USA.CPI._T..M' leaves TYPE_OF_TRANSFORMATION open). "
            "If the database or a code needed for this query has not been resolved yet in this "
            "conversation, resolve it with the discovery tools first instead of guessing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "db": {
                    "type": "string",
                    "description": "Exact database id, e.g. 'IMF.RES.WEO:WEO_LIVE'.",
                },
                "key": {
                    "type": "string",
                    "description": (
                        "Query key: one '.'-separated segment per dimension (in "
                        "idata_get_dimensions order), '+' for multiple values within a "
                        "dimension, empty segment for 'all values'. E.g. 'AUS+BEN.NGDP_RPCH+PCPI.A'."
                    ),
                },
                "start": {
                    "type": "string",
                    "description": (
                        "Start period, e.g. '2020', '2020-01', '2020Q2'. Omit for full history."
                    ),
                },
                "end": {
                    "type": "string",
                    "description": (
                        "End period, e.g. '2026', '2026-12', '2026-12-31'. Note: for monthly/lower "
                        "frequencies, only a full-period date includes that period — '2020-05-30' "
                        "will NOT include May 2020, but '2020-05' or '2020-05-31' will."
                    ),
                },
                "longformat": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "If true, return one row per (dimension combination x date) with an "
                        "OBS_VALUE column, instead of one column per resolved series. Prefer this "
                        "when the key resolves to many series or the caller needs tidy data. "
                        "Mutually exclusive with `panel`."
                    ),
                },
                "panel": {
                    "type": "string",
                    "description": (
                        "Name of a dimension (e.g. 'COUNTRY') to group rows by, alongside dates, "
                        "with remaining dimensions collapsed into column names. Mutually exclusive "
                        "with longformat=true. Omit for the default wide format."
                    ),
                },
            },
            "required": ["db", "key"],
        },
    },
    {
        "name": "idata_get_metadata",
        "description": (
            "Retrieve metadata (e.g. unit, scale, methodology, last update date, source-specific "
            "attributes) for the series matching a database and query key. Uses the same key "
            "syntax as idata_get_data. Useful for explaining a series to the user (units, vintage, "
            "methodology) or for sanity-checking a resolved indicator before downloading the full "
            "time series."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "db": {
                    "type": "string",
                    "description": "Exact database id, e.g. 'IMF.RES:WEO'.",
                },
                "key": {
                    "type": "string",
                    "description": (
                        "Query key using the same '.'/'+' syntax as idata_get_data, e.g. '.NGDP.' "
                        "for indicator NGDP across all open dimensions."
                    ),
                },
            },
            "required": ["db", "key"],
        },
    },
]
