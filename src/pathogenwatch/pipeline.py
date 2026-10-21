"""End-to-end reproducible pipeline: python -m pathogenwatch.pipeline"""
import json
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from . import config as C
from . import io, quality, cleaning, epi, seasonality as SEAS, anomaly as AN, evaluation as EV, reporting, modeling

warnings.filterwarnings("ignore")


def run(verbose: bool = True) -> dict:
    for d in (C.PROCESSED_DIR, C.FIG_DIR, C.TABLE_DIR):
        d.mkdir(parents=True, exist_ok=True)
    log = (lambda *a: print(*a, flush=True)) if verbose else (lambda *a: None)

    log("[1/6] loading raw data (read-only)")
    raw = io.load_raw()
    checksum = io.sha256(C.RAW_CSV)

    log("[2/6] data quality audit")
    q = {
        "summary": quality.audit_summary(raw),
        "duplicates": quality.duplicate_table(raw),
        "missingness": quality.missingness(raw),
        "source_combos": quality.source_combinations(raw),
        "nd_vs_sum_processed": quality.notdefined_vs_sum(raw, "SPEC_PROCESSED_NB"),
        "nd_vs_sum_infa": quality.notdefined_vs_sum(raw, "INF_A"),
        "consistency": quality.consistency_checks(raw),
        "bgd_gaps": quality.week_gaps(raw),
    }

    log("[3/6] cleaning + corrected aggregation")
    dedup = cleaning.drop_exact_duplicates(raw)
    rec = cleaning.recover_inf_all(dedup)
    agg = cleaning.aggregate_fast(rec)
    naive = cleaning.naive_sum_all_rows(raw)
    q["aggregation_error"] = epi.compare_aggregation(agg, naive)
    q["recovered_inf_all_rows"] = int(rec.INF_ALL_RECOVERED.sum())
    q["ambiguous_country_weeks"] = int((agg.N_SOURCES_AVAILABLE > 1).sum())
    agg.to_csv(C.PROCESSED_DIR / "flunet_country_week_clean.csv", index=False)
    s = cleaning.country_series(agg, C.COUNTRY)
    s.to_csv(C.PROCESSED_DIR / f"{C.COUNTRY}_weekly_series.csv")

    log("[4/6] descriptive epidemiology + seasonality")
    weekly = epi.weekly_table(s)
    annual = epi.annual_table(s)
    sub = epi.subtype_table(s)
    results = {
        "trend_all": epi.trend_test(annual),
        "trend_pre_covid_2010_2019": epi.trend_test(annual, (2010, 2019)),
        "seasonality_test": SEAS.harmonic_lr_test(s, 2),
        "month_effect": SEAS.month_effect(s),
    }
    peaks = SEAS.peak_weeks(s)
    stl = SEAS.stl_decompose(s)
    weekly.to_csv(C.TABLE_DIR / "bgd_weekly_positivity.csv")
    annual.to_csv(C.TABLE_DIR / "bgd_annual_positivity.csv", index=False)
    sub.to_csv(C.TABLE_DIR / "bgd_subtype_by_year.csv", index=False)
    peaks.to_csv(C.TABLE_DIR / "bgd_peak_weeks.csv", index=False)
    stl.to_csv(C.TABLE_DIR / "bgd_stl_decomposition.csv")

    log("[5/6] anomaly detection + evaluation")
    det = AN.run_all(s)
    episodes = EV.reference_episodes(s)
    real_eval = EV.evaluate_real(s, det, episodes)
    log("      semi-synthetic simulation (may take ~1-2 min)")
    sim = EV.simulate_evaluation(s)
    alerts = pd.DataFrame({k: v.alert for k, v in det.items()})
    alerts.to_csv(C.TABLE_DIR / "bgd_alerts.csv")
    pd.concat({k: v[[c for c in ("stat", "z") if c in v]] for k, v in det.items()}, axis=1).to_csv(
        C.TABLE_DIR / "bgd_detector_statistics.csv")
    episodes.to_csv(C.TABLE_DIR / "bgd_reference_episodes.csv", index=False)
    real_eval.to_csv(C.TABLE_DIR / "eval_real_proxy.csv", index=False)
    sim["table"].to_csv(C.TABLE_DIR / "eval_simulation.csv", index=False)
    for name, df_ in q.items():
        if isinstance(df_, pd.DataFrame):
            df_.to_csv(C.TABLE_DIR / f"dq_{name}.csv", index=False)

    
    log("[6/7] chronological forecast benchmark")
    forecast, forecast_metrics = modeling.evaluate_forecast(s, target="INF_ALL")
    forecast.to_csv(C.TABLE_DIR / "bgd_forecast_holdout.csv", index=False)

    (C.REPORTS_DIR / "forecast_model_evaluation.json").write_text(
        json.dumps(forecast_metrics, indent=2)
    )

    log("      rolling one-step-ahead backtest")
    rolling_results = modeling.rolling_backtest(
        s[["INF_ALL"]],
        target="INF_ALL",
        initial_train_fraction=0.6,
        horizon=13,
        step=13,
    )
    rolling_results.to_csv(
        C.TABLE_DIR / "bgd_rolling_backtest.csv",
        index=False,
    )

    rolling_summary = {}
    for model_name, prediction_col in [
        ("baseline_last_week", "baseline_last_week"),
        ("random_forest", "random_forest_prediction"),
    ]:
        errors = rolling_results["actual"] - rolling_results[prediction_col]
        rolling_summary[model_name] = {
            "MAE": float(errors.abs().mean()),
            "RMSE": float((errors.pow(2).mean()) ** 0.5),
            "n_predictions": int(errors.notna().sum()),
        }

    (C.REPORTS_DIR / "rolling_backtest_evaluation.json").write_text(
        json.dumps(rolling_summary, indent=2)
    )


    log("[7/7] figures + reports")
    reporting.make_figures(s, weekly, annual, stl, det, episodes, sub)
    ctx = dict(checksum=checksum, q=q, s=s, annual=annual, results=results, peaks=peaks,
               episodes=episodes, real_eval=real_eval, sim=sim, det=det, sub=sub, forecast_metrics=forecast_metrics)
    reporting.write_dq_report(ctx)
    reporting.write_research_report(ctx)
    (C.REPORTS_DIR / "results.json").write_text(json.dumps(
        {"checksum": checksum, "results": results, "simulation_dispersion": sim["dispersion"], "forecast": forecast_metrics},
        indent=2, default=str))
    log("done. See reports/")
    return ctx


if __name__ == "__main__":
    run()
