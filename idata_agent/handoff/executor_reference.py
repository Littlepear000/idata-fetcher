"""
Executor: `idata_fetch` — download the confirmed query and save it as a file.

Rules:
- Refuses to run unless the spec validates and `stage == "confirmed"`. This is the code-level
  guard behind the "confirm before execute" step; the dispatcher checks it too.
- Runs the Python query only. Stata and R code are rendered for the user to copy, never run.
- Attaches SCALE and UNIT columns (values already divided by 10**scale when scale > 0).
- Writes the file to the spec's output_dir (default: the user's Downloads) and a sidecar
  `<file>.spec.json` holding the spec, so the file can be traced and re-run later.
- `fetch_in_subprocess` runs the same thing in a child process using the company interpreter,
  so a blocking browser sign-in cannot freeze the UI. IMF Windows machines have no bash; the
  interpreter is started directly.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from ..spec import QuerySpec, coerce_spec
from . import _idata
from .resolve import download_frame, scale_and_unit

SCALE_LABELS = {0: "Units", 3: "Thousands", 6: "Millions", 9: "Billions"}
COMPANY_PYTHON_WINDOWS = r"C:\ProgramData\Python3\python.exe"


def default_output_dir() -> Path:
    return Path.home() / "Downloads"


def resolve_output_path(spec: QuerySpec) -> Path:
    if spec.output_path:
        return Path(spec.output_path).expanduser()
    out_dir = Path(spec.output_dir).expanduser() if spec.output_dir else default_output_dir()
    return out_dir / spec.default_filename()


def _stata_safe_columns(df):
    """Stata variable names: letters, digits, underscore; max 32 chars; must not start with a digit."""
    seen: set[str] = set()
    renamed = {}
    for col in df.columns:
        name = re.sub(r"[^A-Za-z0-9_]", "_", str(col))[:32]
        if not name or name[0].isdigit():
            name = "v_" + name
        base, i = name[:30], 1
        while name in seen:
            name = f"{base}_{i}"
            i += 1
        seen.add(name)
        renamed[col] = name
    return df.rename(columns=renamed), renamed


def save_frame(df, path: Path, file_format: str) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    if file_format == "csv":
        df.to_csv(path, index=False)
    elif file_format == "xlsx":
        try:
            df.to_excel(path, index=False)
        except ImportError as exc:  # openpyxl missing
            fallback = path.with_suffix(".csv")
            df.to_csv(fallback, index=False)
            warnings.append(f"Excel engine unavailable ({exc}); wrote CSV to {fallback} instead.")
            path = fallback
    elif file_format == "dta":
        safe, renamed = _stata_safe_columns(df)
        changed = {k: v for k, v in renamed.items() if str(k) != v}
        if changed:
            warnings.append(f"Renamed {len(changed)} column(s) to valid Stata names, e.g. {next(iter(changed.items()))}.")
        safe.to_stata(path, write_index=False)
    else:
        raise _idata.IDataToolError(f"unsupported file_format {file_format!r}")
    return {"path": str(path), "warnings": warnings}


def fetch(spec: QuerySpec | dict | str, use_frame_cache: bool = True) -> dict[str, Any]:
    """Execute a confirmed spec. Returns a JSON-safe summary; raises IDataToolError if not allowed."""
    spec = coerce_spec(spec)
    problems = spec.missing_for_execution()
    if problems:
        raise _idata.IDataToolError("cannot execute: " + "; ".join(problems))

    started = time.time()
    df = download_frame(spec, use_cache=use_frame_cache)
    if df is None or len(df) == 0:
        raise _idata.IDataToolError(
            "The query returned no rows. Re-check the codes with idata_search_values and, for internal "
            "databases, whether the browser sign-in has expired. Nothing was written."
        )

    scale, unit_label = scale_and_unit(spec.database, spec.key)
    out = df.reset_index()  # the index (usually `dates`) becomes the first column
    if scale:
        value_cols = out.select_dtypes(include="number").columns
        out[value_cols] = out[value_cols] / (10**scale)
    out["SCALE"] = SCALE_LABELS.get(scale, "") if scale is not None else ""
    if unit_label:
        out["UNIT"] = unit_label

    path = resolve_output_path(spec)
    saved = save_frame(out, path, spec.file_format)
    final_path = Path(saved["path"])

    spec.output_path = str(final_path)
    spec.stage = "executed"
    sidecar = final_path.with_suffix(final_path.suffix + ".spec.json")
    sidecar.write_text(json.dumps({"spec": spec.to_dict(), "executed_at": time.time()}, indent=2), encoding="utf-8")

    preview = _idata.frame_to_records(out.set_index(out.columns[0]), max_rows=5)
    return {
        "path": str(final_path),
        "sidecar": str(sidecar),
        "rows": int(len(out)),
        "columns": [str(c) for c in out.columns],
        "scale": SCALE_LABELS.get(scale, "") if scale is not None else "",
        "unit": unit_label,
        "preview": preview["rows"],
        "warnings": saved["warnings"],
        "seconds": round(time.time() - started, 2),
        "spec": spec.to_dict(),
    }


# ---------------------------------------------------------------------------------------
# subprocess wrapper
# ---------------------------------------------------------------------------------------


def company_python() -> str:
    """The interpreter to run fetches with: the IMF-managed Python on Windows, else this one."""
    if os.name == "nt" and Path(COMPANY_PYTHON_WINDOWS).exists():
        return COMPANY_PYTHON_WINDOWS
    return sys.executable


def fetch_in_subprocess(spec: QuerySpec | dict | str, python_exe: str | None = None, timeout: float = 900) -> dict[str, Any]:
    """Run `fetch` in a child process via the CLI and return its parsed JSON result.

    Starts the interpreter directly (no shell). Returns {"ok": False, "error": ...} on failure
    instead of raising, so the caller can show the message and keep the UI alive.
    """
    spec = coerce_spec(spec)
    repo_root = Path(__file__).resolve().parent.parent.parent
    with tempfile.NamedTemporaryFile("w", suffix=".spec.json", delete=False, encoding="utf-8") as fh:
        fh.write(spec.to_json())
        spec_path = fh.name
    cmd = [python_exe or company_python(), "-m", "idata_agent.cli", "fetch", "--spec", spec_path]
    try:
        proc = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": {"type": "timeout", "message": f"fetch did not finish within {timeout}s (waiting for sign-in?)"}}
    finally:
        try:
            os.unlink(spec_path)
        except OSError:
            pass
    stdout = proc.stdout.strip()
    try:
        return json.loads(stdout.splitlines()[-1]) if stdout else {"ok": False, "error": {"type": "no_output", "message": proc.stderr.strip()}}
    except json.JSONDecodeError:
        return {"ok": False, "error": {"type": "bad_output", "message": (proc.stderr or stdout).strip()[-2000:]}}
