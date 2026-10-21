import numpy as np
import pandas as pd
import pytest

from pathogenwatch import cleaning, config as C


def _row(src, proc, a, b, inf_all=np.nan, wk=1, cc="XXX"):
    d = {c: np.nan for c in cleaning.SUM_COLS}
    d.update(COUNTRY_CODE=cc, ISO_YEAR=2020, ISO_WEEK=wk, ORIGIN_SOURCE=src,
             ISO_WEEKSTARTDATE="2020-01-06", SPEC_PROCESSED_NB=proc, INF_A=a, INF_B=b, INF_ALL=inf_all)
    return d


def test_exact_duplicates_removed():
    df = pd.DataFrame([_row("SENTINEL", 10, 1, 0), _row("SENTINEL", 10, 1, 0)])
    assert len(cleaning.drop_exact_duplicates(df)) == 1


def test_inf_all_recovered_only_when_identity_possible():
    df = pd.DataFrame([_row("SENTINEL", 10, 2, 3), _row("SENTINEL", 10, np.nan, 3, wk=2)])
    out = cleaning.recover_inf_all(df)
    assert out.INF_ALL.iloc[0] == 5 and out.INF_ALL_RECOVERED.iloc[0]
    assert np.isnan(out.INF_ALL.iloc[1]) and not out.INF_ALL_RECOVERED.iloc[1]


def test_notdefined_not_double_counted():
    df = pd.DataFrame([_row("NOTDEFINED", 100, 10, 5, 15), _row("SENTINEL", 60, 6, 3, 9),
                       _row("NONSENTINEL", 40, 4, 2, 6)])
    agg = cleaning.aggregate_fast(df)
    assert len(agg) == 1 and agg.SPEC_PROCESSED_NB.iloc[0] == 100
    assert agg.SOURCE_USED.iloc[0] == "NOTDEFINED" and agg.N_SOURCES_AVAILABLE.iloc[0] == 3
    assert cleaning.naive_sum_all_rows(df).SPEC_PROCESSED_NB.iloc[0] == 200  # the wrong answer


def test_sentinel_and_nonsentinel_are_summed():
    df = pd.DataFrame([_row("SENTINEL", 60, 6, 3, 9), _row("NONSENTINEL", 40, 4, 2, 6)])
    agg = cleaning.aggregate_fast(df)
    assert agg.SPEC_PROCESSED_NB.iloc[0] == 100 and agg.INF_ALL.iloc[0] == 15


def test_all_nan_stays_nan_not_zero():
    df = pd.DataFrame([_row("SENTINEL", 10, np.nan, np.nan)])
    agg = cleaning.aggregate_fast(df)
    assert np.isnan(agg.INF_ALL.iloc[0])


def test_aggregate_fast_matches_reference_implementation():
    rows = []
    for wk in range(1, 6):
        rows += [_row("NOTDEFINED", 100 + wk, 10, 5, 15, wk=wk), _row("SENTINEL", 60, 6, 3, 9, wk=wk)]
        rows += [_row("SENTINEL", 20 + wk, 2, 1, 3, wk=wk, cc="YYY"), _row("NONSENTINEL", 5, 1, 0, 1, wk=wk, cc="YYY")]
    df = pd.DataFrame(rows)
    a = cleaning.aggregate_fast(df).sort_values(C.KEY).reset_index(drop=True)
    b = cleaning.aggregate_country_week(df).sort_values(C.KEY).reset_index(drop=True)
    pd.testing.assert_series_equal(a.SPEC_PROCESSED_NB, b.SPEC_PROCESSED_NB, check_names=False)
    pd.testing.assert_series_equal(a.INF_ALL, b.INF_ALL, check_names=False)


def test_positivity_undefined_when_nothing_processed_and_gaps_explicit():
    rows = []
    for wk, proc in [(1, 10), (3, 0)]:  # week 2 missing entirely
        r = _row("SENTINEL", proc, 1, 0, 1, wk=wk, cc="BGD")
        r["ISO_WEEKSTARTDATE"] = ["2020-01-06", "2020-01-13", "2020-01-20"][wk - 1]
        rows.append(r)
    s = cleaning.country_series(cleaning.aggregate_fast(pd.DataFrame(rows)), "BGD")
    assert len(s) == 3 and s.gap_week.tolist() == [False, True, False]
    assert s.positivity.iloc[0] == pytest.approx(0.1)
    assert np.isnan(s.positivity.iloc[1]) and np.isnan(s.positivity.iloc[2])


def test_notdefined_vs_sum_diagnostic():
    from pathogenwatch import quality
    df = pd.DataFrame([_row("NOTDEFINED", 100, 1, 1), _row("SENTINEL", 60, 1, 1), _row("NONSENTINEL", 40, 1, 1),
                       _row("NOTDEFINED", 90, 1, 1, wk=2), _row("SENTINEL", 60, 1, 1, wk=2)])
    r = quality.notdefined_vs_sum(df).iloc[0]
    assert r.weeks_compared == 2 and r.notdefined_equals_sum == 0.5 and r.notdefined_greater == 0.5
