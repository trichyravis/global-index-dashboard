"""Auditable calculations for local-currency, price-only index histories."""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass
class Study:
    prices: pd.DataFrame
    returns: pd.DataFrame
    metrics: pd.DataFrame
    start: pd.Timestamp
    end: pd.Timestamp


def validate_prices(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or frame.shape[1] == 0:
        raise ValueError("No closing prices were supplied.")
    out = frame.copy()
    out.index = pd.to_datetime(out.index, errors="raise")
    if out.index.isna().any():
        raise ValueError("Dates cannot be blank.")
    if out.index.tz is not None:
        out.index = out.index.tz_localize(None)
    out.index = out.index.normalize()
    if out.index.has_duplicates or out.columns.has_duplicates:
        raise ValueError("Duplicate dates or index names: provide one close per index per date.")
    for name in out:
        out[name] = pd.to_numeric(out[name], errors="raise")
        observed = out[name].dropna()
        if observed.empty or not np.isfinite(observed).all() or (observed <= 0).any():
            raise ValueError(f"{name}: prices must contain finite, positive values.")
    # Listed index closes are published to two decimals; remove binary float noise.
    out = out.round(2)
    if (out <= 0).any().any():
        raise ValueError("Prices must remain positive when rounded to two decimals.")
    return out.sort_index().rename_axis("Date")


def safe_ratio(numerator: float, denominator: float) -> float:
    return float(numerator / denominator) if denominator > 1e-12 else np.nan


def longest_streak(returns: pd.Series, negative: bool = True) -> tuple[int, str, str]:
    best: list[pd.Timestamp] = []
    run: list[pd.Timestamp] = []
    for date, value in returns.items():
        matches = value < 0 if negative else value > 0
        run = run + [date] if matches else []
        if len(run) > len(best):
            best = run[:]
    return (len(best), str(best[0].date()), str(best[-1].date())) if best else (0, "—", "—")


def drawdowns(prices: pd.DataFrame) -> pd.DataFrame:
    return pd.concat({n: s.dropna().div(s.dropna().cummax()).sub(1)
                      for n, s in prices.items()}, axis=1)


def build_study(raw: pd.DataFrame, start, end, risk_free: dict[str, float] | None = None,
                annualization: int = 252) -> Study:
    raw = validate_prices(raw)
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    if start >= end:
        raise ValueError("The end date must be after the start date.")
    common = raw.dropna(how="any")
    before = common.index[common.index <= start]
    after = common.index[common.index <= end]
    if len(before) == 0 or len(after) == 0:
        raise ValueError("Every selected index needs a close on or before the start and end dates. Supply earlier data or change the dates.")
    first, last = before[-1], after[-1]
    if (start - first).days > 10 or (end - last).days > 10:
        raise ValueError("A selected series is missing recent boundary data (over 10 calendar days). Check its coverage or shorten the requested window.")
    if first >= last:
        raise ValueError("The selected window has no usable return observations.")
    prices = raw.loc[first:last].copy()
    returns = pd.concat({n: s.dropna().pct_change(fill_method=None).iloc[1:]
                         for n, s in prices.items()}, axis=1)
    rf = risk_free or {}
    metrics = {}
    for name in prices:
        p, r = prices[name].dropna(), returns[name].dropna()
        if len(r) < 20:
            raise ValueError(f"{name}: at least 20 daily returns are needed for this analysis.")
        rate = rf.get(name, 0.0)
        if not np.isfinite(rate) or rate <= -1:
            raise ValueError("Risk-free assumptions must be finite and above −100%.")
        excess = r - ((1 + rate) ** (1 / annualization) - 1)
        std = r.std(ddof=1)
        downside = np.sqrt(np.mean(np.minimum(excess, 0) ** 2))
        dd = p / p.cummax() - 1
        cagr = (p.iloc[-1] / p.iloc[0]) ** (365.25 / (last - first).days) - 1
        q = r.quantile(0.05)
        tail = r[r <= q]
        streak, streak_start, streak_end = longest_streak(r)
        under_water, longest_under_water = 0, 0
        for d in dd.iloc[1:]:
            under_water = under_water + 1 if d < -1e-12 else 0
            longest_under_water = max(longest_under_water, under_water)
        metrics[name] = {
            "Price return": p.iloc[-1] / p.iloc[0] - 1,
            "CAGR": cagr,
            "Volatility": std * np.sqrt(annualization),
            "Sharpe": safe_ratio(excess.mean() * np.sqrt(annualization), std),
            "Sortino": safe_ratio(excess.mean() * np.sqrt(annualization), downside),
            "Calmar": safe_ratio(cagr, abs(dd.min())),
            "Max drawdown": dd.min(), "Current drawdown": dd.iloc[-1],
            "VaR 95% loss": max(0.0, -q), "Expected shortfall 95%": max(0.0, -tail.mean()),
            "Sessions": len(r), "Down days": int((r < 0).sum()),
            "Up days": int((r > 0).sum()), "Flat days": int((r == 0).sum()),
            "Down-day share": (r < 0).mean(), "Loss ≥1% days": int((r <= -0.01).sum()),
            "Mean up day": r[r > 0].mean(), "Mean down day": r[r < 0].mean(),
            "Best day": r.max(), "Worst day": r.min(),
            "Longest losing streak": streak, "Streak start": streak_start,
            "Streak end": streak_end, "Longest underwater sessions": longest_under_water,
            "Risk-free assumption": rate,
        }
    return Study(prices, returns, pd.DataFrame(metrics).T, first, last)


def monthly_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Compound only the included sessions; first and last months may be partial."""
    columns = {}
    for name, values in prices.items():
        r = values.dropna().pct_change(fill_method=None).dropna()
        columns[name] = (1 + r).resample("ME").prod(min_count=1) - 1
    return pd.DataFrame(columns)


def weekly_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Friday-labelled weekly closes. Omit the unfinished terminal week."""
    closes = prices.resample("W-FRI").last()
    closes = closes.loc[closes.index <= prices.index.max()]
    return closes.pct_change(fill_method=None).iloc[1:]


def relative_metrics(weekly: pd.DataFrame, benchmark: str) -> pd.DataFrame:
    result = {}
    for name in weekly:
        pair = pd.concat([weekly[name].rename("asset"), weekly[benchmark].rename("benchmark")], axis=1).dropna()
        if len(pair) < 12:
            continue
        a, b = pair["asset"], pair["benchmark"]
        active = a - b
        ups, downs = b > 0, b < 0
        result[name] = {
            "Weekly correlation": a.corr(b),
            "Beta": safe_ratio(a.cov(b), b.var(ddof=1)),
            "Tracking error": active.std(ddof=1) * np.sqrt(52),
            "Information ratio": safe_ratio(active.mean() * np.sqrt(52), active.std(ddof=1)),
            "Up capture": a[ups].mean() / b[ups].mean() if ups.sum() >= 5 else np.nan,
            "Down capture": a[downs].mean() / b[downs].mean() if downs.sum() >= 5 else np.nan,
            "Paired weeks": len(pair),
        }
    return pd.DataFrame(result).T


def rolling_metric(returns: pd.DataFrame, window: int, risk_free: dict[str, float],
                   kind: str, annualization: int = 252) -> pd.DataFrame:
    result = {}
    for name, values in returns.items():
        r = values.dropna()
        sd = r.rolling(window, min_periods=window).std(ddof=1)
        if kind == "Volatility":
            result[name] = sd * np.sqrt(annualization)
        else:
            daily_rf = (1 + risk_free.get(name, 0)) ** (1 / annualization) - 1
            result[name] = ((r - daily_rf).rolling(window).mean() / sd.where(sd > 1e-12)) * np.sqrt(annualization)
    return pd.DataFrame(result)
