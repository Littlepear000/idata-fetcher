"""
Tool schemas: what the model may call and with which arguments.

Written once in a provider-neutral shape (`name`, `description`, `input_schema`, which is
exactly Anthropic's tool format) and converted for OpenAI / Azure OpenAI with
`to_openai_tools()`. Each description restates the one rule that matters for that tool,
because tool descriptions stay in the model's context even when the skill text scrolls out.

Tool -> implementation (see tools/__init__.py IMPLEMENTATIONS):
    idata_find_databases   tools.discovery.find_databases
    idata_list_databases   tools.discovery.list_databases
    idata_get_dimensions   tools.discovery.get_dimensions
    idata_search_values    tools.discovery.search_values
    idata_list_values      tools.discovery.list_values
    idata_expand_group     tools.resolve.expand_group
    idata_get_metadata     tools.resolve.get_metadata
    idata_preview          tools.resolve.preview
    render_code            codegen.render.render
    idata_fetch            NOT in this package: implemented by the tool-calling harness
                           (see handoff/README.md); must enforce spec.missing_for_execution()
    ask_user               no implementation: the harness turns it into a UI event
"""

from __future__ import annotations

SPEC_SCHEMA = {
    "type": "object",
    "description": (
        "The QuerySpec (query sheet). dimensions must be in the order returned by "
        "idata_get_dimensions; each has name, values (verified codes; [] = all values), "
        "phrase (the user's words), labels (code -> description) and resolved (bool)."
    ),
    "properties": {
        "database": {"type": "string"},
        "dimensions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "values": {"type": "array", "items": {"type": "string"}},
                    "phrase": {"type": ["string", "null"]},
                    "labels": {"type": "object", "additionalProperties": {"type": "string"}},
                    "resolved": {"type": "boolean"},
                },
                "required": ["name", "values", "resolved"],
            },
        },
        "start": {"type": "string", "description": "e.g. '2015', '2020Q1', '2020-05'"},
        "end": {"type": "string", "description": "e.g. '2026', '2024Q4', '2025-12'"},
        "layout": {"type": "string", "enum": ["long", "wide"], "default": "long"},
        "file_format": {"type": "string", "enum": ["csv", "xlsx", "dta"], "default": "csv"},
        "language": {"type": "string", "enum": ["python", "stata", "r"], "default": "python"},
        "output_dir": {"type": ["string", "null"]},
        "output_path": {"type": ["string", "null"]},
        "stage": {"type": "string", "enum": ["draft", "resolving", "resolved", "confirmed", "executed"]},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["database", "dimensions", "start", "end", "stage"],
}

_KEYWORD = {
    "anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
    "description": "One or more keywords, case-insensitive substring match. Omit to list everything.",
}

TOOLS: list[dict] = [
    {
        "name": "idata_find_databases",
        "description": (
            "Match what the user said about the database ('WEO', 'weo live', 'cpi', 'the published WEO') "
            "against the iData catalogue and return ranked candidates (id, description, score). The user "
            "may use abbreviations or informal names, so always confirm the chosen id with them. If the "
            "user did not mention a database at all, ask them which one before calling this. Never "
            "recall a database id from memory or from EcOS-era names."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "phrase": {"type": "string", "description": "The user's words for the database, or a (partial) id."},
                "limit": {"type": "integer", "default": 5, "minimum": 1, "maximum": 25},
                "refresh": {"type": "boolean", "default": False, "description": "Re-download the cached catalogue."},
            },
            "required": ["phrase"],
        },
    },
    {
        "name": "idata_list_databases",
        "description": "The whole iData catalogue (id, description). Only when the user asks which databases exist.",
        "input_schema": {"type": "object", "properties": {"refresh": {"type": "boolean", "default": False}}, "required": []},
    },
    {
        "name": "idata_get_dimensions",
        "description": (
            "Read the dimensions of one database: names, descriptions and key order. Call it before "
            "building the spec for any database not yet inspected in this session; databases differ "
            "(WEO_LIVE has 3 dimensions, CPI has 5). Copy the result into spec.dimensions as empty slots."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"db": {"type": "string"}, "refresh": {"type": "boolean", "default": False}},
            "required": ["db"],
        },
    },
    {
        "name": "idata_search_values",
        "description": (
            "Resolve the user's words to codes in one dimension. Ranks the database's complete value "
            "list (cached locally) by fuzzy match; a team lookup table may boost a candidate but never "
            "adds codes that are not in the list. Show the top 5 candidates (code, description) and "
            "let the user confirm, even when the first looks obvious. Pass hints such as 'percent "
            "change' or 'constant prices' when the user implied them. Call once per phrase; several "
            "confirmed codes go into the same dimension joined with '+'. Never guess a code."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "db": {"type": "string"},
                "dimension": {"type": "string", "description": "Dimension name from idata_get_dimensions."},
                "phrase": {"type": "string", "description": "The user's words for one value, in English, or a code."},
                "hints": {"type": "array", "items": {"type": "string"}, "description": "Optional qualifiers implied by the user."},
                "limit": {"type": "integer", "default": 15, "minimum": 1, "maximum": 50},
                "refresh": {"type": "boolean", "default": False, "description": "Force re-download of the cached list."},
            },
            "required": ["db", "dimension", "phrase"],
        },
    },
    {
        "name": "idata_list_values",
        "description": (
            "Return the complete value list of one dimension (from the local cache). Use it only when "
            "the user asks 'what options are there for X?'; present the result in readable form."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"db": {"type": "string"}, "dimension": {"type": "string"}, "refresh": {"type": "boolean", "default": False}},
            "required": ["db", "dimension"],
        },
    },
    {
        "name": "idata_expand_group",
        "description": (
            "Expand a WEO country group named by the user ('advanced economies', 'G20', 'G007') into "
            "ISO3 codes using the RES WEO reference tables. Never list a group's members from memory. "
            "If the result is ambiguous, show the candidates and ask the user."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "idata_get_metadata",
        "description": (
            "Metadata (unit, scale, methodology, last update) for the series matching a key. Use it to "
            "describe a candidate on the confirmation screen or to explain a number to the user."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"db": {"type": "string"}, "key": {"type": "string"}, "max_rows": {"type": "integer", "default": 50}},
            "required": ["db", "key"],
        },
    },
    {
        "name": "idata_preview",
        "description": (
            "Download the spec's query and return the first rows and the total row count, to confirm "
            "that observations exist before asking the user to confirm. Zero rows means 'check the "
            "codes or the sign-in', not 'no data exists'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"spec": SPEC_SCHEMA, "rows": {"type": "integer", "default": 5}},
            "required": ["spec"],
        },
    },
    {
        "name": "render_code",
        "description": (
            "Render the spec into Python, Stata and R code from fixed templates (no model involvement). "
            "Returns all three; show the one matching spec.language and offer the others as tabs. The "
            "Python version is exactly what idata_fetch will run."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"spec": SPEC_SCHEMA},
            "required": ["spec"],
        },
    },
    {
        "name": "idata_fetch",
        "description": (
            "Execute the confirmed spec: download the data, attach SCALE and UNIT, save the file to the "
            "user's Downloads folder (or spec.output_dir) with a sidecar .spec.json, and return the path, "
            "row count and a preview. Refused unless spec.stage == 'confirmed' and every dimension is "
            "resolved. On failure, diagnose from the message; do not retry the same call blindly."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"spec": SPEC_SCHEMA},
            "required": ["spec"],
        },
    },
    {
        "name": "ask_user",
        "description": (
            "Ask the user one question, optionally with options to pick from (e.g. indicator candidates, "
            "the time range, which database). Use it whenever a value is ambiguous or missing. Do not "
            "guess instead of asking."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "options": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"value": {"type": "string"}, "label": {"type": "string"}, "detail": {"type": "string"}},
                        "required": ["value", "label"],
                    },
                },
                "allow_free_text": {"type": "boolean", "default": True},
            },
            "required": ["question"],
        },
    },
]

TOOLS_BY_NAME = {t["name"]: t for t in TOOLS}


def to_openai_tools(tools: list[dict] | None = None) -> list[dict]:
    """Wrap the schemas in OpenAI / Azure OpenAI function-calling format."""
    return [
        {
            "type": "function",
            "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]},
        }
        for t in (tools or TOOLS)
    ]


def to_anthropic_tools(tools: list[dict] | None = None) -> list[dict]:
    """The native shape; returned as-is for symmetry with to_openai_tools()."""
    return list(tools or TOOLS)
