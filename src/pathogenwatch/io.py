"""Raw data loading. The raw file is never modified; checksum is verified."""
import hashlib
from pathlib import Path

import pandas as pd

from . import config


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_raw(path: Path | None = None, verify: bool = True) -> pd.DataFrame:
    """Load VIW_FNT.csv exactly as delivered (no cleaning)."""
    path = Path(path or config.RAW_CSV)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Place the WHO FluNet export VIW_FNT.csv in data/raw/.")
    if verify:
        sidecar = path.with_suffix(path.suffix + ".sha256")
        if sidecar.exists():
            expected = sidecar.read_text().split()[0]
            if sha256(path) != expected:
                raise ValueError("Raw file checksum differs from recorded checksum; "
                                 "the raw data changed. Delete the .sha256 sidecar to accept.")
    return pd.read_csv(path, low_memory=False)
