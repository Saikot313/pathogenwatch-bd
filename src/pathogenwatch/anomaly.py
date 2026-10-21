"""Aberration detection: EARS C1/C2/C3 and seasonal-baseline CUSUM.

All detectors are PROSPECTIVE: the score at week t uses only data up to week t.
"""
import numpy as np
import pandas as pd

from . import config as C
from . import seasonality as SEAS


# ----------------------------------------------------------------------------- EARS
def _floor_sd(sd, mean, n, floor_rel=0.0):
    """Binomial sampling SD at the current sample size is used as a lower bound on SD,
    so near-constant baselines do not produce infinite z-scores."""
    p = np.clip(mean, 1e-3, 1 - 1e-3)
    binom_sd = np.sqrt(p * (1 - p) / np.maximum(n, 1))
    return np.maximum(sd, binom_sd)


def ears(s: pd.DataFrame, method: str = "C2", k: float = C.EARS_K,
         baseline: int = C.EARS_BASELINE, guard: int = C.EARS_GUARD,
         value: str = "positivity") -> pd.DataFrame:
    """CDC EARS C1/C2/C3 on weekly positivity.

    C1: baseline = previous `baseline` weeks. C2: same, shifted by `guard` weeks.
    C3: sum over last 3 weeks of max(0, C2_i - 1); alert threshold 2 (CDC convention).
    Weeks with fewer than MIN_BASELINE_TESTS processed specimens are not scored.
    Missing weeks inside the baseline are skipped (mean/SD over available values; >=5 needed).
    """
    x = s[value].where(s.SPEC_PROCESSED_NB >= C.MIN_BASELINE_TESTS)
    g = 0 if method == "C1" else guard
    base = x.shift(1 + g)
    mean = base.rolling(baseline, min_periods=5).mean()
    sd = base.rolling(baseline, min_periods=5).std(ddof=1)
    sd = _floor_sd(sd, mean, s.SPEC_PROCESSED_NB)
    z = (x - mean) / sd
    out = pd.DataFrame({"value": x, "baseline_mean": mean, "z": z})
    if method == "C3":
        c3 = (z - 1).clip(lower=0).rolling(3, min_periods=3).sum()
        out["stat"] = c3
        out["alert"] = (c3 > 2) & (z > 1)
    else:
        out["stat"] = z
        out["alert"] = z > k
    out["alert"] = out["alert"].fillna(False)
    return out


# ----------------------------------------------------------------------------- CUSUM
def cusum_scores(z: np.ndarray, k: float = C.CUSUM_K, h: float = C.CUSUM_H):
    """One-sided upper CUSUM on standardised residuals; statistic resets to 0 after an alarm."""
    S = np.zeros(len(z))
    alert = np.zeros(len(z), bool)
    prev = 0.0
    for i, zi in enumerate(z):
        if not np.isfinite(zi):
            S[i] = prev
            continue
        prev = max(0.0, prev + zi - k)
        S[i] = prev
        if prev > h:
            alert[i] = True
            prev = 0.0
    return S, alert


def pearson_resid(y, n, p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return (y - n * p) / np.sqrt(n * p * (1 - p))


def cusum_seasonal(s: pd.DataFrame, k: float = C.CUSUM_K, h: float = C.CUSUM_H,
                   min_train_weeks: int = 156, refit_every: int = 26,
                   harmonics: int = 2) -> pd.DataFrame:
    """CUSUM on quasi-binomial Pearson residuals from a harmonic GLM refit prospectively.

    The model used at week t is fitted on data strictly before the most recent refit date,
    so no future information leaks. Residuals are divided by sqrt(dispersion) to correct
    for extra-binomial variation.
    """
    idx = s.index
    valid = s.INF_ALL.notna() & (s.SPEC_PROCESSED_NB >= C.MIN_BASELINE_TESTS)
    z = np.full(len(s), np.nan)
    expected = np.full(len(s), np.nan)
    res = None
    for i in range(len(s)):
        if i >= min_train_weeks and (res is None or (i - min_train_weeks) % refit_every == 0):
            new = SEAS.fit_seasonal_glm(s.iloc[:i], k=harmonics, exclude_covid=True)
            res = new if new is not None else res
        if res is None or not valid.iloc[i]:
            continue
        p = SEAS.predict(res, idx[i:i + 1], k=harmonics)[0]
        expected[i] = p
        z[i] = pearson_resid(s.INF_ALL.iloc[i], s.SPEC_PROCESSED_NB.iloc[i], p) / np.sqrt(res.disp)
    S, alert = cusum_scores(z, k, h)
    return pd.DataFrame({"expected_positivity": expected, "z": z, "stat": S, "alert": alert}, index=idx)


def run_all(s: pd.DataFrame) -> dict:
    out = {m: ears(s, m) for m in ("C1", "C2", "C3")}
    out["CUSUM"] = cusum_seasonal(s)
    for k, v in out.items():
        v.index = s.index
        # never alert on provisional (incomplete) last week
        v.loc[s.provisional.values, "alert"] = False
    return out
