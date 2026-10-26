"""
Codebook cache: the complete value list of one dimension of one database, stored locally.
The same cache also holds the database catalogue (`get_databases()`), used to fuzzy-match what
the user says about the database.

This is the *foundation* of indicator resolution (architecture doc, section 5). The first call
for (database, dimension) downloads every row of `get_dimension_values(db, dim)` and writes it
to a JSON file. Later calls read the file. These lists change rarely, so the default refresh
interval is 90 days; the user can force a refresh at any time.

Cache location, in order of precedence:
    1. the `cache_dir` argument
    2. the IDATA_AGENT_CACHE_DIR environment variable (phase 2: point it at a shared drive)
    3. ~/.idata_agent/cache
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from . import _idata

DEFAULT_TTL_DAYS = 90


def default_cache_dir() -> Path:
    env = os.environ.get("IDATA_AGENT_CACHE_DIR")
    if env:
        return Path(env)
    return Path.home() / ".idata_agent" / "cache"


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)


class CodebookCache:
    def __init__(self, cache_dir: str | Path | None = None, ttl_days: int = DEFAULT_TTL_DAYS):
        self.dir = Path(cache_dir) if cache_dir else default_cache_dir()
        self.ttl_seconds = ttl_days * 86400

    # ------------------------------------------------------------------ paths

    def path(self, db: str, dimension: str) -> Path:
        return self.dir / f"{_safe(db)}__{_safe(dimension)}.json"

    # ------------------------------------------------------------------ read / write

    def load(self, db: str, dimension: str) -> dict[str, Any] | None:
        p = self.path(db, dimension)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def is_fresh(self, entry: dict[str, Any] | None) -> bool:
        if not entry:
            return False
        return (time.time() - float(entry.get("fetched_at", 0))) < self.ttl_seconds

    def store(self, db: str, dimension: str, values: list[dict[str, str]]) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        p = self.path(db, dimension)
        payload = {
            "db": db,
            "dimension": dimension,
            "fetched_at": time.time(),
            "count": len(values),
            "values": values,  # [{"code": ..., "name": ...}, ...]
        }
        p.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
        return p

    # ------------------------------------------------------------------ main entry point

    def values(self, db: str, dimension: str, refresh: bool = False) -> list[dict[str, str]]:
        """Return [{"code", "name"}, ...] for the dimension, from cache or from iData."""
        entry = None if refresh else self.load(db, dimension)
        if self.is_fresh(entry):
            return entry["values"]
        values = fetch_dimension_values(db, dimension)
        self.store(db, dimension, values)
        return values

    def databases(self, refresh: bool = False) -> list[dict[str, str]]:
        """The database catalogue, from cache or from iData."""
        entry = None if refresh else self.load(*CATALOGUE_KEY)
        if self.is_fresh(entry):
            return entry["values"]
        values = fetch_databases()
        self.store(*CATALOGUE_KEY, values)
        return values

    def status(self, db: str, dimension: str) -> dict[str, Any]:
        entry = self.load(db, dimension)
        if not entry:
            return {"cached": False, "path": str(self.path(db, dimension))}
        age_days = (time.time() - float(entry.get("fetched_at", 0))) / 86400
        return {
            "cached": True,
            "fresh": self.is_fresh(entry),
            "age_days": round(age_days, 1),
            "count": entry.get("count"),
            "path": str(self.path(db, dimension)),
        }


CATALOGUE_KEY = ("_catalogue", "databases")


def fetch_databases() -> list[dict[str, str]]:
    """Download the complete database catalogue: [{"id", "description"}, ...]."""
    utils = _idata.idata_utilities()
    df = utils.get_databases()
    desc_col = "Description" if "Description" in df.columns else (df.columns[0] if len(df.columns) else None)
    return [
        {"id": str(db_id), "description": str(row[desc_col]) if desc_col is not None else ""}
        for db_id, row in df.iterrows()
    ]


def fetch_dimension_values(db: str, dimension: str) -> list[dict[str, str]]:
    """Download the complete value list for one dimension (no keyword filter)."""
    utils = _idata.idata_utilities()
    df = utils.get_dimension_values(db, dimension)
    name_col = "Name" if "Name" in df.columns else (df.columns[0] if len(df.columns) else None)
    out: list[dict[str, str]] = []
    for code, row in df.iterrows():
        name = str(row[name_col]) if name_col is not None else ""
        out.append({"code": str(code), "name": name})
    return out
