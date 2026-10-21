"""Seasonality: harmonic binomial GLM, STL decomposition, nonparametric month test."""
import numpy as np
import pandas as pd
from scipy import stats
import statsmodels.api as sm
from statsmodels.tsa.seasonal import STL

PERIOD_WEEKS = 365.25 / 7.0

# COVID-19 period excluded from baseline *training* (positivity fell to ~half of pre-/post-level)
COVID_WINDOW = (pd.Timestamp("2020-03-01"), pd.Timestamp("2021-12-31"))


def harmonics(index: pd.DatetimeIndex, k: int = 2) -> pd.DataFrame:
    t = (index - pd.Timestamp("2000-01-03")).days.values / 7.0
    X = {}
    for j in range(1, k + 1):
        X[f"sin{j}"] = np.sin(2 * np.pi * j * t / PERIOD_WEEKS)
        X[f"cos{j}"] = np.cos(2 * np.pi * j * t / PERIOD_WEEKS)
    return pd.DataFrame(X, index=index)


def fit_seasonal_glm(s: pd.DataFrame, k: int = 2, exclude_covid: bool = True, end=None):
    """Quasi-binomial GLM: INF_ALL / SPEC_PROCESSED_NB ~ harmonics(k). Returns fitted result or None."""
    d = s[s.INF_ALL.notna() & (s.SPEC_PROCESSED_NB > 0)]
    if end is not None:
        d = d[d.index < end]
    if exclude_covid:
        d = d[~((d.index >= COVID_WINDOW[0]) & (d.index <= COVID_WINDOW[1]))]
    if len(d) < 52:
        return None
    X = sm.add_constant(harmonics(d.index, k))
    y = np.column_stack([d.INF_ALL, d.SPEC_PROCESSED_NB - d.INF_ALL])
    res = sm.GLM(y, X, family=sm.families.Binomial()).fit()
    res.disp = dispersion(res)
    return res


def dispersion(res) -> float:
    """Pearson dispersion (chi2 / df). statsmodels' scale='X2' is NOT used: with a two-column
    binomial response it returned a value ~n-times too small (0.09 instead of 19.4), which
    would have produced wildly over-sensitive detectors. Verified against a manual calculation."""
    return float(res.pearson_chi2 / res.df_resid)


def predict(res, index: pd.DatetimeIndex, k: int = 2) -> np.ndarray:
    X = sm.add_constant(harmonics(index, k), has_constant="add")
    return np.asarray(res.predict(X))


def harmonic_lr_test(s: pd.DataFrame, k: int = 2) -> dict:
    """Likelihood-ratio style test (quasi-F via scaled deviance) of seasonality vs. intercept only."""
    d = s[s.INF_ALL.notna() & (s.SPEC_PROCESSED_NB > 0)]
    d = d[~((d.index >= COVID_WINDOW[0]) & (d.index <= COVID_WINDOW[1]))]
    y = np.column_stack([d.INF_ALL, d.SPEC_PROCESSED_NB - d.INF_ALL])
    full = sm.GLM(y, sm.add_constant(harmonics(d.index, k)), family=sm.families.Binomial()).fit()
    null = sm.GLM(y, np.ones((len(d), 1)), family=sm.families.Binomial()).fit()
    df_diff = 2 * k
    disp = dispersion(full)
    F = ((null.deviance - full.deviance) / df_diff) / disp
    p = stats.f.sf(F, df_diff, full.df_resid)
    return {"harmonics": k, "n_weeks": int(len(d)), "dispersion": disp,
            "quasi_F": float(F), "df": (df_diff, int(full.df_resid)), "p_value": float(p)}


def stl_decompose(s: pd.DataFrame):
    """STL on weekly positivity (linear interpolation over short gaps; flagged in output)."""
    pos = s.positivity.copy()
    filled = pos.isna()
    pos = pos.interpolate(limit=4, limit_direction="both").dropna()
    res = STL(pos, period=52, robust=True).fit()
    out = pd.DataFrame({"observed": pos, "trend": res.trend, "seasonal": res.seasonal,
                        "resid": res.resid, "interpolated": filled.reindex(pos.index)})
    return out


def month_effect(s: pd.DataFrame) -> dict:
    d = s[s.positivity.notna()].copy()
    d = d[~((d.index >= COVID_WINDOW[0]) & (d.index <= COVID_WINDOW[1]))]
    groups = [g.positivity.values for _, g in d.groupby(d.index.month)]
    H, p = stats.kruskal(*groups)
    med = d.groupby(d.index.month).positivity.median()
    return {"kruskal_H": float(H), "p_value": float(p), "median_by_month": med.round(4).to_dict()}


def peak_weeks(s: pd.DataFrame) -> pd.DataFrame:
    """ISO week of maximum positivity per year (only years with >=40 valid weeks)."""
    d = s[s.positivity.notna()]
    rows = []
    for y, g in d.groupby("ISO_YEAR"):
        if len(g) < 40:
            continue
        i = g.positivity.idxmax()
        rows.append({"ISO_YEAR": y, "peak_week": int(g.loc[i, "ISO_WEEK"]),
                     "peak_positivity": float(g.loc[i, "positivity"]), "valid_weeks": len(g)})
    return pd.DataFrame(rows)
