"""Evaluation of detectors.

IMPORTANT: the dataset contains NO labelled outbreaks. Two complementary, clearly-labelled designs:

  A. Proxy-reference evaluation on REAL data. "Reference episodes" are derived retrospectively from
     smoothed positivity (centred median, uses future data => allowed for a retrospective label
     only). This is a proxy for epidemic waves, NOT laboratory-confirmed outbreak truth.
  B. Semi-synthetic injection on SIMULATED data. Known outbreaks are injected into baseline series
     simulated from the fitted seasonal model; this gives true sensitivity / delay / false-alarm
     rates *under the simulation assumptions*.
"""
import numpy as np
import pandas as pd

from . import config as C
from . import anomaly as AN
from . import seasonality as SEAS


# ----------------------------------------------------------------------------- A. real data
def reference_episodes(s: pd.DataFrame, q: float = 0.75, min_len: int = 3, merge_gap: int = 2) -> pd.DataFrame:
    pos = s.positivity.interpolate(limit=3, limit_direction="both")
    sm_ = pos.rolling(3, center=True, min_periods=2).median()
    ref = pos[~((pos.index >= SEAS.COVID_WINDOW[0]) & (pos.index <= SEAS.COVID_WINDOW[1]))].dropna()
    thr = float(ref.quantile(q))
    on = (sm_ >= thr).fillna(False).values
    idx = s.index
    eps, i, n = [], 0, len(on)
    while i < n:
        if on[i]:
            j = i
            while j + 1 < n and on[j + 1]:
                j += 1
            eps.append([i, j])
            i = j + 1
        else:
            i += 1
    merged = []
    for e in eps:
        if merged and e[0] - merged[-1][1] - 1 <= merge_gap:
            merged[-1][1] = e[1]
        else:
            merged.append(e)
    rows = []
    for a, b in merged:
        if b - a + 1 < min_len:
            continue
        seg = sm_.iloc[a:b + 1]
        pk = seg.idxmax()
        rows.append({"onset": idx[a], "end": idx[b], "peak_week": pk, "peak_positivity": float(seg.max()),
                     "duration_weeks": b - a + 1, "threshold": thr})
    return pd.DataFrame(rows)


def evaluate_real(s: pd.DataFrame, det: dict, episodes: pd.DataFrame, lead_weeks: int = 2) -> pd.DataFrame:
    """Sensitivity / delay / false alarms vs. proxy episodes, on a common evaluation window."""
    start = det["CUSUM"].stat.index[det["CUSUM"].z.notna()].min()
    scored = s.index >= start
    scored &= ~s.provisional.values
    scored &= s.positivity.notna().values
    n_scored = int(scored.sum())
    last_obs = s.index[~s.provisional.values][-1]
    eps = episodes[(episodes.onset >= start) & (episodes.end < last_obs)].reset_index(drop=True)  # drop right-censored ongoing episode
    rows = []
    for name, d in det.items():
        alerts = d.alert.values & scored
        alert_dates = s.index[alerts]
        in_window = np.zeros(len(s), bool)
        delays, hit, early = [], 0, 0
        for _, e in eps.iterrows():
            lo = e.onset - pd.Timedelta(weeks=lead_weeks)
            in_window |= (s.index >= lo) & (s.index <= e.end)
            cand = alert_dates[(alert_dates >= lo) & (alert_dates <= e.peak_week)]
            if len(cand):
                hit += 1
                dl = (cand.min() - e.onset).days / 7
                delays.append(dl)
        false_alerts = int((alerts & ~in_window).sum())
        out_weeks = int((scored & ~in_window).sum())
        rows.append({
            "detector": name,
            "episodes_evaluated": len(eps),
            "episodes_detected_by_peak": hit,
            "sensitivity": hit / len(eps) if len(eps) else np.nan,
            "median_delay_weeks_from_onset": float(np.median(delays)) if delays else np.nan,
            "mean_delay_weeks": float(np.mean(delays)) if delays else np.nan,
            "total_alert_weeks": int(alerts.sum()),
            "alerts_outside_episodes": false_alerts,
            "weeks_outside_episodes": out_weeks,
            "false_alert_rate_per_52wk": 52 * false_alerts / out_weeks if out_weeks else np.nan,
            "evaluation_start": start.date(), "weeks_scored": n_scored,
        })
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- B. simulation
def _simulate_series(n, p, rho, rng):
    """Beta-binomial draws: overdispersed like the real data (rho from GLM Pearson scale)."""
    if rho <= 1e-8:
        return rng.binomial(n, p)
    conc = 1 / rho - 1
    a, b = p * conc, (1 - p) * conc
    pi = rng.beta(a, b)
    return rng.binomial(n, pi)


def _inject(p, start, odds_ratio, ramp=4, plateau=4):
    lo = np.log(p / (1 - p))
    delta = np.zeros(len(p))
    for j in range(ramp + plateau):
        if start + j < len(p):
            delta[start + j] = np.log(odds_ratio) * min(1.0, (j + 1) / ramp)
    return 1 / (1 + np.exp(-(lo + delta)))


def simulate_evaluation(s: pd.DataFrame, n_rep: int = 300, odds_ratios=(1.5, 2.0, 3.0),
                        window_years=(2023, 2025), seed: int = C.SEED, detect_horizon: int = 8) -> dict:
    rng = np.random.default_rng(seed)
    res = SEAS.fit_seasonal_glm(s, k=2, exclude_covid=True)
    sim = s[s.ISO_YEAR.between(*window_years)].copy()
    n_t = sim.SPEC_PROCESSED_NB.fillna(sim.SPEC_PROCESSED_NB.median()).clip(lower=C.MIN_BASELINE_TESTS).round().astype(int).values
    p_t = SEAS.predict(res, sim.index, k=2)
    rho = max((res.disp - 1) / (n_t.mean() - 1), 1e-6)
    L = len(sim)
    prov = np.zeros(L, bool)

    def make_df(y):
        d = pd.DataFrame({"INF_ALL": y, "SPEC_PROCESSED_NB": n_t}, index=sim.index)
        d["positivity"] = d.INF_ALL / d.SPEC_PROCESSED_NB
        return d

    def detectors(y):
        d = make_df(y)
        o = {m: AN.ears(d, m) for m in ("C1", "C2", "C3")}
        pr = np.clip(p_t, 1e-4, 1 - 1e-4)
        z = AN.pearson_resid(y, n_t, pr) / np.sqrt(res.disp)
        _, al = AN.cusum_scores(z)
        o["CUSUM"] = pd.DataFrame({"alert": al}, index=sim.index)
        return {k: v.alert.values for k, v in o.items()}

    warm = 12  # ignore the first weeks (EARS baseline warm-up)
    # in-control: false alerts per 52 weeks
    fa = {m: [] for m in ("C1", "C2", "C3", "CUSUM")}
    for _ in range(n_rep):
        al = detectors(_simulate_series(n_t, p_t, rho, rng))
        for m, a in al.items():
            fa[m].append(a[warm:].sum() * 52 / (L - warm))
    rows = []
    for m in fa:
        rows.append({"scenario": "no outbreak", "detector": m, "odds_ratio": 1.0,
                     "false_alerts_per_52wk": float(np.mean(fa[m])), "sensitivity": np.nan,
                     "median_delay_weeks": np.nan, "mean_delay_weeks": np.nan})
    # outbreaks
    for orr in odds_ratios:
        det = {m: [] for m in fa}
        dly = {m: [] for m in fa}
        for _ in range(n_rep):
            start = int(rng.integers(warm + 4, L - detect_horizon - 1))
            p_out = _inject(p_t, start, orr)
            al = detectors(_simulate_series(n_t, p_out, rho, rng))
            for m, a in al.items():
                w = np.where(a[start:start + detect_horizon])[0]
                det[m].append(len(w) > 0)
                if len(w):
                    dly[m].append(w[0])
        for m in fa:
            rows.append({"scenario": f"outbreak OR={orr}", "detector": m, "odds_ratio": orr,
                         "false_alerts_per_52wk": np.nan, "sensitivity": float(np.mean(det[m])),
                         "median_delay_weeks": float(np.median(dly[m])) if dly[m] else np.nan,
                         "mean_delay_weeks": float(np.mean(dly[m])) if dly[m] else np.nan})
    return {"table": pd.DataFrame(rows), "n_rep": n_rep, "rho": float(rho), "dispersion": float(res.disp),
            "window": window_years, "horizon_weeks": detect_horizon}
