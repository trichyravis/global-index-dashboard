import numpy as np
import pandas as pd
import pytest

from analytics import (build_study, longest_streak, monthly_returns,
                       relative_metrics, validate_prices, weekly_returns)
from data_access import live_prices, read_upload, snapshot_prices


def series_frame(values):
    return pd.DataFrame({"Test": values}, index=pd.bdate_range("2024-01-01", periods=len(values)))


def test_snapshot_two_year_reconciliation():
    raw = snapshot_prices(("Nifty 50", "S&P 500"))
    s = build_study(raw, "2024-09-25", "2026-09-25")
    assert s.metrics.loc["Nifty 50", "Sessions"] == 496
    assert s.metrics.loc["Nifty 50", "Down days"] == 257
    for name in raw:
        r = s.returns[name].dropna()
        assert np.prod(1 + r) - 1 == pytest.approx(s.metrics.loc[name, "Price return"])
        assert ((1 + monthly_returns(s.prices)[name].dropna()).prod() - 1) == pytest.approx(s.metrics.loc[name, "Price return"])
        assert sum(s.metrics.loc[name, c] for c in ["Up days", "Down days", "Flat days"]) == len(r)


def test_holidays_are_not_flat_observations():
    frame = series_frame(np.arange(100, 140, dtype=float)).rename(columns={"Test": "A"})
    frame["B"] = frame["A"] * 2
    frame.loc[frame.index[10], "B"] = np.nan
    s = build_study(frame, frame.index[0], frame.index[-1])
    assert s.metrics.loc["A", "Sessions"] == 39
    assert s.metrics.loc["B", "Sessions"] == 38
    assert s.metrics.loc["B", "Flat days"] == 0
    assert pd.isna(s.returns.loc[frame.index[10], "B"])
    assert s.returns.loc[frame.index[11], "B"] == pytest.approx(111 / 109 - 1)


def test_flat_market_ratios_undefined():
    frame = series_frame([100.0] * 40)
    m = build_study(frame, frame.index[0], frame.index[-1]).metrics.loc["Test"]
    for column in ["Sharpe", "Sortino", "Calmar"]:
        assert pd.isna(m[column])
    assert m["Flat days"] == 39
    assert m["Max drawdown"] == 0


def test_drawdown_and_loss_signs():
    frame = series_frame([100, 120, 90, 96] + [96] * 30)
    m = build_study(frame, frame.index[0], frame.index[-1]).metrics.loc["Test"]
    assert m["Max drawdown"] == pytest.approx(-.25)
    assert m["Current drawdown"] == pytest.approx(-.2)
    assert m["Worst day"] == pytest.approx(-.25)
    assert m["Expected shortfall 95%"] >= m["VaR 95% loss"] >= 0


def test_risk_free_is_applied_to_sharpe_and_sortino():
    frame = series_frame([100 + i + 2 * (i % 3) for i in range(40)])
    low = build_study(frame, frame.index[0], frame.index[-1], {"Test": 0}).metrics.loc["Test"]
    high = build_study(frame, frame.index[0], frame.index[-1], {"Test": .08}).metrics.loc["Test"]
    assert high["Sharpe"] < low["Sharpe"]
    assert high["Sortino"] < low["Sortino"]
    assert high["Price return"] == low["Price return"]


def test_streak_spans_holidays_and_flat_breaks_it():
    r = pd.Series([-.1, -.1, 0, -.1], index=pd.to_datetime(["2024-01-05", "2024-01-08", "2024-01-09", "2024-01-10"]))
    assert longest_streak(r) == (2, "2024-01-05", "2024-01-08")


@pytest.mark.parametrize("bad", [0, -1, np.inf])
def test_invalid_prices_rejected(bad):
    with pytest.raises(ValueError, match="positive"):
        validate_prices(series_frame([100, bad, 101]))


def test_duplicate_dates_rejected():
    frame = series_frame([100, 101])
    frame.index = [frame.index[0]] * 2
    with pytest.raises(ValueError, match="Duplicate"):
        validate_prices(frame)


def test_no_silent_shortened_window():
    frame = series_frame(range(100, 140))
    with pytest.raises(ValueError, match="before the start"):
        build_study(frame, "2023-01-01", frame.index[-1])
    with pytest.raises(ValueError, match="10 calendar days"):
        build_study(frame, frame.index[0], "2025-01-01")


def test_weekly_no_fill_and_terminal_partial_week_removed():
    frame = pd.DataFrame({"Test": [100., 110., 120.]}, index=pd.to_datetime(["2024-01-05", "2024-01-19", "2024-01-23"]))
    weekly = weekly_returns(frame)
    assert weekly["Test"].isna().all()
    assert pd.Timestamp("2024-01-26") not in weekly.index


def test_beta_known_relationship():
    r = pd.Series(np.tile([.01, -.02, .03, -.01], 10), index=pd.date_range("2024-01-05", periods=40, freq="W-FRI"))
    result = relative_metrics(pd.DataFrame({"Benchmark": r, "Double": 2 * r}), "Benchmark")
    assert result.loc["Double", "Beta"] == pytest.approx(2)
    assert result.loc["Double", "Weekly correlation"] == pytest.approx(1)
    assert result.loc["Double", "Up capture"] == pytest.approx(2)
    assert result.loc["Double", "Down capture"] == pytest.approx(2)


def test_csv_rejects_unrecognised_or_missing_columns():
    with pytest.raises(ValueError, match="Date column"):
        read_upload(b"Unknown,Price\n2024-01-01,100")
    with pytest.raises(ValueError, match="Unrecognised"):
        read_upload(b"Date,Unknown\n2024-01-01,100")


def test_live_loader_end_exclusive_and_special_session(monkeypatch):
    import yfinance
    seen = {}
    def download(symbol, **kwargs):
        seen.update(kwargs)
        return pd.DataFrame({"Close": [25320.65, 25088.4]}, index=pd.to_datetime(["2026-01-30", "2026-02-02"]))
    monkeypatch.setattr(yfinance, "download", download)
    p, notes = live_prices(("Nifty 50",), "2026-01-30", "2026-02-02")
    assert str(seen["end"]) == "2026-02-03"
    assert p.loc["2026-02-01", "Nifty 50"] == 24825.45
    assert len(notes) == 1


def test_live_failure_does_not_silently_use_snapshot(monkeypatch):
    import yfinance
    monkeypatch.setattr(yfinance, "download", lambda *args, **kwargs: pd.DataFrame())
    with pytest.raises(ValueError, match="Could not load"):
        live_prices(("Nifty 50",), "2024-09-25", "2026-09-25")
