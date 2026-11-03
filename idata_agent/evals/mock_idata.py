"""
A fake `imf_datatools` package for offline tests and evals.

Call `install()` before importing anything that touches the SDK. The mock mirrors the real
function signatures and DataFrame shapes documented in references/api_reference.md, with a
small but realistic catalogue:

    IMF.RES.WEO:WEO_LIVE   COUNTRY.INDICATOR.FREQUENCY   (3 dimensions, FREQUENCY has one value)
    IMF.STA:CPI            COUNTRY.INDEX_TYPE.COICOP_1999.TYPE_OF_TRANSFORMATION.FREQUENCY
    IMF.FAD:GFS            COUNTRY.INDICATOR.FREQUENCY

The WEO indicator list deliberately contains two "fiscal balance" candidates (overall and
primary) so tests can check that ambiguity is surfaced rather than silently resolved.
"""

from __future__ import annotations

import sys
import types

WEO_INDICATORS = {
    "NGDP_R": "Gross domestic product, constant prices",
    "NGDP_RPCH": "Gross domestic product, constant prices, percent change",
    "NGDP": "Gross domestic product, current prices",
    "NGDPD": "Gross domestic product, current prices, U.S. dollars",
    "NGDPDPC": "Gross domestic product per capita, current prices, U.S. dollars",
    "PPPGDP": "Gross domestic product, current prices, purchasing power parity; international dollars",
    "PCPI": "Inflation, average consumer prices, index",
    "PCPIPCH": "Inflation, average consumer prices, percent change",
    "PCPIEPCH": "Inflation, end of period consumer prices, percent change",
    "LUR": "Unemployment rate, percent of total labor force",
    "LP": "Population, persons",
    "BCA": "Current account balance, U.S. dollars",
    "BCA_NGDPD": "Current account balance, percent of GDP",
    "GGXCNL_NGDP": "General government net lending/borrowing, percent of GDP",
    "GGXONLB_NGDP": "General government primary net lending/borrowing, percent of GDP",
    "GGXWDG_NGDP": "General government gross debt, percent of GDP",
    "GGR_NGDP": "General government revenue, percent of GDP",
    "GGX_NGDP": "General government total expenditure, percent of GDP",
    "TM_RPCH": "Volume of imports of goods and services, percent change",
    "TX_RPCH": "Volume of exports of goods and services, percent change",
}

COUNTRIES = {
    "USA": "United States",
    "JPN": "Japan",
    "AUS": "Australia",
    "BEN": "Benin",
    "KOR": "Korea, Republic of",
    "DEU": "Germany",
    "FRA": "France",
    "GBR": "United Kingdom",
    "CHN": "China, People's Republic of",
    "G001": "World",
    "G163": "Euro Area (EA)",
}

DATABASES = {
    "IMF.RES.WEO:WEO_LIVE": "World Economic Outlook (WEO) live database",
    "IMF.RES:WEO": "World Economic Outlook (WEO) published vintages",
    "IMF.STA:CPI": "Consumer Price Index (CPI)",
    "IMF.FAD:GFS": "Government Finance Statistics (GFS), fiscal balance and government debt",
}

DIMENSIONS = {
    "IMF.RES.WEO:WEO_LIVE": [("COUNTRY", "Country"), ("INDICATOR", "Indicator"), ("FREQUENCY", "Frequency")],
    "IMF.RES:WEO": [("COUNTRY", "Country"), ("INDICATOR", "Indicator"), ("FREQUENCY", "Frequency")],
    "IMF.STA:CPI": [
        ("COUNTRY", "Country"),
        ("INDEX_TYPE", "Index type"),
        ("COICOP_1999", "Expenditure Category"),
        ("TYPE_OF_TRANSFORMATION", "Type of Transformation"),
        ("FREQUENCY", "Frequency"),
    ],
    "IMF.FAD:GFS": [("COUNTRY", "Country"), ("INDICATOR", "Indicator"), ("FREQUENCY", "Frequency")],
}

VALUES = {
    ("IMF.RES.WEO:WEO_LIVE", "COUNTRY"): COUNTRIES,
    ("IMF.RES.WEO:WEO_LIVE", "INDICATOR"): WEO_INDICATORS,
    ("IMF.RES.WEO:WEO_LIVE", "FREQUENCY"): {"A": "Annual"},
    ("IMF.RES:WEO", "COUNTRY"): COUNTRIES,
    ("IMF.RES:WEO", "INDICATOR"): WEO_INDICATORS,
    ("IMF.RES:WEO", "FREQUENCY"): {"A": "Annual"},
    ("IMF.STA:CPI", "COUNTRY"): COUNTRIES,
    ("IMF.STA:CPI", "INDEX_TYPE"): {"CPI": "Consumer Price Index", "HICP": "Harmonized Index of Consumer Prices"},
    ("IMF.STA:CPI", "COICOP_1999"): {"_T": "All items", "CP01": "Food and non-alcoholic beverages", "CP04": "Housing, water, electricity, gas and other fuels"},
    ("IMF.STA:CPI", "TYPE_OF_TRANSFORMATION"): {
        "IX": "Index",
        "POP_PCH_PA_PT": "Period-on-period percent change",
        "YOY_PCH_PA_PT": "Year-on-year percent change",
    },
    ("IMF.STA:CPI", "FREQUENCY"): {"A": "Annual", "Q": "Quarterly", "M": "Monthly"},
    ("IMF.FAD:GFS", "COUNTRY"): COUNTRIES,
    ("IMF.FAD:GFS", "INDICATOR"): {"G1_T": "Revenue", "G2_T": "Expense", "GNLB": "Net lending/borrowing"},
    ("IMF.FAD:GFS", "FREQUENCY"): {"A": "Annual"},
}

GROUPS = {"G007": "Advanced Economies", "G200": "Emerging Market and Developing Economies", "G020": "Group of Twenty (G20)", "G163": "Euro Area"}
GROUP_MEMBERS = {
    "G007": ["USA", "JPN", "AUS", "KOR", "DEU", "FRA", "GBR"],
    "G200": ["BEN", "CHN"],
    "G020": ["USA", "JPN", "AUS", "KOR", "DEU", "FRA", "GBR", "CHN"],
    "G163": ["DEU", "FRA"],
}


def _filter(rows: dict, keyword, searchmode):
    import re

    if keyword is None:
        return rows
    keywords = [keyword] if isinstance(keyword, str) else list(keyword)
    combine = all if searchmode == "and" else any
    return {
        k: v
        for k, v in rows.items()
        if combine(re.search(re.escape(kw), f"{k} {v}", re.IGNORECASE) is not None for kw in keywords)
    }


def install() -> types.ModuleType:
    """Register the mock as `imf_datatools` in sys.modules. Safe to call more than once."""
    import numpy as np
    import pandas as pd

    pkg = types.ModuleType("imf_datatools")
    utils = types.ModuleType("imf_datatools.idata_utilities")
    utils.PRIVATE = False
    utils.calls: list[tuple] = []  # every call recorded as (function, args) for assertions

    def get_databases(keyword=None, searchmode="or", refresh=False, debug=False):
        utils.calls.append(("get_databases", keyword))
        rows = _filter(DATABASES, keyword, searchmode)
        df = pd.DataFrame({"Description": list(rows.values())}, index=list(rows.keys()))
        df.index.name = "db"
        return df

    def get_dimensions(db, keyword=None, searchmode="or", refresh=False, debug=False):
        utils.calls.append(("get_dimensions", db))
        if db not in DIMENSIONS:
            raise ValueError(f"unknown database {db}")
        dims = DIMENSIONS[db]
        return pd.DataFrame(
            {"Description": [d for _, d in dims], "Order": list(range(len(dims)))},
            index=[n for n, _ in dims],
        )

    def get_dimension_values(db, dimension, keyword=None, searchmode="or", refresh=False, debug=False):
        utils.calls.append(("get_dimension_values", db, dimension, keyword))
        if (db, dimension) not in VALUES:
            raise ValueError(f"unknown dimension {dimension} for {db}")
        rows = _filter(VALUES[(db, dimension)], keyword, searchmode)
        df = pd.DataFrame({"Name": list(rows.values())}, index=list(rows.keys()))
        df.index.name = "Code"
        return df

    def _series_columns(db, key):
        segments = key.split(".")
        dims = [n for n, _ in DIMENSIONS[db]]
        if len(segments) != len(dims):
            raise ValueError(f"key {key!r} has {len(segments)} segments but {db} has {len(dims)} dimensions")
        choices = []
        for seg, dim in zip(segments, dims):
            valid = VALUES[(db, dim)]
            vals = seg.split("+") if seg else list(valid.keys())
            bad = [v for v in vals if v not in valid]
            if bad:
                return []  # invalid code -> iData returns nothing
            choices.append(vals)
        import itertools

        return [".".join(c) for c in itertools.product(*choices)]

    def get_idata_data(db, key, start=None, end=None, params=None, longformat=False, panel=None, debug=False):
        utils.calls.append(("get_idata_data", db, key, start, end, longformat))
        cols = _series_columns(db, key)
        y0 = int(str(start)[:4]) if start else 2015
        y1 = int(str(end)[:4]) if end else 2026
        idx = pd.to_datetime([f"{y}-01-01" for y in range(y0, y1 + 1)])
        if not cols:
            return pd.DataFrame(index=idx[:0])
        rng = np.random.default_rng(0)
        if longformat:
            dims = [n for n, _ in DIMENSIONS[db]]
            rows = []
            for c in cols:
                parts = c.split(".")
                for d in idx:
                    rows.append({**dict(zip(dims, parts)), "dates": d, "OBS_VALUE": float(rng.normal(2, 1))})
            return pd.DataFrame(rows)
        df = pd.DataFrame({c: rng.normal(2, 1, size=len(idx)).round(3) for c in cols}, index=idx)
        df.index.name = "dates"
        return df

    def get_idata_metadata(db, key, debug=False):
        utils.calls.append(("get_idata_metadata", db, key))
        return pd.DataFrame({"unit": ["PCT"], "scale": [0], "methodology": ["mock"]})

    def get_weo_country_groups(save=False):
        df = pd.DataFrame({"name": list(GROUPS.values())}, index=list(GROUPS.keys()))
        df.index.name = "groupcode"
        return df

    def get_weo_country_info(save=False):
        rows = []
        for iso, name in COUNTRIES.items():
            if iso.startswith("G"):
                continue
            row = {"iso3": iso, "country": name}
            for g, members in GROUP_MEMBERS.items():
                row[g] = 1 if iso in members else 0
            rows.append(row)
        return pd.DataFrame(rows)

    for fn in (get_databases, get_dimensions, get_dimension_values, get_idata_data, get_idata_metadata):
        setattr(utils, fn.__name__, fn)
        setattr(pkg, fn.__name__, fn)
    pkg.get_weo_country_groups = get_weo_country_groups
    pkg.get_weo_country_info = get_weo_country_info
    pkg.idata_utilities = utils
    sys.modules["imf_datatools"] = pkg
    sys.modules["imf_datatools.idata_utilities"] = utils
    return pkg
