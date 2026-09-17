# Runtime paths and Python

Read once before running `scripts/fetch_idata.py`, and again only when setup or path
resolution changes.

## Locate this skill from the host

Use the path of the `SKILL.md` actually loaded by the host as this skill's root. Resolve
`scripts/fetch_idata.py` and `scripts/check_environment.py` relative to that root, and execute
using absolute paths — not relative to the user's current working directory. Do not assume a
particular username, plugin cache version, or host directory. If a script is missing where
expected, report that rather than inventing a path or writing a replacement script.

Quote paths that contain spaces. In PowerShell, put `&` before a quoted executable path; cmd
and POSIX shells invoke the quoted path directly.

## Use the company Python — no venv, no conda

On IMF-managed Windows computers, use `C:\ProgramData\Python3\python.exe`. If it doesn't exist
or won't run, ask the user to install Python via **Software Center**, or report the failure for
IMF IT — do not silently substitute another interpreter.

**Do not create or use a virtual environment or conda environment**, including implicit
creation via uv/Poetry/Pipenv, and do not use `pip install --user`. On IMF-managed Windows
machines, packages install into the global
`C:\ProgramData\Python3\Lib\site-packages`, and the same resolved executable is used for
dependency checks, installation, and running the scripts. If that directory isn't writable,
report the blocker to IMF IT rather than changing the destination.

On a non-IMF machine, use an existing system Python and verify the required imports; this
portability allowance does not permit installing `imf_datatools` on unsupported machines.

## Installing `imf_datatools`

Before installing anything, run:

```bash
python "<SKILL_DIR>/scripts/check_environment.py" --profile data
```

If it exits `0`, the SDK and its dependencies (`pandas`, `openpyxl`) are already usable — skip
installation entirely. If it exits `1`, install only what's missing, using the official
installer and the same resolved Python executable:

```bash
python \\ecnswn12p\ems_shared\pub\datatools\installer.py
```

Never append `dev`, never `pip install imf_datatools` from PyPI, never pull from an unofficial
source, and don't re-run the installer on an SDK that already passes the check just to "update"
it. If `pandas`/`openpyxl` are still missing afterward, install only those two:

```bash
python -m pip install --no-user pandas openpyxl
```

Never use `--user`, `--target`, `--prefix`, `--upgrade`, or admin escalation. If installation is
blocked, report the exact blocker to IMF IT rather than working around it.

## Keep user files in the workspace

Keep the current working directory at the user's own workspace, and resolve `--output` there
(or honor a supplied absolute path) — never write fetched data into this skill's installed
directory. If no `--output` is given, `fetch_idata.py` auto-names a file in the current
directory; report the resulting path to the user.
