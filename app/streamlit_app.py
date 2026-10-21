"""PathogenWatch BD dashboard.  Run:  streamlit run app/streamlit_app.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from pathogenwatch import config as C, cleaning, epi, seasonality as SEAS, anomaly as AN, evaluation as EV, io

st.set_page_config(page_title="PathogenWatch BD", layout="wide")


@st.cache_data(show_spinner="Loading and cleaning WHO FluNet data ...")
def load_clean() -> pd.DataFrame:
    p = C.PROCESSED_DIR / "flunet_country_week_clean.csv"
    if p.exists():
        return pd.read_csv(p, parse_dates=["ISO_WEEKSTARTDATE"], low_memory=False)
    raw = io.load_raw()
    return cleaning.aggregate_fast(cleaning.recover_inf_all(cleaning.drop_exact_duplicates(raw)))


@st.cache_data(show_spinner="Running detectors ...")
def detect(country: str):
    s = cleaning.country_series(load_clean(), country)
    det = AN.run_all(s)
    return s, det


def table(name):
    p = C.TABLE_DIR / name
    return pd.read_csv(p) if p.exists() else None


agg = load_clean()
codes = (agg.groupby(["COUNTRY_CODE", "COUNTRY_AREA_TERRITORY"]).size().reset_index()
         .assign(label=lambda d: d.COUNTRY_AREA_TERRITORY + " (" + d.COUNTRY_CODE + ")"))
default = int(codes.index[codes.COUNTRY_CODE == C.COUNTRY][0])
label = st.sidebar.selectbox("Country / area", codes.label, index=codes.label.tolist().index(codes.label[default]))
country = codes.set_index("label").COUNTRY_CODE[label]
s, det = detect(country)
s_ok = s[~s.gap_week]

st.title("PathogenWatch BD: influenza surveillance (WHO FluNet)")
st.caption("Positivity = influenza-positive / specimens processed. Missing is never treated as zero. "
           "The most recent week is provisional and is never alerted on. Alerts are screening signals, not confirmed outbreaks.")

yrs = sorted(s.ISO_YEAR.unique())
y0, y1 = st.sidebar.select_slider("Years", yrs, value=(yrs[max(0, len(yrs) - 6)], yrs[-1]))
view = s[(s.ISO_YEAR >= y0) & (s.ISO_YEAR <= y1)]

tab_ov, tab_se, tab_an, tab_ev, tab_ml, tab_dq = st.tabs(["Overview", "Seasonality", "Anomaly detection", "Evaluation", "Forecast benchmark", "Data quality"])

with tab_ov:
    last = s_ok[~s_ok.provisional].iloc[-1]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Latest complete week", str(last.name.date()))
    c2.metric("Positivity", f"{last.positivity:.1%}" if pd.notna(last.positivity) else "n/a")
    c3.metric("Specimens processed", f"{int(last.SPEC_PROCESSED_NB):,}" if pd.notna(last.SPEC_PROCESSED_NB) else "n/a")
    c4.metric("Weeks with gaps (all years)", int(s.gap_week.sum()))
    w = epi.weekly_table(view)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[.7, .3], vertical_spacing=.05)
    fig.add_trace(go.Scatter(x=w.index, y=w.pos_hi, line=dict(width=0), showlegend=False, hoverinfo="skip"), 1, 1)
    fig.add_trace(go.Scatter(x=w.index, y=w.pos_lo, fill="tonexty", line=dict(width=0), fillcolor="rgba(31,95,139,.2)", name="95% CI"), 1, 1)
    fig.add_trace(go.Scatter(x=w.index, y=w.positivity, name="Positivity", line=dict(color="#1f5f8b")), 1, 1)
    fig.add_trace(go.Bar(x=w.index, y=w.SPEC_PROCESSED_NB, name="Processed", marker_color="#8a8f98"), 2, 1)
    fig.update_yaxes(title_text="Positivity", tickformat=".0%", row=1, col=1)
    fig.update_yaxes(title_text="Specimens", row=2, col=1)
    fig.update_layout(height=520, margin=dict(t=20))
    st.plotly_chart(fig, width="stretch")
    a = epi.annual_table(s)
    st.subheader("Annual positivity (valid weeks only)")
    st.dataframe(a.style.format({"positivity": "{:.3f}", "pos_lo": "{:.3f}", "pos_hi": "{:.3f}", "share_A": "{:.2f}", "share_B": "{:.2f}"}), width="stretch")

with tab_se:
    try:
        stl = SEAS.stl_decompose(s)
        f = make_subplots(rows=3, cols=1, shared_xaxes=True, subplot_titles=("Trend", "Seasonal", "Residual"))
        for i, c in enumerate(["trend", "seasonal", "resid"], 1):
            f.add_trace(go.Scatter(x=stl.index, y=stl[c], showlegend=False, line=dict(color="#1f5f8b")), i, 1)
        f.update_layout(height=600)
        st.plotly_chart(f, width="stretch")
        t = SEAS.harmonic_lr_test(s)
        m = SEAS.month_effect(s)
        st.write(f"Harmonic GLM vs null: quasi-F = {t['quasi_F']:.1f}, p = {t['p_value']:.2g}; dispersion {t['dispersion']:.1f}. "
                 f"Kruskal-Wallis over months: H = {m['kruskal_H']:.1f}, p = {m['p_value']:.2g} (COVID window excluded).")
        st.dataframe(SEAS.peak_weeks(s), width="stretch")
    except Exception as e:  # sparse series for small countries
        st.warning(f"Seasonality analysis not possible for this series: {e}")

with tab_an:
    names = st.multiselect("Detectors", list(det), default=["C2", "CUSUM"])
    ex = st.checkbox("Re-score EARS with custom threshold", value=False)
    k = st.slider("EARS z threshold", 2.0, 5.0, C.EARS_K, .1) if ex else C.EARS_K
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=view.index, y=view.positivity, name="Positivity", line=dict(color="#1f5f8b")))
    cols = {"C1": "#c0392b", "C2": "#e67e22", "C3": "#8e44ad", "CUSUM": "#16a085"}
    n_alerts = {}
    for n in names:
        d = det[n].loc[view.index]
        al = d.alert if (n == "CUSUM" or not ex) else (AN.ears(s, n, k=k).alert.loc[view.index] & ~s.provisional.loc[view.index])
        n_alerts[n] = int(al.sum())
        fig.add_trace(go.Scatter(x=view.index[al.values], y=view.positivity[al.values], mode="markers", name=f"{n} alert",
                                 marker=dict(size=9, color=cols[n], symbol="diamond")))
    fig.update_layout(height=450, yaxis_tickformat=".0%")
    st.plotly_chart(fig, width="stretch")
    st.write("Alert weeks in the selected period:", n_alerts)
    st.info("Detectors are prospective. Weeks with fewer than "
            f"{C.MIN_BASELINE_TESTS} processed specimens are not scored. CUSUM needs 156 weeks of history.")

with tab_ev:
    st.warning("The dataset has no labelled outbreaks. Table A uses proxy episodes derived from the same data; "
               "Table B is a simulation. Neither is a measured outbreak-detection performance.")
    ra, rb = table("eval_real_proxy.csv"), table("eval_simulation.csv")
    if country == C.COUNTRY and ra is not None:
        st.subheader("A. Real data vs proxy reference episodes (Bangladesh)")
        st.dataframe(ra, width="stretch")
        st.subheader("B. Semi-synthetic simulation (Bangladesh baseline)")
        st.dataframe(rb, width="stretch")
    else:
        st.write("Pre-computed evaluation tables exist for Bangladesh only (run the pipeline). "
                 "Proxy episodes for the selected country:")
        e = EV.reference_episodes(s)
        st.dataframe(e if len(e) else pd.DataFrame({"note": ["no episodes found"]}), width="stretch")


with tab_ml:
    st.subheader(f"One-week-ahead exploratory forecast benchmark ({country})")
    st.caption(
        "Chronological holdout; features use past observations only. "
        "Exploratory forecast, not an outbreak alert."
    )

    try:
        from pathogenwatch.modeling import evaluate_forecast

        # Use the selected country's weekly series, not Bangladesh's
        country_series = s.copy()
        country_series.index = pd.to_datetime(country_series.index)
        country_series = country_series.sort_index()
    

        country_series = country_series[["INF_ALL"]].copy()

        # Fill missing calendar weeks explicitly; do not invent target counts.
        full_weeks = pd.date_range(
            country_series.index.min(),
            country_series.index.max(),
            freq="7D",
        )
        country_series = country_series.reindex(full_weeks)
        country_series.index.name = "week_start"

        if country_series["INF_ALL"].notna().sum() < 80:
            st.warning(
                "Not enough weekly observations for a reliable chronological "
                "forecast benchmark. At least 80 usable weeks are required."
            )
        else:
            pred, metrics = evaluate_forecast(country_series, target="INF_ALL")

            m1, m2 = st.columns(2)
            m1.markdown("**Last-week baseline**")
            m1.json(metrics["baseline_last_week"])
            m2.markdown("**Random Forest**")
            m2.json(metrics["random_forest"])

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=pred["week_start"], y=pred["actual"], name="Observed"
            ))
            fig.add_trace(go.Scatter(
                x=pred["week_start"], y=pred["baseline_last_week"],
                name="Last-week baseline"
            ))
            fig.add_trace(go.Scatter(
                x=pred["week_start"], y=pred["random_forest_prediction"],
                name="Random Forest"
            ))
            fig.update_layout(
                height=420,
                yaxis_title="Influenza-positive detections",
            )
            st.plotly_chart(fig, width="stretch")
            st.dataframe(pred, width="stretch")
            st.json({
                "country": country,
                "n_usable": metrics["n_usable"],
                "n_train": metrics["n_train"],
                "n_test": metrics["n_test"],
                "split_method": metrics["split_method"],
                "feature_importance": metrics["feature_importance"],
            })

    except ValueError as exc:
        st.warning(f"Forecast unavailable for {country}: {exc}")


with tab_dq:
    rep = C.REPORTS_DIR / "data_quality_report.md"
    if rep.exists():
        st.markdown(rep.read_text(encoding="utf-8"))
    else:
        st.write("Run `python -m pathogenwatch.pipeline` to generate the data quality report.")
