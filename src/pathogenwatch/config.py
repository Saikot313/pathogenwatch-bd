"""Central configuration. All analysis parameters live here so runs are reproducible."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW_CSV = ROOT / "data" / "raw" / "VIW_FNT.csv"
PROCESSED_DIR = ROOT / "data" / "processed"
REPORTS_DIR = ROOT / "reports"
FIG_DIR = REPORTS_DIR / "figures"
TABLE_DIR = REPORTS_DIR / "tables"

COUNTRY = "BGD"
SEED = 20261020

KEY = ["COUNTRY_CODE", "ISO_YEAR", "ISO_WEEK"]
SOURCE_COL = "ORIGIN_SOURCE"

A_SUBTYPES = ["AH1N12009", "AH1", "AH3", "AH5", "AH7N9",
              "ANOTSUBTYPED", "ANOTSUBTYPABLE", "AOTHER_SUBTYPE"]
B_LINEAGES = ["BVIC_2DEL", "BVIC_3DEL", "BVIC_NODEL", "BVIC_DELUNK",
              "BYAM", "BNOTDETERMINED"]

# Aggregation policy when several ORIGIN_SOURCE rows exist for one country-week.
# NOTDEFINED = national total of unspecified source; it is NOT always the sum of
# SENTINEL + NONSENTINEL (see data quality report), so it is never summed with them.
SOURCE_PRIORITY = ["NOTDEFINED", "SENTINEL+NONSENTINEL"]

# Anomaly detection
EARS_BASELINE = 7          # weeks in the EARS baseline window
EARS_GUARD = 2             # guard-band weeks for C2 / C3
EARS_K = 3.0               # z-threshold
CUSUM_K = 0.5              # reference value (in SD units)
CUSUM_H = 4.0              # decision interval (in SD units)
MIN_BASELINE_TESTS = 30    # weeks with fewer processed specimens are not scored

# The most recent week is usually incomplete (processed < received); drop from scoring.
PROVISIONAL_WEEKS = 1
