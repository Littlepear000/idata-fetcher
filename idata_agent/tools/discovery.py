"""
Discovery tools: find a database, read its dimensions, resolve plain words to codes.

    find_databases(phrase)                       -> idata_find_databases (fuzzy, user confirms)
    get_dimensions(db)                           -> idata_get_dimensions
    search_values(db, dimension, phrase, hints)  -> idata_search_values

`search_values` implements section 5 of the architecture doc:

    foundation  the database's own complete value list (cached, see cache.py)
    scoring     word overlap + string similarity + abbreviation expansion, all ordinary code
    boost       a hand-maintained lookup table may add score to a candidate; it can never
                introduce a code that is not in the list
    output      ranked candidates; the caller shows the top 5 and the user confirms

No model call happens in this module.
"""

from __future__ import annotations

import difflib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import _idata
from .cache import CodebookCache

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"
LOOKUP_TABLE_PATH = KNOWLEDGE_DIR / "lookup_table.json"
ABBREVIATIONS_PATH = KNOWLEDGE_DIR / "abbreviations.json"

LOOKUP_BOOST = 0.35  # added to the score of a code the lookup table points at
WEIGHT_OVERLAP = 0.55  # share of query tokens found in the description
WEIGHT_SIMILARITY = 0.30  # difflib ratio between normalised strings
WEIGHT_HINTS = 0.15  # share of hint tokens found in the description

_STOPWORDS = {"of", "the", "in", "and", "for", "to", "a", "an", "on", "at", "by", "as", "vs"}


# ---------------------------------------------------------------------------------------
# idata_find_databases
# ---------------------------------------------------------------------------------------


def _db_tokens(item: dict[str, str]) -> set[str]:
    """Tokens of a catalogue entry: id parts ('IMF.RES.WEO:WEO_LIVE' -> imf, res, weo, live, weo_live) + description."""
    db_id = item["id"]
    parts = re.split(r"[.:]", db_id)
    toks = set()
    for part in parts:
        toks.add(part.lower())
        toks.update(tokens(part.replace("_", " ")))
    toks |= tokens(item.get("description", ""))
    return toks


def rank_databases(catalogue: list[dict[str, str]], phrase: str, limit: int = 5) -> list[dict[str, Any]]:
    """Pure ranking of the catalogue against what the user said ('WEO', 'weo live', 'cpi')."""
    q = tokens(phrase)
    phrase_norm = normalize(phrase)
    ranked = []
    for item in catalogue:
        db_id, desc = item["id"], item.get("description", "")
        if phrase_norm == normalize(db_id) or phrase.strip().lower() == db_id.lower():
            score = 1.0  # the user typed the exact id
        else:
            d = _db_tokens(item)
            overlap = len(q & d) / len(q) if q else 0.0
            tail = db_id.split(":")[-1].replace("_", " ")
            sim_id = difflib.SequenceMatcher(None, phrase_norm, normalize(tail)).ratio()
            sim_desc = difflib.SequenceMatcher(None, phrase_norm, normalize(desc)).ratio()
            score = 0.6 * overlap + 0.25 * sim_id + 0.15 * sim_desc
        ranked.append({"id": db_id, "description": desc, "score": round(score, 4)})
    ranked.sort(key=lambda r: (-r["score"], r["id"]))
    return ranked[:limit]


def find_databases(phrase: str, limit: int = 5, refresh: bool = False, cache: CodebookCache | None = None) -> dict[str, Any]:
    """Fuzzy-match the user's words for a database against the full catalogue.

    The user must have named a database (possibly informally: 'WEO', 'weo live', 'cpi'); if they
    did not, the agent asks first. The result is shown to the user for confirmation.
    """
    if not phrase or not phrase.strip():
        raise _idata.IDataToolError("'phrase' is required: what the user said about the database. If they said nothing, ask them first.")
    cache = cache or CodebookCache()
    catalogue = cache.databases(refresh=refresh)
    candidates = rank_databases(catalogue, phrase, limit=limit)
    return {"phrase": phrase, "candidates": candidates, "total_databases": len(catalogue)}


def list_databases(refresh: bool = False, cache: CodebookCache | None = None) -> dict[str, Any]:
    """The whole catalogue, for 'which databases are there?' questions."""
    cache = cache or CodebookCache()
    catalogue = cache.databases(refresh=refresh)
    return {"databases": catalogue, "count": len(catalogue)}


# ---------------------------------------------------------------------------------------
# idata_get_dimensions
# ---------------------------------------------------------------------------------------


def get_dimensions(db: str, refresh: bool = False) -> dict[str, Any]:
    """Dimension names in key order, with descriptions. The result seeds QuerySpec.dimensions."""
    if not db:
        raise _idata.IDataToolError("'db' is required; call idata_find_databases first.")
    utils = _idata.idata_utilities()
    df = utils.get_dimensions(db, refresh=refresh)
    desc_col = "Description" if "Description" in df.columns else None
    order_col = "Order" if "Order" in df.columns else None
    dims = []
    for name, row in df.iterrows():
        dims.append(
            {
                "name": str(name),
                "description": str(row[desc_col]) if desc_col else "",
                "order": int(row[order_col]) if order_col else len(dims),
            }
        )
    dims.sort(key=lambda d: d["order"])
    return {"db": db, "dimensions": dims, "key_template": ".".join(d["name"] for d in dims)}


# ---------------------------------------------------------------------------------------
# idata_search_values
# ---------------------------------------------------------------------------------------


@lru_cache(maxsize=1)
def load_abbreviations() -> dict[str, str]:
    if not ABBREVIATIONS_PATH.exists():
        return {}
    data = json.loads(ABBREVIATIONS_PATH.read_text(encoding="utf-8"))
    return {k.lower(): v.lower() for k, v in data.get("abbreviations", {}).items()}


@lru_cache(maxsize=1)
def load_lookup_table() -> dict[str, Any]:
    if not LOOKUP_TABLE_PATH.exists():
        return {}
    return json.loads(LOOKUP_TABLE_PATH.read_text(encoding="utf-8"))


def normalize(text: str) -> str:
    text = (text or "").lower().replace("%", " percent ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokens(text: str, abbreviations: dict[str, str] | None = None) -> set[str]:
    """Lower-cased word set with stopwords removed and abbreviations expanded (originals kept)."""
    abbreviations = load_abbreviations() if abbreviations is None else abbreviations
    words = [w for w in normalize(text).split() if w not in _STOPWORDS]
    out = set(words)
    for w in words:
        if w in abbreviations:
            out.update(x for x in abbreviations[w].split() if x not in _STOPWORDS)
    # Also expand multi-word phrases from the abbreviation table ("per cent" -> "percent").
    joined = " " + " ".join(words) + " "
    for k, v in abbreviations.items():
        if " " in k and f" {k} " in joined:
            out.update(v.split())
    return out


def lookup_codes(db: str, dimension: str, phrase: str) -> list[str]:
    """Codes the lookup table maps this phrase to, for this database and dimension."""
    table = load_lookup_table()
    entries = table.get(db, {}).get(dimension, {})
    key = normalize(phrase)
    codes: list[str] = []
    for k, v in entries.items():
        if normalize(k) == key:
            codes.extend(v if isinstance(v, list) else [v])
    return codes


def validate_lookup_table(db: str, dimension: str, valid_codes: set[str]) -> list[dict[str, str]]:
    """Entries that point at codes not present in the live list. Shown to the team, never used."""
    table = load_lookup_table()
    bad = []
    for phrase, v in table.get(db, {}).get(dimension, {}).items():
        for code in v if isinstance(v, list) else [v]:
            if code not in valid_codes:
                bad.append({"phrase": phrase, "code": code})
    return bad


def score_candidate(phrase: str, description: str, code: str, hints: list[str] | None = None) -> float:
    q = tokens(phrase)
    d = tokens(description) | {code.lower()}
    if not q:
        return 0.0
    overlap = len(q & d) / len(q)
    similarity = difflib.SequenceMatcher(None, normalize(phrase), normalize(description)).ratio()
    hint_score = 0.0
    if hints:
        h = set()
        for hint in hints:
            h |= tokens(hint)
        if h:
            hint_score = len(h & d) / len(h)
    return WEIGHT_OVERLAP * overlap + WEIGHT_SIMILARITY * similarity + WEIGHT_HINTS * hint_score


def rank_values(
    values: list[dict[str, str]],
    phrase: str,
    hints: list[str] | None = None,
    boosted_codes: list[str] | None = None,
    limit: int = 15,
) -> list[dict[str, Any]]:
    """Pure ranking over an in-memory value list; used by search_values and by the tests."""
    boosted = set(boosted_codes or [])
    phrase_norm = normalize(phrase)
    ranked = []
    for item in values:
        code, name = item["code"], item.get("name", "")
        if phrase_norm == normalize(code):
            score = 1.0  # the user typed the code itself
        else:
            score = score_candidate(phrase, name, code, hints)
        if code in boosted:
            score += LOOKUP_BOOST
        ranked.append({"code": code, "name": name, "score": round(score, 4), "boosted": code in boosted})
    ranked.sort(key=lambda r: (-r["score"], r["code"]))
    return ranked[:limit]


def search_values(
    db: str,
    dimension: str,
    phrase: str,
    hints: list[str] | None = None,
    limit: int = 15,
    refresh: bool = False,
    cache: CodebookCache | None = None,
) -> dict[str, Any]:
    """Rank the dimension's complete value list against the phrase.

    Returns {"candidates": [{code, name, score, boosted}], "total_values", "cache", "lookup_issues"}.
    The caller shows the first five candidates for confirmation.
    """
    if not db or not dimension:
        raise _idata.IDataToolError("'db' and 'dimension' are required; call idata_get_dimensions first.")
    if not phrase or not phrase.strip():
        raise _idata.IDataToolError("'phrase' is required: the user's words (or a code) to search for.")
    cache = cache or CodebookCache()
    values = cache.values(db, dimension, refresh=refresh)
    valid = {v["code"] for v in values}
    boosted = [c for c in lookup_codes(db, dimension, phrase) if c in valid]
    candidates = rank_values(values, phrase, hints=hints, boosted_codes=boosted, limit=limit)
    return {
        "db": db,
        "dimension": dimension,
        "phrase": phrase,
        "candidates": candidates,
        "total_values": len(values),
        "cache": cache.status(db, dimension),
        "lookup_issues": validate_lookup_table(db, dimension, valid),
    }


def list_values(db: str, dimension: str, refresh: bool = False, cache: CodebookCache | None = None) -> dict[str, Any]:
    """The whole cached list, for "what options are there for X?" questions."""
    cache = cache or CodebookCache()
    values = cache.values(db, dimension, refresh=refresh)
    return {"db": db, "dimension": dimension, "values": values, "count": len(values), "cache": cache.status(db, dimension)}
