"""
render(spec) -> {"python": str, "stata": str, "r": str}

Templates live in ./templates/*.txt and use `$placeholder` substitution (string.Template), so
there is no Jinja dependency to install on IMF machines. Every language gets the same values;
only the save line and the long-format option differ per language.

Syntax references (documents/imf_datatools_doc.pdf, documents/idata_codebook_v1.docx):
    Python  idata_utilities.get_idata_data(db, key=..., start=..., end=..., longformat=...)
    Stata   idatause data, database(DB) query(KEY) tin(START, END) [panel(DIM)] clear
    R       imf_datatools$get_idata_data(db, key, start=..., end=..., longformat=TRUE)
"""

from __future__ import annotations

from pathlib import Path
from string import Template
from typing import Any

from ..spec import QuerySpec, coerce_spec

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def _template(name: str) -> Template:
    return Template((TEMPLATES_DIR / f"{name}.txt").read_text(encoding="utf-8"))


def _output_path(spec: QuerySpec) -> str:
    """Path shown in generated code. Uses the spec's path if set, else a Windows Downloads path."""
    if spec.output_path:
        return spec.output_path
    base = spec.output_dir or r"C:\Users\<you>\Downloads"
    sep = "/" if "/" in base and "\\" not in base else "\\"
    return f"{base}{sep}{spec.default_filename()}"


def _dimension_lines(spec: QuerySpec, comment: str) -> str:
    """One comment line per dimension: '# COUNTRY: USA+JPN  (the US and Japan)'."""
    lines = []
    for d in spec.dimensions:
        seg = d.segment() or "<all values>"
        phrase = f"  ({d.phrase})" if d.phrase else ""
        lines.append(f"{comment} {d.name}: {seg}{phrase}")
    return "\n".join(lines)


def _python_save(spec: QuerySpec, path: str) -> str:
    raw = "r" if "\\" in path else ""
    if spec.file_format == "xlsx":
        return f"df.to_excel({raw}'{path}')"
    if spec.file_format == "dta":
        return (
            "# Stata variable names must be letters, digits and underscores (max 32 chars).\n"
            "df.columns = [c.replace('.', '_').replace('+', '_')[:32] for c in df.columns]\n"
            f"df.to_stata({raw}'{path}')"
        )
    return f"df.to_csv({raw}'{path}')"


def _stata_save(spec: QuerySpec, path: str) -> str:
    if spec.file_format == "xlsx":
        return f'export excel using "{path}", firstrow(variables) replace'
    if spec.file_format == "dta":
        return f'save "{path}", replace'
    return f'export delimited using "{path}", replace'


def _r_save(spec: QuerySpec, path: str) -> str:
    rpath = path.replace("\\", "/")
    if spec.file_format == "xlsx":
        return f'openxlsx::write.xlsx(df, "{rpath}", rowNames = TRUE)'
    if spec.file_format == "dta":
        return f'haven::write_dta(df, "{rpath}")'
    return f'write.csv(df, "{rpath}")'


def render(spec: QuerySpec | dict | str) -> dict[str, Any]:
    spec = coerce_spec(spec)
    problems = [p for p in spec.validate() if "stage" not in p]
    if problems:
        from ..tools._idata import IDataToolError

        raise IDataToolError("spec is not ready for code generation: " + "; ".join(problems))

    path = _output_path(spec)
    long_dim = spec.dimensions[0].name if spec.dimensions else "COUNTRY"
    values = {
        "database": spec.database,
        "key": spec.key,
        "key_order": spec.dimension_order_comment,
        "start": spec.start,
        "end": spec.end,
        "output_path": path,
        "output_path_r": path.replace("\\", "/"),
    }

    py = _template("python").substitute(
        values,
        dimension_lines=_dimension_lines(spec, "#"),
        longformat="True" if spec.layout == "long" else "False",
        save_line=_python_save(spec, path),
    )
    st = _template("stata").substitute(
        values,
        dimension_lines=_dimension_lines(spec, "*"),
        panel_option=f" panel({long_dim})" if spec.layout == "long" else "",
        save_line=_stata_save(spec, path),
    )
    r = _template("r").substitute(
        values,
        dimension_lines=_dimension_lines(spec, "#"),
        longformat="TRUE" if spec.layout == "long" else "FALSE",
        save_line=_r_save(spec, path),
    )
    return {"python": py, "stata": st, "r": r, "language": spec.language, "output_path": path}
