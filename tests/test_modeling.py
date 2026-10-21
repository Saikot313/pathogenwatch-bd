import numpy as np
import pandas as pd
import pytest
from pathogenwatch.modeling import build_forecasting_frame, evaluate_forecast

def sample_series(n=180):
    idx = pd.date_range("2018-01-01", periods=n, freq="W-MON")
    y = 50 + 20*np.sin(2*np.pi*np.arange(n)/52) + np.arange(n)*0.1
    return pd.DataFrame({"INF_ALL": y}, index=idx)

def test_forecast_features_use_past_only():
    s = sample_series()
    frame = build_forecasting_frame(s)
    row = frame.iloc[0]
    idx = frame.index[0]
    assert row["lag_1"] == s.loc[idx - pd.Timedelta(weeks=1), "INF_ALL"]
    assert row["rolling_mean_4"] == pytest.approx(s.loc[idx-pd.Timedelta(weeks=4):idx-pd.Timedelta(weeks=1), "INF_ALL"].mean())

def test_forecast_evaluation_is_chronological_and_returns_metrics():
    pred, result = evaluate_forecast(sample_series())
    assert len(pred) == result["n_test"]
    assert pred.week_start.is_monotonic_increasing
    assert result["split_method"] == "chronological_holdout"
    assert result["n_train"] + result["n_test"] == result["n_usable"]
    assert result["baseline_last_week"]["mae"] >= 0
    assert result["random_forest"]["rmse"] >= 0

def test_forecast_rejects_too_short_series():
    with pytest.raises(ValueError):
        evaluate_forecast(sample_series(60))

def test_forecast_does_not_bridge_missing_weeks():
    s = sample_series(180)
    s.loc[s.index[90:95], "INF_ALL"] = np.nan
    frame = build_forecasting_frame(s)
    # Missing targets must not be silently converted to zero.
    assert frame["target"].notna().all()
    assert not (frame.index.isin(s.index[90:95])).any()


def test_rolling_backtest_uses_chronological_cutoffs():
    from pathogenwatch.modeling import rolling_backtest

    result = rolling_backtest(
        sample_series(220),
        initial_train_fraction=0.6,
        horizon=13,
        step=13,
    )

    assert not result.empty
    assert result["week_start"].is_monotonic_increasing
    assert result["cutoff_week"].notna().all()
    assert (result["week_start"] > result["cutoff_week"]).all()
    assert result["actual"].notna().all()
    assert result["baseline_last_week"].notna().all()
    assert result["random_forest_prediction"].notna().all()
