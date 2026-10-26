"""
QuerySpec — the single structured object that runs through the whole agent.

The parse step drafts it with the user's own words, the resolve step replaces each slot with
verified codes, the user confirms it, codegen renders it, and the executor runs it. Nothing is
executed unless `stage == "confirmed"` and `validate()` returns no errors.

Design rules encoded here:
- Dimensions are a list read from `get_dimensions(db)` at runtime, in key order. Nothing about
  COUNTRY / INDICATOR / FREQUENCY is hard-coded; those are just the usual names.
- The query key is *derived* from the dimensions (`QuerySpec.key`). The model never types it.
- Several values in one dimension are joined with `+` inside one key, so "GDP growth and
  inflation for the US and Japan" is one query, one download, one file.
- Output defaults: long layout, CSV, the user's Downloads folder.
- Every resolved value keeps the user's phrase and the official description beside the code,
  so the confirmation screen can show "real GDP growth -> NGDP_RPCH (Gross domestic product,
  constant prices, percent change)".
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

STAGES = ("draft", "resolving", "resolved", "confirmed", "executed")
LAYOUTS = ("wide", "long")
FILE_FORMATS = ("csv", "xlsx", "dta")
LANGUAGES = ("python", "stata", "r")

_CODE_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


@dataclass
class DimensionSlot:
    """One dimension of the target database, in key order."""

    name: str
    values: list[str] = field(default_factory=list)  # verified codes; empty = all values (open)
    phrase: str | None = None  # the user's words this slot was resolved from
    labels: dict[str, str] = field(default_factory=dict)  # code -> official description
    resolved: bool = False  # True once values were verified, or deliberately left open

    def segment(self) -> str:
        return "+".join(self.values)


@dataclass
class QuerySpec:
    database: str | None = None
    dimensions: list[DimensionSlot] = field(default_factory=list)
    start: str | None = None
    end: str | None = None
    layout: str = "long"  # long (default) | wide
    file_format: str = "csv"  # csv | xlsx | dta
    language: str = "python"  # python | stata | r  (which code tab the user is looking at)
    output_dir: str | None = None  # defaults to the user's Downloads folder at execution time
    output_path: str | None = None  # filled by the executor (or set explicitly by the user)
    stage: str = "draft"
    notes: list[str] = field(default_factory=list)  # free-text notes shown on the confirm screen

    # ------------------------------------------------------------------ derived values

    @property
    def key(self) -> str:
        """Dot-separated query key, one segment per dimension, in dimension order."""
        return ".".join(d.segment() for d in self.dimensions)

    @property
    def dimension_order_comment(self) -> str:
        """e.g. 'COUNTRY.INDICATOR.FREQUENCY' — used as a comment in generated code."""
        return ".".join(d.name for d in self.dimensions)

    def dimension(self, name: str) -> DimensionSlot | None:
        for d in self.dimensions:
            if d.name.upper() == name.upper():
                return d
        return None

    # ------------------------------------------------------------------ validation

    def validate(self) -> list[str]:
        """Return a list of problems. Empty list means the spec can be rendered and executed."""
        errors: list[str] = []
        if not self.database:
            errors.append("database is not set (use idata_find_databases)")
        if not self.dimensions:
            errors.append("dimensions are empty (use idata_get_dimensions)")
        for d in self.dimensions:
            if not d.resolved:
                errors.append(f"dimension {d.name} is not resolved (use idata_search_values)")
            for v in d.values:
                if not _CODE_RE.match(v):
                    errors.append(f"dimension {d.name} has an invalid code {v!r}")
        if self.dimensions and all(not d.values for d in self.dimensions):
            errors.append("every dimension is open; restrict at least one (e.g. the indicator)")
        if not self.start or not self.end:
            errors.append("start and end are required (ask the user; never assume a window)")
        if self.layout not in LAYOUTS:
            errors.append(f"layout must be one of {LAYOUTS}")
        if self.file_format not in FILE_FORMATS:
            errors.append(f"file_format must be one of {FILE_FORMATS}")
        if self.language not in LANGUAGES:
            errors.append(f"language must be one of {LANGUAGES}")
        if self.stage not in STAGES:
            errors.append(f"stage must be one of {STAGES}")
        return errors

    def missing_for_execution(self) -> list[str]:
        problems = self.validate()
        if self.stage != "confirmed":
            problems.append(f"stage is {self.stage!r}; the user must confirm the spec first")
        return problems

    # ------------------------------------------------------------------ file naming

    def default_filename(self) -> str:
        """{DB}_{seg1}_{seg2}..._{start}-{end}.{ext}; long segments are shortened with a hash."""
        db_short = (self.database or "idata").split(":")[-1]
        parts = [db_short]
        for d in self.dimensions:
            seg = d.segment() or "ALL"
            if len(seg) > 40:
                seg = seg[:24] + "_" + hashlib.sha1(seg.encode()).hexdigest()[:6]
            parts.append(seg)
        parts.append(f"{self.start}-{self.end}")
        name = "_".join(parts)
        name = re.sub(r"[^A-Za-z0-9_+\-.]", "_", name)
        return f"{name}.{self.file_format}"

    # ------------------------------------------------------------------ serialisation

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["key"] = self.key
        return data

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "QuerySpec":
        data = dict(data)
        data.pop("key", None)  # derived; never trusted from input
        dims = [
            d if isinstance(d, DimensionSlot) else DimensionSlot(**d)
            for d in data.pop("dimensions", [])
        ]
        return cls(dimensions=dims, **data)

    @classmethod
    def from_json(cls, text: str) -> "QuerySpec":
        return cls.from_dict(json.loads(text))


def coerce_spec(spec: "QuerySpec | dict[str, Any] | str") -> QuerySpec:
    """Accept a QuerySpec, a dict, or a JSON string and return a QuerySpec."""
    if isinstance(spec, QuerySpec):
        return spec
    if isinstance(spec, str):
        return QuerySpec.from_json(spec)
    return QuerySpec.from_dict(spec)
