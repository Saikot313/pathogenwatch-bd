import numpy as np
import pandas as pd

from pathogenwatch import anomaly as AN, config as C, epi


def _series(pos, n=200):
    idx = pd.date_range("2020-01-06", periods=len(pos), freq="W-MON")
    pos = np.asarray(pos, float)
    s = pd.DataFrame({"SPEC_PROCESSED_NB": float(n), "positivity": pos, "INF_ALL": pos * n}, index=idx)
    s["provisional"] = False
    return s


def test_ears_no_alert_on_flat_series():
    rng = np.random.default_rng(1)
    s = _series(0.1 + rng.normal(0, 0.005, 60))
    assert not AN.ears(s, "C1").alert.any()


def test_ears_alerts_on_sudden_jump():
    pos = np.r_[np.full(30, 0.10) + np.random.default_rng(2).normal(0, .004, 30), 0.35]
    s = _series(pos)
    assert AN.ears(s, "C1").alert.iloc[-1]
    assert AN.ears(s, "C2").alert.iloc[-1]


def test_ears_is_prospective_no_lookahead():
    rng = np.random.default_rng(3)
    pos = 0.1 + rng.normal(0, 0.01, 60)
    full = _series(pos)
    cut = _series(pos[:40])
    for m in ("C1", "C2", "C3"):
        a = AN.ears(full, m).iloc[:40]
        b = AN.ears(cut, m)
        np.testing.assert_allclose(a.z.fillna(-99), b.z.fillna(-99))


def test_ears_skips_low_volume_weeks():
    s = _series(np.r_[np.full(20, .1), .9])
    s.loc[s.index[-1], "SPEC_PROCESSED_NB"] = C.MIN_BASELINE_TESTS - 1
    assert not AN.ears(s, "C1").alert.iloc[-1]


def test_cusum_detects_sustained_shift_and_resets():
    z = np.r_[np.zeros(20), np.full(10, 1.5)]
    S, al = AN.cusum_scores(z, k=0.5, h=4)
    assert al[20:].any() and not al[:20].any()
    first = np.where(al)[0][0]
    assert S[first] == 0.0 or S[first + 1] < 4  # reset after alarm


def test_cusum_ignores_nan_and_never_negative():
    S, al = AN.cusum_scores(np.array([np.nan, -3, -3, np.nan]), 0.5, 4)
    assert (S >= 0).all() and not al.any()


def test_wilson_interval_contains_estimate_and_handles_zero_n():
    lo, hi = epi.wilson(np.array([5, 0]), np.array([20, 0]))
    assert lo[0] < 0.25 < hi[0] and np.isnan(lo[1])
