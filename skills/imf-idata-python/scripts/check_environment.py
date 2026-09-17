"""
check_environment.py — inspect the current Python for iData work.

Never installs, fetches, or creates an environment. Run this before installing anything,
and again after a machine/workspace change or an import failure.

Exit code: 0 means the "data" profile passed, 1 means a missing/broken dependency, 2 is a
CLI/report-write error.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

PROFILES = {
    "data": ("imf_datatools", "imf_datatools.idata_utilities", "pandas", "openpyxl"),
}

MIN_PYTHON = (3, 9)

_PROBE = """
import importlib, json, sys
name = sys.argv[1]
try:
    mod = importlib.import_module(name)
except ModuleNotFoundError:
    print(json.dumps({"status": "missing"}))
except Exception as exc:
    print(json.dumps({"status": "broken", "error": str(exc)}))
else:
    print(json.dumps({
        "status": "ok",
        "location": getattr(mod, "__file__", None),
        "version": getattr(mod, "__version__", None),
    }))
"""


def probe_module(name: str, timeout: float) -> dict:
    """Bounded subprocess probe so one broken module can't crash/hide the rest."""
    try:
        result = subprocess.run(
            [sys.executable, "-c", _PROBE, name],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"status": "timeout"}
    if result.returncode != 0 or not result.stdout.strip():
        return {"status": "broken", "error": result.stderr.strip() or "no output"}
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except json.JSONDecodeError:
        return {"status": "broken", "error": "unparseable probe output"}


def inspect_environment(profile: str, timeout: float) -> dict:
    module_results = {name: probe_module(name, timeout) for name in PROFILES[profile]}
    py_ok = sys.version_info >= MIN_PYTHON
    all_ok = all(r.get("status") == "ok" for r in module_results.values())
    installer_path = r"\\ecnswn12p\ems_shared\pub\datatools\installer.py"
    return {
        "schema_version": 1,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "profile": profile,
        "python": {
            "executable": sys.executable,
            "version": sys.version,
            "minimum_version": ".".join(map(str, MIN_PYTHON)),
            "supported": py_ok,
        },
        "skill_directory": str(Path(__file__).resolve().parent),
        "modules": module_results,
        "python_ready": py_ok and all_ok,
        "live_data_access": "not_tested",
        "stable_installer": {
            "path": installer_path,
            "readable": os.name == "nt" and Path(installer_path).exists(),
        },
    }


def write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=str(path.parent), delete=False, suffix=".tmp") as tmp:
        json.dump(report, tmp, indent=2)
        tmp_path = tmp.name
    os.replace(tmp_path, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=list(PROFILES), default="data")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    if not (0 < args.timeout <= 60):
        parser.error("--timeout must be > 0 and <= 60.")

    report = inspect_environment(args.profile, args.timeout)
    print(json.dumps(report, indent=2))

    if args.output:
        try:
            write_report(args.output, report)
        except OSError as exc:
            print(f"ERROR writing report to {args.output}: {exc}", file=sys.stderr)
            return 2

    return 0 if report["python_ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
