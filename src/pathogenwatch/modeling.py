"""Leakage-aware exploratory one-week-ahead forecasting for Bangladesh FluNet counts.

This is a research baseline, not an outbreak classifier. Evaluation is chronological;
all features use only observations available before the target week.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

FEATURES = ["lag_1", "lag_2", "lag_3", "lag_4", "lag_52", "rolling_mean_4", "rolling_mean_13", "iso_week"]


def build_forecasting_frame(series: pd.DataFrame, target: str = "INF_ALL") -> pd.DataFrame:
    if target not in series.columns:
        raise ValueError(f"Target column {target!r} is missing")

    values = pd.to_numeric(series[target], errors="coerce").clip(lower=0)
    values.index = pd.to_datetime(values.index)
    values = values.sort_index()

    # Require a unique, chronological weekly index.
    if values.index.has_duplicates:
        raise ValueError("Weekly series index must not contain duplicate dates")

    frame = pd.DataFrame(index=values.index)
    frame.index.name = "week_start"
    frame["target"] = values

    # Only use lag values from the immediately preceding calendar weeks.
    for lag in (1, 2, 3, 4, 52):
        frame[f"lag_{lag}"] = frame["target"].shift(lag)

    frame["rolling_mean_4"] = (
        frame["target"].shift(1).rolling(4, min_periods=4).mean()
    )
    frame["rolling_mean_13"] = (
        frame["target"].shift(1).rolling(13, min_periods=13).mean()
    )
    frame["iso_week"] = frame.index.isocalendar().week.astype(int).to_numpy()

    # Reject irregular weekly indexes rather than treating adjacent rows as adjacent weeks.
    week_gaps = frame.index.to_series().diff().dropna()
    if not week_gaps.eq(pd.Timedelta(days=7)).all():
        raise ValueError("Series index must be a regular weekly sequence; reindex missing weeks first")

    return (
        frame.replace([np.inf, -np.inf], np.nan)
        .dropna(subset=["target"] + FEATURES)
    )


def evaluate_forecast(
    series: pd.DataFrame,
    target: str = "INF_ALL",
    test_fraction: float = 0.2,
    seed: int = 20261020,
) -> tuple[pd.DataFrame, dict]:
    if not 0.1 <= test_fraction <= 0.4:
        raise ValueError("test_fraction must be between 0.1 and 0.4")

    data = build_forecasting_frame(series, target)

    if len(data) < 80:
        raise ValueError(
            f"Need at least 80 usable weekly observations; found {len(data)}"
        )

    split = int(len(data) * (1 - test_fraction))
    train = data.iloc[:split]
    test = data.iloc[split:]

    # Baseline 1: previous week's observed count.
    baseline_last_week = test["lag_1"].to_numpy(dtype=float)

    # Baseline 2: count from the same week one year earlier.
    baseline_seasonal = test["lag_52"].to_numpy(dtype=float)

    model = RandomForestRegressor(
        n_estimators=300,
        min_samples_leaf=3,
        max_features=0.8,
        random_state=seed,
        n_jobs=-1,
    )
    model.fit(train[FEATURES], train["target"])

    prediction = np.maximum(0, model.predict(test[FEATURES]))
    actual = test["target"].to_numpy(dtype=float)

    def metrics(y_true, y_pred):
        return {
            "mae": float(mean_absolute_error(y_true, y_pred)),
            "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
            "r2": float(r2_score(y_true, y_pred)),
        }

    summary = {
        "target": target,
        "n_usable": int(len(data)),
        "n_train": int(len(train)),
        "n_test": int(len(test)),
        "split_method": "chronological_holdout",
        "test_fraction": test_fraction,
        "seed": seed,
        "baseline_last_week": metrics(actual, baseline_last_week),
        "baseline_seasonal_52_week": metrics(actual, baseline_seasonal),
        "random_forest": metrics(actual, prediction),
        "feature_importance": {
            name: float(value)
            for name, value in zip(FEATURES, model.feature_importances_)
        },
        "interpretation": (
            "Exploratory forecast only; not an outbreak diagnosis "
            "or validated public-health alert."
        ),
    }

    predictions = pd.DataFrame({
        "week_start": test.index,
        "actual": actual,
        "baseline_last_week": baseline_last_week,
        "baseline_seasonal_52_week": baseline_seasonal,
        "random_forest_prediction": prediction,
    })

    return predictions, summary


def rolling_backtest(
    series: pd.DataFrame,
    target: str = "INF_ALL",
    initial_train_fraction: float = 0.6,
    horizon: int = 13,
    step: int = 13,
    seed: int = 20261020,
) -> pd.DataFrame:
    """Evaluate one-week-ahead models over multiple chronological cutoffs."""
    if not 0.4 <= initial_train_fraction <= 0.8:
        raise ValueError("initial_train_fraction must be between 0.4 and 0.8")
    if horizon < 1 or step < 1:
        raise ValueError("horizon and step must be positive")

    data = build_forecasting_frame(series, target)
    initial_train = int(len(data) * initial_train_fraction)

    if initial_train < 52 or initial_train + horizon > len(data):
        raise ValueError("Not enough usable observations for rolling backtesting")

    records = []

    for cutoff in range(initial_train, len(data) - horizon + 1, step):
        train = data.iloc[:cutoff]
        test = data.iloc[cutoff:cutoff + horizon]

        model = RandomForestRegressor(
            n_estimators=300,
            min_samples_leaf=3,
            max_features=0.8,
            random_state=seed,
            n_jobs=-1,
        )
        model.fit(train[FEATURES], train["target"])
        rf_pred = np.maximum(0, model.predict(test[FEATURES]))

        actual = test["target"].to_numpy(dtype=float)
        last_week = test["lag_1"].to_numpy(dtype=float)

        for i, (_, row) in enumerate(test.iterrows()):
            records.append({
                "week_start": row.name,
                "cutoff_week": train.index[-1],
                "actual": actual[i],
                "baseline_last_week": last_week[i],
                "random_forest_prediction": rf_pred[i],
            })

    return pd.DataFrame(records)
