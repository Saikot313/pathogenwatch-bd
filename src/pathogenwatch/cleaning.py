"""Cleaning & correct aggregation. Raw data is never overwritten; this returns new frames."""
import numpy as np
import pandas as pd

from . import config as C

SUM_COLS = (["SPEC_PROCESSED_NB", "SPEC_RECEIVED_NB", "INF_A", "INF_B", "INF_ALL", "INF_NEGATIVE"]
            + C.A_SUBTYPES + C.B_LINEAGES)


def drop_exact_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    return df.drop_duplicates().reset_index(drop=True)


def recover_inf_all(df: pd.DataFrame) -> pd.DataFrame:
    """INF_ALL is missing in many rows although INF_A and INF_B are present.
    INF_ALL == INF_A + INF_B holds in 100% of rows where all three exist, so the
    identity is used to recover it. Recovered values are flagged."""
    d = df.copy()
    can = d.INF_ALL.isna() & d.INF_A.notna() & d.INF_B.notna()
    d["INF_ALL_RECOVERED"] = can
    d.loc[can, "INF_ALL"] = d.loc[can, "INF_A"] + d.loc[can, "INF_B"]
    return d


def aggregate_country_week(df: pd.DataFrame) -> pd.DataFrame:
    """One row per country-week without double counting.

    Policy (documented assumption):
      * If a NOTDEFINED row exists, it is taken as the national total and used alone
        (it is not the sum of the other sources in the data; summing would double count).
      * Else SENTINEL and NONSENTINEL rows are summed (min_count=1 so all-NaN stays NaN).
    `SOURCE_USED` records the choice; `N_SOURCES_AVAILABLE` flags ambiguous weeks.
    """
    d = df.copy()
    pieces = []
    for key, g in d.groupby(C.KEY, sort=False):
        srcs = set(g[C.SOURCE_COL])
        if "NOTDEFINED" in srcs:
            use = g[g[C.SOURCE_COL] == "NOTDEFINED"]
            used = "NOTDEFINED"
        else:
            use = g
            used = "+".join(sorted(srcs))
        row = use.iloc[0][[c for c in d.columns if c not in SUM_COLS]].to_dict()
        for c in SUM_COLS:
            row[c] = use[c].sum(min_count=1)
        row["SOURCE_USED"] = used
        row["N_SOURCES_AVAILABLE"] = len(srcs)
        pieces.append(row)
    out = pd.DataFrame(pieces)
    out["ISO_WEEKSTARTDATE"] = pd.to_datetime(out.ISO_WEEKSTARTDATE)
    return out


def aggregate_fast(df: pd.DataFrame) -> pd.DataFrame:
    """Vectorised equivalent of aggregate_country_week for the full global table."""
    d = df.copy()
    d["_is_nd"] = (d[C.SOURCE_COL] == "NOTDEFINED")
    has_nd = d.groupby(C.KEY)["_is_nd"].transform("any")
    use = d[(~has_nd) | d["_is_nd"]]
    meta = [c for c in d.columns if c not in SUM_COLS + ["_is_nd"]]
    agg = {c: "sum" for c in SUM_COLS}
    g = use.groupby(C.KEY, sort=False)
    sums = g[SUM_COLS].sum(min_count=1)
    first = g[meta].first().drop(columns=[c for c in C.KEY if c in meta], errors="ignore")
    out = sums.join(first).reset_index()
    nsrc = d.groupby(C.KEY)[C.SOURCE_COL].nunique().rename("N_SOURCES_AVAILABLE")
    used = use.groupby(C.KEY)[C.SOURCE_COL].apply(lambda s: "+".join(sorted(set(s)))).rename("SOURCE_USED")
    out = out.join(nsrc, on=C.KEY).join(used, on=C.KEY)
    out["ISO_WEEKSTARTDATE"] = pd.to_datetime(out.ISO_WEEKSTARTDATE)
    return out


def naive_sum_all_rows(df: pd.DataFrame) -> pd.DataFrame:
    """The INCORRECT approach (sum every row incl. duplicates and all sources).
    Kept only so the data-quality report can quantify the size of the error."""
    return df.groupby(C.KEY)[SUM_COLS].sum(min_count=1).reset_index()


def country_series(agg: pd.DataFrame, country: str = C.COUNTRY) -> pd.DataFrame:
    """Complete weekly index for one country; gaps become explicit NaN rows.
    Positivity = INF_ALL / SPEC_PROCESSED_NB, undefined when nothing was processed."""
    s = agg[agg.COUNTRY_CODE == country].sort_values("ISO_WEEKSTARTDATE").set_index("ISO_WEEKSTARTDATE")
    full = pd.date_range(s.index.min(), s.index.max(), freq="W-MON")
    s = s.reindex(full)
    s.index.name = "week_start"
    s["gap_week"] = s.ISO_YEAR.isna()
    s["ISO_YEAR"] = s.index.isocalendar().year.astype(int)
    s["ISO_WEEK"] = s.index.isocalendar().week.astype(int)
    proc = s.SPEC_PROCESSED_NB.where(s.SPEC_PROCESSED_NB > 0)
    s["positivity"] = s.INF_ALL / proc
    s["positivity_A"] = s.INF_A / proc
    s["positivity_B"] = s.INF_B / proc
    s["provisional"] = False
    if C.PROVISIONAL_WEEKS:
        s.iloc[-C.PROVISIONAL_WEEKS:, s.columns.get_loc("provisional")] = True
    return s
