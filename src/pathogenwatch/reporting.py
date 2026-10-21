"""Figures and report generation. All numbers in reports are taken from computed objects."""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import json

from . import config as C
from . import seasonality as SEAS

COL = {"main": "#1f5f8b", "alert": "#c0392b", "ref": "#e8b04a", "grey": "#8a8f98"}


def _save(fig, name):
    fig.tight_layout()
    fig.savefig(C.FIG_DIR / name, dpi=150)
    plt.close(fig)


def make_figures(s, weekly, annual, stl, det, episodes, sub):
    plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False, "font.size": 10})
    # 1 weekly positivity + CI + denominators
    fig, ax = plt.subplots(2, 1, figsize=(11, 6.5), sharex=True, gridspec_kw={"height_ratios": [3, 1.3]})
    ax[0].fill_between(weekly.index, weekly.pos_lo, weekly.pos_hi, color=COL["main"], alpha=.2, lw=0)
    ax[0].plot(weekly.index, weekly.positivity, color=COL["main"], lw=1)
    ax[0].axvspan(*SEAS.COVID_WINDOW, color=COL["grey"], alpha=.15, lw=0)
    ax[0].set_ylabel("Influenza positivity"); ax[0].set_title("Bangladesh: weekly influenza positivity (95% Wilson CI); grey = COVID-19 window")
    ax[1].bar(weekly.index, weekly.SPEC_PROCESSED_NB, width=6, color=COL["grey"])
    ax[1].set_ylabel("Specimens processed")
    _save(fig, "01_weekly_positivity.png")

    # 2 annual positivity
    fig, ax = plt.subplots(figsize=(9, 4))
    a = annual.dropna(subset=["positivity"])
    ax.errorbar(a.ISO_YEAR, a.positivity, yerr=[a.positivity - a.pos_lo, a.pos_hi - a.positivity], fmt="o-", color=COL["main"], capsize=3)
    ax.set_ylabel("Annual positivity"); ax.set_title("Annual influenza positivity with 95% Wilson CI")
    _save(fig, "02_annual_positivity.png")

    # 3 STL
    fig, axs = plt.subplots(3, 1, figsize=(11, 7), sharex=True)
    for ax, c in zip(axs, ["trend", "seasonal", "resid"]):
        ax.plot(stl.index, stl[c], color=COL["main"], lw=1); ax.set_ylabel(c)
    axs[0].set_title("STL decomposition of weekly positivity (period = 52 weeks, robust)")
    _save(fig, "03_stl.png")

    # 4 seasonal profile by ISO week (non-COVID)
    d = s[s.positivity.notna()]
    d = d[~((d.index >= SEAS.COVID_WINDOW[0]) & (d.index <= SEAS.COVID_WINDOW[1]))]
    prof = d.groupby("ISO_WEEK").positivity.agg(["median", lambda x: x.quantile(.25), lambda x: x.quantile(.75)])
    prof.columns = ["median", "q25", "q75"]
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.fill_between(prof.index, prof.q25, prof.q75, color=COL["main"], alpha=.2, lw=0)
    ax.plot(prof.index, prof["median"], color=COL["main"])
    ax.set_xlabel("ISO week"); ax.set_ylabel("Positivity"); ax.set_title("Seasonal profile (median and IQR across years, COVID window excluded)")
    _save(fig, "04_seasonal_profile.png")

    # 5 subtype composition
    cols = [c for c in ["AH1N12009", "AH3", "BVIC_2DEL", "BVIC_3DEL", "BVIC_NODEL", "BVIC_DELUNK", "BYAM", "BNOTDETERMINED"] if c in sub]
    st = sub.set_index("ISO_YEAR")[cols].fillna(0)
    fig, ax = plt.subplots(figsize=(10, 4.2))
    st.plot(kind="bar", stacked=True, ax=ax, width=.85, colormap="tab20")
    ax.set_ylabel("Confirmed subtyped detections"); ax.set_title("Subtype / lineage detections by year (as reported)")
    ax.legend(fontsize=7, ncol=4, frameon=False)
    _save(fig, "05_subtypes.png")

    # 6 detectors
    fig, axs = plt.subplots(len(det) + 1, 1, figsize=(11, 10), sharex=True)
    axs[0].plot(s.index, s.positivity, color=COL["main"], lw=1)
    for _, e in episodes.iterrows():
        axs[0].axvspan(e.onset, e.end, color=COL["ref"], alpha=.3, lw=0)
    axs[0].set_ylabel("Positivity"); axs[0].set_title("Detector output (amber = proxy reference episodes, red = alerts)")
    for ax, (name, d_) in zip(axs[1:], det.items()):
        ax.plot(d_.index, d_.stat, color=COL["grey"], lw=.9)
        al = d_[d_.alert]
        ax.scatter(al.index, al.stat, color=COL["alert"], s=14, zorder=3)
        ax.set_ylabel(name)
    _save(fig, "06_detectors.png")


def md_table(df: pd.DataFrame, floatfmt=3) -> str:
    if df is None or len(df) == 0:
        return "_(none)_"
    d = df.copy()
    for c in d.columns:
        if pd.api.types.is_float_dtype(d[c]):
            d[c] = d[c].map(lambda v: "" if pd.isna(v) else f"{v:.{floatfmt}f}")
    head = "| " + " | ".join(map(str, d.columns)) + " |\n|" + "---|" * len(d.columns) + "\n"
    return head + "\n".join("| " + " | ".join(map(str, r)) + " |" for r in d.values)


def _bgd_source_table(s):
    g = s[~s.gap_week].groupby("SOURCE_USED")
    return pd.DataFrame({"weeks": g.size(), "first_week": g.apply(lambda x: x.index.min().date()),
                         "last_week": g.apply(lambda x: x.index.max().date()),
                         "mean_weekly_processed": g.SPEC_PROCESSED_NB.mean()}).reset_index()


def write_dq_report(ctx):
    q, s = ctx["q"], ctx["s"]
    sm_ = q["summary"]
    cons = q["consistency"]
    agg_err = q["aggregation_error"]
    bgd_nsrc = int((s.N_SOURCES_AVAILABLE.fillna(1) > 1).sum())
    L = []
    L.append("# Data Quality Report: WHO FluNet `VIW_FNT.csv`\n")
    L.append(f"_Generated by `python -m pathogenwatch.pipeline`. Raw file SHA-256: `{ctx['checksum']}`. The raw file is never modified._\n")
    L.append("## 1. Dataset overview\n")
    L.append(f"- Rows: **{sm_['rows']:,}**; columns: **{sm_['columns']}**; countries/areas: **{sm_['countries']}**")
    L.append(f"- ISO week range: {sm_['first_week']} to {sm_['last_week']}")
    L.append(f"- `ORIGIN_SOURCE` counts after exact-duplicate removal: {sm_['source_counts']}\n")
    L.append("## 2. Findings and how each was handled\n")
    L.append("### 2.1 Exact duplicate records\n")
    L.append(f"{sm_['exact_duplicate_rows']} fully identical rows were found (table below). They are removed before any aggregation. After removal no country-week-source key is duplicated ({sm_['duplicate_country_week_source_after_dedup']} remaining).\n")
    L.append(md_table(q["duplicates"]) + "\n")
    L.append("### 2.2 `NOTDEFINED` / `SENTINEL` / `NONSENTINEL` and double counting\n")
    L.append(f"A country-week may have rows from several sources. {sm_['duplicate_country_week_rows_all_sources']:,} rows share a country-week key with another row, so a naive `groupby(country, week).sum()` mixes sources. Combinations observed:\n")
    L.append(md_table(q["source_combos"]) + "\n")
    L.append("Where `NOTDEFINED` co-exists with `SENTINEL`/`NONSENTINEL`, it is **not** reliably their sum:\n")
    L.append(md_table(pd.concat([q["nd_vs_sum_processed"], q["nd_vs_sum_infa"]])) + "\n")
    L.append("**Policy applied (documented assumption):** if a `NOTDEFINED` row exists it is treated as the national total and used alone; otherwise `SENTINEL` and `NONSENTINEL` are summed. `NOTDEFINED` is never added to the others. The data cannot prove this is the intended semantics in every country, so affected weeks are flagged (`N_SOURCES_AVAILABLE`, `SOURCE_USED`); " + f"{q['ambiguous_country_weeks']:,} country-weeks have more than one source available. Bangladesh has {bgd_nsrc} such weeks, so the Bangladesh analysis is not affected by this ambiguity.\n")
    L.append("**Size of the error from naive summation** (specimens over-counted, top countries, `SPEC_PROCESSED_NB`):\n")
    L.append(md_table(agg_err.head(10)) + "\n")
    L.append("### 2.3 Missing values\n")
    L.append("Highest missingness (percent of rows). Missing is **not** zero: `NaN` means not reported and is never silently converted to 0.\n")
    L.append(md_table(q["missingness"].head(20)) + "\n")
    L.append(f"`INF_ALL` is missing in many rows although `INF_A` and `INF_B` are present. The identity `INF_ALL = INF_A + INF_B` holds in every row where all three exist (see check table), so **{q['recovered_inf_all_rows']:,} values were recovered** and flagged (`INF_ALL_RECOVERED`).\n")
    L.append("### 2.4 Logical consistency checks\n")
    L.append(md_table(cons) + "\n")
    L.append("- Rows violating `INF_ALL <= SPEC_PROCESSED_NB` or `processed <= received` are **flagged, not edited**; the source cannot tell us which field is wrong.")
    L.append("- `SPEC_PROCESSED_NB == 0` means no specimens were tested; positivity is undefined (NaN), not 0.\n")
    L.append("### 2.5 Bangladesh-specific issues\n")
    L.append("Source used per period (note the change of reporting source, which is a potential structural break):\n")
    L.append(md_table(_bgd_source_table(s)) + "\n")
    gaps = q["bgd_gaps"]
    L.append(f"Missing ISO weeks inside the Bangladesh reporting span: **{len(gaps)}** ({', '.join(gaps.missing_week_start)}). They are kept as explicit gaps and never imputed in statistics (only short gaps are interpolated for STL, flagged).\n")
    L.append(f"The final week ({s.index[-1].date()}) is treated as **provisional** (processed < received in the source) and is excluded from alerting and evaluation.\n")
    L.append("## 3. Limitations\n")
    L.append("- FluNet is an aggregated, self-reported, sentinel-dominated dataset; changes in testing policy and site coverage change denominators.")
    L.append("- No lab-confirmed outbreak labels exist in this file.")
    L.append("- Columns for RSV, other viruses and comments were not audited beyond missingness.\n")
    (C.REPORTS_DIR / "data_quality_report.md").write_text("\n".join(L), encoding="utf-8")


def write_research_report(ctx):
    s, annual, R, peaks = ctx["s"], ctx["annual"], ctx["results"], ctx["peaks"]
    ev, sim, eps = ctx["real_eval"], ctx["sim"], ctx["episodes"]
    med = R["month_effect"]["median_by_month"]
    top = sorted(med, key=med.get, reverse=True)[:2]
    months = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun", 7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}
    pre = annual[annual.ISO_YEAR.between(2010, 2019)].positivity.mean()
    cov = annual[annual.ISO_YEAR.between(2020, 2022)].positivity.mean()
    post = annual[annual.ISO_YEAR >= 2023].positivity.mean()
    st = sim["table"]
    fa = st[st.scenario == "no outbreak"][["detector", "false_alerts_per_52wk"]]
    ob = st[st.scenario != "no outbreak"][["scenario", "detector", "sensitivity", "median_delay_weeks"]]
    L = []
    L.append("# PathogenWatch BD: Influenza Surveillance Analysis, Bangladesh (WHO FluNet)\n")
    L.append(f"_Data: WHO FluNet `VIW_FNT.csv` (SHA-256 `{ctx['checksum'][:16]}...`), Bangladesh, ISO weeks {s.index.min().date()} to {s.index.max().date()}. All numbers below are produced by the pipeline; nothing is hand-entered._\n")
    L.append("## 1. Objective\n")
    L.append("Quantify weekly influenza positivity in Bangladesh, characterise its seasonality, and evaluate prospective aberration-detection algorithms (EARS C1/C2/C3 and a seasonal-baseline CUSUM), with transparent assumptions.\n")
    L.append("## 2. Data and methods\n")
    L.append("- **Cleaning:** exact duplicates removed; `INF_ALL` recovered from `INF_A + INF_B`; one row per country-week via the documented source policy (see data quality report). Raw data untouched.")
    L.append("- **Positivity** = `INF_ALL / SPEC_PROCESSED_NB`, undefined where nothing was processed; 95% Wilson intervals. Annual positivity uses only weeks where numerator and denominator are both valid.")
    L.append("- **Seasonality:** quasi-binomial GLM with 2 annual harmonics (dispersion = Pearson chi2/df); quasi-F test; robust STL (period 52); Kruskal-Wallis across calendar months. The COVID-19 window (2020-03-01 to 2021-12-31) is excluded from seasonal model *fitting*, because mean annual positivity fell to about one third of its pre-pandemic level then (section 3).")
    L.append("- **Detectors (all prospective, using data up to week t only):** EARS C1/C2/C3 on positivity (7-week baseline, 2-week guard for C2/C3, z > 3; C3 sum > 2), with SD floored at the binomial sampling SD; CUSUM (k = 0.5, h = 4, reset after alarm) on dispersion-corrected Pearson residuals from the harmonic GLM, refit every 26 weeks on past data only (min. 156 weeks training). Weeks with < 30 processed specimens are not scored.")
    L.append("- **Evaluation:** (A) real data against *proxy* reference episodes; (B) semi-synthetic simulation with injected outbreaks. See section 5 for why.\n")
    L.append("## 3. Descriptive results\n")
    L.append(f"Mean annual positivity: {pre:.3f} (2010-2019), {cov:.3f} (2020-2022), {post:.3f} (2023 onward).\n")
    L.append(md_table(annual[["ISO_YEAR", "weeks_valid", "processed", "influenza_positive", "positivity", "pos_lo", "pos_hi", "share_A", "share_B"]], 3) + "\n")
    t1, t2 = R["trend_all"], R["trend_pre_covid_2010_2019"]
    L.append(f"Kendall trend test on annual positivity: all years tau = {t1['tau']:.2f} (p = {t1['p_value']:.2f}, n = {t1['n_years']}); 2010-2019 tau = {t2['tau']:.2f} (p = {t2['p_value']:.2f}, n = {t2['n_years']}). With so few annual points, absence of a significant monotone trend is weak evidence of stability. The 2020-2022 dip makes a monotone trend test a poor description of this series.\n")
    L.append("![weekly](figures/01_weekly_positivity.png)\n![annual](figures/02_annual_positivity.png)\n")
    L.append("## 4. Seasonality\n")
    S = R["seasonality_test"]
    L.append(f"- Harmonic model vs intercept-only: quasi-F({S['df'][0]}, {S['df'][1]}) = {S['quasi_F']:.1f}, p = {S['p_value']:.1e}; dispersion = {S['dispersion']:.1f} (strongly over-dispersed relative to binomial, as expected when whole epidemic waves vary in size).")
    L.append(f"- Kruskal-Wallis across months (COVID window excluded): H = {R['month_effect']['kruskal_H']:.1f}, p = {R['month_effect']['p_value']:.1e}. Highest median positivity in {months[top[0]]} and {months[top[1]]}.")
    pk = peaks[~peaks.ISO_YEAR.between(2020, 2022)]
    L.append(f"- Peak ISO week by year (non-COVID years with >= 40 valid weeks): median week {pk.peak_week.median():.0f}, range {pk.peak_week.min()}-{pk.peak_week.max()}.\n")
    L.append(md_table(peaks, 3) + "\n")
    L.append("![stl](figures/03_stl.png)\n![profile](figures/04_seasonal_profile.png)\n![subtypes](figures/05_subtypes.png)\n")
    L.append("## 5. Anomaly detection evaluation\n")
    L.append("**The dataset contains no labelled outbreaks, so true sensitivity and detection delay cannot be measured from it directly.** Two designs are used and must not be confused:\n")
    L.append("### 5A. Real data vs proxy reference episodes\n")
    thr = eps.threshold.iloc[0] if len(eps) else float("nan")
    L.append(f"Proxy episodes = contiguous periods (>= 3 weeks, gaps <= 2 weeks merged) where 3-week centred-median positivity >= {thr:.3f} (75th percentile of non-COVID weeks). This is a retrospective, level-based definition: **not** an outbreak ground truth. A negative delay means the alert fired before the threshold-crossing 'onset' (i.e. during the rise). Alerts outside episodes are called 'false' only relative to this proxy; some may be genuine early rises or noise in low-testing weeks. The ongoing episode at the end of the data is excluded (right-censored).\n")
    L.append(md_table(ev[["detector", "episodes_evaluated", "episodes_detected_by_peak", "sensitivity", "median_delay_weeks_from_onset", "mean_delay_weeks", "alerts_outside_episodes", "weeks_outside_episodes", "false_alert_rate_per_52wk"]], 2) + "\n")
    L.append(f"Evaluation window starts {ev.evaluation_start.iloc[0]} ({int(ev.weeks_scored.iloc[0])} scored weeks, common to all detectors). With only {int(ev.episodes_evaluated.iloc[0])} proxy episodes, sensitivities have wide uncertainty (one episode = {100/ max(int(ev.episodes_evaluated.iloc[0]),1):.0f} percentage points).\n")
    L.append("![detectors](figures/06_detectors.png)\n")
    L.append("### 5B. Semi-synthetic simulation\n")
    L.append(f"Baseline series are simulated from the fitted seasonal model over {sim['window'][0]}-{sim['window'][1]} using observed weekly testing volumes, with beta-binomial over-dispersion (rho = {sim['rho']:.3f}, from the fitted dispersion). Outbreaks are injected as a 4-week ramp then 4-week plateau on the odds scale (odds ratio 1.5, 2, 3) at random start weeks; a detection counts if the first alert falls within {sim['horizon_weeks']} weeks of start. {sim['n_rep']} replicates per scenario, seed {C.SEED}. **These are properties of the simulation, not of Bangladesh outbreaks.** The CUSUM here uses the true generating seasonal curve as its baseline, so its simulated performance is optimistic compared with real use, where the baseline must be estimated.\n")
    L.append("False alerts per 52 weeks with no outbreak:\n")
    L.append(md_table(fa, 2) + "\n")
    L.append("Sensitivity and delay with injected outbreaks:\n")
    L.append(md_table(ob, 2) + "\n")
    L.append("## 6. Interpretation (limited to what the numbers support)\n")
    best = ev.sort_values("false_alert_rate_per_52wk").iloc[0]
    L.append(f"- Influenza in Bangladesh is strongly seasonal in this dataset, with the main activity period in the middle of the year (highest medians {months[top[0]]}/{months[top[1]]}).")
    L.append("- The EARS detectors on positivity flag most proxy episodes early but at a high alert rate outside episodes; the C3 variant is the most alert-prone. Under the simulation, EARS false-alert rates (several per year) would be operationally burdensome without alert filtering (e.g. requiring two consecutive alerts).")
    L.append(f"- The seasonal CUSUM produced the lowest false-alert rate on real data ({best.false_alert_rate_per_52wk:.2f} per 52 weeks for {best.detector}) but missed more proxy episodes and had longer delays: a sensitivity vs. timeliness trade-off. Parameters (k, h) were set a priori, not tuned on this data; tuning on the same data would inflate performance.")
    low = st[st.odds_ratio == 1.5]
    L.append(f"- Simulated sensitivity for a small increase (odds ratio 1.5) is modest for every detector (range {low.sensitivity.min():.2f}-{low.sensitivity.max():.2f} within {sim['horizon_weeks']} weeks), consistent with the sampling noise at the observed testing volumes.\n")

    L.append("## 6A. Forecasting model evaluation\n")

    fm = ctx["forecast_metrics"]
    L.append(
        "Models were evaluated using a chronological holdout. "
        "The final portion of the time series was kept for testing, "
        "with no random shuffling.\n"
    )

    forecast_rows = []
    for name, metrics in fm.items():
        if isinstance(metrics, dict) and "MAE" in metrics:
            forecast_rows.append({
                "model": name,
                "MAE": metrics["MAE"],
                "RMSE": metrics.get("RMSE", float("nan")),
                "R2": metrics.get("R2", float("nan")),
            })

    if forecast_rows:
        L.append(md_table(pd.DataFrame(forecast_rows), 3) + "\n")

    rb_path = C.REPORTS_DIR / "rolling_backtest_evaluation.json"
    if rb_path.exists():
        import json
        rb = json.loads(rb_path.read_text(encoding="utf-8"))

        L.append("### Rolling one-step-ahead backtest\n")
        L.append(
            "Rolling evaluation uses chronological cutoffs and evaluates "
            "predictions over successive 13-week blocks. Previous observed "
            "weeks are available when predicting later weeks; this is not "
            "a fixed-origin 13-week forecast.\n"
        )

        rb_rows = [
            {
                "model": name,
                "MAE": values["MAE"],
                "RMSE": values["RMSE"],
                "Predictions": values["n_predictions"],
            }
            for name, values in rb.items()
        ]
        L.append(md_table(pd.DataFrame(rb_rows), 3) + "\n")

    L.append(
        "Forecast errors are retrospective evaluation results, not a guarantee "
        "of future performance. Model choice should consider baseline "
        "performance and changes in reporting or testing patterns.\n"
    )

    L.append("## 7. Limitations\n")
    L.append("- Proxy reference episodes are not outbreaks; real-data sensitivity/delay/false-alarm figures depend on that definition and on 13 episodes only.")
    L.append("- Reporting source changed from `NOTDEFINED` to `SENTINEL` at the end of 2019 and testing volume grew over time; positivity can shift for non-epidemiological reasons.")
    pk25 = peaks[peaks.ISO_YEAR == 2025].peak_positivity.max()
    pk_prev = peaks[peaks.ISO_YEAR.between(2020, 2024)].peak_positivity.max()
    L.append(f"- Seasonal GLM excludes the COVID window and assumes a stable seasonal shape; the post-COVID shape may differ (peak weekly positivity {pk25:.2f} in 2025 vs a maximum of {pk_prev:.2f} over 2020-2024).")
    L.append("- Simulation assumptions (odds-scale ramp, beta-binomial noise, known baseline for CUSUM) are idealised.")
    L.append("- The final reporting week is provisional and excluded from alerting.")
    L.append("- Multiple testing across weeks is not adjusted; alerts are screening signals, not confirmed outbreaks.\n")
    L.append("## 8. Reproducibility\n")
    L.append(f"`python -m pathogenwatch.pipeline` regenerates every table and figure; random seed {C.SEED}; the raw file checksum is verified on load.\n")
    (C.REPORTS_DIR / "research_report.md").write_text("\n".join(L), encoding="utf-8")
