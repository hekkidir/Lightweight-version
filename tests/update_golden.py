"""
update_golden.py — regenerate the golden expected outputs from the fixture.

Run ONLY when you've changed pipeline logic on purpose and confirmed the new
numbers are correct. The golden test compares against whatever this writes.

    python tests/update_golden.py
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN   = FIXTURES / "golden"
OUTPUTS  = ["metrics.parquet", "sectors.parquet",
            "rotation.parquet", "rotation_tail.parquet"]


def main():
    from pipeline import indicators, rotation, sectors
    from pipeline.config import load

    cfg = load(ROOT / "config.ini")
    GOLDEN.mkdir(parents=True, exist_ok=True)

    d = Path(tempfile.mkdtemp())
    shutil.copy(FIXTURES / "prices_sample.parquet", d / "prices.parquet")
    indicators.run(cfg, d)
    sectors.run(cfg, d)
    rotation.run(cfg, d)

    for name in OUTPUTS:
        shutil.copy(d / name, GOLDEN / name)
        print(f"updated {name}")


if __name__ == "__main__":
    main()
