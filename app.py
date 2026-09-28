"""Run with: python -m streamlit run app.py"""
from __future__ import annotations

from datetime import date, timedelta
import html
import json
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from analytics import (build_study, drawdowns, monthly_returns, relative_metrics,
                       rolling_metric, weekly_returns)
from data_access import (DEFAULT_INDICES, INDICES, live_prices, quality_table,
                         read_upload, snapshot_payload, snapshot_prices)

st.set_page_config(page_title="Global index performance", page_icon="📈", layout="wide")
COLORS = dict(zip(INDICES, ["#13b8a6", "#4c8dff", "#a08bf4", "#f2b65b", "#e78293", "#6abbd7", "#e79a58", "#91b969"]))
st.html("""<style>
.block-container {padding-top:2.5rem;max-width:1480px;padding-bottom:3rem}
h1 {letter-spacing:-1.3px;font-weight:750!important}
h2,h3 {letter-spacing:-.4px}
[data-testid="stMetric"] {background:#14243a;border:1px solid #2a3c53;border-radius:12px;padding:16px 20px}
[data-testid="stMetricLabel"] {color:#afc0d4}
[data-testid="stMetricValue"] {font-size:1.95rem}
.eyebrow {font-size:12px;letter-spacing:2.4px;color:#51cfbd;font-weight:700;margin-bottom:8px}
.lead {color:#afc0d4;font-size:17px;margin-bottom:22px;max-width:900px}
.insight {border-left:3px solid #13b8a6;padding:12px 18px;background:#14243a;border-radius:0 8px 8px 0;margin:14px 0}
</style>""")


@st.cache_data(ttl=3600, show_spinner=False)
def get_live(names: tuple[str, ...], start: str, end: str):
    return live_prices(names, start, end)


@st.cache_data(show_spinner=False)
def get_snapshot(names: tuple[str, ...]):
    return snapshot_prices(names)


def style_chart(fig: go.Figure, height: int = 410) -> go.Figure:
    fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)", font=dict(family="Arial, sans-serif", color="#c9d6e5"),
                      margin=dict(l=15, r=20, t=25, b=25), height=height,
                      legend=dict(orientation="h", y=-.2, x=0, title=None),
                      hovermode="x unified")
    fig.update_xaxes(showgrid=False, zeroline=False, title=None)
    fig.update_yaxes(gridcolor="#23354b", zerolinecolor="#516174")
    return fig


def line_chart(frame: pd.DataFrame, ylabel: str, percent: bool = False) -> go.Figure:
    fig = go.Figure()
    for name in frame:
        values = frame[name].dropna()
        fig.add_trace(go.Scatter(x=values.index, y=values, name=name, mode="lines",
                                line=dict(color=COLORS[name], width=2.7 if name == "Nifty 50" else 1.8),
                                hovertemplate="%{y:.2%}<extra>%{fullData.name}</extra>" if percent else "%{y:.2f}<extra>%{fullData.name}</extra>"))
    style_chart(fig)
    fig.update_yaxes(title=ylabel, tickformat=".0%" if percent else None)
    return fig


def show_chart(fig, key):
    st.plotly_chart(fig, width="stretch", key=key,
                    config={"displaylogo": False, "toImageButtonOptions": {"format": "png", "scale": 2}})


def show_table(frame: pd.DataFrame, percent=(), integer=()):
    formats = {c: "{:.2f}" for c in frame.select_dtypes(include="number").columns}
    formats.update({c: "{:.2%}" for c in percent if c in frame})
    formats.update({c: "{:,.0f}" for c in integer if c in frame})
    st.dataframe(frame.style.format(formats, na_rep="—"), width="stretch")


def pct(value) -> str:
    return f"{float(value):+.1%}"


with st.sidebar:
    st.markdown("### Study settings")
    mode = st.radio("Data source", ["Bundled snapshot", "Live Yahoo Finance", "Upload CSV"], key="source")
    uploaded = None
    if mode == "Upload CSV":
        uploaded = st.file_uploader("Daily closing prices", type="csv")
        st.caption("Columns: Date, Nifty 50, S&P 500, … Use index names exactly as listed. Leave holidays blank.")
    universe = DEFAULT_INDICES if mode == "Bundled snapshot" else list(INDICES)
    selected = st.multiselect("Indices", universe, default=DEFAULT_INDICES, key="indices")
    if not selected:
        st.info("Select at least one index.")
        st.stop()
    if mode == "Bundled snapshot":
        default_end = date(2026, 9, 25)
        st.caption("Saved history through 25 Sep 2026. This mode works offline.")
    else:
        default_end = date.today() - timedelta(days=1)
    default_start = (pd.Timestamp(default_end) - pd.DateOffset(years=2)).date()
    start = st.date_input("Start / baseline date", value=default_start, key=f"start_{mode}")
    end = st.date_input("End date", value=default_end, max_value=date.today() - timedelta(days=1), key=f"end_{mode}")
    benchmark = st.selectbox("Comparison benchmark", selected, index=selected.index("Nifty 50") if "Nifty 50" in selected else 0)
    rolling_window = st.select_slider("Rolling window (sessions)", [21, 63, 126], value=63)
    st.markdown("#### Risk assumptions")
    st.caption("Annual risk-free rates in each index’s local currency. Defaults are 0%; they are assumptions, not observed rates.")
    with st.expander("Edit risk-free rates"):
        rf = {n: st.number_input(f"{n} · {INDICES[n][2]} (%)", min_value=-5.0, max_value=30.0,
                                value=0.0, step=0.25, key=f"rf_{n}") / 100 for n in selected}
    if mode == "Live Yahoo Finance" and st.button("Refresh market data"):
        get_live.clear()
    st.caption("Daily risk annualisation: 252 sessions. Weekly comparisons: 52 weeks.")

st.html('<div class="eyebrow" style="margin-top:16px;margin-bottom:-8px;color:#51cfbd;-webkit-text-fill-color:#51cfbd;user-select:none">MARKET RESEARCH / GLOBAL EQUITIES</div>')
st.title("Global index performance")
st.html('<div class="lead" style="margin-bottom:6px;color:#afc0d4;-webkit-text-fill-color:#afc0d4;user-select:none">Compare Nifty with global markets. See what drove returns, how often markets fell, and the risk taken along the way.</div>')

notes = []
try:
    if start >= end:
        raise ValueError("Choose an end date after the start date.")
    with st.spinner("Preparing daily histories and risk measures…"):
        if mode == "Bundled snapshot":
            raw = get_snapshot(tuple(selected))
            notes = [f"{n}: {r['date']} — {r['supplement_source']}"
                     for n in selected for r in snapshot_payload()["indices"][n]["daily"]
                     if "supplement_source" in r and str(start) <= r["date"] <= str(end)]
        elif mode == "Live Yahoo Finance":
            raw, notes = get_live(tuple(selected), str(start), str(end))
        else:
            if uploaded is None:
                st.info("Upload a daily-close CSV to begin, or select the bundled snapshot.")
                st.stop()
            raw = read_upload(uploaded.getvalue())
            missing = set(selected) - set(raw)
            if missing:
                raise ValueError("The upload is missing selected indices: " + ", ".join(sorted(missing)))
            raw = raw[selected]
        study = build_study(raw, start, end, rf)
except (ValueError, KeyError, TypeError, OSError) as exc:
    st.error(str(exc))
    st.stop()

p, r, m = study.prices, study.returns, study.metrics
numeric = [c for c in m if c not in ["Streak start", "Streak end"]]
m[numeric] = m[numeric].astype(float)
growth = p.div(p.iloc[0]).mul(100)
dd = drawdowns(p)
weekly = weekly_returns(p)
relative = relative_metrics(weekly, benchmark)
period = f"{study.start:%d %b %Y} – {study.end:%d %b %Y}"
st.caption(f"{period}  ·  {len(selected)} indices  ·  {mode}  ·  Daily closing prices")
st.info("Returns are price-only and measured in each market’s local currency. Dividends and FX conversion are excluded. A 100-point starting value is a comparison scale, not a rupee investment.")
if study.start.date() != start or study.end.date() != end:
    st.warning(f"To keep endpoints comparable, the actual common closing dates are {period}. All selected indices have observations on these two dates.")

focus = "Nifty 50" if "Nifty 50" in selected else benchmark
best = m["Price return"].idxmax()
k1, k2, k3, k4 = st.columns(4)
k1.metric(f"{focus} · price return", pct(m.loc[focus, "Price return"]))
k2.metric(f"{focus} · down days", f"{int(m.loc[focus, 'Down days'])} / {int(m.loc[focus, 'Sessions'])}",
          help="A return observation is counted only on an actual session after the baseline close.")
k3.metric("Highest period return", pct(m.loc[best, "Price return"]), best, delta_color="off")
k4.metric(f"{focus} · max drawdown", f"{m.loc[focus, 'Max drawdown']:.1%}",
          help="Largest fall from a preceding closing peak within the selected study.")

overview, risk, daily, relationships, evidence = st.tabs(["Performance", "Risk & drawdowns", "Trading-day behaviour", "Market relationships", "Data & methodology"])
growth_fig = line_chart(growth, "Starting value = 100")
dd_fig = line_chart(dd, "Below previous closing peak", True)

with overview:
    st.subheader("How the markets compounded")
    show_chart(growth_fig, "growth")
    gap = float(m.loc[best, "Price return"] - m.loc[focus, "Price return"]) * 100
    if best != focus:
        insight = f"{best} gained {pct(m.loc[best, 'Price return'])}, ahead of {focus} by {gap:.1f} percentage points over this window."
    else:
        insight = f"{focus} delivered the highest return in this selection: {pct(m.loc[focus, 'Price return'])}."
    st.html(f'<div class="insight" style="color:#e5edf6;-webkit-text-fill-color:#e5edf6;user-select:none">{html.escape(insight)} Down-day frequency and cumulative return measure different things.</div>')
    show_table(m[["Price return", "CAGR", "Volatility", "Max drawdown", "Sharpe", "Down-day share"]],
               percent=["Price return", "CAGR", "Volatility", "Max drawdown", "Down-day share"])
    st.subheader("Monthly returns")
    month_index = st.selectbox("Heatmap index", selected, key="monthly_index")
    months = monthly_returns(p)[month_index].dropna()
    heat = pd.DataFrame({"Year": months.index.year, "Month": months.index.month, "Return": months.values}).pivot(index="Year", columns="Month", values="Return").reindex(columns=range(1, 13))
    heat.columns = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    labels = [["" if pd.isna(v) else f"{v:+.1%}" for v in row] for row in heat.values]
    heat_fig = go.Figure(go.Heatmap(z=heat.values, x=list(heat.columns), y=heat.index.astype(str), text=labels,
                                  texttemplate="%{text}", colorscale=[[0,"#af425b"],[.5,"#14243a"],[1,"#159a89"]],
                                  zmid=0, colorbar=dict(tickformat=".0%"), hovertemplate="%{y} %{x}: %{z:.2%}<extra></extra>"))
    show_chart(style_chart(heat_fig, 280), "monthly")
    st.caption("Boundary months contain only the selected sessions and can be partial. Blank cells are outside the window or lack observations.")

with risk:
    st.subheader("Depth and duration of declines")
    show_chart(dd_fig, "drawdown")
    left, right = st.columns(2)
    with left:
        st.markdown("#### Return versus volatility")
        scatter = m.reset_index(names="Index")
        fig = px.scatter(scatter, x="Volatility", y="CAGR", color="Index", text="Index", color_discrete_map=COLORS,
                         hover_data={"Max drawdown": ":.2%", "Volatility": ":.2%", "CAGR": ":.2%"})
        style_chart(fig)
        fig.update_traces(marker_size=13, textposition="top center", cliponaxis=False)
        fig.update_layout(showlegend=False, hovermode="closest")
        span = max(float(m["Volatility"].max() - m["Volatility"].min()), .05)
        fig.update_xaxes(title="Annualised volatility", tickformat=".0%",
                         range=[max(0, float(m["Volatility"].min()) - .3 * span),
                                float(m["Volatility"].max()) + .3 * span])
        fig.update_yaxes(title="Annualised return (CAGR)", tickformat=".0%")
        show_chart(fig, "scatter")
    with right:
        st.markdown("#### Rolling risk")
        rolling_kind = st.selectbox("Rolling measure", ["Volatility", "Sharpe"], key="rolling_kind")
        rolling = rolling_metric(r, rolling_window, rf, rolling_kind)
        if rolling.dropna(how="all").empty:
            st.info("Choose a shorter rolling window or a longer analysis period.")
        else:
            show_chart(line_chart(rolling, f"{rolling_window}-session {rolling_kind.lower()}", rolling_kind == "Volatility"), "rolling")
    show_table(m[["Volatility", "Sharpe", "Sortino", "Calmar", "Max drawdown", "Current drawdown", "VaR 95% loss", "Expected shortfall 95%", "Longest underwater sessions"]],
               percent=["Volatility", "Max drawdown", "Current drawdown", "VaR 95% loss", "Expected shortfall 95%"], integer=["Longest underwater sessions"])
    st.caption("VaR and expected shortfall are historical one-session loss estimates, not maximum possible losses. A dash indicates an undefined ratio, such as zero volatility or no downside observations.")

with daily:
    st.subheader("How often markets fell — and by how much")
    left, right = st.columns(2)
    with left:
        counts = go.Figure()
        for col, color in [("Down days", "#e78293"), ("Up days", "#13b8a6"), ("Flat days", "#8b9aab")]:
            counts.add_trace(go.Bar(y=m.index, x=m[col]/m["Sessions"], name=col, orientation="h", marker_color=color,
                                   customdata=m[col], hovertemplate="%{y}: %{customdata:.0f} sessions (%{x:.1%})<extra>%{fullData.name}</extra>"))
        style_chart(counts)
        counts.update_layout(barmode="stack", hovermode="closest")
        counts.update_xaxes(tickformat=".0%", title="Share of trading sessions")
        show_chart(counts, "day_counts")
    with right:
        hist_index = st.selectbox("Daily-return distribution", selected, key="hist_index")
        hist = go.Figure(go.Histogram(x=r[hist_index].dropna(), nbinsx=50, marker_color=COLORS[hist_index]))
        style_chart(hist)
        hist.update_layout(showlegend=False, hovermode="closest")
        hist.update_xaxes(tickformat=".0%", title="Daily return")
        hist.update_yaxes(title="Sessions")
        show_chart(hist, "histogram")
    show_table(m[["Sessions", "Down days", "Up days", "Flat days", "Down-day share", "Loss ≥1% days", "Best day", "Worst day", "Mean up day", "Mean down day"]],
               percent=["Down-day share", "Best day", "Worst day", "Mean up day", "Mean down day"],
               integer=["Sessions", "Down days", "Up days", "Flat days", "Loss ≥1% days"])
    st.markdown("#### Longest consecutive declines")
    show_table(m[["Longest losing streak", "Streak start", "Streak end"]], integer=["Longest losing streak"])
    st.caption("Streaks count consecutive actual sessions; holidays do not break a streak. Ties show the earliest streak. Flat days break both up and down streaks.")
    st.markdown("#### Worst individual sessions")
    worst = r.stack().rename("Return").reset_index()
    worst.columns = ["Date", "Index", "Return"]
    worst = worst.nsmallest(10, "Return")
    worst["Date"] = worst["Date"].dt.strftime("%d %b %Y")
    show_table(worst.set_index("Date"), percent=["Return"])

with relationships:
    st.subheader("How markets move together")
    st.caption("Weekly returns reduce the influence of different closing times. They use the last observed close in each Friday-ending week; holiday closing dates can still differ. This is association, not causation.")
    if len(weekly.dropna(how="any")) < 12:
        st.info("At least 12 paired weekly observations are required. Select a longer period.")
    else:
        corr = weekly.corr(min_periods=12)
        fig = go.Figure(go.Heatmap(z=corr.values, x=corr.columns, y=corr.index, zmin=-1, zmax=1,
                                  text=np.round(corr.values, 2), texttemplate="%{text}", colorscale="RdBu", reversescale=True,
                                  hovertemplate="%{y} / %{x}: %{z:.2f}<extra></extra>"))
        show_chart(style_chart(fig, 430), "correlations")
        st.markdown(f"#### Relative to {benchmark}")
        show_table(relative, percent=["Tracking error", "Up capture", "Down capture"], integer=["Paired weeks"])
        st.caption("Beta uses weekly covariance / benchmark variance. Capture ratios compare average returns in benchmark up/down weeks; a negative downside capture can mean gains while the benchmark fell. Cross-currency results describe local markets, not a common-currency portfolio.")

with evidence:
    st.subheader("Inputs, coverage and reproducibility")
    st.dataframe(quality_table(p), width="stretch")
    if (quality_table(p)["Largest gap (calendar days)"] > 10).any():
        st.warning("At least one history has a gap exceeding 10 calendar days. Check whether it is a market holiday or missing data before interpreting exact daily counts.")
    st.caption("Blank dates are not filled with prices or zero returns. This table reports coverage; it does not certify a complete exchange calendar. Undetected missing sessions can affect daily counts and risk measures.")
    with st.expander("Verified supplemental sessions", expanded=False):
        if notes:
            for note in notes:
                st.write(note)
        else:
            st.write("No supplemental sessions were applied within this window.")
    with st.expander("Definitions and assumptions", expanded=True):
        st.markdown("""
* **Window:** use the latest date on/before each requested boundary with a close for every selected index. A boundary gap over 10 calendar days is rejected. Count returns after the baseline through the final close.
* **Daily return:** close / previous actual session close − 1. Holidays are absent; a missing provider observation cannot automatically be distinguished from a holiday.
* **Price return shown:** cumulative **price** change. It excludes reinvested dividends. All indices here use price series; Nasdaq is the Composite.
* **CAGR:** (last / first)^(365.25 / elapsed calendar days) − 1.
* **Volatility:** sample standard deviation of daily returns × √252.
* **Sharpe:** mean daily return above the assumed daily risk-free rate / daily sample standard deviation × √252. Daily risk-free = (1 + annual assumption)^(1/252) − 1.
* **Sortino:** the same numerator divided by √mean(min(daily excess return, 0)²), using all observations in the denominator, then annualised by √252.
* **Calmar:** CAGR / absolute maximum drawdown. **Drawdown:** close / highest prior close in the window − 1. Pre-window peaks are excluded.
* **VaR 95%:** negative fifth percentile of observed daily returns, floored at zero. **Expected shortfall:** negative mean of returns at/below that percentile, floored at zero. Both are reported as positive loss magnitudes.
* **Underwater duration:** longest consecutive run of closes below a prior peak, in sessions. It can end before recovery at the study boundary.
* **Weekly comparisons:** last close per Friday-ending week. Drop the first return-less week and unfinished terminal week. No missing-week forward fill. Beta, capture and tracking error use paired observations. Information ratio = mean active weekly return / its sample standard deviation × √52.
* **Risk-free assumptions:** editable by index; defaults are zero to avoid implying a verified current cash yield. Meaningful cross-market investor comparisons require a common currency and appropriate investable total-return series.
* **Data limits:** public Yahoo data may omit sessions, be revised, or rate-limit downloads. Known Indian special-session supplements are bundled with source URLs. Live failures are displayed and never silently replaced with snapshot data.
""")
    st.markdown("#### Data sources")
    for name in selected:
        symbol = INDICES[name][0].replace("^", "%5E")
        st.markdown(f"[{name} daily history](https://finance.yahoo.com/quote/{symbol}/history/) · {INDICES[name][1]} · {INDICES[name][2]}")
    st.markdown("#### Inspect the daily observations")
    inspect_name = st.selectbox("Index to inspect", selected, key="inspect_index")
    inspect = pd.DataFrame({"Close": p[inspect_name].dropna(), "Daily return": r[inspect_name]})
    negative_only = st.checkbox("Negative days only", key="negative_only")
    if negative_only:
        inspect = inspect.loc[inspect["Daily return"] < 0]
    show_table(inspect.sort_index(ascending=False), percent=["Daily return"])

st.divider()
st.markdown("### Export this study")
metadata = {"source": mode, "requested_start": str(start), "requested_end": str(end),
            "actual_start": str(study.start.date()), "actual_end": str(study.end.date()),
            "indices": selected, "benchmark": benchmark, "risk_free_annual": rf,
            "annualization_sessions": 252, "currency_basis": "local currency, no FX conversion",
            "return_basis": "closing price; no reinvested dividends", "supplements": notes}
e1, e2, e3, e4 = st.columns(4)
e1.download_button("Summary CSV", m.to_csv().encode(), "index-risk-return-summary.csv", "text/csv")
e2.download_button("Daily closes CSV", p.to_csv().encode(), "daily-index-closes.csv", "text/csv")
e3.download_button("Daily returns CSV", r.to_csv().encode(), "daily-index-returns.csv", "text/csv")
e4.download_button("Study settings JSON", json.dumps(metadata, indent=2).encode(), "study-settings.json", "application/json")
st.caption("CSV return and risk percentages are stored as decimal fractions: 0.10 = 10%. Every chart can be downloaded as a PNG from its toolbar.")

# ── The Mountain Path Academy footer ─────────────────────────────────────────
MP_GOLD, MP_CARD, MP_MUTED, MP_TXT = "#FFD700", "#112240", "#8892b0", "#e6f1ff"


def mp_link(url: str, label: str) -> str:
    return (f'<a href="{url}" target="_blank" rel="noopener noreferrer" '
            f'style="color:{MP_GOLD};-webkit-text-fill-color:{MP_GOLD};text-decoration:none;'
            f'font-weight:700;margin:0 10px">{label}</a>')


MP_FOOTER = (
    f'<div style="margin-top:2.2rem;padding:18px 20px;background:{MP_CARD};border-top:2px solid {MP_GOLD};'
    f'border-radius:10px;text-align:center;user-select:none;font-family:Arial,sans-serif">'
    f'<div style="color:{MP_TXT};-webkit-text-fill-color:{MP_TXT};font-weight:700;font-size:15px;margin-bottom:6px">'
    f'Prof. V. Ravichandran · The Mountain Path Academy</div>'
    f'<div style="color:{MP_MUTED};-webkit-text-fill-color:{MP_MUTED};font-size:14px;margin-bottom:8px">'
    f'{mp_link("https://themountainpathacademy.com", "themountainpathacademy.com")}|'
    f'{mp_link("https://www.linkedin.com/in/trichyravis", "LinkedIn")}|'
    f'{mp_link("https://github.com/trichyravis", "GitHub")}</div>'
    f'<div style="color:{MP_MUTED};-webkit-text-fill-color:{MP_MUTED};font-size:12px">'
    f'For education and research only. Not investment advice.</div></div>'
)
st.html(MP_FOOTER)
