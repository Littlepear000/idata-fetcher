"""Bloomberg market series through iData (EMBIG spreads, 10-year government bond yields).

Follows fadfp_useful_charts/EMBIG/embig.py: tickers come from a team-maintained table, are
upper-cased with spaces replaced by '_', and are queried from the iData Bloomberg database
``IMF.CSF:BBGDL`` with the key ``TICKER1+TICKER2+....PX_LAST.D`` (daily last price).
Daily values are averaged to the requested frequency and returned in the long format the
research assistant saves as a dataset.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable

import pandas as pd

BLOOMBERG_DB = "IMF.CSF:BBGDL"
FIELD = "PX_LAST"
MAX_TICKERS_PER_QUERY = 25          # iData key segments are chunked at 25 values
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TICKER_FILES = {
    "embig_spreads": DATA_DIR / "embig_tickers.csv",
    "bond_yield_10y": DATA_DIR / "bond_yield_10y_tickers.csv",
}
SERIES = {
    "embig_spreads": {"indicator": "EMBIG_SPREAD", "label": "J.P. Morgan EMBIG sovereign spread",
                      "unit": "Basis points"},
    "bond_yield_10y": {"indicator": "GOVT_YIELD_10Y", "label": "10-year government bond yield (generic)",
                       "unit": "Percent per annum"},
}
FREQUENCIES = {"D": None, "W": "W", "M": "M", "Q": "Q", "A": "Y"}   # pandas Period aliases

Fetcher = Callable[[str, str, str | None, str | None], pd.DataFrame]


def default_fetcher(database: str, key: str, start: str | None, end: str | None) -> pd.DataFrame:
    """Query iData with the IMF-managed imf_datatools package (needs an authorized session)."""
    from imf_datatools import idata_utilities  # IMF-distributed; not on PyPI

    idata_utilities.PRIVATE = True
    return idata_utilities.get_idata_data(database, key=key, start=start, end=end)


def normalize_ticker(ticker: str) -> str:
    return " ".join(str(ticker).split()).upper().replace(" ", "_")


def load_ticker_table(series: str, path: str | Path | None = None) -> pd.DataFrame:
    """Read the ticker table: columns ticker, country, iso3 (optional ifscode, active).

    Accepts the team CSV in ``data/`` or the original Excel workbook
    (``Bloomberg EMBIG tickers.xlsx``, sheet ``filtered_list``).
    """
    path = Path(path) if path else TICKER_FILES[series]
    if not path.is_file():
        raise FileNotFoundError(f"Ticker table not found: {path}. See references/{series}.md.")
    if path.suffix.lower() in {".xlsx", ".xls"}:
        table = pd.read_excel(path, sheet_name="filtered_list", dtype=str)
    else:
        table = pd.read_csv(path, dtype=str, comment="#", keep_default_na=False)
    table.columns = [str(column).strip().lower() for column in table.columns]
    if not {"ticker", "country"} <= set(table.columns):
        raise ValueError(f"{path.name} needs at least the columns ticker and country.")
    if "active" in table.columns:
        table = table[table["active"].str.strip().str.lower().isin({"", "1", "true", "yes", "y"})]
    table = table[table["ticker"].str.strip() != ""].copy()
    if table.empty:
        raise ValueError(f"{path.name} lists no active tickers. Fill it in first (see references/{series}.md).")
    table["ticker"] = table["ticker"].map(normalize_ticker)
    for column in ("iso3", "ifscode"):
        if column not in table.columns:
            table[column] = ""
        table[column] = table[column].fillna("").astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    # Fill missing ISO3 / IFS codes from the team country table (the EMBIG workbook has names + IFS codes only).
    from .countries import lookup
    for row in table.itertuples():
        record = lookup(row.ifscode) if row.ifscode else None
        record = record or lookup(row.country)
        if record is not None:
            if not row.iso3:
                table.at[row.Index, "iso3"] = record["iso3"]
            if not row.ifscode:
                table.at[row.Index, "ifscode"] = record["ifscode"]
    return table[["ticker", "country", "iso3", "ifscode"]].reset_index(drop=True)


def select_countries(table: pd.DataFrame, countries: Iterable[str] | None) -> pd.DataFrame:
    """Keep rows whose country name, ISO3, IFS code or ticker matches (case-insensitive)."""
    if not countries:
        return table
    wanted = {str(item).strip().casefold() for item in countries if str(item).strip()}
    keys = table[["country", "iso3", "ifscode", "ticker"]].astype(str).apply(lambda col: col.str.casefold())
    mask = keys.isin(wanted).any(axis=1)
    unmatched = sorted(wanted - set(keys.to_numpy().ravel()))
    if unmatched:
        raise ValueError(f"No ticker for {unmatched}. Available countries: {sorted(table['country'])}.")
    return table[mask].reset_index(drop=True)


def fetch_px_last(tickers: list[str], start: str | None = None, end: str | None = None,
                  fetcher: Fetcher | None = None) -> pd.DataFrame:
    """Daily PX_LAST, one column per ticker, DatetimeIndex. Queries in chunks of 25 tickers."""
    fetcher = fetcher or default_fetcher
    parts = []
    for index in range(0, len(tickers), MAX_TICKERS_PER_QUERY):
        chunk = tickers[index:index + MAX_TICKERS_PER_QUERY]
        key = "+".join(chunk) + f".{FIELD}.D"
        frame = fetcher(BLOOMBERG_DB, key, start, end)
        if frame is None or frame.empty:
            continue
        frame = frame.copy()
        if not isinstance(frame.index, pd.DatetimeIndex):
            date_column = next((c for c in frame.columns if str(c).lower() in {"dates", "date", "time_period"}), None)
            if date_column is None:
                raise ValueError("Bloomberg response has no date index or dates column.")
            frame = frame.set_index(date_column)
        frame.index = pd.to_datetime(frame.index)
        frame.columns = [str(column).upper().replace(f".{FIELD}.D", "") for column in frame.columns]
        parts.append(frame[[column for column in frame.columns if column in chunk]])
    if not parts:
        return pd.DataFrame(index=pd.DatetimeIndex([], name="dates"))
    wide = pd.concat(parts, axis=1).sort_index()
    wide.index.name = "dates"
    return wide.apply(pd.to_numeric, errors="coerce")


def _period_label(index: pd.DatetimeIndex, frequency: str) -> pd.Index:
    if frequency == "M":
        return index.strftime("%Y-%m")
    if frequency == "Q":
        return pd.Index([f"{stamp.year}-Q{stamp.quarter}" for stamp in index])
    if frequency == "W":
        return index.strftime("%Y-%m-%d")
    if frequency == "A":
        return index.strftime("%Y")
    return index.strftime("%Y-%m-%d")


def fetch_series(series: str, frequency: str = "M", start_period: str | None = "2008-01-01",
                 end_period: str | None = None, countries: Iterable[str] | None = None,
                 ticker_path: str | Path | None = None, fetcher: Fetcher | None = None
                 ) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Download one Bloomberg series family and return (long frame, lineage entry).

    Long columns: source, database, INDICATOR, indicator_label, COUNTRY (ISO3 when known),
    country_name, IFSCODE, ticker, FREQUENCY, TIME_PERIOD, OBS_VALUE, UNIT, n_daily_obs.
    Period values are simple averages of daily PX_LAST within the period.
    """
    if series not in SERIES:
        raise ValueError(f"series must be one of {sorted(SERIES)}.")
    frequency = str(frequency or "M").upper()
    if frequency not in FREQUENCIES:
        raise ValueError(f"frequency must be one of {sorted(FREQUENCIES)}.")
    table = select_countries(load_ticker_table(series, ticker_path), countries)
    tickers = table["ticker"].tolist()
    daily = fetch_px_last(tickers, start_period or None, end_period or None, fetcher)
    rule = FREQUENCIES[frequency]
    if rule:
        # Group by calendar period (works on pandas 2.1 and 2.2 alike, unlike resample aliases).
        periods = daily.index.to_period(rule)
        averaged = daily.groupby(periods).mean()
        counts = daily.groupby(periods).count()
        averaged.index = counts.index = averaged.index.to_timestamp()
    else:
        averaged, counts = daily, daily.notna().astype(int)
    labels = _period_label(pd.DatetimeIndex(averaged.index), frequency)
    meta = SERIES[series]
    by_ticker = table.set_index("ticker")
    rows = []
    for ticker in averaged.columns:
        info = by_ticker.loc[ticker]
        frame = pd.DataFrame({"TIME_PERIOD": labels, "OBS_VALUE": averaged[ticker].to_numpy(),
                              "n_daily_obs": counts[ticker].to_numpy()})
        frame = frame.dropna(subset=["OBS_VALUE"])
        frame["ticker"] = ticker
        frame["COUNTRY"] = info["iso3"] or info["country"]
        frame["country_name"] = info["country"]
        frame["IFSCODE"] = info["ifscode"]
        rows.append(frame)
    long = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(
        columns=["TIME_PERIOD", "OBS_VALUE", "n_daily_obs", "ticker", "COUNTRY", "country_name", "IFSCODE"])
    long["source"] = "Bloomberg via IMF iData"
    long["database"] = BLOOMBERG_DB
    long["INDICATOR"] = meta["indicator"]
    long["indicator_label"] = meta["label"]
    long["FREQUENCY"] = frequency
    long["UNIT"] = meta["unit"]
    long = long[["source", "database", "INDICATOR", "indicator_label", "COUNTRY", "country_name", "IFSCODE",
                 "ticker", "FREQUENCY", "TIME_PERIOD", "OBS_VALUE", "UNIT", "n_daily_obs"]]
    returned = set(daily.columns)
    missing = [row.country for row in table.itertuples() if row.ticker not in returned]
    lineage = {
        "source": "Bloomberg via IMF iData", "label": meta["label"], "count": len(long),
        "request": {"database": BLOOMBERG_DB, "field": f"{FIELD}.D", "tickers": tickers,
                    "start_period": start_period, "end_period": end_period, "frequency": frequency,
                    "aggregation": "simple average of daily values" if rule else "none (daily)"},
        "coverage": {"missing_requested_areas": {"country": missing}} if missing else {},
    }
    return long.sort_values(["COUNTRY", "TIME_PERIOD"], kind="stable").reset_index(drop=True), lineage
