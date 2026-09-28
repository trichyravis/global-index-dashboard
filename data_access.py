"""Data sources are explicit: cached live prices, bundled history, or user CSV."""
from __future__ import annotations

from pathlib import Path
from io import BytesIO
import json
import pandas as pd

ROOT = Path(__file__).resolve().parent
INDICES = {
    "Nifty 50": ("^NSEI", "India", "INR"),
    "S&P 500": ("^GSPC", "United States", "USD"),
    "Nasdaq Composite": ("^IXIC", "United States", "USD"),
    "FTSE 100": ("^FTSE", "United Kingdom", "GBP"),
    "Nikkei 225": ("^N225", "Japan", "JPY"),
    "Hang Seng": ("^HSI", "Hong Kong", "HKD"),
    "Dow Jones": ("^DJI", "United States", "USD"),
    "Euro Stoxx 50": ("^STOXX50E", "Euro area", "EUR"),
}
DEFAULT_INDICES = list(INDICES)[:6]


def snapshot_payload() -> dict:
    return json.loads((ROOT / "data" / "snapshot.json").read_text(encoding="utf-8"))


def snapshot_prices(names: tuple[str, ...]) -> pd.DataFrame:
    payload = snapshot_payload()
    result = {}
    for name in names:
        item = payload["indices"][name]
        rows = [item["baseline"]] + item["daily"]
        result[name] = pd.Series({pd.Timestamp(r["date"]): r["close"] for r in rows})
    return pd.DataFrame(result).sort_index().rename_axis("Date")


def read_upload(content: bytes) -> pd.DataFrame:
    from analytics import validate_prices
    frame = pd.read_csv(BytesIO(content))
    if "Date" not in frame:
        raise ValueError("CSV needs a Date column (YYYY-MM-DD) and one numeric closing-price column per index.")
    unknown = set(frame.columns) - {"Date"} - set(INDICES)
    if unknown:
        raise ValueError("Unrecognised index columns: " + ", ".join(sorted(unknown)))
    return validate_prices(frame.set_index("Date"))


def live_prices(names: tuple[str, ...], start: str, end: str) -> tuple[pd.DataFrame, list[str]]:
    import yfinance as yf
    from analytics import validate_prices
    begin = pd.Timestamp(start) - pd.Timedelta(days=30)
    finish = pd.Timestamp(end) + pd.Timedelta(days=1)  # Yahoo's end is exclusive.
    result, notes = {}, []
    supplements = snapshot_payload()["indices"]
    for name in names:
        symbol = INDICES[name][0]
        try:
            history = yf.download(
                symbol, start=begin.date(), end=finish.date(), interval="1d",
                auto_adjust=False, actions=False, progress=False, threads=False,
                multi_level_index=False, timeout=20,
            )
            if history is None or history.empty or "Close" not in history:
                raise ValueError("No daily closing prices returned")
            closes = history["Close"]
            if isinstance(closes, pd.DataFrame):
                closes = closes.iloc[:, 0]
            closes = closes.dropna().copy()
            closes.index = pd.to_datetime(closes.index).tz_localize(None).normalize()
            for row in supplements.get(name, {}).get("daily", []):
                day = pd.Timestamp(row["date"])
                if "supplement_source" in row and begin <= day < finish and day not in closes.index:
                    closes.loc[day] = row["close"]
                    notes.append(f"{name}: added verified session {day.date()} — {row['supplement_source']}")
            result[name] = closes.sort_index()
        except Exception as exc:
            # Never substitute the bundled history for a failed live request.
            raise ValueError(f"Could not load {name} ({symbol}): {exc}. Retry, select fewer indices, upload data, or explicitly select the bundled snapshot.") from exc
    return validate_prices(pd.DataFrame(result)), notes


def quality_table(prices: pd.DataFrame) -> pd.DataFrame:
    records = []
    for name, values in prices.items():
        values = values.dropna()
        gaps = values.index.to_series().diff().dt.days
        records.append({"Index": name, "First close": str(values.index.min().date()),
                        "Last close": str(values.index.max().date()), "Closes": len(values),
                        "Largest gap (calendar days)": int(gaps.max()) if len(values) > 1 else 0,
                        "Currency": INDICES[name][2], "Symbol": INDICES[name][0]})
    return pd.DataFrame(records).set_index("Index")
