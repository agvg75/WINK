"""Frame-type census: a folder is not one recording just because it is one folder.

From Carlee's AVG6 - 1,154 grayscale planes and 108 RGB planes in one
directory, which every tool had treated as a single recording. The failure
mode that matters is not the crash; it is the SILENT version, where a loader
keeps the majority and returns a recording quietly 108 frames shorter.
"""
import numpy as np
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import tifffile                                    # noqa: E402
from frame_census import (                         # noqa: E402
    census, describe, require_homogeneous, MixedFramesError)

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("frame census - one folder is not one recording\n")

tmp = Path(tempfile.mkdtemp(prefix="wink_census_"))

clean = tmp / "clean"
clean.mkdir()
for i in range(6):
    tifffile.imwrite(clean / f"f{i:03d}.tif",
                     np.zeros((32, 48), np.uint16))

mixed = tmp / "mixed"
mixed.mkdir()
for i in range(9):
    tifffile.imwrite(mixed / f"f{i:03d}.tif", np.zeros((32, 48), np.uint16))
for i in range(9, 12):
    tifffile.imwrite(mixed / f"f{i:03d}.tif", np.zeros((32, 48, 3), np.uint8))

# ------------------------------------------------------------- homogeneous
record = census(clean)
check("a uniform folder is homogeneous", record["homogeneous"] is True)
check("and reports one type", len(record["types"]) == 1, record["types"])
check("with its dtype and channel count MEASURED, not inferred from the "
      "extension", record["types"][0]["dtype"] == "uint16"
      and record["types"][0]["channels"] == 1, record["types"][0])
check("require_homogeneous passes it through", require_homogeneous(clean) is not None)

# ------------------------------------------------------------------ mixed
record = census(mixed)
check("a mixed folder is NOT homogeneous", record["homogeneous"] is False)
check("both types are reported, neither dropped",
      len(record["types"]) == 2, record["types"])
counts = {t["channels"]: t["count"] for t in record["types"]}
check("with an exact count for each - the split is the finding",
      counts == {1: 9, 3: 3}, counts)
check("the dominant type is the majority one",
      record["dominant"]["count"] == 9)

text = describe(record)
check("the description names the split in a form a person can act on",
      "2 TYPES" in text and "9" in text and "3" in text, text)

try:
    require_homogeneous(mixed)
    check("a mixed folder is REFUSED for series treatment", False, "no raise")
except MixedFramesError as exc:
    message = str(exc)
    check("a mixed folder is REFUSED for series treatment", True)
    check("and the refusal names the split, unlike 'all input arrays must "
          "have the same shape'", "TYPES" in message, message.splitlines()[1])
    check("and says nothing was loaded, so the reader knows no silent "
          "majority was kept", "Nothing was loaded" in message)
    check("and refuses to coerce rather than offering to",
          "Coercing" in message or "coerc" in message.lower())

# --------------------------------------------------------------- degenerate
empty = tmp / "empty"
empty.mkdir()
record = census(empty)
check("an empty folder reports no frames rather than raising",
      record["n_frames"] == 0 and record["homogeneous"] is None)
try:
    require_homogeneous(empty)
    check("and is refused for series treatment", False, "no raise")
except MixedFramesError:
    check("and is refused for series treatment", True)

# ------------------------------------------------- unreadable files counted
(mixed / "notanimage.tif").write_bytes(b"this is not a tiff")
record = census(mixed)
check("an unreadable file is COUNTED rather than silently skipped - a file "
      "that cannot be read is a fact about the recording",
      record["n_unreadable"] == 1, record["n_unreadable"])

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("FRAME_CENSUS_PASS")
