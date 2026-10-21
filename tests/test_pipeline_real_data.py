"""Integration tests on the real file (skipped if absent)."""
import pytest

from pathogenwatch import config as C

pytestmark = pytest.mark.skipif(not C.RAW_CSV.exists(), reason="raw data not present")


@pytest.fixture(scope="module")
def bgd():
    from pathogenwatch import io, cleaning
    raw = io.load_raw()
    agg = cleaning.aggregate_fast(cleaning.recover_inf_all(cleaning.drop_exact_duplicates(raw)))
    return raw, agg, cleaning.country_series(agg, "BGD")


def test_unique_country_week_after_aggregation(bgd):
    _, agg, _ = bgd
    assert not agg.duplicated(["COUNTRY_CODE", "ISO_YEAR", "ISO_WEEK"]).any()


def test_raw_file_untouched():
    from pathogenwatch import io
    expected = (C.RAW_CSV.with_suffix(".csv.sha256")).read_text().split()[0]
    assert io.sha256(C.RAW_CSV) == expected


def test_bangladesh_series_sane(bgd):
    _, _, s = bgd
    v = s.positivity.dropna()
    assert ((v >= 0) & (v <= 1)).all()
    assert s.index.is_monotonic_increasing and s.index.to_series().diff().dropna().eq(pd_week()).all()


def pd_week():
    import pandas as pd
    return pd.Timedelta(weeks=1)


def test_aggregate_never_exceeds_naive_sum(bgd):
    from pathogenwatch import cleaning, config
    raw, agg, _ = bgd
    naive = cleaning.naive_sum_all_rows(raw)
    m = agg.merge(naive, on=config.KEY, suffixes=("", "_n"))
    ok = m.SPEC_PROCESSED_NB.notna()
    assert (m.SPEC_PROCESSED_NB[ok] <= m.SPEC_PROCESSED_NB_n[ok] + 1e-9).all()


def test_seasonality_detected(bgd):
    from pathogenwatch import seasonality
    _, _, s = bgd
    assert seasonality.harmonic_lr_test(s)["p_value"] < 1e-6
