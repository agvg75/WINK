"""coerce_numeric must fix the pandas-3 failure WITHOUT destroying text columns.

The second requirement is the one with teeth: an earlier version matched column
NAMES and would have turned `fps_source` ("declared") into NaN, erasing whether
a frame rate was measured or guessed. That is a worse bug than the one being
fixed, so it is asserted explicitly rather than assumed.
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from table_io import coerce_numeric, read_table   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print(f"table io - regression (pandas {pd.__version__})\n")

df = pd.DataFrame({
    "midbody_curvature_px_inv": ["0.1", "none", "0.3", "0.4"],
    "speed_um_s": [1.0, 2.0, 3.0, 4.0],
    "fps_source": ["declared", "declared", "guessed", "declared"],
    "spine_skip_reason": ["", "too_short", "", ""],
    "modality": ["swim", "crawl", "swim", "swim"],
})
out = coerce_numeric(df.copy())

check("a numeric column carrying a stray word becomes numeric",
      out["midbody_curvature_px_inv"].dtype.kind == "f",
      str(out["midbody_curvature_px_inv"].dtype))
check("...and numpy will now accept it",
      bool(np.isfinite(out["midbody_curvature_px_inv"]).sum() == 3))
check("...with the bad cell as NaN, not as a number",
      bool(out["midbody_curvature_px_inv"].isna().sum() == 1))
check("an already-numeric column is untouched",
      out["speed_um_s"].dtype.kind == "f")

check("a TEXT provenance column keeps its dtype",
      out["fps_source"].dtype.kind not in "fiu", str(out["fps_source"].dtype))
check("...and its values, so 'declared' vs 'guessed' survives",
      out["fps_source"].tolist() == ["declared", "declared", "guessed",
                                     "declared"])
check("a mostly-empty text column is not converted",
      out["spine_skip_reason"].dtype.kind not in "fiu")
check("a label column is not converted",
      out["modality"].tolist() == ["swim", "crawl", "swim", "swim"])

check("columns that were rescued are recorded, not silently changed",
      out.attrs.get("coerced_numeric_columns") == ["midbody_curvature_px_inv"],
      str(out.attrs.get("coerced_numeric_columns")))

# an all-text column that happens to contain digits must NOT be coerced away
ids = pd.DataFrame({"plate_id": ["A1", "A2", "B1"]})
check("an identifier column with letters is left alone",
      coerce_numeric(ids.copy())["plate_id"].dtype.kind not in "fiu")

# a column that is genuinely half numbers and half words is ambiguous: leave it
half = pd.DataFrame({"x": ["1", "two", "3", "four", "5", "six"]})
check("a half-and-half column is left alone rather than half destroyed",
      coerce_numeric(half.copy())["x"].dtype.kind not in "fiu")

# round trip through a file
import tempfile
with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
    p = Path(td) / "t.csv"
    p.write_text("t,v,fps_source\n0,1.0,declared\n1,none,guessed\n2,3.0,declared\n",
                 encoding="utf-8")
    got = read_table(p)
    check("read_table fixes the column on the way in",
          got["v"].dtype.kind == "f", str(got["v"].dtype))
    check("...and still leaves fps_source alone",
          got["fps_source"].tolist() == ["declared", "guessed", "declared"])
    raw = read_table(p, coerce=False)
    check("coerce=False gives the unfixed frame, for comparison",
          raw["v"].dtype.kind != "f")

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("TABLE_IO_PASS")
