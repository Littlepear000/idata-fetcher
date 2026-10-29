"""
idata_agent.cli — the discovery, resolve and code-generation tools as subcommands.
JSON in (flags or a --spec file), one JSON object out on the last line.

Used by skill hosts that run tools through a shell (following skills/imf-idata-python/SKILL.md),
by people testing a tool against real iData, and by the eval suite. Execution (`idata_fetch`)
is not here: it is implemented by the tool-calling harness (see handoff/README.md).

Run from the repository root:

    python -m idata_agent.cli find-databases --phrase "weo live"
    python -m idata_agent.cli list-databases
    python -m idata_agent.cli get-dimensions --db IMF.RES.WEO:WEO_LIVE
    python -m idata_agent.cli new-spec --db IMF.RES.WEO:WEO_LIVE --start 2015 --end 2026 > spec.json
    python -m idata_agent.cli search-values --db IMF.RES.WEO:WEO_LIVE --dimension INDICATOR \
        --phrase "real GDP growth" --hint "percent change"
    python -m idata_agent.cli list-values --db IMF.RES.WEO:WEO_LIVE --dimension FREQUENCY
    python -m idata_agent.cli expand-group --query "advanced economies"
    python -m idata_agent.cli get-metadata --db IMF.RES.WEO:WEO_LIVE --key .NGDP_RPCH.A
    python -m idata_agent.cli preview --spec spec.json
    python -m idata_agent.cli render-code --spec spec.json [--language stata]

Output: {"ok": true, "data": ...} or {"ok": false, "error": {"type", "message"}}. Exit 0 on ok.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from .codegen.render import render
from .spec import DimensionSlot, QuerySpec
from .tools import _idata, discovery, resolve


def envelope(fn: Callable[..., dict], **kwargs: Any) -> dict[str, Any]:
    """Run one tool function and wrap the outcome the way the harness is expected to."""
    try:
        return {"ok": True, "data": fn(**kwargs)}
    except _idata.IDataToolError as exc:
        return {"ok": False, "error": {"type": "invalid_call", "message": str(exc)}}
    except _idata.IDataEnvironmentError as exc:
        return {"ok": False, "error": {"type": "environment_error", "message": str(exc)}}
    except Exception as exc:  # upstream SDK / network / permissions
        return {"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}


def _load_spec(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _emit(result: dict, pretty: bool) -> int:
    print(json.dumps(result, indent=2 if pretty else None, ensure_ascii=False, default=str))
    return 0 if result.get("ok") else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m idata_agent.cli", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--compact", action="store_true", help="print JSON on one line")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("find-databases", help="fuzzy-match the user's words against the catalogue")
    s.add_argument("--phrase", required=True)
    s.add_argument("--limit", type=int, default=5)
    s.add_argument("--refresh", action="store_true")

    s = sub.add_parser("list-databases", help="the whole catalogue")
    s.add_argument("--refresh", action="store_true")

    s = sub.add_parser("get-dimensions", help="dimension names in key order")
    s.add_argument("--db", required=True)
    s.add_argument("--refresh", action="store_true")

    s = sub.add_parser("search-values", help="rank a dimension's values against a phrase")
    s.add_argument("--db", required=True)
    s.add_argument("--dimension", required=True)
    s.add_argument("--phrase", required=True)
    s.add_argument("--hint", action="append", dest="hints", help="repeatable qualifier, e.g. 'percent change'")
    s.add_argument("--limit", type=int, default=15)
    s.add_argument("--refresh", action="store_true", help="re-download the cached list")

    s = sub.add_parser("list-values", help="the complete cached value list of a dimension")
    s.add_argument("--db", required=True)
    s.add_argument("--dimension", required=True)
    s.add_argument("--refresh", action="store_true")

    s = sub.add_parser("expand-group", help="WEO country group -> ISO3 codes")
    s.add_argument("--query", required=True)

    s = sub.add_parser("get-metadata", help="unit / scale / methodology for a key")
    s.add_argument("--db", required=True)
    s.add_argument("--key", required=True)
    s.add_argument("--max-rows", type=int, default=50)

    s = sub.add_parser("preview", help="first rows + total count for a spec")
    s.add_argument("--spec", required=True, help="path to a QuerySpec JSON file")
    s.add_argument("--rows", type=int, default=5)

    s = sub.add_parser("render-code", help="Python / Stata / R code for a spec")
    s.add_argument("--spec", required=True)
    s.add_argument("--language", choices=["python", "stata", "r"], help="print only this language's code as text")

    s = sub.add_parser("new-spec", help="write an empty spec with the database's dimension slots")
    s.add_argument("--db", required=True)
    s.add_argument("--start")
    s.add_argument("--end")
    s.add_argument("--layout", choices=["long", "wide"], default="long")
    s.add_argument("--file-format", choices=["csv", "xlsx", "dta"], default="csv")
    s.add_argument("--language", choices=["python", "stata", "r"], default="python")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    pretty = not args.compact
    c = args.command

    if c == "find-databases":
        return _emit(envelope(discovery.find_databases, phrase=args.phrase, limit=args.limit, refresh=args.refresh), pretty)
    if c == "list-databases":
        return _emit(envelope(discovery.list_databases, refresh=args.refresh), pretty)
    if c == "get-dimensions":
        return _emit(envelope(discovery.get_dimensions, db=args.db, refresh=args.refresh), pretty)
    if c == "search-values":
        return _emit(envelope(discovery.search_values, db=args.db, dimension=args.dimension, phrase=args.phrase, hints=args.hints, limit=args.limit, refresh=args.refresh), pretty)
    if c == "list-values":
        return _emit(envelope(discovery.list_values, db=args.db, dimension=args.dimension, refresh=args.refresh), pretty)
    if c == "expand-group":
        return _emit(envelope(resolve.expand_group, query=args.query), pretty)
    if c == "get-metadata":
        return _emit(envelope(resolve.get_metadata, db=args.db, key=args.key, max_rows=args.max_rows), pretty)
    if c == "preview":
        return _emit(envelope(resolve.preview, spec=_load_spec(args.spec), rows=args.rows), pretty)
    if c == "render-code":
        result = envelope(render, spec=_load_spec(args.spec))
        if args.language and result.get("ok"):
            print(result["data"][args.language])
            return 0
        return _emit(result, pretty)
    if c == "new-spec":
        dims = envelope(discovery.get_dimensions, db=args.db)
        if not dims.get("ok"):
            return _emit(dims, pretty)
        spec = QuerySpec(
            database=args.db,
            dimensions=[DimensionSlot(name=d["name"]) for d in dims["data"]["dimensions"]],
            start=args.start,
            end=args.end,
            layout=args.layout,
            file_format=args.file_format,
            language=args.language,
            stage="resolving",
        )
        print(spec.to_json())
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
