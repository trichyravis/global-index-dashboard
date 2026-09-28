# Global index performance

A Streamlit research dashboard comparing **Nifty 50** with major global equity indices over a default **two-year period**. Sensex is excluded.

## Start the app

Requires Python 3.11 or 3.12. Open a terminal in this project folder.

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

### Windows PowerShell

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m streamlit run app.py
```

Open the local URL printed by Streamlit, normally http://localhost:8501.

The app starts with the bundled public-data snapshot, so no API key or internet connection is required after installing packages. For fresh prices, choose **Live Yahoo Finance** in the sidebar. This switches the default dates to the two years ending yesterday, excluding today's potentially incomplete sessions. The snapshot stays explicitly labelled and is never silently used after a live-download failure.

`requirements-lock.txt` records the exact tested environment. For reproducibility on Python 3.12, install it instead of `requirements.txt`. The bounded main requirements are more portable across platforms.

## Included analysis

| Section | What it shows |
|---|---|
| Performance | Indexed growth from 100, cumulative price return, CAGR, monthly heatmap |
| Risk & drawdowns | Peak-to-trough declines, return/volatility scatter, rolling volatility or Sharpe, Sortino, Calmar, historical VaR and expected shortfall |
| Trading-day behaviour | Up/down/flat counts, negative-day percentages, daily-return distribution, losing streaks, worst sessions |
| Market relationships | Weekly correlations, beta, tracking error, information ratio, upside/downside capture versus a selectable benchmark |
| Data & methodology | Coverage, sources, supplemental observations, precise definitions, filterable daily prices and returns |
| Downloads | Summary, daily closes and daily returns as CSV; study assumptions as JSON; chart images via Plotly's toolbar |

### Markets

- Nifty 50 — India — INR
- S&P 500 — United States — USD
- Nasdaq Composite — United States — USD
- FTSE 100 — United Kingdom — GBP
- Nikkei 225 — Japan — JPY
- Hang Seng — Hong Kong — HKD
- Dow Jones and Euro Stoxx 50 — additionally available in live and upload modes

## Reading the results correctly

**These are local-currency price returns.** Dividends, FX conversion, fees and taxes are excluded. A growth line from 100 is an index comparison, not a rupee-denominated investment simulation. The dashboard does not compare common-currency portfolio returns.

Risk-free assumptions are editable separately for each market and default to **0%**. Zero is an explicit modelling assumption, not a current market yield. Daily risk measures annualise using 252 sessions; weekly relative measures use 52 weeks. CAGR uses actual elapsed calendar days.

Daily returns are calculated within each index's actual observed session series. The app does not forward-fill holidays or count them as zero-return days. For comparable performance endpoints, it uses dates on which every selected index has a close, on or before the selected start/end. These actual dates are displayed. A boundary gap over 10 calendar days is rejected.

Correlations and beta use Friday-ending weekly returns to reduce the effect of non-synchronous daily closes. Holiday endpoints may still differ. Correlation does not establish causation, and different local currencies affect interpretation.

Undefined ratios display a dash. Zero volatility, no downside observations, and zero drawdown are handled explicitly. Historical VaR/expected shortfall estimate one-session losses from the sample and do not bound future losses.

## Historical snapshot and session corrections

The snapshot covers 25 September 2023 through 25 September 2026. The default study is **25 September 2024 close to 25 September 2026 close**. The starting close is the baseline; return observations begin after it.

In this default study, Nifty has **496 trading-return observations and 257 negative days**. Its cumulative price return is approximately **−11.0%**.

Main data: public Yahoo Finance daily closing prices, downloaded 28 September 2026. Closing levels are rounded to their published two decimals to avoid floating-point noise in flat-day classification.

The provider omitted five Indian special sessions from the longer Nifty history. These were supplemented with published closing reports, with source URLs retained per observation:

| Date | Nifty close | Source |
|---|---:|---|
| 2023-11-12 | 19,525.55 | [Moneycontrol](https://www.moneycontrol.com/news/business/markets/taking-stock-sensex-jumps-355-points-as-investors-grow-richer-by-rs-2-22-lakh-crore-11729361.html) |
| 2024-01-20 | 21,571.80 | [India Infoline](https://www.indiainfoline.com/blog/weekly-musings-index-performance-for-week-ended-january-20-2024) |
| 2024-03-02 | 22,378.40 | [Reuters / Business Recorder](https://www.brecorder.com/news/40291643) |
| 2024-05-18 | 22,502.00 | [Ajcon research](https://www.ajcononline.com/wp-content/uploads/research/weekly/2024/Weekly180524.pdf) |
| 2026-02-01 | 24,825.45 | [Bajaj Broking market report](https://www.bfsl.co.in/news-details/live-1772798) |

Only 1 February 2026 falls inside the default two-year study. Live mode applies these verified supplemental rows only when the provider omits them; it never overwrites an observed live close.

The coverage table is **not an exchange-calendar completeness certification**. Other missing sessions or subsequent source revisions can affect results. Use official exchange files in upload mode if exact institutional reconciliation is required. Public Yahoo downloads may be delayed, revised or rate-limited. Review data-provider usage terms before redistribution or commercial deployment.

## Upload your own daily prices

Use a wide CSV with one date per row and the exact index names used by the app. Supply a baseline close on/before the selected start date; include earlier history if that date is a holiday. Leave cells blank when a market did not trade. Do not insert zero prices.

```csv
Date,Nifty 50,S&P 500
2026-09-25,23140.50,7743.41
```

This single-row example illustrates the format only. Analysis requires at least 20 return observations. Select only the indices included in your upload. `data/example-upload.csv` contains the actual bundled histories in this format for testing upload mode.

## Project structure

```text
app.py                     Streamlit interface and Plotly charts
analytics.py               Pure calculation functions
data_access.py             Live, snapshot and upload data loaders
data/snapshot.json         Historical prices with supplemental source links
data/example-upload.csv    Complete CSV upload example
.streamlit/config.toml     Navy/teal theme and app configuration
requirements.txt           Runtime dependency ranges
requirements-lock.txt      Exact tested package versions
requirements-dev.txt       Test dependencies
tests/                     Calculation, data-loader and app interaction tests
```

## Run the tests

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Tests cover compounding and count reconciliation, holiday handling, drawdowns, undefined ratios, risk-free assumptions, streaks, invalid/duplicate prices, incomplete coverage, weekly gaps, known beta/capture relationships, special-session supplements, live failure handling, and Streamlit interactions.

## Deployment

The folder is ready to run as a standard Streamlit project. For Streamlit Community Cloud, put it in a repository, select `app.py` as the entry point and use Python 3.12. Hosting is not configured or published by this delivery. The app has no authentication layer; add access controls before using a hosted instance with private uploaded files.

## API references

- [Streamlit caching](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.cache_data)
- [Streamlit Plotly charts](https://docs.streamlit.io/develop/api-reference/charts/st.plotly_chart)
- [Streamlit app testing](https://docs.streamlit.io/develop/api-reference/app-testing/st.testing.v1.apptest)
- [yfinance download parameters](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html)

## Author

Prof. V. Ravichandran · [The Mountain Path Academy](https://themountainpathacademy.com)  
[LinkedIn](https://www.linkedin.com/in/trichyravis) · [GitHub](https://github.com/trichyravis)
