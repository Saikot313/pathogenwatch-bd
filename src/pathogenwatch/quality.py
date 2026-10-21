"""Data-quality audit: pure functions returning tidy tables/dicts (no side effects)."""
import numpy as np
import pandas as pd

from . import config as C


def audit_summary(df: pd.DataFrame) -> dict:
    out = {
        "rows": len(df),
        "columns": df.shape[1],
        "countries": df.COUNTRY_CODE.nunique(),
        "first_week": df.ISO_WEEKSTARTDATE.min(),
        "last_week": df.ISO_WEEKSTARTDATE.max(),
        "exact_duplicate_rows": int(df.duplicated().sum()),
        "duplicate_country_week_rows_all_sources": int(df.duplicated(C.KEY).sum()),
    }
    d = df.drop_duplicates()
    out["duplicate_country_week_source_after_dedup"] = int(d.duplicated(C.KEY + [C.SOURCE_COL]).sum())
    out["source_counts"] = d[C.SOURCE_COL].value_counts().to_dict()
    return out


def duplicate_table(df: pd.DataFrame) -> pd.DataFrame:
    dup = df[df.duplicated()]
    return (dup.groupby(["COUNTRY_CODE", C.SOURCE_COL]).size()
            .rename("exact_duplicate_rows").reset_index())


def missingness(df: pd.DataFrame) -> pd.DataFrame:
    m = df.isna().mean().mul(100).round(2).rename("missing_pct")
    return m.sort_values(ascending=False).reset_index().rename(columns={"index": "column"})


def source_combinations(df: pd.DataFrame) -> pd.DataFrame:
    d = df.drop_duplicates()
    combo = d.groupby(C.KEY)[C.SOURCE_COL].apply(lambda s: "+".join(sorted(set(s))))
    return combo.value_counts().rename("country_weeks").reset_index().rename(
        columns={C.SOURCE_COL: "source_combination", "index": "source_combination"})


def notdefined_vs_sum(df: pd.DataFrame, col: str = "SPEC_PROCESSED_NB") -> pd.DataFrame:
    """For weeks where NOTDEFINED coexists with SENTINEL/NONSENTINEL, is it their sum?"""
    d = df.drop_duplicates()
    nd = d[d[C.SOURCE_COL] == "NOTDEFINED"].groupby(C.KEY)[col].sum(min_count=1)
    oth = d[d[C.SOURCE_COL] != "NOTDEFINED"].groupby(C.KEY)[col].sum(min_count=1)
    both = pd.concat([nd.rename("nd"), oth.rename("oth")], axis=1, join="inner").dropna()
    x, o = both.nd, both.oth
    m = pd.Series(True, index=both.index)
    return pd.DataFrame({
        "column": [col], "weeks_compared": [int(m.sum())],
        "notdefined_equals_sum": [float((x == o).mean())],
        "notdefined_greater": [float((x > o).mean())],
        "notdefined_smaller": [float((x < o).mean())],
    })


def consistency_checks(df: pd.DataFrame) -> pd.DataFrame:
    """Logical-consistency violations on the de-duplicated table."""
    d = df.drop_duplicates()
    a = d[C.A_SUBTYPES].sum(axis=1, min_count=1)
    b = d[C.B_LINEAGES].sum(axis=1, min_count=1)
    rows = []

    def add(name, mask, denom):
        rows.append({"check": name, "violations": int(mask.sum()), "rows_checked": int(denom.sum())})

    m = d.INF_A.notna() & a.notna()
    add("INF_A != sum(A subtypes)", m & (d.INF_A != a), m)
    m = d.INF_B.notna() & b.notna()
    add("INF_B != sum(B lineages)", m & (d.INF_B != b), m)
    m = d.INF_A.notna() & d.INF_B.notna() & d.INF_ALL.notna()
    add("INF_ALL != INF_A + INF_B", m & (d.INF_ALL != d.INF_A + d.INF_B), m)
    m = d.INF_ALL.notna() & d.SPEC_PROCESSED_NB.notna()
    add("INF_ALL > SPEC_PROCESSED_NB", m & (d.INF_ALL > d.SPEC_PROCESSED_NB), m)
    m = d.INF_ALL.notna() & d.INF_NEGATIVE.notna() & d.SPEC_PROCESSED_NB.notna()
    add("INF_ALL + INF_NEGATIVE > SPEC_PROCESSED_NB", m & ((d.INF_ALL + d.INF_NEGATIVE) > d.SPEC_PROCESSED_NB), m)
    m = d.SPEC_PROCESSED_NB.notna() & d.SPEC_RECEIVED_NB.notna()
    add("SPEC_PROCESSED_NB > SPEC_RECEIVED_NB", m & (d.SPEC_PROCESSED_NB > d.SPEC_RECEIVED_NB), m)
    add("INF_ALL missing although INF_A/INF_B present (recoverable)",
        d.INF_ALL.isna() & (d.INF_A.notna() & d.INF_B.notna()), d.INF_A.notna() & d.INF_B.notna())
    num = d.select_dtypes("number")
    neg = int((num.drop(columns=[c for c in num if c.startswith(("ISO", "MMWR"))], errors="ignore") < 0).sum().sum())
    rows.append({"check": "negative counts", "violations": neg, "rows_checked": len(d)})
    rows.append({"check": "SPEC_PROCESSED_NB == 0 (no testing; not zero cases)",
                 "violations": int((d.SPEC_PROCESSED_NB == 0).sum()), "rows_checked": len(d)})
    return pd.DataFrame(rows)


def week_gaps(df: pd.DataFrame, country: str = C.COUNTRY) -> pd.DataFrame:
    b = df[df.COUNTRY_CODE == country].drop_duplicates(C.KEY + [C.SOURCE_COL])
    wk = pd.to_datetime(b.ISO_WEEKSTARTDATE).sort_values().unique()
    full = pd.date_range(wk.min(), wk.max(), freq="W-MON")
    missing = full.difference(pd.DatetimeIndex(wk))
    return pd.DataFrame({"missing_week_start": missing.strftime("%Y-%m-%d")})
