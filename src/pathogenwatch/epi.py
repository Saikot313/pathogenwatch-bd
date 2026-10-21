"""Descriptive epidemiology: weekly/annual positivity with CIs, subtype composition, trend test."""
import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.proportion import proportion_confint

from . import config as C


def wilson(pos, n, alpha=0.05):
    pos, n = np.asarray(pos, float), np.asarray(n, float)
    lo, hi = np.full(pos.shape, np.nan), np.full(pos.shape, np.nan)
    ok = (n > 0) & np.isfinite(pos) & np.isfinite(n)
    if ok.any():
        l, h = proportion_confint(pos[ok], n[ok], alpha=alpha, method="wilson")
        lo[ok], hi[ok] = l, h
    return lo, hi


def weekly_table(s: pd.DataFrame) -> pd.DataFrame:
    """Weekly positivity with 95% Wilson CI. Weeks without a valid numerator/denominator stay NaN."""
    t = s[["ISO_YEAR", "ISO_WEEK", "SPEC_PROCESSED_NB", "INF_ALL", "INF_A", "INF_B",
           "positivity", "gap_week", "provisional"]].copy()
    valid = t.INF_ALL.notna() & (t.SPEC_PROCESSED_NB > 0)
    lo, hi = wilson(t.INF_ALL.where(valid), t.SPEC_PROCESSED_NB.where(valid))
    t["pos_lo"], t["pos_hi"] = lo, hi
    t["positivity"] = t.positivity.where(valid)
    return t


def annual_table(s: pd.DataFrame) -> pd.DataFrame:
    """Annual positivity using only weeks where both numerator and denominator are valid
    (avoids the bias of dividing a complete denominator by an incomplete numerator)."""
    v = s[s.INF_ALL.notna() & (s.SPEC_PROCESSED_NB > 0)]
    g = v.groupby("ISO_YEAR")
    out = pd.DataFrame({
        "weeks_valid": g.size(),
        "processed": g.SPEC_PROCESSED_NB.sum(),
        "influenza_positive": g.INF_ALL.sum(),
        "influenza_A": g.INF_A.sum(min_count=1),
        "influenza_B": g.INF_B.sum(min_count=1),
    })
    out["positivity"] = out.influenza_positive / out.processed
    lo, hi = wilson(out.influenza_positive, out.processed)
    out["pos_lo"], out["pos_hi"] = lo, hi
    out["share_A"] = out.influenza_A / out.influenza_positive
    out["share_B"] = out.influenza_B / out.influenza_positive
    return out.reset_index()


def subtype_table(s: pd.DataFrame) -> pd.DataFrame:
    cols = ["AH1N12009", "AH3", "BVIC_2DEL", "BVIC_3DEL", "BVIC_NODEL", "BVIC_DELUNK", "BYAM",
            "BNOTDETERMINED", "ANOTSUBTYPED", "ANOTSUBTYPABLE"]
    cols = [c for c in cols if c in s]
    return s.groupby("ISO_YEAR")[cols].sum(min_count=1).reset_index()


def trend_test(annual: pd.DataFrame, years=None) -> dict:
    """Kendall tau / Mann-Kendall-type test on annual positivity (non-parametric)."""
    a = annual.dropna(subset=["positivity"])
    if years is not None:
        a = a[a.ISO_YEAR.between(*years)]
    if len(a) < 4:
        return {"n_years": len(a), "tau": np.nan, "p_value": np.nan}
    tau, p = stats.kendalltau(a.ISO_YEAR, a.positivity)
    slope = stats.theilslopes(a.positivity, a.ISO_YEAR)[0]
    return {"n_years": int(len(a)), "tau": float(tau), "p_value": float(p),
            "theil_sen_slope_per_year": float(slope)}


def compare_aggregation(agg: pd.DataFrame, naive: pd.DataFrame, country_list=None) -> pd.DataFrame:
    """Quantify the error of naive summation of all rows versus the corrected aggregation."""
    m = agg.merge(naive, on=C.KEY, suffixes=("_correct", "_naive"))
    m["proc_diff"] = m.SPEC_PROCESSED_NB_naive - m.SPEC_PROCESSED_NB_correct
    bad = m[m.proc_diff.abs() > 0]
    g = bad.groupby("COUNTRY_CODE").agg(
        weeks_affected=("proc_diff", "size"),
        specimens_overcounted=("proc_diff", "sum")).sort_values("specimens_overcounted", ascending=False)
    return g.reset_index()
